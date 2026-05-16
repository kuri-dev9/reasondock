from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.models import Conversation, Message, RcaJob, RcaResult
from app.rca.pipeline import analyze_xdr_file
from app.rca.prompt_builder import build_rca_prompt
from app.services.llm import stream_chat as llm_stream_chat
from app.schemas import MessageResponse, RcaAnalyzeResponse, RcaJobResponse


router = APIRouter(prefix="/api/rca", tags=["rca"])

BASE_DIR = Path.cwd()
UPLOAD_DIR = BASE_DIR / "xdr_uploads"
RESULT_DIR = BASE_DIR / "rca_results"
RCA_LLM_OPTIONS = {"temperature": 0.1, "num_predict": 8192}
RCA_LLM_TIMEOUT_SECONDS = 1800.0
RCA_HEARTBEAT_SECONDS = 30.0

_event_history: dict[int, list[dict[str, Any]]] = {}
_event_queues: dict[int, set[asyncio.Queue[dict[str, Any]]]] = {}


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


def _publish(job_id: int, event: dict[str, Any]) -> None:
    event = {"job_id": job_id, **event}
    _event_history.setdefault(job_id, []).append(event)
    for queue in _event_queues.get(job_id, set()).copy():
        queue.put_nowait(event)


async def _update_job(
    db: AsyncSession,
    job_id: int,
    *,
    status: str,
    progress: int,
    current_step: str,
    error_message: str | None = None,
) -> RcaJob:
    result = await db.execute(select(RcaJob).where(RcaJob.id == job_id))
    job = result.scalar_one()
    job.status = status
    job.progress = progress
    job.current_step = current_step
    if error_message is not None:
        job.error_message = error_message
    await db.commit()
    return job


def _failure_message(markdown: str, llm_error: str) -> str:
    return (
        f"{markdown}\n\n---\n\n"
        "### LLM RCA 생성 실패\n"
        "- Rule 기반 RCA 결과는 정상 생성되었습니다.\n"
        f"- LLM 리포트 생성 실패 사유: `{llm_error}`\n"
        "- Ollama 상태, 모델명, 모델 로딩 시간, 컨테이너의 `OLLAMA_BASE_URL` 설정을 확인하세요."
    )


def _llm_stream_error(reason: str, detail: str, raw: dict | None = None) -> str:
    diagnostic = {
        key: value
        for key, value in (raw or {}).items()
        if key in {"done", "done_reason", "eval_count", "prompt_eval_count"}
    }
    if diagnostic:
        return f"{reason}: {detail} (raw={diagnostic})"
    return f"{reason}: {detail}"


