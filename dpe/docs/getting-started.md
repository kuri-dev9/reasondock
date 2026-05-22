# DPE Getting Started
> Version: 0.1
> Last Updated: 2026-05-21

---

## 1. Overview

DPE(Document Processing Engine)는 Python + FastAPI 기반의 upload-time 문서 전처리 서비스다.

DPE는 LLM을 직접 호출하지 않는다. backend가 파일 업로드 시 DPE에 이미 추출된 텍스트를 전달하면, DPE는 structure detection을 수행하고 필요 시 backend `/api/normalize`를 통해 LLM normalization을 요청한다. 결과로 normalized content와 DocumentMetadata를 반환하며, backend가 DB에 저장한다.

UCE는 항상 markdown처럼 구조화된 문서를 받게 된다. DPE가 그 보장을 담당한다.

---

## 2. Requirements

- Python 3.11+
- pip
- Docker 또는 로컬 Python 실행 환경
- reasondock backend (normalization 기능 사용 시)

주요 의존성:

```text
fastapi
uvicorn[standard]
pydantic
httpx
```

---

## 3. Directory Structure

구현 완료 후 기준:

```text
dpe/
  app/
    main.py
    server.py
    api/
      routes.py
      schemas.py
    core/
      processor.py          ← 전체 흐름 오케스트레이터
      structure_detector.py ← 확장자 힌트 + content sniffing
      normalizer.py         ← backend /api/normalize 호출
      metadata_builder.py   ← DocumentProcessResult 조립
    adapters/
      backend_client.py     ← backend HTTP 클라이언트
  docs/
    architecture.md
    api-reference.md
    getting-started.md        ← 이 문서
    implementation-guide.md
    roadmap.md
  scripts/
    smoke-api.sh
  requirements.txt
  Dockerfile
```

---

## 4. Run

### Docker

```bash
docker build -t dpe:local .
docker run --rm -p 8200:8200 dpe:local
```

### Local Development

```bash
cd dpe
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m app.server
```

또는 FastAPI reload 모드:

```bash
uvicorn app.main:app --reload --port 8100
```

확인:

```bash
curl http://localhost:8200/health
curl http://localhost:8200/status
```

---

## 5. Environment Variables

DPE 서비스 자체:

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `DPE_NORMALIZATION_ENABLED` | `false` | LLM normalization 기본 활성화 여부 |
| `DPE_NORMALIZATION_MIN_CONFIDENCE` | `0.55` | 이 값 미만이면 normalization 후보 |
| `DPE_NORMALIZATION_MAX_CHARS` | `8000` | normalization 대상 텍스트 상한선. 초과 시 normalization 건너뜀 |

backend 서비스 (backend `.env`에 추가):

| 환경변수 | 기본값 | 설명 |
|----------|--------|------|
| `DPE_ENABLED` | `false` | DPE 연동 활성화. false이면 기존 직접 저장 로직 동작 |
| `DPE_BASE_URL` | `http://dpe:8200` | DPE 서비스 URL |
| `DPE_TIMEOUT_SECONDS` | `30` | DPE 호출 timeout |
| `DPE_NORMALIZATION_ENABLED` | `false` | DPE 요청 시 normalization 옵션 전달값 |
| `DPE_NORMALIZATION_MIN_CONFIDENCE` | `0.55` | normalization 판단 임계값 |

---

## 6. Backend Integration

DPE를 backend에 통합하려면 아래 변경이 필요하다. 상세 구현은 [implementation-guide.md](./implementation-guide.md)를 참고한다.

### 6.1 환경변수 추가

`backend/app/config.py`에 DPE 설정 추가:

```python
dpe_enabled: bool = False
dpe_base_url: str = "http://dpe:8200"
dpe_timeout_seconds: float = 30.0
dpe_normalization_enabled: bool = False
```

`backend/.env`에 추가:

```env
DPE_ENABLED=false
DPE_BASE_URL=http://dpe:8200
DPE_TIMEOUT_SECONDS=30
DPE_NORMALIZATION_ENABLED=false
```

### 6.2 DPE 클라이언트 추가

