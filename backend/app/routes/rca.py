from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Conversation, Message, RcaJob, RcaResult
from app.rca.pipeline import analyze_xdr_file
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
    if not conv_result.scalar_one_or_none():
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
        result_path = RESULT_DIR / f"rca_job_{job.id}.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result["job_id"] = job.id
        result["conversation_id"] = conversation_id
        result["result_path"] = str(result_path)
        result["markdown"] = result["markdown"].replace('"result_file": ""', f'"result_file": "{result_path}"')
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
            llm_response=None,
        )
        db.add(rca_result)

        message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=result["markdown"],
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
