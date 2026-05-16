import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
import httpx

from app.database import get_db
from app.config import settings
from app.models import Conversation, Message, Attachment, KnowledgeDocument
from app.schemas import ChatRequest
from app import vector_store
from app.tokenizer import tokenize as _tokenize

router = APIRouter(prefix="/api/conversations", tags=["chat"])


async def generate_title(model: str, user_message: str, assistant_response: str) -> str:
    prompt = (
        "다음 대화의 내용을 요약하여 짧은 제목(15자 이내)을 한국어로 만들어주세요. "
        "제목만 출력하고 다른 설명은 하지 마세요.\n\n"
        f"사용자: {user_message[:200]}\n"
        f"AI: {assistant_response[:200]}"
    )
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            data = resp.json()
            title = data.get("response", "").strip().strip('"').strip("'")
            return title[:50] if title else user_message[:50]
    except Exception:
        return user_message[:50]


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

    async def generate():
        full_response = ""
        thinking_content = ""
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST",
                    f"{settings.ollama_base_url}/api/chat",
                    json={"model": conv.model, "messages": messages, "stream": True},
                ) as response:
                    async for line in response.aiter_lines():
                        if line:
                            chunk = json.loads(line)
                            msg = chunk.get("message", {})
                            thinking = msg.get("thinking", "")
                            content = msg.get("content", "")

                            if thinking:
                                thinking_content += thinking
                                yield f"data: {json.dumps({'thinking': thinking})}\n\n"
                            if content:
                                full_response += content
                                yield f"data: {json.dumps({'token': content})}\n\n"
                            if chunk.get("done"):
                                break
        except httpx.HTTPError as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return

        if full_response.strip():
            assistant_message = Message(
                conversation_id=conversation_id, role="assistant", content=full_response,
                references=rag_references if rag_references else None
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
        if rag_references:
            done_data['references'] = rag_references
        yield f"data: {json.dumps(done_data)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