`backend/app/services/dpe_client.py` 신규 생성.
DPE `/process` 호출 및 fallback 처리를 담당한다.

### 6.3 Normalize 엔드포인트 추가

`backend/app/routes/normalize.py` 신규 생성.
DPE가 normalization을 요청할 때 backend가 LLM을 호출하고 결과를 반환한다.

`backend/app/main.py`에 라우터 등록 추가:

```python
from app.routes import normalize
app.include_router(normalize.router)
```

### 6.4 Knowledge 문서 처리 흐름 변경

`backend/app/routes/knowledge.py`의 `process_document()` 함수:

```text
기존:
  extract_text → summary 생성 → split_text → vector_store 저장

변경 (DPE_ENABLED=true일 때):
  extract_text → DPE /process 호출 → normalized_content 사용
  → summary 생성 → chunk_strategy에 따른 청킹 → vector_store 저장
  → dpe_metadata DB 저장
```

`DPE_ENABLED=false`이면 기존 로직 그대로 동작. 하위 호환 보장.

### 6.5 Attachment 처리 흐름 변경

`backend/app/routes/attachments.py`의 `upload_attachment()` 함수:

```text
기존:
  extract_text → Attachment(content_text=text) 저장

변경 (DPE_ENABLED=true일 때):
  extract_text → DPE /process 호출 (normalization_enabled=False 권장)
  → Attachment(content_text=normalized_content) 저장
```

첨부파일은 동기 처리이므로 normalization을 비활성화하는 것이 권장된다. normalization은 LLM 호출이 포함되어 응답이 느려진다.

### 6.6 DB 스키마 변경

`KnowledgeDocument` 테이블에 `dpe_metadata` 컬럼 추가:

```sql
ALTER TABLE knowledge_documents ADD COLUMN dpe_metadata JSON NULL;
```

`backend/app/models.py`의 `KnowledgeDocument` 모델에 필드 추가:

```python
dpe_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
```

---

## 7. Docker Compose 통합

`reasondock/docker-compose.yml`에 dpe 서비스 추가:

```yaml
dpe:
  build: ./dpe
  ports:
    - "8200:8200"
  environment:
    - DPE_NORMALIZATION_ENABLED=false
    - DPE_NORMALIZATION_MIN_CONFIDENCE=0.55
  restart: unless-stopped
```

backend 서비스에 환경변수 추가:

```yaml
backend:
  environment:
    - DPE_ENABLED=true
    - DPE_BASE_URL=http://dpe:8200
    - DPE_TIMEOUT_SECONDS=30
    - DPE_NORMALIZATION_ENABLED=false
```

---

## 8. Smoke Test

DPE 단독 테스트:

```bash
curl -sS -X POST http://localhost:8200/process \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "test_001",
    "filename": "report.txt",
    "content": "장애 시각: 2026-05-10 14:30\n원인: 서버 다운\n영향도: 사용자 1000명"
  }'
```

정상 응답 확인:
- `structure_type`: `plain_text`
- `structure_confidence`: 0.55 미만
- `chunk_strategy`: `sliding-window`
- `normalization_applied`: `false`

markdown 파일 테스트:

```bash
curl -sS -X POST http://localhost:8200/process \
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "test_002",
    "filename": "architecture.md",
    "content": "# 시스템 개요\n\n## 목적\n\n이 시스템은..."
  }'
```

정상 응답 확인:
- `structure_type`: `markdown`
- `structure_confidence`: 0.8 이상
- `chunk_strategy`: `heading-aware`
- `normalization_applied`: `false`

backend 전체 통합 테스트:

```bash
# DPE_ENABLED=true 상태에서 지식 문서 업로드
curl -sS -X POST http://localhost:8000/api/knowledge/upload \
  -F "file=@/path/to/test.txt"

# 처리 상태 확인
curl http://localhost:8000/api/knowledge/1/status
```

스크립트 경로: `dpe/scripts/smoke-api.sh`

---

## 9. Next Docs

- [Architecture](./architecture.md)
- [API Reference](./api-reference.md)
- [Implementation Guide](./implementation-guide.md)
- [Roadmap](./roadmap.md)
