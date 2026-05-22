import logging
from app.adapters.backend_client import BackendClient

logger = logging.getLogger(__name__)


class Normalizer:
    def __init__(self, client: BackendClient):
        self._client = client

    async def normalize(
        self,
        content: str,
        structure_type: str,
        filename: str,
        backend_normalize_url: str,
        model: str | None = None,
    ) -> tuple[str, str | None]:
        """
        Returns (normalized_content, model_used).
        Raises on failure — caller is responsible for fallback.
        """
        data = await self._client.call_normalize(
            url=backend_normalize_url,
            content=content,
            structure_type=structure_type,
            filename=filename,
            model=model,
        )
        normalized = data.get("normalized_content", "").strip()
        model_used = data.get("model_used")

        if not normalized:
            logger.warning("normalize 응답이 비어있음 (filename=%s), 원본 유지", filename)
            return content, None

        return normalized, model_used
