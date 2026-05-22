import time
import logging
from fastapi import APIRouter, HTTPException
from app.api.schemas import ProcessRequest, DocumentProcessResult
from app.core.processor import process
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()
_start_time = time.time()


@router.post("/process", response_model=DocumentProcessResult)
async def process_document(request: ProcessRequest):
    try:
        return await process(request)
    except Exception as e:
        logger.exception("처리 실패 (document_id=%s)", request.document_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@router.get("/status")
async def status():
    return {
        "normalization_enabled": settings.dpe_normalization_enabled,
        "min_confidence_threshold": settings.dpe_normalization_min_confidence,
        "max_chars_for_normalization": settings.dpe_normalization_max_chars,
        "uptime_seconds": int(time.time() - _start_time),
    }
