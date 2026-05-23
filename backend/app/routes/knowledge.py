import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.database import get_db, async_session
from app.config import settings
from app.models import KnowledgeDocument
from app.file_parser import extract_text
from app.chunker import split_text
from app import vector_store
from app.services.dpe_client import call_dpe_process

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


class UserIrBody(BaseModel):
    content: str


# ── Helpers ───────────────────────────────────────────────────────────────

async def _get_doc_or_404(db: AsyncSession, doc_id: int) -> KnowledgeDocument:
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")
    return doc


def _chunk_metadata(
    *,
    doc_id: int,
    filename: str,
    chunk_index: int,
) -> dict:
    return {
        "id": f"doc_{doc_id}_chunk_{chunk_index + 1}",
        "filename": filename,
        "title": filename,
        "source": filename,
        "chunk_index": chunk_index,
        "content_type": "text",
    }


async def generate_summary(text: str, filename: str, model: str) -> str:
    preview = text[:4000]
    prompt = (
        "다음 문서의 내용을 분석하여 3~5문장으로 요약해주세요. "
        "문서의 주제, 핵심 내용, 주요 키워드를 포함해주세요. "
        "요약만 출력하고 다른 설명은 하지 마세요.\n\n"
        f"[문서명: {filename}]\n\n"
        f"{preview}"
    )
    try:
        from app.services.llm import chat as llm_chat
        summary = await llm_chat(
            model,
            [{"role": "user", "content": prompt}],
            options={"temperature": 0.2, "num_predict": 512},
            timeout=120.0,
        )
        return summary[:2000] if summary else ""
    except Exception as e:
        logger.warning("요약 생성 실패 (filename=%s): %s", filename, e)
        return ""


# ── Background task: upload processing (DPE 자동 실행 제거) ────────────────

async def process_document(doc_id: int, filename: str, content: bytes):
    async with async_session() as db:
        try:
            text = extract_text(filename, content)
            if not text.strip():
                await db.execute(
                    update(KnowledgeDocument)
                    .where(KnowledgeDocument.id == doc_id)
                    .values(status="error", error_message="문서에서 텍스트를 추출할 수 없습니다")
                )
                await db.commit()
                return

            # 청킹은 원본 텍스트 기반 (UCE OFF용)
            chunks = split_text(text, chunk_size=500, overlap=50, strategy="sliding-window")
            if not chunks:
                await db.execute(
                    update(KnowledgeDocument)
                    .where(KnowledgeDocument.id == doc_id)
                    .values(status="error", error_message="청크 분할 결과가 없습니다")
                )
                await db.commit()
                return

            chunk_metadatas = [
                _chunk_metadata(doc_id=doc_id, filename=filename, chunk_index=index)
                for index, _ in enumerate(chunks)
            ]
            vector_store.add_chunks(doc_id, chunks, metadatas=chunk_metadatas)

            summary = await generate_summary(text, filename, settings.default_ollama_model)

            await db.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id == doc_id)
                .values(
                    status="ready",
                    chunk_count=len(chunks),
                    summary=summary or None,
                    dpe_ir_status="RAW_ONLY",
                )
            )
            await db.commit()

        except Exception as e:
            logger.exception("문서 처리 실패 (doc_id=%d, filename=%s)", doc_id, filename)
            await db.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id == doc_id)
                .values(status="error", error_message=str(e)[:500])
            )
            await db.commit()


# ── List / Upload / Delete ─────────────────────────────────────────────────

