# DPE API Reference
> Version: 0.1
> Last Updated: 2026-05-21

Base URL: `http://localhost:8200`

---

## POST /process

파일 업로드 시 backend가 호출하는 단일 처리 엔드포인트.

backend는 `file_parser.extract_text()`로 원본 텍스트를 먼저 추출한 뒤, 이 엔드포인트에 텍스트를 전달한다. DPE는 파일 바이너리를 직접 받지 않는다.

### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | string | ✅ | 문서 식별자 (예: `"att_123"`, `"doc_5"`) |
| `filename` | string | ✅ | 원본 파일명. 확장자 기반 구조 힌트에 사용 |
| `content` | string | ✅ | 이미 추출된 원본 텍스트 전체 |
| `options` | Options | ❌ | 처리 옵션 |

```json
{
  "document_id": "doc_5",
  "filename": "report.txt",
  "content": "장애 시각: 2026-05-10 14:30\n원인: 서버 다운\n영향도: 사용자 1000명",
  "options": {
    "normalization_enabled": false,
    "normalization_model": null,
    "backend_normalize_url": "http://backend:8000/api/normalize"
  }
}
```

### Options

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `normalization_enabled` | bool | `false` | LLM normalization 활성화 여부 |
| `normalization_model` | string \| null | `null` | normalization에 사용할 모델명. null이면 backend 기본 모델 사용 |
| `backend_normalize_url` | string | `"http://backend:8000/api/normalize"` | backend normalize 엔드포인트 URL |

### Response Body

**정형 문서 (normalization 불필요):**

```json
{
  "document_id": "doc_5",
  "normalized_content": "원본 내용 그대로 또는 경미한 정규화만 적용",
  "structure_type": "markdown",
  "structure_confidence": 0.95,
  "chunk_strategy": "heading-aware",
  "normalization_applied": false,
  "normalization_model": null,
  "retrieval_hints": ["heading", "entity", "table"],
  "metadata_version": 1
}
```

**비정형 문서 (normalization 적용):**

```json
{
  "document_id": "doc_5",
  "normalized_content": "## 장애 원인\n2026-05-10 14:30 서버 다운 발생\n\n## 영향도\n사용자 1000명 접속 불가",
  "structure_type": "plain_text",
  "structure_confidence": 0.31,
  "chunk_strategy": "heading-aware",
  "normalization_applied": true,
  "normalization_model": "exaone3.5:7.8b",
  "retrieval_hints": ["heading", "entity"],
  "metadata_version": 1
}
```

**비정형 문서 (normalization 비활성화, fallback):**

```json
{
  "document_id": "doc_5",
  "normalized_content": "원본 텍스트 그대로",
  "structure_type": "plain_text",
  "structure_confidence": 0.31,
  "chunk_strategy": "sliding-window",
  "normalization_applied": false,
  "normalization_model": null,
  "retrieval_hints": [],
  "metadata_version": 1
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `document_id` | string | 요청의 document_id 그대로 반환 |
| `normalized_content` | string | UCE에 전달할 최종 텍스트. normalization 적용 시 markdown IR, 미적용 시 원본 |
| `structure_type` | string | 감지된 구조 유형 (아래 표 참고) |
| `structure_confidence` | float | 구조 감지 신뢰도 0.0~1.0 |
| `chunk_strategy` | string | backend가 청킹에 사용할 전략 힌트 (아래 표 참고) |
| `normalization_applied` | bool | LLM normalization 실제 적용 여부 |
| `normalization_model` | string \| null | 사용된 모델명. 미적용 시 null |
| `retrieval_hints` | string[] | UCE retrieval boosting 힌트 |
| `metadata_version` | int | 스키마 버전. 현재 1 |

### structure_type 값

| 값 | 설명 |
|----|------|
| `markdown` | markdown heading/list 구조 확인 |
| `json` | JSON 객체/배열 |
| `yaml` | YAML key-value 구조 |
| `code` | 프로그래밍 언어 소스코드 |
| `log` | timestamp 반복 패턴의 로그 |
| `table` | CSV/TSV 등 delimiter 기반 테이블 |
| `mixed` | 여러 구조가 혼재 |
| `plain_text` | 위 패턴 미해당 비정형 텍스트 |
| `unknown` | 판단 불가 |

### chunk_strategy 값

| 값 | 적용 대상 |
|----|----------|
| `heading-aware` | markdown, normalized IR |
| `sliding-window` | plain_text fallback |
| `log-window` | log 문서 |
| `table-row` | table/csv |
| `json-object` | json |
| `semantic-window` | mixed fallback |

---

## GET /health

DPE 서비스 상태 확인.

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

## GET /status

DPE 현재 설정 상태 확인.

```json
{
  "normalization_enabled": false,
  "min_confidence_threshold": 0.55,
  "uptime_seconds": 3842
}
```

---

## Error Behavior

| 상황 | 동작 |
|------|------|
| DPE 서비스 불가 | backend가 legacy 직접 저장 flow로 fallback |
| timeout | backend가 fallback. DPE_TIMEOUT_SECONDS 환경변수로 설정 |
| HTTP 5xx | backend가 fallback |
| `content` 빈 문자열 | DPE가 `plain_text` / confidence 0.0 / `sliding-window`로 반환 |
| normalization backend 호출 실패 | DPE가 normalization 없이 원본 텍스트로 fallback 응답 |

backend는 DPE 실패를 절대 사용자 에러로 노출하지 않는다. DPE 실패 시 기존 직접 저장 로직이 그대로 동작한다.

---

## Backend API — POST /api/normalize

DPE가 normalization이 필요할 때 backend에 역방향으로 호출하는 엔드포인트.

**DPE → backend 방향.** backend가 이 엔드포인트를 구현하고 DPE가 호출한다.

### Request Body

```json
{
  "content": "원본 비정형 텍스트",
  "structure_type": "plain_text",
  "filename": "report.txt"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | ✅ | 원본 비정형 텍스트 |
| `structure_type` | string | ✅ | DPE가 감지한 구조 유형 |
| `filename` | string | ❌ | 컨텍스트 힌트용 파일명 |

### Response Body

```json
{
  "normalized_content": "## 섹션1\n...\n## 섹션2\n...",
  "model_used": "exaone3.5:7.8b"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `normalized_content` | string | LLM이 생성한 markdown IR |
| `model_used` | string | 실제 사용된 모델명 |

### Normalization Prompt 원칙

backend가 LLM에 전달하는 prompt는 다음 원칙을 따른다.

```
다음 문서를 retrieval에 최적화된 markdown 구조로 변환하세요.
- 원문 정보를 삭제하지 마세요
- 의미 단위로 section과 heading을 생성하세요
- 요약하지 마세요. 구조만 추가하세요
- 시간순 흐름, entity, 관계를 보존하세요
```

**금지 사항:**
- 의미 요약
- 정보 삭제
- abstract 생성

**허용 사항:**
- section/heading 생성
- list 정규화
- entity 보존
- 시간순 흐름 보존
