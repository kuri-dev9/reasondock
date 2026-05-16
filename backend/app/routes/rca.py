from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Conversation, Message, RcaJob, RcaResult
from app.rca.pipeline import analyze_xdr_file
from app.rca.prompt_builder import build_rca_prompt
from app.services.llm import LLMError, chat as llm_chat
from app.schemas import MessageResponse, RcaAnalyzeResponse, RcaJobResponse


router = APIRouter(prefix="/api/rca", tags=["rca"])

BASE_DIR = Path.cwd()
UPLOAD_DIR = BASE_DIR / "xdr_uploads"
RESULT_DIR = BASE_DIR / "rca_results"


async def _save_upload(file: UploadFile, target: Path) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with target.open("wb") as output:
        while True:
            chunk = await file.read(8 * 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            output.write(chunk)
    return size


@router.post("/jobs", response_model=RcaAnalyzeResponse)
async def create_rca_job(
    conversation_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = conv_result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")

    filename = file.filename or "xdr.dat"
    if not filename.lower().endswith(".dat"):
        raise HTTPException(status_code=422, detail="RCA 분석은 .dat 파일만 지원합니다")

    job = RcaJob(
        conversation_id=conversation_id,
        filename=filename,
        file_size=0,
        file_path="",
        status="queued",
        progress=0,
        current_step="uploading",
    )
    db.add(job)
    await db.flush()

    safe_filename = Path(filename).name
    file_path = UPLOAD_DIR / str(job.id) / safe_filename
    job.file_path = str(file_path)
    try:
        job.file_size = await _save_upload(file, file_path)
        job.status = "parsing"
        job.progress = 20
        job.current_step = "parsing"
        await db.commit()

        result = analyze_xdr_file(file_path, filename)
        job.status = "llm"
        job.progress = 85
        job.current_step = "llm"
        await db.commit()

        prompt = build_rca_prompt(result)
        messages = [
            {
                "role": "system",
                "content": "You are an LTE/EPC RCA expert. Return a grounded Korean RCA report.",
            },
            {"role": "user", "content": prompt},
        ]
        try:
            llm_response = await llm_chat(
                conversation.model,
                messages,
                options={"temperature": 0.1, "num_predict": 1400},
                timeout=1800.0,
            )
            llm_error = None
        except LLMError as exc:
            llm_response = None
            llm_error = f"{exc.reason}: {exc.detail} (raw={exc.raw})"

        result_path = RESULT_DIR / f"rca_job_{job.id}.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result["job_id"] = job.id
        result["conversation_id"] = conversation_id
        result["result_path"] = str(result_path)
        if llm_response:
            result["llm_response"] = llm_response
        if llm_error:
            result["llm_error"] = llm_error
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        job.status = "done"
        job.progress = 100
        job.current_step = "done"
        job.result_path = str(result_path)
        job.total_records = result["file_info"]["parse"]["total_lines"]
        job.parsed_records = result["file_info"]["parse"]["parsed_records"]

        rca_result = RcaResult(
            job_id=job.id,
            conversation_id=conversation_id,
            summary_json=result,
            llm_response=llm_response,
        )
        db.add(rca_result)

        message_content = result["markdown"]
        if llm_response:
            message_content = f"{message_content}\n\n---\n\n{llm_response}"
        elif llm_error:
            message_content = (
                f"{message_content}\n\n---\n\n"
                "### LLM RCA 생성 실패\n"
                "- Rule 기반 RCA 결과는 정상 생성되었습니다.\n"
                f"- LLM 리포트 생성 실패 사유: `{llm_error}`\n"
                "- Ollama 상태, 모델명, 모델 로딩 시간, 컨테이너의 `OLLAMA_BASE_URL` 설정을 확인하세요."
            )

        message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=message_content,
            references=[
                {
                    "filename": filename,
                    "score": result["overall"]["fail_rate"],
                    "matched_summary": False,
                    "type": "rca",
                    "job_id": job.id,
                }
            ],
        )
        db.add(message)
        await db.commit()
        await db.refresh(job)
        await db.refresh(message)

        return RcaAnalyzeResponse(
            job=RcaJobResponse.model_validate(job),
            result=result,
            message=MessageResponse.model_validate(message),
        )
    except HTTPException:
        raise
    except Exception as exc:
        job.status = "error"
        job.progress = 100
        job.current_step = "error"
        job.error_message = str(exc)
        await db.commit()
        raise HTTPException(status_code=422, detail=f"RCA 분석 실패: {exc}") from exc


@router.get("/jobs", response_model=list[RcaJobResponse])
async def list_rca_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RcaJob).order_by(RcaJob.created_at.desc()))
    return result.scalars().all()


@router.get("/jobs/{job_id}", response_model=RcaJobResponse)
async def get_rca_job(job_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RcaJob).where(RcaJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="RCA Job을 찾을 수 없습니다")
    return job


@router.get("/results/{job_id}")
async def get_rca_result(job_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RcaResult).where(RcaResult.job_id == job_id))
    rca_result = result.scalar_one_or_none()
    if not rca_result:
        raise HTTPException(status_code=404, detail="RCA 결과를 찾을 수 없습니다")
    return rca_result.summary_json
