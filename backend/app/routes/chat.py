import json
import re
import time
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.config import settings
from app.models import Conversation, Message, Attachment, KnowledgeDocument
from app.schemas import ChatRequest
from app.services.llm import LLMError, chat as llm_chat, stream_chat
from app.services import uce_client
from app import vector_store
from app.tokenizer import tokenize as _tokenize

router = APIRouter(prefix="/api/conversations", tags=["chat"])


TITLE_STOPWORDS = {
    "안녕하세요",
    "있습니다",
    "합니다",
    "주세요",
    "그리고",
    "하지만",
    "대한",
    "관련",
    "내용",
    "질문",
    "답변",
    "사용자",
    "설명",
    "가능",
    "정도",
    "부분",
    "것은",
    "것이",
    "있는",
    "없는",
    "the",
    "and",
    "for",
    "with",
}


def _estimate_prompt_tokens(messages: list[dict]) -> int:
    text = "\n".join(str(message.get("content", "")) for message in messages)
    return max(1, len(text) // 4) if text else 0


def _legacy_metrics(messages: list[dict]) -> dict:
    prompt_tokens = _estimate_prompt_tokens(messages)
    return {
        "use_uce": False,
        "fallback_used": False,
        "original_prompt_tokens": prompt_tokens,
        "final_prompt_tokens": prompt_tokens,
        "compression_ratio": 1.0,
        "build_context_latency_ms": 0,
        "llm_first_token_ms": None,
        "llm_total_latency_ms": None,
        "selected_context_count": 0,
        "dropped_context_count": 0,
        "intent": None,
        "topic_relation": None,
    }


def _uce_metrics(uce_result: uce_client.UceContextResult, fallback_used: bool = False) -> dict:
    metadata = uce_result.metadata
    prompt_pack = uce_result.prompt_pack
    return {
        "use_uce": not fallback_used,
        "fallback_used": fallback_used,
        "original_prompt_tokens": prompt_pack.get("original_tokens"),
        "final_prompt_tokens": prompt_pack.get("estimated_tokens"),
        "compression_ratio": metadata.get("compression_ratio"),
        "build_context_latency_ms": uce_result.latency_ms,
        "llm_first_token_ms": None,
        "llm_total_latency_ms": None,
        "selected_context_count": metadata.get("selected_context_count", 0),
        "dropped_context_count": metadata.get("dropped_context_count", 0),
        "intent": metadata.get("primary_intent"),
        "topic_relation": metadata.get("topic_relation"),
    }


def _messages_from_uce_prompt(system_prompt: str | None, prompt_pack_content: str) -> list[dict]:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt_pack_content})
    return messages


def _clean_title_candidate(title: str) -> str:
    title = title.strip().splitlines()[0] if title.strip() else ""
    title = re.sub(r"^[#*\-\s'\"]+|[#*\-\s'\"]+$", "", title)
    title = re.sub(r"^(제목|Title)\s*[:：]\s*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[.!?。]+$", "", title)
    title = " ".join(title.split())
    return title[:15]


def _is_copied_title(title: str, user_message: str, assistant_response: str) -> bool:
    if not title:
        return True
    compact_title = re.sub(r"\s+", "", title)
    compact_user = re.sub(r"\s+", "", user_message)
    compact_assistant = re.sub(r"\s+", "", assistant_response)
    if len(compact_title) >= 6 and (
        compact_title in compact_user or compact_title in compact_assistant
    ):
        return True
    return user_message.startswith(title) or assistant_response.startswith(title)


def fallback_title(user_message: str, assistant_response: str) -> str:
    source = f"{user_message}\n{assistant_response}"
    tokens = re.findall(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9_\-]{1,}", source)
    scored: dict[str, int] = {}
    for token in tokens:
        normalized = token.strip("_-")
        key = normalized.lower()
        if len(normalized) < 2 or key in TITLE_STOPWORDS:
            continue
        score = 3 if normalized in user_message else 1
        if normalized.isupper() or any(char.isdigit() for char in normalized):
            score += 1
        scored[normalized] = scored.get(normalized, 0) + score

    keywords = [
        token
        for token, _ in sorted(scored.items(), key=lambda item: (-item[1], len(item[0]), item[0]))[:3]
    ]
    if not keywords:
        return "새 대화"
    return _clean_title_candidate(" ".join(keywords)) or "새 대화"


