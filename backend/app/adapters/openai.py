from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from app.adapters.base import ChatResult


class OpenAIAdapter:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _client(self):
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=self.api_key)

    def _model_name(self, model: str) -> str:
        return model.removeprefix("openai/")

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        options: dict[str, Any],
        timeout: float,
    ) -> AsyncGenerator[dict[str, Any], None]:
        stream = await self._client().chat.completions.create(
            model=self._model_name(model),
            messages=messages,
            temperature=options.get("temperature", 0.7),
            max_tokens=options.get("max_tokens", options.get("num_predict", 1024)),
            stream=True,
            timeout=timeout,
        )
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield {"type": "token", "content": content, "raw": chunk.model_dump()}
        yield {"type": "done", "raw": {}}

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        options: dict[str, Any],
        timeout: float,
    ) -> ChatResult:
        response = await self._client().chat.completions.create(
            model=self._model_name(model),
            messages=messages,
            temperature=options.get("temperature", 0.7),
            max_tokens=options.get("max_tokens", options.get("num_predict", 1024)),
            timeout=timeout,
        )
        content = response.choices[0].message.content or ""
        return ChatResult(content=content.strip(), raw=response.model_dump())
