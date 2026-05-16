from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ChatResult:
    content: str
    thinking: str = ""
    raw: dict[str, Any] | None = None


class ModelAdapter(Protocol):
    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        options: dict[str, Any],
        timeout: float,
    ) -> AsyncGenerator[dict[str, Any], None]:
        ...

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        options: dict[str, Any],
        timeout: float,
    ) -> ChatResult:
        ...
