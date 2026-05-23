import logging
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["normalize"])

_PROMPT_TEMPLATE = """다음 문서를 semantic markdown IR로 변환하세요.

반드시 아래 형식으로 출력하세요:

# [문서 주제]

## [섹션명]
내용...

## [섹션명]
내용...

규칙:
- 반드시 # 제목과 ## 소제목을 포함한 markdown 형식으로 출력하세요
- 원문의 모든 정보를 보존하세요
- 의미 단위로 ## 섹션을 구분하세요
- 요약하지 말고 내용을 그대로 유지하세요
- 원문에 없는 내용을 추가하지 마세요
- 반드시 markdown heading(#, ##)을 사용해야 합니다

[문서명: {filename}]
[감지된 구조: {structure_type}]

{content}"""


class NormalizeRequest(BaseModel):
    content: str
    structure_type: str
    filename: str = ""
    model: str | None = None


class NormalizeResponse(BaseModel):
    normalized_content: str
    model_used: str


@router.post("/normalize", response_model=NormalizeResponse)
async def normalize_document(request: NormalizeRequest):
    model = request.model or settings.default_ollama_model
    prompt = _PROMPT_TEMPLATE.format(
        filename=request.filename,
        structure_type=request.structure_type,
        content=request.content,
    )

    try:
        async with httpx.AsyncClient(timeout=settings.dpe_timeout_seconds) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error("normalize LLM 호출 실패: %s", e)
        raise HTTPException(status_code=502, detail=f"LLM 호출 실패: {e}")

    normalized = data.get("response", "").strip()
    if not normalized:
        raise HTTPException(status_code=502, detail="LLM 응답이 비어있음")

    return NormalizeResponse(normalized_content=normalized, model_used=model)
