from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session, get_db
from app.models import Conversation, ConversationDataset, Message, RcaDataset, RcaJob, RcaResult, XdrSchemaProfile
from app.qie.datasets import dataset_manager
from app.qie.datasets.duckdb_store import make_dataset_id
from app.rca.llm_gate import should_invoke_llm
from app.qie.datasets.parser import parse_xdr_file
from app.rca.pipeline import analyze_xdr_file
from app.rca.prompt_builder import build_llm_context, build_rca_prompt
from app.qie.schema.spec_loader import load_lte_call_kpi_spec
from app.routes.xdr_schema import active_schema_id
from app.services.llm import stream_chat as llm_stream_chat
from app.services import uce_client
from app.schemas import MessageResponse, RcaAnalyzeResponse, RcaJobResponse


router = APIRouter(prefix="/api/rca", tags=["rca"])

BASE_DIR = Path.cwd()
UPLOAD_DIR = BASE_DIR / "xdr_uploads"
RESULT_DIR = BASE_DIR / "rca_results"
RCA_LLM_OPTIONS = {"temperature": 0.1, "num_predict": 2048}
RCA_LLM_TIMEOUT_SECONDS = 1800.0
RCA_HEARTBEAT_SECONDS = 30.0
RCA_SUMMARY_STREAM_DELAY_SECONDS = 0.18
RCA_STAGE_DELAY_SECONDS = 0.8

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


