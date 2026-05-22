import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class DpeProcessResult:
    def __init__(self, data: dict):
        self.normalized_content: str = data["normalized_content"]
        self.structure_type: str = data["structure_type"]
        self.structure_confidence: float = data["structure_confidence"]
        self.chunk_strategy: str = data["chunk_strategy"]
        self.normalization_applied: bool = data["normalization_applied"]
        self.normalization_model: str | None = data.get("normalization_model")
        self.normalization_skipped_reason: str | None = data.get("normalization_skipped_reason")
        self.retrieval_hints: list[str] = data.get("retrieval_hints", [])
        self.metadata_version: int = data.get("metadata_version", 1)
        self.content_type: str = data.get("content_type", "text")
        self.denoised_content: str | None = data.get("denoised_content")

    def to_metadata_dict(self) -> dict:
        return {
            "structure_type": self.structure_type,
            "structure_confidence": self.structure_confidence,
            "chunk_strategy": self.chunk_strategy,
            "normalization_applied": self.normalization_applied,
            "normalization_model": self.normalization_model,
            "normalization_skipped_reason": self.normalization_skipped_reason,
            "retrieval_hints": self.retrieval_hints,
            "metadata_version": self.metadata_version,
            "content_type": self.content_type,
        }


async def call_dpe_process(
    document_id: str,
    filename: str,
    content: str,
    normalization_enabled: bool | None = None,
    normalization_model: str | None = None,
) -> DpeProcessResult | None:
    """
    DPE /process 호출. 실패 시 None 반환.
    None이면 호출자가 기존 로직으로 fallback한다.
    """
    if not settings.dpe_enabled:
        return None

    payload = {
        "document_id": document_id,
        "filename": filename,
        "content": content,
        "options": {
            "normalization_enabled": (
                settings.dpe_normalization_enabled
                if normalization_enabled is None
                else normalization_enabled
            ),
            "normalization_model": normalization_model,
            "backend_normalize_url": f"{settings.dpe_backend_self_url}/api/normalize",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=settings.dpe_timeout_seconds) as client:
            resp = await client.post(f"{settings.dpe_base_url}/process", json=payload)
            resp.raise_for_status()
            return DpeProcessResult(resp.json())
    except Exception as e:
        logger.warning(
            "DPE 호출 실패 (document_id=%s, filename=%s): %s", document_id, filename, e
        )
        return None