@router.get("")
async def list_documents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())
    )
    docs = result.scalars().all()
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "file_size": d.file_size,
            "chunk_count": d.chunk_count,
            "summary": d.summary,
            "status": d.status,
            "error_message": d.error_message,
            "dpe_metadata": d.dpe_metadata,
            "has_dpe_ir": d.normalized_content is not None,
            "has_uce_denoised": d.uce_denoised_content is not None,
            "dpe_ir_status": d.dpe_ir_status or "RAW_ONLY",
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="파일 크기는 20MB 이하여야 합니다")

    doc = KnowledgeDocument(
        filename=file.filename or "document.txt",
        file_size=len(content),
        status="processing",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    background_tasks.add_task(process_document, doc.id, doc.filename, content)

    return {
        "id": doc.id,
        "filename": doc.filename,
        "file_size": doc.file_size,
        "status": doc.status,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    doc = await _get_doc_or_404(db, doc_id)
    vector_store.delete_by_doc_id(doc_id)
    await db.delete(doc)
    await db.commit()


# ── Status / Chunks / Raw text ─────────────────────────────────────────────

@router.get("/{doc_id}/status")
async def get_document_status(doc_id: int, db: AsyncSession = Depends(get_db)):
    doc = await _get_doc_or_404(db, doc_id)
    return {
        "id": doc.id,
        "status": doc.status,
        "chunk_count": doc.chunk_count,
        "summary": doc.summary,
        "error_message": doc.error_message,
        "dpe_metadata": doc.dpe_metadata,
        "dpe_ir_status": doc.dpe_ir_status or "RAW_ONLY",
    }


@router.get("/{doc_id}/chunks")
async def get_document_chunks(
    doc_id: int,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_doc_or_404(db, doc_id)
    chunks = vector_store.chunks_by_doc_id(doc_id, limit=max(1, min(limit, 100)))
    return {
        "id": doc.id,
        "filename": doc.filename,
        "dpe_metadata": doc.dpe_metadata,
        "chunks": chunks,
    }


@router.get("/{doc_id}/text", response_class=PlainTextResponse)
async def get_document_text(doc_id: int, db: AsyncSession = Depends(get_db)):
    await _get_doc_or_404(db, doc_id)
    text = vector_store.text_by_doc_id(doc_id)
    if not text:
        raise HTTPException(status_code=404, detail="저장된 텍스트를 찾을 수 없습니다")
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")


@router.get("/{doc_id}/normalized", response_class=PlainTextResponse)
async def get_normalized_content(doc_id: int, db: AsyncSession = Depends(get_db)):
    doc = await _get_doc_or_404(db, doc_id)
    text = doc.normalized_content or vector_store.text_by_doc_id(doc_id)
    if not text:
        raise HTTPException(status_code=404, detail="저장된 콘텐츠를 찾을 수 없습니다")
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")


@router.get("/{doc_id}/uce-denoised", response_class=PlainTextResponse)
async def get_uce_denoised_content(doc_id: int, db: AsyncSession = Depends(get_db)):
    doc = await _get_doc_or_404(db, doc_id)
    if not doc.uce_denoised_content:
        raise HTTPException(status_code=404, detail="UCE denoised 콘텐츠가 없습니다")
    return PlainTextResponse(doc.uce_denoised_content, media_type="text/plain; charset=utf-8")


# ── DPE 수동 실행 ──────────────────────────────────────────────────────────

@router.post("/{doc_id}/analyze")
async def analyze_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    doc = await _get_doc_or_404(db, doc_id)
    if doc.status != "ready":
        raise HTTPException(status_code=400, detail="문서가 준비되지 않았습니다")

    raw_text = vector_store.text_by_doc_id(doc_id)
    if not raw_text:
        raise HTTPException(status_code=400, detail="원본 텍스트를 찾을 수 없습니다")

    try:
        dpe_result = await call_dpe_process(
            document_id=str(doc_id),
            filename=doc.filename,
            content=raw_text,
        )
    except Exception as e:
        await db.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == doc_id)
            .values(
                dpe_ir_status="ERROR",
                error_message=f"DPE 분석 실패: {str(e)[:300]}",
            )
        )
        await db.commit()
        raise HTTPException(status_code=502, detail=f"DPE 분석 실패: {e}")

    if not dpe_result or not dpe_result.normalization_applied:
        reason = (
            getattr(dpe_result, "normalization_skipped_reason", "알 수 없음")
            if dpe_result
            else "DPE 응답 없음"
        )
        await db.execute(
            update(KnowledgeDocument)
            .where(KnowledgeDocument.id == doc_id)
            .values(
                dpe_ir_status="ERROR",
                error_message=f"DPE normalization 실패: {reason}",
            )
        )
        await db.commit()
        raise HTTPException(status_code=500, detail=f"DPE normalization 실패: {reason}")

    await db.execute(
        update(KnowledgeDocument)
        .where(KnowledgeDocument.id == doc_id)
        .values(
            normalized_content=dpe_result.normalized_content,
            uce_denoised_content=dpe_result.normalized_content,
            dpe_metadata=dpe_result.to_metadata_dict(),
            dpe_ir_status="GENERATED",
            error_message=None,
        )
    )
    await db.commit()
    return {"status": "ok", "doc_id": doc_id, "dpe_ir_status": "GENERATED"}


# ── 사용자 IR 편집 / 복원 ──────────────────────────────────────────────────

@router.put("/{doc_id}/user-ir")
async def update_user_ir(
    doc_id: int,
    body: UserIrBody,
    db: AsyncSession = Depends(get_db),
):
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="content가 비어있습니다")

    doc = await _get_doc_or_404(db, doc_id)
    if not doc.normalized_content:
        raise HTTPException(status_code=400, detail="DPE IR이 없습니다. 먼저 분석을 실행하세요")

    await db.execute(
        update(KnowledgeDocument)
        .where(KnowledgeDocument.id == doc_id)
        .values(
            uce_denoised_content=content,
            dpe_ir_status="USER_EDITED",
        )
    )
    await db.commit()
    return {"status": "ok", "doc_id": doc_id, "dpe_ir_status": "USER_EDITED"}


@router.post("/{doc_id}/restore-ir")
async def restore_generated_ir(doc_id: int, db: AsyncSession = Depends(get_db)):
    doc = await _get_doc_or_404(db, doc_id)
    if not doc.normalized_content:
        raise HTTPException(status_code=400, detail="복원할 generated IR이 없습니다")

    await db.execute(
        update(KnowledgeDocument)
        .where(KnowledgeDocument.id == doc_id)
        .values(
            uce_denoised_content=doc.normalized_content,
            dpe_ir_status="GENERATED",
        )
    )
    await db.commit()
    return {"status": "ok", "doc_id": doc_id, "dpe_ir_status": "GENERATED"}