def _estimate_prompt_tokens(messages: list[dict]) -> int:
    text = "\n".join(str(message.get("content", "")) for message in messages)
    return max(1, len(text) // 4) if text else 0


def _is_korean_sufficient(text: str, threshold: float = 0.15) -> bool:
    if not text:
        return False
    alpha_chars = [char for char in text if char.isalpha()]
    if not alpha_chars:
        return False
    korean_chars = [char for char in alpha_chars if "\uac00" <= char <= "\ud7a3"]
    return len(korean_chars) / len(alpha_chars) >= threshold


def _legacy_metrics(messages: list[dict], fallback_used: bool = False) -> dict:
    prompt_tokens = _estimate_prompt_tokens(messages)
    final_prompt = "\n\n".join(str(m.get("content", "")) for m in messages) if messages else None
    return {
        "use_uce": False,
        "fallback_used": fallback_used,
        "original_prompt_tokens": prompt_tokens,
        "final_prompt_tokens": prompt_tokens,
        "compression_ratio": 1.0,
        "build_context_latency_ms": 0,
        "llm_first_token_ms": None,
        "llm_total_latency_ms": None,
        "selected_context_count": 0,
        "dropped_context_count": 0,
        "intent": None,
        "topic_relation": None,
        "final_prompt": final_prompt,
    }


def _uce_metrics(result: uce_client.UceContextResult, messages: list[dict] | None = None) -> dict:
    metadata = result.metadata
    prompt_pack = result.prompt_pack
    # final_prompt includes the full system + user messages so the debug panel
    # can show the exact text sent to the LLM (not just the UCE context fragment).
    final_prompt = "\n\n".join(str(m.get("content", "")) for m in messages) if messages else None
    return {
        "use_uce": True,
        "fallback_used": False,
        "original_prompt_tokens": prompt_pack.get("original_tokens"),
        "final_prompt_tokens": prompt_pack.get("estimated_tokens"),
        "compression_ratio": metadata.get("compression_ratio"),
        "build_context_latency_ms": result.latency_ms,
        "llm_first_token_ms": None,
        "llm_total_latency_ms": None,
        "selected_context_count": metadata.get("selected_context_count", 0),
        "dropped_context_count": metadata.get("dropped_context_count", 0),
        "retrieval_confidence": metadata.get("retrieval_confidence"),
        "retrieval_warning": metadata.get("retrieval_warning"),
        "survived_items": metadata.get("survived_items", []),
        "dropped_items": metadata.get("dropped_items", []),
        "query_type": metadata.get("query_type"),
        "compression_level": metadata.get("compression_level"),
        "intent": metadata.get("primary_intent"),
        "topic_relation": metadata.get("topic_relation"),
        "final_prompt": final_prompt,
    }


async def _run_rca_job(job_id: int, use_uce: bool = False) -> None:
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

            # Pre-parse: store xDR records in DuckDB before running the full analysis pipeline.
            # This is a separate parse pass so the records are persisted even if the LLM step fails.
            dataset_id = make_dataset_id(job.filename)
            duckdb_saved = False
            try:
                fields = load_lte_call_kpi_spec()
                parsed_xdr = await asyncio.to_thread(parse_xdr_file, Path(job.file_path), fields)
                await dataset_manager.create_dataset(
                    dataset_id=dataset_id,
                    job_id=job_id,
                    conversation_id=job.conversation_id,
                    filename=job.filename,
                    file_size=job.file_size,
                    records=parsed_xdr.records,
                    fields=fields,
                )
                # MySQL RcaDataset record — upsert (같은 dataset_id가 이미 있을 수 있음)
                try:
                    from sqlalchemy.dialects.mysql import insert as mysql_insert
                    await db.execute(
                        mysql_insert(RcaDataset).values(
                            dataset_id=dataset_id,
                            job_id=job_id,
                            conversation_id=job.conversation_id,
                            filename=job.filename,
                            file_size=job.file_size,
                            record_count=parsed_xdr.stats.total_lines,
                            parsed_records=parsed_xdr.stats.parsed_records,
                            status="PROCESSING",
                            schema_id=job.schema_id,
                        ).on_duplicate_key_update(
                            job_id=job_id,
                            conversation_id=job.conversation_id,
                            file_size=job.file_size,
                            record_count=parsed_xdr.stats.total_lines,
                            parsed_records=parsed_xdr.stats.parsed_records,
                            status="PROCESSING",
                            schema_id=job.schema_id,
                        )
                    )
                    await db.commit()
                except Exception as _mysql_exc:
                    logger.warning("MySQL RcaDataset upsert 실패 (계속 진행): %s", _mysql_exc)
                    await db.rollback()
                # Auto-attach dataset to conversation (primary if no primary exists yet)
                try:
                    existing_primary = await db.execute(
                        select(ConversationDataset).where(
                            ConversationDataset.conversation_id == job.conversation_id,
                            ConversationDataset.is_primary == True,
                        )
                    )
                    has_primary = existing_primary.scalar_one_or_none() is not None
                    # INSERT IGNORE equivalent: upsert with no-op on conflict
                    from sqlalchemy.dialects.mysql import insert as mysql_insert
                    await db.execute(
                        mysql_insert(ConversationDataset)
                        .values(
                            conversation_id=job.conversation_id,
                            dataset_id=dataset_id,
                            is_primary=not has_primary,
                        )
                        .on_duplicate_key_update(dataset_id=dataset_id)  # no-op on conflict
                    )
                    await db.commit()
                except Exception:
                    logger.warning("ConversationDataset auto-attach 실패 (계속 진행)")
                    await db.rollback()
                duckdb_saved = True
            except Exception:
                logging.getLogger(__name__).exception(
                    "DuckDB pre-parse failed for job %d; continuing with legacy pipeline", job_id
                )

            summary = analyze_xdr_file(Path(job.file_path), job.filename)

            await _update_job(db, job_id, status="aggregating", progress=65, current_step="aggregating")
            _publish(job_id, {"step": "aggregating", "progress": 65, "status": "aggregating"})
            for line in summary["markdown"].splitlines():
                _publish(job_id, {"step": "summary_token", "progress": 70, "token": f"{line}\n"})
                await asyncio.sleep(RCA_SUMMARY_STREAM_DELAY_SECONDS)
            _publish(job_id, {"step": "summary_done", "progress": 78, "status": "aggregating"})

            _publish(job_id, {"step": "llm_prepare", "progress": 80})
            llm_response = ""
            thinking = ""
            done_raw: dict | None = None
            llm_error = None
            language_validation_passed: bool | None = None
            invoke_llm, llm_gate_reason = should_invoke_llm(summary)
            prompt_metrics = _legacy_metrics([])

            if not invoke_llm:
                status = "bypassed_healthy" if summary.get("analysis_mode") == "healthy" else "bypassed_confirmed"
                summary["llm_explanation_status"] = status
                summary["llm_bypass_reason"] = llm_gate_reason
                _publish(
                    job_id,
                    {
                        "step": "llm_bypassed",
                        "progress": 85,
                        "status": "deterministic",
                        "reason": llm_gate_reason,
                    },
                )
            else:
                await asyncio.sleep(RCA_STAGE_DELAY_SECONDS)
                messages = build_rca_prompt(summary)
                _publish(job_id, {"step": "llm_prepare", "progress": 82})
                await asyncio.sleep(RCA_STAGE_DELAY_SECONDS)
                legacy_messages = list(messages)
                prompt_metrics = _legacy_metrics(legacy_messages)

                if use_uce and settings.uce_enabled:
                    try:
                        compact_context = json.dumps(build_llm_context(summary), ensure_ascii=False)
                        # Pass empty current_message to activate UCE's "summarize all sections by
                        # importance" mode — no query-based section dropping, all RCA sections
                        # preserved and compressed by semantic importance ordering.
                        uce_result = await uce_client.build_context(
                            conversation_id=job.conversation_id,
                            current_message="",
                            recent_messages=[],
                            rag_chunks=[
                                {
                                    "id": f"rca_context_{job_id}",
                                    "title": f"RCA 구조화 컨텍스트: {job.filename}",
                                    "content": compact_context,
                                    "source": job.filename,
                                    "importance": 0.95,
                                    "content_type": "json",
                                },
                                {
                                    "id": f"rca_summary_{job_id}",
                                    "title": f"RCA 분석 요약: {job.filename}",
                                    "content": summary["markdown"],
                                    "source": job.filename,
                                    "importance": 0.85,
                                    "content_type": "markdown",
                                },
                            ],
                            model=conversation.model,
                        )
                        # Keep the RCA expert system prompt; replace only the user context
                        # with the UCE-optimized version.
                        rca_system = build_rca_prompt(summary)[0]
                        messages = [
                            rca_system,
                            {"role": "user", "content": uce_result.prompt_pack["content"]},
                        ]
                        prompt_metrics = _uce_metrics(uce_result, messages)
                    except Exception:
                        logging.getLogger(__name__).exception("UCE failed in RCA flow; falling back to compressed prompt")
                        messages = legacy_messages
                        prompt_metrics = _legacy_metrics(legacy_messages, fallback_used=True)

                await _update_job(db, job_id, status="llm", progress=85, current_step="llm")
                _publish(
                    job_id,
                    {
                        "step": "llm",
                        "progress": 85,
                        "status": "llm",
                    },
                )

                stream_started = time.perf_counter()
                first_token_seen = False
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
                        if not first_token_seen:
                            prompt_metrics["llm_first_token_ms"] = int((time.perf_counter() - stream_started) * 1000)
                            first_token_seen = True
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
                prompt_metrics["llm_total_latency_ms"] = int((time.perf_counter() - stream_started) * 1000)
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

                if llm_response:
                    language_validation_passed = _is_korean_sufficient(llm_response)
                    if not language_validation_passed:
                        summary["llm_error"] = "language_control_failure: LLM returned non-Korean output"
                        summary["llm_explanation_status"] = "language_fallback"
                        llm_response = ""

            result_path = RESULT_DIR / f"rca_job_{job_id}.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            summary["job_id"] = job_id
            summary["conversation_id"] = job.conversation_id
            summary["result_path"] = str(result_path)
            if llm_response:
                summary["llm_response"] = llm_response
                summary["llm_explanation_status"] = "done"
            if llm_error and summary.get("llm_explanation_status") != "language_fallback":
                summary["llm_error"] = llm_error
                summary["llm_explanation_status"] = "error"
            summary["uce_metrics"] = prompt_metrics
            processing_metrics = summary.setdefault("processing_metrics", {})
            processing_metrics["llm_total_latency_ms"] = prompt_metrics.get("llm_total_latency_ms")
            processing_metrics["llm_first_token_ms"] = prompt_metrics.get("llm_first_token_ms")
            processing_metrics["llm_invoked"] = invoke_llm
            processing_metrics["llm_bypass_reason"] = None if invoke_llm else llm_gate_reason
            processing_metrics["llm_prompt_tokens"] = prompt_metrics.get("final_prompt_tokens") if invoke_llm else None
            processing_metrics["llm_explanation_status"] = summary.get("llm_explanation_status")
            processing_metrics["language_validation_passed"] = language_validation_passed
            processing_metrics["final_result_json_bytes"] = len(
                json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8")
            )
            input_bytes = processing_metrics.get("input_xdr_bytes") or 0
            final_bytes = processing_metrics["final_result_json_bytes"]
            processing_metrics["xdr_to_final_json_ratio"] = round(final_bytes / input_bytes, 6) if input_bytes else None
            processing_metrics["final_reduction_ratio"] = round(1 - (final_bytes / input_bytes), 6) if input_bytes else None

            # DuckDB summary (lightweight — only store if DuckDB save succeeded)
            if duckdb_saved:
                try:
                    await dataset_manager.store_summary(dataset_id, summary)
                    period_start = (summary.get("file_info") or {}).get("period", {}).get("start_us")
                    period_end = (summary.get("file_info") or {}).get("period", {}).get("end_us")
                    # Update MySQL RcaDataset with final stats
                    ds_result = await db.execute(
                        select(RcaDataset).where(RcaDataset.dataset_id == dataset_id)
                    )
                    ds = ds_result.scalar_one_or_none()
                    if ds:
                        ds.period_start = period_start
                        ds.period_end = period_end
                        ds.record_count = summary["file_info"]["parse"]["total_lines"]
                        ds.parsed_records = summary["file_info"]["parse"]["parsed_records"]
                        ds.status = "READY"
                        ds.schema_id = job.schema_id
                        await db.commit()
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Failed to update DuckDB summary / RcaDataset for %s", dataset_id
                    )

            upload_path = Path(job.file_path)
            deleted_upload = False
            delete_error = None
            # Only delete the upload file after DuckDB persistence is confirmed.
            if duckdb_saved and upload_path.exists():
                try:
                    upload_path.unlink()
                    deleted_upload = True
                except OSError as exc:
                    delete_error = str(exc)
            elif not duckdb_saved and upload_path.exists():
                # DuckDB save failed; keep the file so the user can retry.
                delete_error = "DuckDB save failed — upload file retained"
            processing_metrics["upload_file_deleted"] = deleted_upload
            processing_metrics["upload_file_delete_error"] = delete_error
            for _ in range(3):
                result_payload = json.dumps(summary, ensure_ascii=False, indent=2)
                final_size = len(result_payload.encode("utf-8"))
                if (
                    processing_metrics.get("final_result_json_bytes") == final_size
                    and processing_metrics.get("result_file_bytes") == final_size
                ):
                    break
                processing_metrics["final_result_json_bytes"] = final_size
                processing_metrics["result_file_bytes"] = final_size
                processing_metrics["xdr_to_final_json_ratio"] = round(final_size / input_bytes, 6) if input_bytes else None
                processing_metrics["final_reduction_ratio"] = round(1 - (final_size / input_bytes), 6) if input_bytes else None
            result_path.write_text(result_payload, encoding="utf-8")
            prompt_metrics["rca_processing"] = processing_metrics

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
            elif llm_error and summary.get("llm_explanation_status") != "language_fallback":
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
                metrics=prompt_metrics,
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
                    "metadata": prompt_metrics,
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
    use_uce: bool = Form(False),
    schema_id: int | None = Form(None),
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

    selected_schema_id = schema_id or await active_schema_id(db)
    schema_result = await db.execute(
        select(XdrSchemaProfile).where(XdrSchemaProfile.id == selected_schema_id)
    )
    if not schema_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="xDR 스키마를 찾을 수 없습니다")

    job = RcaJob(
        conversation_id=conversation_id,
        filename=filename,
        file_size=0,
        file_path="",
        status="queued",
        progress=0,
        current_step="uploading",
        schema_id=selected_schema_id,
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
        background_tasks.add_task(_run_rca_job, job.id, use_uce)
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


# ---------------------------------------------------------------------------
# Dataset management endpoints (Phase 1)
# ---------------------------------------------------------------------------

@router.get("/datasets")
async def list_datasets(conversation_id: int | None = None, db: AsyncSession = Depends(get_db)):
    datasets = await dataset_manager.list_datasets(conversation_id)
    ids = [dataset.get("dataset_id") for dataset in datasets if dataset.get("dataset_id")]
    if not ids:
        return datasets
    result = await db.execute(
        select(RcaDataset, XdrSchemaProfile)
        .outerjoin(XdrSchemaProfile, XdrSchemaProfile.id == RcaDataset.schema_id)
        .where(RcaDataset.dataset_id.in_(ids))
    )
    schema_map = {
        ds.dataset_id: {
            "schema_id": ds.schema_id,
            "schema_name": profile.name if profile else None,
        }
        for ds, profile in result.all()
    }
    for dataset in datasets:
        dataset.update(schema_map.get(dataset.get("dataset_id"), {"schema_id": None, "schema_name": None}))
    return datasets


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    meta = await dataset_manager.get_dataset_info(dataset_id)
    if not meta:
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
    return meta


@router.get("/datasets/{dataset_id}/summary")
async def get_dataset_summary(dataset_id: str):
    summary = await dataset_manager.get_summary(dataset_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="데이터셋 요약을 찾을 수 없습니다")
    return summary


@router.get("/datasets/{dataset_id}/detail")
async def get_dataset_detail(dataset_id: str):
    """인터페이스별/원인별 실패 통계 — DuckDB 직접 집계."""
    import asyncio as _asyncio
    from app.qie.datasets.duckdb_store import query_records

    table = f"xdr_{dataset_id}"
    base_where = f"WHERE attempt_flag='1' AND success_flag='0'"

    async def _run(sql: str) -> list[dict]:
        try:
            return await _asyncio.to_thread(query_records, dataset_id, sql)
        except Exception:
            return []

    by_interface, by_cause = await _asyncio.gather(
        _run(
            f'SELECT first_error_interface_protocol AS interface, COUNT(*) AS cnt '
            f'FROM "{table}" {base_where} '
            f'GROUP BY first_error_interface_protocol ORDER BY cnt DESC LIMIT 10'
        ),
        _run(
            f'SELECT first_error_cause AS cause, COUNT(*) AS cnt '
            f'FROM "{table}" {base_where} '
            f'GROUP BY first_error_cause ORDER BY cnt DESC LIMIT 10'
        ),
    )
    return {"by_interface": by_interface, "by_cause": by_cause}


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)):
    meta = await dataset_manager.get_dataset_info(dataset_id)
    if not meta:
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
    await dataset_manager.delete_dataset(dataset_id)
    # Remove all conversation attachments and the dataset record
    att_result = await db.execute(
        select(ConversationDataset).where(ConversationDataset.dataset_id == dataset_id)
    )
    for att in att_result.scalars().all():
        await db.delete(att)
    result = await db.execute(select(RcaDataset).where(RcaDataset.dataset_id == dataset_id))
    ds = result.scalar_one_or_none()
    if ds:
        await db.delete(ds)
    await db.commit()


