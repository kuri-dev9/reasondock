import httpx


class BackendClient:
    def __init__(self, timeout: float = 120.0):
        self._timeout = timeout

    async def call_normalize(
        self,
        url: str,
        content: str,
        structure_type: str,
        filename: str,
        model: str | None = None,
    ) -> dict:
        """
        Returns: {"normalized_content": str, "model_used": str}
        Raises: httpx.HTTPError on HTTP error, Exception on other failures
        """
        payload = {
            "content": content,
            "structure_type": structure_type,
            "filename": filename,
        }
        if model:
            payload["model"] = model

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()


_default_client = BackendClient()
