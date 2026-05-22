# DPE Implementation Guide
> Version: 0.1
> Last Updated: 2026-05-21

이 문서는 DPE를 구현하기 위한 개발 가이드다. 설계 기반으로 작성되었으며, 구현 AI가 참고하는 기준 문서다.

---

## 1. 구현 범위 요약

**DPE 신규 구현:**
- `dpe/` 디렉토리 전체 (FastAPI 앱, Dockerfile, requirements.txt)

**backend 변경:**
- `app/config.py` — DPE 설정 추가
- `app/services/dpe_client.py` — 신규 (DPE HTTP 클라이언트)
- `app/routes/normalize.py` — 신규 (DPE가 호출하는 LLM normalize 엔드포인트)
- `app/routes/knowledge.py` — `process_document()` 함수 변경
- `app/routes/attachments.py` — `upload_attachment()` 함수 변경
- `app/models.py` — `KnowledgeDocument.dpe_metadata` 필드 추가
- `app/main.py` — normalize 라우터 등록

**변경 금지:**
- UCE 관련 코드 (`services/uce_client.py`, `routes/chat.py`의 UCE 통합 부분)
- API 응답 스키마 (`schemas.py`) — 기존 knowledge/attachment 응답 포맷 유지
- DB 테이블 구조 — `dpe_metadata` 컬럼 추가만 허용

---

## 2. DPE 모듈 구조

```text
dpe/
  app/
    main.py           ← FastAPI 앱 생성, 라우터 등록, lifespan
    server.py         ← uvicorn 진입점 (python -m app.server)
    api/
      routes.py       ← POST /process, GET /health, GET /status
      schemas.py      ← Pydantic 요청/응답 스키마
    core/
      processor.py    ← 전체 흐름 오케스트레이터
      structure_detector.py ← 구조 감지 (확장자 힌트 + content sniffing)
      normalizer.py   ← backend /api/normalize 호출
      metadata_builder.py  ← DocumentProcessResult 최종 조립
    adapters/
      backend_client.py    ← httpx 기반 backend HTTP 클라이언트
  scripts/
    smoke-api.sh
  requirements.txt
  Dockerfile
```

---

## 3. DPE 핵심 컴포넌트

### 3.1 app/api/schemas.py

요청/응답 스키마 정의.

```python
from pydantic import BaseModel

class ProcessOptions(BaseModel):
    normalization_enabled: bool = False
    normalization_model: str | None = None
    backend_normalize_url: str = "http://backend:8000/api/normalize"

class ProcessRequest(BaseModel):
    document_id: str
    filename: str
    content: str
    options: ProcessOptions = ProcessOptions()

class DocumentProcessResult(BaseModel):
    document_id: str
    normalized_content: str
    structure_type: str
    structure_confidence: float
    chunk_strategy: str
    normalization_applied: bool
    normalization_model: str | None
    retrieval_hints: list[str]
    metadata_version: int = 1
```

### 3.2 app/core/structure_detector.py

두 단계로 구조를 감지한다.

**1단계: 확장자 기반 힌트**

```python
EXTENSION_HINTS: dict[str, str] = {
    ".md":       "markdown",
    ".markdown": "markdown",
    ".json":     "json",
    ".yaml":     "yaml",
    ".yml":      "yaml",
    ".py":       "code",
    ".js":       "code",
    ".ts":       "code",
    ".java":     "code",
    ".go":       "code",
    ".rs":       "code",
    ".csv":      "table",
    ".tsv":      "table",
    ".log":      "log",
    ".txt":      "unknown",
}
```

`.txt`와 미등록 확장자는 `"unknown"` — 2단계 판단 필요.

**2단계: Content sniffing**

| 패턴 | 판단 |
|------|------|
| `\n#` 빈도 높음 (전체 줄 대비 3% 이상) | `markdown` |
| `{` 또는 `[`로 시작 | `json` |
| `---` + `key: value` 패턴 | `yaml` |
| `def `, `class `, `import ` 포함 | `code` |
| timestamp 패턴 반복 (`\d{4}-\d{2}-\d{2}` 등) | `log` |
| `,` delimiter 3개 이상 반복 줄 비율 30% 이상 | `table` |
| 여러 패턴 동시 해당 | `mixed` |
| 해당 없음 | `plain_text` |