async def generate_title(model: str, user_message: str, assistant_response: str) -> str:
    prompt = (
        "다음 사용자 질문과 AI 답변을 모두 참고하여 대화 목록에 표시할 짧은 제목을 만드세요.\n"
        "규칙:\n"
        "- 15자 이내\n"
        "- 한국어 명사구 형태\n"
        "- 제목만 출력\n"
        "- 사용자 질문이나 AI 답변 문장을 그대로 복사하지 말 것\n"
        "- 인사말, 설명문, 따옴표, 마침표 금지\n\n"
        f"[사용자 질문]\n{user_message[:500]}\n\n"
        f"[AI 답변]\n{assistant_response[:700]}"
    )
    try:
        title = await llm_chat(
            model,
            [
                {
                    "role": "system",
                    "content": "너는 대화 내용을 짧은 한국어 제목으로 요약하는 도우미다. 원문 문장 복사는 금지한다.",
                },
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.2, "num_predict": 64},
            timeout=60.0,
        )
        title = _clean_title_candidate(title)
        if _is_copied_title(title, user_message, assistant_response):
            return fallback_title(user_message, assistant_response)
        return title
    except LLMError:
        return fallback_title(user_message, assistant_response)


def _compute_summary_similarity(query: str, summaries: list[dict]) -> list[dict]:
    """질문과 문서 요약 간 TF-IDF 코사인 유사도를 계산하여 점수순 정렬 반환"""
    if not summaries:
        return []

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    texts = [s["summary"] for s in summaries]
    all_texts = texts + [query]
    tfidf = TfidfVectorizer(tokenizer=_tokenize, token_pattern=None)
    tfidf_matrix = tfidf.fit_transform(all_texts)
    query_vec = tfidf_matrix[-1]
    doc_matrix = tfidf_matrix[:-1]
    scores = cosine_similarity(query_vec, doc_matrix).flatten()

    scored = []
    for i, s in enumerate(summaries):
        scored.append({**s, "similarity": float(scores[i])})
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored


