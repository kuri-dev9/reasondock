from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings


class UceError(Exception):
    pass


@dataclass(frozen=True)
class UceContextResult:
    prompt_pack: dict[str, Any]
    metadata: dict[str, Any]
    compressed_context: dict[str, Any]
    conversation_state: dict[str, Any]
    latency_ms: int


def _message_to_uce(message: Any) -> dict[str, str]:
    return {
        "role": getattr(message, "role", "user") or "user",
        "content": getattr(message, "content", "") or "",
    }


def _chunk_to_document(chunk: dict[str, Any], index: int) -> dict[str, Any]:
    content = str(chunk.get("content") or "")
    title = str(chunk.get("title") or chunk.get("filename") or "RAG Chunk")
    source = str(chunk.get("source") or chunk.get("filename") or "vector_store")
    content_type = str(chunk.get("content_type") or "")
    if not content_type:
        if chunk.get("normalization_applied"):
            content_type = "dpe_ir"
        elif chunk.get("chunk_strategy") == "heading-aware":
            content_type = "markdown"
        elif chunk.get("structure_type") in {"code", "json", "yaml", "log"}:
            content_type = str(chunk["structure_type"])
        elif any(name.lower().endswith((".md", ".markdown")) for name in (title, source)):
            content_type = "markdown"
        elif content.lstrip().startswith("#"):
            content_type = "markdown"
        else:
            content_type = "text"
    return {
        "id": str(chunk.get("id") or chunk.get("chunk_id") or f"rag_chunk_{index + 1}"),
        "title": title,
        "content": content,
        "content_type": content_type,
        "source": source,
        "importance": float(chunk.get("importance", 0.75)),
    }


async def build_context(
    *,
    conversation_id: int,
    current_message: str,
    recent_messages: list[Any],
    rag_chunks: list[dict[str, Any]],
    model: str,
    rag_context: str = "",
    previous_state: dict[str, Any] | None = None,
) -> UceContextResult:
    documents = [_chunk_to_document(chunk, index) for index, chunk in enumerate(rag_chunks)]
    if rag_context.strip():
        documents.insert(
            0,
            {
                "id": "knowledge_rag_context",
                "title": "Knowledge Search Results",
                "content": rag_context,
                "content_type": "markdown" if "#" in rag_context else "text",
                "source": "knowledge_store",
                "importance": 1.0,
            },
        )

    payload = {
        "session_id": str(conversation_id),
        "current_message": {
            "role": "user",
            "content": current_message,
        },
        "recent_messages": [_message_to_uce(message) for message in recent_messages[-15:]],
        "previous_state": previous_state,
        "documents": documents,
        "options": {
            "target_model": model,
            "compression_level": "medium",
            "include_trace": True,
        },
    }

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.uce_timeout_seconds) as client:
            response = await client.post(f"{settings.uce_base_url.rstrip('/')}/build-context", json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise UceError(str(exc)) from exc

    prompt_pack = data.get("prompt_pack") or {}
    if not isinstance(prompt_pack, dict) or not prompt_pack.get("content"):
        raise UceError("UCE response did not include prompt_pack.content")

    return UceContextResult(
        prompt_pack=prompt_pack,
        metadata=data.get("metadata") or {},
        compressed_context=data.get("compressed_context") or {},
        conversation_state=data.get("conversation_state") or {},
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