**Confidence 계산:**

확장자와 content sniffing 결과가 일치하면 confidence 상승, 불일치하면 하락.

```python
def detect(filename: str, content: str) -> tuple[str, float]:
    """
    Returns:
        structure_type: 감지된 구조 유형
        confidence: 0.0 ~ 1.0
    """
```

**Confidence 기준:**

| 상황 | 신뢰도 범위 |
|------|------------|
| 확장자 + content sniffing 일치 | 0.75 ~ 0.95 |
| content sniffing만 명확 | 0.55 ~ 0.75 |
| 확장자 힌트만 (`.md`, `.json` 등 명확한 것) | 0.70 ~ 0.85 |
| 패턴 애매 | 0.30 ~ 0.55 |
| 판단 불가 | 0.10 ~ 0.30 |

`confidence < 0.55`이면 normalization 후보.

### 3.3 app/core/normalizer.py

DPE → backend `/api/normalize` 호출.

```python
class Normalizer:
    def __init__(self, backend_client: BackendClient):
        self._client = backend_client

    async def normalize(
        self,
        content: str,
        structure_type: str,
        filename: str,
        backend_normalize_url: str,
        model: str | None = None,
    ) -> tuple[str, str | None]:
        """
        Returns:
            normalized_content: LLM이 생성한 markdown IR
            model_used: 사용된 모델명 또는 None (실패 시)
        """
```

normalization 호출 실패 시 예외를 던지지 않고 원본 content를 반환한다. processor가 fallback을 처리한다.

### 3.4 app/core/processor.py

전체 흐름을 조율한다.

```python
async def process(request: ProcessRequest) -> DocumentProcessResult:
    # 1. content 비어있으면 즉시 fallback 반환
    if not request.content.strip():
        return _fallback_result(request)

    # 2. structure detection
    structure_type, confidence = detector.detect(request.filename, request.content)

    # 3. normalization 필요 여부 판단
    needs_normalization = (
        request.options.normalization_enabled
        and confidence < settings.dpe_normalization_min_confidence
        and structure_type in {"plain_text", "mixed", "unknown", "log"}
        and len(request.content) <= settings.dpe_normalization_max_chars  # 상한선 초과 시 skip
    )

    # 4. normalization 수행
    normalized_content = request.content
    normalization_applied = False
    normalization_model = None

    if needs_normalization:
        try:
            normalized_content, normalization_model = await normalizer.normalize(
                content=request.content,
                structure_type=structure_type,
                filename=request.filename,
                backend_normalize_url=request.options.backend_normalize_url,
                model=request.options.normalization_model,
            )
            normalization_applied = True
        except Exception:
            # normalization 실패 → 원본으로 fallback
            normalized_content = request.content
            normalization_applied = False

    # 5. chunk_strategy 결정
    chunk_strategy = _select_chunk_strategy(
        structure_type=structure_type,
        normalization_applied=normalization_applied,
    )

    # 6. retrieval_hints 생성
    retrieval_hints = _build_retrieval_hints(
        structure_type=structure_type,
        normalized_content=normalized_content,
        normalization_applied=normalization_applied,
    )

    # 7. 결과 조립 및 반환
    return DocumentProcessResult(
        document_id=request.document_id,
        normalized_content=normalized_content,
        structure_type=structure_type,
        structure_confidence=confidence,
        chunk_strategy=chunk_strategy,
        normalization_applied=normalization_applied,
        normalization_model=normalization_model,
        retrieval_hints=retrieval_hints,
    )
```

**chunk_strategy 결정 로직:**

```python
def _select_chunk_strategy(
    structure_type: str,
    normalization_applied: bool,
) -> str:
    if normalization_applied or structure_type == "markdown":
        return "heading-aware"
    match structure_type:
        case "log":
            return "log-window"
        case "table":
            return "table-row"
        case "json":
            return "json-object"
        case "mixed":
            return "semantic-window"
        case _:
            return "sliding-window"
```

