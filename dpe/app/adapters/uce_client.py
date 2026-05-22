import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


async def call_uce_denoise(
    content: str,
    content_type: str = "text",
    document_id: str | None = None,
    title: str | None = None,
) -> str | None:
    """
    UCE /denoise 호출.
    실패 시 None 반환 → 호출자가 원문 사용.
    """
    if not getattr(settings, "uce_base_url", None):
        return None

    payload = {
        "document_id": document_id,
        "content": content,
        "content_type": content_type,
        "title": title,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.uce_base_url.rstrip('/')}/denoise",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            denoised = data.get("denoised_content", "").strip()
            if not denoised:
                return None
            logger.info(
                "UCE denoise: doc_id=%s original=%d denoised=%d reduction=%.1f%%",
                document_id,
                data.get("original_chars", 0),
                data.get("denoised_chars", 0),
                data.get("reduction_ratio", 0) * 100,
            )
            return denoised
    except Exception as e:
        logger.warning("UCE denoise 호출 실패 (doc_id=%s): %s", document_id, e)
        return None
