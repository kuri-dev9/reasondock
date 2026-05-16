from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from app.adapters import get_adapter


class LLMError(Exception):
    def __init__(self, reason: str, detail: str = "", raw: dict | None = None):
        self.reason = reason
        self.detail = detail
        self.raw = raw or {}
        super().__init__(f"[{reason}] {detail}")


_chat_semaphore = asyncio.Semaphore(3)
_rca_semaphore = asyncio.Semaphore(1)


def _raw_diagnostics(raw: dict | None, thinking: str = "") -> dict[str, Any]:
    raw = raw or {}
    diagnostic = {
        "done": raw.get("done"),
        "done_reason": raw.get("done_reason"),
        "eval_count": raw.get("eval_count"),
        "prompt_eval_count": raw.get("prompt_eval_count"),
    }
    if thinking:
        diagnostic["thinking_preview"] = thinking[:500]
        diagnostic["thinking_chars"] = len(thinking)
    return {key: value for key, value in diagnostic.items() if value is not None}


def _classify_empty_response(raw: dict | None, thinking: str = "") -> LLMError:
    diagnostics = _raw_diagnostics(raw, thinking)
    if diagnostics.get("done_reason") == "length":
        return LLMError("context_exceeded", "LLM 컨텍스트 또는 생성 길이 제한에 도달했습니다.", diagnostics)
    if thinking:
        return LLMError("thinking_only", "LLM이 thinking만 반환하고 최종 content를 비웠습니다.", diagnostics)
    return LLMError("empty_response", "LLM 최종 응답이 비어 있습니다.", diagnostics)


async def stream_chat(
    model: str,
    messages: list[dict],
    options: dict | None = None,
    timeout: float = 300.0,
) -> AsyncGenerator[dict, None]:
    async with _chat_semaphore:
        adapter = get_adapter(model)
        try:
            async for event in adapter.stream_chat(messages, model, options or {}, timeout):
                if event.get("type") in {"thinking", "token", "done"}:
                    yield event
        except Exception as exc:
            yield {"type": "error", "content": str(exc)}


async def chat(
    model: str,
    messages: list[dict],
    options: dict | None = None,
    timeout: float = 1800.0,
) -> str:
    async with _rca_semaphore:
        adapter = get_adapter(model)
        try:
            result = await adapter.chat(messages, model, options or {}, timeout)
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("provider_error", str(exc)) from exc

        if result.content:
            return result.content
        raise _classify_empty_response(result.raw, result.thinking)