**retrieval_hints 생성 로직:**

```python
def _build_retrieval_hints(
    structure_type: str,
    normalized_content: str,
    normalization_applied: bool,
) -> list[str]:
    hints = []
    content = normalized_content

    if structure_type == "markdown" or normalization_applied:
        if re.search(r"^#{1,3} ", content, re.MULTILINE):
            hints.append("heading")

    if re.search(r"\b[A-Z][a-zA-Z]*\b", content):
        hints.append("entity")

    if "|" in content and "---" in content:
        hints.append("table")

    if re.search(r"\d{4}-\d{2}-\d{2}", content):
        hints.append("timestamp")

    return hints
```

### 3.5 app/adapters/backend_client.py

```python
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
    ) -> dict:
        """
        Returns: {"normalized_content": str, "model_used": str}
        Raises: httpx.HTTPError on failure
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json={
                "content": content,
                "structure_type": structure_type,
                "filename": filename,
            })
            resp.raise_for_status()
            return resp.json()
```

### 3.6 app/api/routes.py

```python
from fastapi import APIRouter
from app.api.schemas import ProcessRequest, DocumentProcessResult
from app.core.processor import process
import time

router = APIRouter()
_start_time = time.time()

@router.post("/process", response_model=DocumentProcessResult)
async def process_document(request: ProcessRequest):
    return await process(request)

@router.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

@router.get("/status")
async def status():
    return {
        "normalization_enabled": settings.dpe_normalization_enabled,
        "min_confidence_threshold": settings.dpe_normalization_min_confidence,
        "uptime_seconds": int(time.time() - _start_time),
    }
```

### 3.7 app/main.py

```python
from fastapi import FastAPI
from app.api.routes import router

app = FastAPI(title="DPE", version="0.1.0")
app.include_router(router)
```

### 3.8 app/server.py

```python
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8200, reload=False)
```

---

## 4. DPE 설정

`dpe/app/config.py`:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    dpe_normalization_enabled: bool = False
    dpe_normalization_min_confidence: float = 0.55
    dpe_normalization_max_chars: int = 8000  # LLM context window 안전 상한선

    class Config:
        env_file = ".env"

settings = Settings()
```

**`dpe_normalization_max_chars` 설계 근거:**

| 모델 | Context Window | 권장 max_chars |
|------|---------------|----------------|
| EXAONE 3.5 7.8b | ~32k tokens | 8,000자 (~2,000 토큰) |
| gemma4:26b | ~128k tokens | 30,000자 (~7,500 토큰) |
| 일반 로컬 7B 모델 | ~8k tokens | 3,000자 (~750 토큰) |

한국어 기준 1 토큰 ≈ 3~4자. 8,000자는 EXAONE 3.5 7.8b에서 프롬프트 오버헤드 + normalization 출력을 포함해도 안전한 범위다.

초과 시 normalization을 건너뛰고 원본을 그대로 반환한다. 부분 텍스트만 normalize하면 나머지 부분이 구조 없이 남아 오히려 일관성을 해친다.

---

## 5. Backend 변경 사항

### 5.1 app/config.py

기존 `Settings` 클래스에 DPE 설정 추가:

```python
dpe_enabled: bool = False
dpe_base_url: str = "http://dpe:8200"
dpe_timeout_seconds: float = 30.0
dpe_normalization_enabled: bool = False
```

### 5.2 app/services/dpe_client.py (신규)

```python
import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

class DpeProcessResult:
    def __init__(self, data: dict):
        self.normalized_content: str = data["normalized_content"]
        self.structure_type: str = data["structure_type"]
        self.structure_confidence: float = data["structure_confidence"]
        self.chunk_strategy: str = data["chunk_strategy"]
        self.normalization_applied: bool = data["normalization_applied"]
        self.normalization_model: str | None = data.get("normalization_model")
        self.retrieval_hints: list[str] = data.get("retrieval_hints", [])
        self.metadata_version: int = data.get("metadata_version", 1)

    def to_metadata_dict(self) -> dict:
        return {
            "structure_type": self.structure_type,
            "structure_confidence": self.structure_confidence,
            "chunk_strategy": self.chunk_strategy,
            "normalization_applied": self.normalization_applied,
            "normalization_model": self.normalization_model,
            "retrieval_hints": self.retrieval_hints,
            "metadata_version": self.metadata_version,
        }