async def _run_rca_job(job_id: int) -> None:
    async with async_session() as db:
        try:
            result = await db.execute(select(RcaJob).where(RcaJob.id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                return
            conv_result = await db.execute(
                select(Conversation).where(Conversation.id == job.conversation_id)
            )
            conversation = conv_result.scalar_one_or_none()
            if not conversation:
                raise ValueError("대화를 찾을 수 없습니다")

            await _update_job(db, job_id, status="parsing", progress=20, current_step="parsing")
            _publish(job_id, {"step": "parsing", "progress": 20, "status": "parsing"})

            summary = analyze_xdr_file(Path(job.file_path), job.filename)

            await _update_job(db, job_id, status="aggregating", progress=65, current_step="aggregating")
            _publish(
                job_id,
                {
                    "step": "aggregating",
                    "progress": 65,
                    "status": "aggregating",
                    "content": summary["markdown"],
                },
            )

            prompt = build_rca_prompt(summary)
            messages = [
                {
                    "role": "system",
                    "content": "You are an LTE/EPC RCA expert. Return a grounded Korean RCA report.",
                },
                {"role": "user", "content": prompt},
            ]

            await _update_job(db, job_id, status="llm", progress=85, current_step="llm")
            _publish(job_id, {"step": "llm", "progress": 85, "status": "llm"})

            llm_response = ""
            thinking = ""
            done_raw: dict | None = None
            llm_error = None
            async for event in llm_stream_chat(
                conversation.model,
                messages,
                options=RCA_LLM_OPTIONS,
                timeout=RCA_LLM_TIMEOUT_SECONDS,
            ):
                event_type = event.get("type")
                if event_type == "thinking":
                    thinking += event.get("content", "")
                elif event_type == "token":
                    token = event.get("content", "")
                    llm_response += token
                    _publish(job_id, {"step": "llm_token", "progress": 90, "token": token})
                elif event_type == "done":
                    done_raw = event.get("raw") or {}
                elif event_type == "error":
                    llm_error = _llm_stream_error(
                        "provider_error",
                        event.get("content", "LLM streaming 오류"),
                    )

            llm_response = llm_response.strip()
            if not llm_response and not llm_error:
                done_reason = (done_raw or {}).get("done_reason")
                if done_reason == "length":
                    llm_error = _llm_stream_error(
                        "context_exceeded",
                        "LLM 입력 컨텍스트 또는 생성 길이 제한에 도달했습니다.",
                        done_raw,
                    )
                elif thinking:
                    llm_error = _llm_stream_error(
                        "thinking_only",
                        "LLM이 thinking만 반환하고 최종 content를 비웠습니다.",
                        done_raw,
                    )
                else:
                    llm_error = _llm_stream_error("empty_response", "LLM 최종 응답이 비어 있습니다.", done_raw)

            result_path = RESULT_DIR / f"rca_job_{job_id}.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            summary["job_id"] = job_id
            summary["conversation_id"] = job.conversation_id
            summary["result_path"] = str(result_path)
            if llm_response:
                summary["llm_response"] = llm_response
            if llm_error:
                summary["llm_error"] = llm_error
            result_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            result = await db.execute(select(RcaJob).where(RcaJob.id == job_id))
            job = result.scalar_one()
            job.status = "done"
            job.progress = 100
            job.current_step = "done"
            job.result_path = str(result_path)
            job.total_records = summary["file_info"]["parse"]["total_lines"]
            job.parsed_records = summary["file_info"]["parse"]["parsed_records"]

            rca_result = RcaResult(
                job_id=job_id,
                conversation_id=job.conversation_id,
                summary_json=summary,
                llm_response=llm_response or None,
            )
            db.add(rca_result)

            message_content = summary["markdown"]
            if llm_response:
                message_content = f"{message_content}\n\n---\n\n{llm_response}"
            elif llm_error:
                message_content = _failure_message(summary["markdown"], llm_error)

            message = Message(
                conversation_id=job.conversation_id,
                role="assistant",
                content=message_content,
                references=[
                    {
                        "filename": job.filename,
                        "score": summary["overall"]["fail_rate"],
                        "matched_summary": False,
                        "type": "rca",
                        "job_id": job_id,
                    }
                ],
            )
            db.add(message)
            await db.commit()
            await db.refresh(message)
            _publish(
                job_id,
                {
                    "step": "done",
                    "progress": 100,
                    "status": "done",
                    "message_id": message.id,
                    "message": MessageResponse.model_validate(message).model_dump(mode="json"),
                },
            )
        except Exception as exc:
            await _update_job(
                db,
                job_id,
                status="error",
                progress=100,
                current_step="error",
                error_message=str(exc),
            )
            _publish(
                job_id,
                {
                    "step": "error",
                    "progress": 100,
                    "status": "error",
                    "error": str(exc),
                },
            )


@router.post("/jobs", response_model=RcaAnalyzeResponse)
async def create_rca_job(
    background_tasks: BackgroundTasks,
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
        job.status = "queued"
        job.progress = 5
        job.current_step = "queued"
        await db.commit()
        await db.refresh(job)
        _publish(job.id, {"step": "queued", "progress": 5, "status": "queued"})
        background_tasks.add_task(_run_rca_job, job.id)
        return RcaAnalyzeResponse(
            job=RcaJobResponse.model_validate(job),
            result=None,
            message=None,
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


@router.get("/jobs/{job_id}/stream")
async def stream_rca_job(job_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RcaJob).where(RcaJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="RCA Job을 찾을 수 없습니다")

    async def event_generator():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        initial_history = list(_event_history.get(job_id, []))
        _event_queues.setdefault(job_id, set()).add(queue)
        history_index = 0
        try:
            while True:
                while history_index < len(initial_history):
                    event = initial_history[history_index]
                    history_index += 1
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("step") in {"done", "error"}:
                        return

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=RCA_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("step") in {"done", "error"}:
                    return
        finally:
            queues = _event_queues.get(job_id)
            if queues:
                queues.discard(queue)
                if not queues:
                    _event_queues.pop(job_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
