from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.adapters.base import ChatResult


class OllamaAdapter:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _model_name(self, model: str) -> str:
        return model.removeprefix("ollama/")

    def _options(self, options: dict[str, Any]) -> dict[str, Any]:
        merged = {
            "temperature": options.get("temperature", 0.7),
        }
        if "num_predict" in options:
            merged["num_predict"] = options["num_predict"]
        elif "max_tokens" in options:
            merged["num_predict"] = options["max_tokens"]
        return merged

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        options: dict[str, Any],
        timeout: float,
    ) -> AsyncGenerator[dict[str, Any], None]:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": self._model_name(model),
                    "messages": messages,
                    "stream": True,
                    "options": self._options(options),
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    msg = chunk.get("message", {})
                    thinking = msg.get("thinking", "")
                    content = msg.get("content", "")
                    if thinking:
                        yield {"type": "thinking", "content": thinking, "raw": chunk}
                    if content:
                        yield {"type": "token", "content": content, "raw": chunk}
                    if chunk.get("done"):
                        yield {"type": "done", "raw": chunk}
                        break

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        options: dict[str, Any],
        timeout: float,
    ) -> ChatResult:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self._model_name(model),
                    "messages": messages,
                    "stream": False,
                    "options": self._options(options),
                },
            )
            response.raise_for_status()
            data = response.json()
            msg = data.get("message", {})
            return ChatResult(
                content=(msg.get("content") or "").strip(),
                thinking=msg.get("thinking") or "",
                raw=data,
            )