async def call_dpe_process(
    document_id: str,
    filename: str,
    content: str,
) -> DpeProcessResult | None:
    """
    DPE /process 호출. 실패 시 None 반환 (fallback 처리는 호출자 담당).
    """
    if not settings.dpe_enabled:
        return None

    payload = {
        "document_id": document_id,
        "filename": filename,
        "content": content,
        "options": {
            "normalization_enabled": settings.dpe_normalization_enabled,
            "backend_normalize_url": f"{_self_base_url()}/api/normalize",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=settings.dpe_timeout_seconds) as client:
            resp = await client.post(
                f"{settings.dpe_base_url}/process",
                json=payload,
            )
            resp.raise_for_status()
            return DpeProcessResult(resp.json())
    except Exception as e:
        logger.warning("DPE 호출 실패 (document_id=%s, filename=%s): %s", document_id, filename, e)
        return None


def _self_base_url() -> str:
    # backend가 자기 자신을 가리키는 URL.
    # docker-compose 환경에서는 서비스명 기반, 로컬에서는 localhost.
    return "http://backend:8000"
```

**핵심 원칙:** `call_dpe_process()`는 절대 예외를 던지지 않는다. DPE 실패 시 `None`을 반환하고, 호출자(knowledge.py, attachments.py)가 fallback을 처리한다.

### 5.3 app/routes/normalize.py (신규)

DPE가 normalization을 요청할 때 backend가 LLM을 호출하는 엔드포인트.

```python
import logging
import httpx
from fastapi import APIRouter
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["normalize"])

class NormalizeRequest(BaseModel):
    content: str
    structure_type: str
    filename: str = ""

class NormalizeResponse(BaseModel):
    normalized_content: str
    model_used: str

NORMALIZE_PROMPT_TEMPLATE = """다음 문서를 retrieval에 최적화된 markdown 구조로 변환하세요.

규칙:
- 원문 정보를 삭제하지 마세요
- 의미 단위로 section과 heading을 생성하세요 (## 형식 사용)
- 요약하지 마세요. 구조만 추가하세요
- 시간순 흐름, entity, 관계를 보존하세요
- abstract 또는 요약문을 새로 만들지 마세요

[문서명: {filename}]
[구조 유형: {structure_type}]

{content}"""

@router.post("/normalize", response_model=NormalizeResponse)
async def normalize_document(request: NormalizeRequest):
    model = settings.default_ollama_model
    prompt = NORMALIZE_PROMPT_TEMPLATE.format(
        filename=request.filename,
        structure_type=request.structure_type,
        content=request.content,
    )

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
        )
        data = resp.json()
        normalized = data.get("response", "").strip()

    if not normalized:
        normalized = request.content

    return NormalizeResponse(normalized_content=normalized, model_used=model)
```

### 5.4 app/routes/knowledge.py 변경

`process_document()` 함수에 DPE 통합 추가.

변경 전:
```python
async def process_document(doc_id: int, filename: str, content: bytes):
    async with async_session() as db:
        text = extract_text(filename, content)
        summary = await generate_summary(text, filename)
        chunks = split_text(text, chunk_size=500, overlap=50)
        vector_store.add_chunks(doc_id, chunks)
        await db.execute(update(KnowledgeDocument)...)
```

변경 후:
```python
from app.services.dpe_client import call_dpe_process