# ---------------------------------------------------------------------------
# Conversation ↔ Dataset attachment endpoints
# ---------------------------------------------------------------------------

@router.get("/conversations/{conversation_id}/datasets")
async def list_conversation_datasets(conversation_id: int, db: AsyncSession = Depends(get_db)):
    """Return datasets attached to a conversation, primary first."""
    result = await db.execute(
        select(ConversationDataset, RcaDataset)
        .join(RcaDataset, RcaDataset.dataset_id == ConversationDataset.dataset_id)
        .where(ConversationDataset.conversation_id == conversation_id)
        .order_by(ConversationDataset.is_primary.desc(), ConversationDataset.attached_at.desc())
    )
    rows = result.all()
    out = []
    for att, ds in rows:
        item = {
            "id": ds.id,
            "dataset_id": ds.dataset_id,
            "filename": ds.filename,
            "file_size": ds.file_size,
            "record_count": ds.record_count,
            "parsed_records": ds.parsed_records,
            "period_start": ds.period_start,
            "period_end": ds.period_end,
            "status": ds.status,
            "schema_id": ds.schema_id,
            "schema_name": None,
            "is_primary": att.is_primary,
            "attached_at": att.attached_at.isoformat() if att.attached_at else None,
            "created_at": ds.created_at.isoformat() if ds.created_at else None,
        }
        if ds.schema_id:
            schema = await db.execute(select(XdrSchemaProfile).where(XdrSchemaProfile.id == ds.schema_id))
            profile = schema.scalar_one_or_none()
            item["schema_name"] = profile.name if profile else None
        out.append(item)
    return out