@router.post("/{conversation_id}/chat")
async def chat(
    conversation_id: int,
    data: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages), selectinload(Conversation.attachments))
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")

    is_first_message = len(conv.messages) == 0

    user_message = Message(
        conversation_id=conversation_id, role="user", content=data.message
    )
    db.add(user_message)
    await db.commit()

    messages = []

    # RAG: 문서 요약 기반 우선 검색 + 청크 검색
    rag_context = ""
    rag_references = []
    try:
        # 1단계: 모든 지식 문서의 요약을 로드하여 질문과 유사도 비교
        doc_result = await db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.status == "ready",
                KnowledgeDocument.summary.isnot(None),
            )
        )
        docs_with_summary = doc_result.scalars().all()

        priority_doc_ids = set()
        if docs_with_summary:
            summaries = [
                {"doc_id": d.id, "filename": d.filename, "summary": d.summary}
                for d in docs_with_summary
            ]
            scored = _compute_summary_similarity(data.message, summaries)
            # 유사도 0.01 이상인 문서를 우선 문서로 선정
            priority_doc_ids = {s["doc_id"] for s in scored if s["similarity"] >= 0.01}

        # 2단계: 청크 검색 (기존 하이브리드 검색)
        all_results = vector_store.search(query=data.message, n_results=10)

        if all_results and priority_doc_ids:
            # 우선 문서의 청크를 앞에, 나머지를 뒤에 배치
            priority_results = [r for r in all_results if r["doc_id"] in priority_doc_ids]
            other_results = [r for r in all_results if r["doc_id"] not in priority_doc_ids]
            results = (priority_results + other_results)[:7]
        else:
            results = all_results[:5]

        if results:
            # 우선 문서에는 요약도 함께 컨텍스트에 추가
            summary_context_parts = []
            if priority_doc_ids:
                summary_map = {d.id: d for d in docs_with_summary}
                added_summaries = set()
                for r in results:
                    did = r["doc_id"]
                    if did in priority_doc_ids and did not in added_summaries and did in summary_map:
                        doc = summary_map[did]
                        summary_context_parts.append(
                            f"[문서 '{doc.filename}' 요약]\n{doc.summary}"
                        )
                        added_summaries.add(did)

            chunk_parts = [r["content"] for r in results]
            rag_context = "\n\n---\n\n".join(summary_context_parts + chunk_parts)

            # 참조 문서 정보 수집
            all_doc_ids = list(set(r["doc_id"] for r in results))
            doc_name_result = await db.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.id.in_(all_doc_ids))
            )
            doc_map = {d.id: d.filename for d in doc_name_result.scalars().all()}
            seen = set()
            for r in results:
                did = r["doc_id"]
                if did not in seen and did in doc_map:
                    seen.add(did)
                    is_priority = did in priority_doc_ids
                    rag_references.append({
                        "filename": doc_map[did],
                        "score": round(r["score"], 3),
                        "matched_summary": is_priority,
                    })
    except Exception:
        pass

    # 대화별 첨부파일 컨텍스트
    attachment_context = ""
    if conv.attachments:
        context_parts = []
        for att in conv.attachments:
            context_parts.append(f"[첨부파일: {att.filename}]\n{att.content_text[:8000]}")
        attachment_context = "\n\n".join(context_parts)

    # 시스템 프롬프트 구성
    system_parts = []
    if conv.system_prompt:
        system_parts.append(conv.system_prompt)
    if rag_context:
        system_parts.append(
            "다음은 지식 저장소에서 검색된 관련 문서 내용입니다. "
            "문서 요약이 포함된 경우 해당 문서의 내용을 특히 우선적으로 참고하여 답변하세요.\n\n" + rag_context
        )
    if attachment_context:
        system_parts.append(
            "다음은 사용자가 이 대화에 첨부한 문서 내용입니다.\n\n" + attachment_context
        )
    if system_parts:
        messages.append({"role": "system", "content": "\n\n".join(system_parts)})

    for m in conv.messages:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": data.message})
    legacy_messages = list(messages)
    prompt_metrics = _legacy_metrics(legacy_messages)

    if data.use_uce and settings.uce_enabled:
        rag_chunks = []
        for index, result in enumerate(results if "results" in locals() else []):
            rag_chunks.append(
                {
                    "id": result.get("id") or f"rag_chunk_{index + 1}",
                    "title": result.get("filename") or f"RAG Chunk {index + 1}",
                    "content": result.get("content", ""),
                    "source": result.get("filename") or "vector_store",
                    "importance": 0.85 if result.get("doc_id") in (priority_doc_ids if "priority_doc_ids" in locals() else set()) else 0.7,
                }
            )
        for index, att in enumerate(conv.attachments or []):
            rag_chunks.append(
                {
                    "id": f"attachment_{att.id}",
                    "title": att.filename,
                    "content": att.content_text[:8000],
                    "source": "attachment",
                    "importance": 0.8,
                }
            )
        try:
            uce_result = await uce_client.build_context(
                conversation_id=conversation_id,
                current_message=data.message,
                recent_messages=list(conv.messages)[-15:],
                rag_chunks=rag_chunks,
                model=conv.model,
            )
            messages = _messages_from_uce_prompt(conv.system_prompt, uce_result.prompt_pack["content"])
            prompt_metrics = _uce_metrics(uce_result)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("UCE failed; falling back to legacy prompt flow")
            messages = legacy_messages
            prompt_metrics = _legacy_metrics(legacy_messages)
            prompt_metrics["fallback_used"] = True

    async def generate():
        full_response = ""
        stream_started = time.perf_counter()
        first_token_seen = False
        metrics = dict(prompt_metrics)
        async for event in stream_chat(conv.model, messages, timeout=300.0):
            if event["type"] == "thinking":
                yield f"data: {json.dumps({'thinking': event['content']})}\n\n"
            elif event["type"] == "token":
                if not first_token_seen:
                    metrics["llm_first_token_ms"] = int((time.perf_counter() - stream_started) * 1000)
                    first_token_seen = True
                full_response += event["content"]
                yield f"data: {json.dumps({'token': event['content']})}\n\n"
            elif event["type"] == "error":
                yield f"data: {json.dumps({'error': event['content']})}\n\n"
                return
            elif event["type"] == "done":
                break

        if full_response.strip():
            metrics["llm_total_latency_ms"] = int((time.perf_counter() - stream_started) * 1000)
            assistant_message = Message(
                conversation_id=conversation_id, role="assistant", content=full_response,
                references=rag_references if rag_references else None,
                metrics=metrics,
            )
            db.add(assistant_message)
            await db.commit()

        title = None
        if is_first_message and full_response:
            title = await generate_title(conv.model, data.message, full_response)
            await db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(title=title)
            )
            await db.commit()

        done_data = {'done': True, 'title': title}
        done_data['metadata'] = metrics
        if rag_references:
            done_data['references'] = rag_references
        yield f"data: {json.dumps(done_data)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