async def process_document(doc_id: int, filename: str, content: bytes):
    async with async_session() as db:
        try:
            text = extract_text(filename, content)
            if not text.strip():
                # ... error 처리 (기존과 동일)
                return

            # DPE 통합
            dpe_result = await call_dpe_process(
                document_id=str(doc_id),
                filename=filename,
                content=text,
            )

            if dpe_result is not None:
                # DPE 성공: normalized_content 사용
                final_text = dpe_result.normalized_content
                dpe_metadata = dpe_result.to_metadata_dict()
            else:
                # DPE 실패 또는 비활성화: 원본 텍스트 사용
                final_text = text
                dpe_metadata = None

            summary = await generate_summary(final_text, filename)
            chunks = split_text(final_text, chunk_size=500, overlap=50)

            if not chunks:
                # ... error 처리 (기존과 동일)
                return

            vector_store.add_chunks(doc_id, chunks)

            await db.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id == doc_id)
                .values(
                    status="ready",
                    chunk_count=len(chunks),
                    summary=summary or None,
                    dpe_metadata=dpe_metadata,  # ← 신규
                )
            )
            await db.commit()

        except Exception as e:
            # ... error 처리 (기존과 동일)
```

### 5.5 app/routes/attachments.py 변경

`upload_attachment()` 함수에 DPE 통합 추가.

변경 전:
```python
text = extract_text(file.filename or "file.txt", content)
attachment = Attachment(
    conversation_id=conversation_id,
    filename=file.filename or "file.txt",
    content_text=text,
    file_size=len(content),
)
```

변경 후:
```python
from app.services.dpe_client import call_dpe_process

filename = file.filename or "file.txt"
text = extract_text(filename, content)

# DPE 통합 (normalization은 동기 응답 지연 때문에 권장하지 않음)
dpe_result = await call_dpe_process(
    document_id=f"att_{conversation_id}_{filename}",
    filename=filename,
    content=text,
)
final_text = dpe_result.normalized_content if dpe_result is not None else text

attachment = Attachment(
    conversation_id=conversation_id,
    filename=filename,
    content_text=final_text,
    file_size=len(content),
)
```

첨부파일은 동기 처리이므로 `DPE_NORMALIZATION_ENABLED=false`가 권장 설정이다. structure detection만 수행하면 DPE 응답은 빠르다.

### 5.6 app/models.py 변경

`KnowledgeDocument` 모델에 `dpe_metadata` 필드 추가:

```python
from sqlalchemy import JSON

class KnowledgeDocument(Base):
    # ... 기존 필드들 ...
    dpe_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
```

DB migration (Alembic 미사용):

```sql
ALTER TABLE knowledge_documents ADD COLUMN dpe_metadata JSON NULL;
```

### 5.7 app/main.py 변경

normalize 라우터 등록:

```python
from app.routes import conversations, chat, models, attachments, knowledge, rca, normalize  # ← normalize 추가

# ...
app.include_router(normalize.router)  # ← 추가
```

---

## 6. DPE requirements.txt

```text
fastapi
uvicorn[standard]
pydantic
pydantic-settings
httpx
```

---

## 7. Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8200
CMD ["python", "-m", "app.server"]
```

---

## 8. 핵심 제약

- **DPE는 LLM을 직접 호출하지 않는다.** normalization이 필요하면 반드시 `backend /api/normalize`를 통해 요청한다.
- **DPE는 DB에 아무것도 쓰지 않는다.** 결과 저장은 backend가 담당한다.
- **DPE는 파일 바이너리를 받지 않는다.** backend가 `file_parser.extract_text()`로 텍스트를 추출한 뒤 전달한다.
- **DPE 실패 시 backend는 기존 로직으로 fallback한다.** 사용자에게 에러를 노출하지 않는다.
- **UCE는 변경하지 않는다.** DPE가 normalized markdown을 생성하므로 UCE의 heading-aware retrieval은 그대로 동작한다.
- **`DPE_ENABLED=false`가 기본값이다.** 기존 동작이 그대로 유지된다.

---

## 9. 구현 순서 (권장)

1. `dpe/` 디렉토리 전체 구현 (FastAPI 앱, structure_detector, processor, Dockerfile)
2. DPE 단독 smoke test (`/health`, `/status`, `/process` 기본 동작)
3. backend `config.py` + `dpe_client.py` 추가
4. backend `routes/normalize.py` + `main.py` 등록
5. backend `knowledge.py` 변경 + `models.py` 변경 + DB 마이그레이션
6. backend `attachments.py` 변경
7. `docker-compose.yml` dpe 서비스 추가
8. 전체 통합 smoke test