@router.post("/conversations/{conversation_id}/datasets/{dataset_id}", status_code=201)
async def attach_dataset(
    conversation_id: int,
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Attach an existing dataset to a conversation."""
    # Verify dataset exists
    ds_res = await db.execute(select(RcaDataset).where(RcaDataset.dataset_id == dataset_id))
    if not ds_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
    # Determine if this should be primary
    existing = await db.execute(
        select(ConversationDataset).where(
            ConversationDataset.conversation_id == conversation_id,
            ConversationDataset.is_primary == True,
        )
    )
    has_primary = existing.scalar_one_or_none() is not None
    from sqlalchemy.dialects.mysql import insert as mysql_insert
    await db.execute(
        mysql_insert(ConversationDataset)
        .values(
            conversation_id=conversation_id,
            dataset_id=dataset_id,
            is_primary=not has_primary,
        )
        .on_duplicate_key_update(dataset_id=dataset_id)  # no-op if already attached
    )
    await db.commit()
    return {"conversation_id": conversation_id, "dataset_id": dataset_id, "is_primary": not has_primary}


@router.delete("/conversations/{conversation_id}/datasets/{dataset_id}", status_code=204)
async def detach_dataset(
    conversation_id: int,
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Detach a dataset from a conversation WITHOUT deleting the dataset."""
    result = await db.execute(
        select(ConversationDataset).where(
            ConversationDataset.conversation_id == conversation_id,
            ConversationDataset.dataset_id == dataset_id,
        )
    )
    att = result.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="이 대화에 해당 데이터셋이 첨부되어 있지 않습니다")
    was_primary = att.is_primary
    await db.delete(att)
    # If detached was primary, promote the next attachment
    if was_primary:
        next_res = await db.execute(
            select(ConversationDataset)
            .where(ConversationDataset.conversation_id == conversation_id)
            .order_by(ConversationDataset.attached_at.desc())
            .limit(1)
        )
        next_att = next_res.scalar_one_or_none()
        if next_att:
            next_att.is_primary = True
    await db.commit()


@router.patch("/conversations/{conversation_id}/datasets/{dataset_id}/primary", status_code=200)
async def set_primary_dataset(
    conversation_id: int,
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Promote a dataset to primary for a conversation."""
    # Demote all current primaries
    all_res = await db.execute(
        select(ConversationDataset).where(
            ConversationDataset.conversation_id == conversation_id,
            ConversationDataset.is_primary == True,
        )
    )
    for att in all_res.scalars().all():
        att.is_primary = False
    # Promote target
    target_res = await db.execute(
        select(ConversationDataset).where(
            ConversationDataset.conversation_id == conversation_id,
            ConversationDataset.dataset_id == dataset_id,
        )
    )
    target = target_res.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="이 대화에 해당 데이터셋이 첨부되어 있지 않습니다")
    target.is_primary = True
    await db.commit()
    return {"conversation_id": conversation_id, "dataset_id": dataset_id, "is_primary": True}
