from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from app.adapters.base import ChatResult


class AnthropicAdapter:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def _client(self):
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(api_key=self.api_key)

    def _model_name(self, model: str) -> str:
        return model.removeprefix("anthropic/")

    def _convert_messages(self, messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
        system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
        converted = [
            {
                "role": "assistant" if m.get("role") == "assistant" else "user",
                "content": m.get("content", ""),
            }
            for m in messages
            if m.get("role") != "system"
        ]
        return system, converted

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        options: dict[str, Any],
        timeout: float,
    ) -> AsyncGenerator[dict[str, Any], None]:
        system, converted = self._convert_messages(messages)
        async with self._client().messages.stream(
            model=self._model_name(model),
            system=system or None,
            messages=converted,
            temperature=options.get("temperature", 0.7),
            max_tokens=options.get("max_tokens", options.get("num_predict", 1024)),
            timeout=timeout,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    yield {"type": "token", "content": text, "raw": {}}
        yield {"type": "done", "raw": {}}

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        options: dict[str, Any],
        timeout: float,
    ) -> ChatResult:
        system, converted = self._convert_messages(messages)
        response = await self._client().messages.create(
            model=self._model_name(model),
            system=system or None,
            messages=converted,
            temperature=options.get("temperature", 0.7),
            max_tokens=options.get("max_tokens", options.get("num_predict", 1024)),
            timeout=timeout,
        )
        content = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        return ChatResult(content=content.strip(), raw=response.model_dump())
