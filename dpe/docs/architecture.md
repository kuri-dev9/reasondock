# DPE (Document Processing Engine) — 설계 문서

> 작성일: 2026-05-21
> 상태: 설계 확정, 구현 대기
> 짝꿍: UCE (Universal Context Engine)

---

## 개요

DPE는 reasondock의 문서 ingestion 전처리 계층이다.

UCE가 query-time context optimization에 집중한다면,
DPE는 upload-time document understanding에 집중한다.

```
파일 업로드
    ↓
DPE (Document Processing Engine)
    → structure detection
    → optional normalization
    → markdown IR 생성
    ↓
backend DB 저장 (normalized content_text)
    ↓
UCE → 항상 markdown처럼 보이는 문서만 수신
    → 기존 heading-aware retrieval 그대로 동작
```

UCE 입장에서는 모든 문서가 markdown처럼 보인다.
DPE가 그 보장을 담당한다.

---

## 역할 분리

| 계층 | 역할 | 시점 |
|------|------|------|
| DPE | 문서 구조 분석 + normalization | upload-time |
| UCE | retrieval + compression + prompt assembly | query-time |
| Answer LLM | reasoning + answer generation | query-time |

**DPE는 절대 답변을 생성하지 않는다.**
**UCE는 절대 structure detection/normalization을 수행하지 않는다.**

---

## 시스템 구성

별도 컨테이너로 운영된다.

```
reasondock/
  backend/         ← 기존
  frontend/        ← 기존
  uce/             ← 기존
  dpe/             ← 신규 (Document Processing Engine)
```

호출 흐름:

```
사용자 파일 업로드
    ↓
backend (파일 저장)
    ↓
backend → DPE /process  (HTTP API)
    ↓
DPE → structure detection
    ↓
정형 문서?
    ├── YES → 기존 parser/chunker
    └── NO
           ↓
        normalization 옵션 활성화?
           ├── NO  → fallback plain chunking
           └── YES
                  ↓
               DPE → backend /api/normalize (HTTP)
                  ↓
               backend → configured LLM 호출
                  ↓
               normalized markdown IR 반환
    ↓
Document Metadata 생성
    ↓
normalized content + metadata → backend 반환
    ↓
backend DB 저장
```

**DPE는 LLM을 직접 호출하지 않는다.**
normalization이 필요한 경우 backend `/api/normalize` 엔드포인트를 통해 요청한다.
backend가 현재 설정된 모델(Ollama)을 사용하여 처리 후 반환한다.

---

## API

### DPE가 제공하는 API

#### `POST /process`

파일 업로드 시 backend가 호출하는 단일 엔드포인트.

**Request:**
```json
{
  "document_id": "att_123",
  "filename": "report.txt",
  "content": "원본 문서 전체 텍스트",
  "options": {
    "normalization_enabled": true,
    "normalization_model": null,
    "backend_normalize_url": "http://backend:8000/api/normalize"
  }
}
```

**Response:**
```json
{
  "document_id": "att_123",
  "normalized_content": "## 장애 원인\n...\n## 영향도\n...",
  "structure_type": "plain_text",
  "structure_confidence": 0.31,
  "chunk_strategy": "heading-aware",
  "normalization_applied": true,
  "normalization_model": "exaone3.5:7.8b",
  "retrieval_hints": ["heading", "entity"],
  "metadata_version": 1
}
```

normalization이 불필요한 정형 문서의 경우:
```json
{
  "document_id": "att_123",
  "normalized_content": "원본 내용 그대로 (또는 경미한 정규화만)",
  "structure_type": "markdown",
  "structure_confidence": 0.95,
  "chunk_strategy": "heading-aware",
  "normalization_applied": false,
  "normalization_model": null,
  "retrieval_hints": ["heading", "entity", "table"],
  "metadata_version": 1
}
```

### backend가 제공하는 API (DPE → backend)

#### `POST /api/normalize`

DPE가 normalization이 필요할 때 backend에 요청.
backend는 현재 설정된 LLM으로 처리 후 반환.

**Request:**
```json
{
  "content": "원본 비정형 텍스트",
  "structure_type": "plain_text",
  "filename": "report.txt"
}
```

**Response:**
```json
{
  "normalized_content": "## 섹션1\n...\n## 섹션2\n...",
  "model_used": "exaone3.5:7.8b"
}
```

---

## Structure Detection

### 1차: 확장자 기반 hint

| 확장자 | 추정 structure_type |
|--------|-------------------|
| `.md`, `.markdown` | markdown |
| `.json` | json |
| `.yaml`, `.yml` | yaml |
| `.py`, `.js`, `.ts` 등 | code |
| `.csv`, `.tsv` | table/csv |
| `.log` | log |
| `.txt` | unknown (2차 판단 필요) |
| 기타 | unknown |

### 2차: Content sniffing

| 패턴 | 판단 |
|------|------|
| `\n#` 빈도 높음 | markdown |
| `{`, `[` 시작 | json |
| `---`, `key: value` 패턴 | yaml |
| `def `, `class `, `import ` | code |
| timestamp 패턴 반복 | log |
| `,` delimiter 반복 | table/csv |
| 위 패턴 혼재 | mixed |
| 해당 없음 | plain_text |

### Structure Confidence

0.0 ~ 1.0 점수.
`0.55` 미만이면 normalization 후보로 판단.

---

## LLM Normalization 대상

다음 조건 중 하나 이상 해당 시 normalization 후보:

- `structure_type`: `plain_text`, `mixed`, `unknown`
- `structure_confidence` < 0.55
- log + narrative 혼합
- excel-derived text

### Normalization 목표

답변 생성이 아니라 **retrieval-friendly structure 생성**이 목적이다.

```
BAD (하면 안 되는 것):
- 의미 요약
- 정보 삭제
- abstract 생성

GOOD (목표):
- section 생성
- heading 생성
- list 정규화
- entity 보존
- 시간순 흐름 보존
- 관계 보존
```

### LLM Prompt 방향 (예시)

```
다음 문서를 retrieval에 최적화된 markdown 구조로 변환하세요.
- 원문 정보를 삭제하지 마세요
- 의미 단위로 section과 heading을 생성하세요
- 요약하지 마세요. 구조만 추가하세요
```

### Normalization Content 상한선

LLM context window 제약으로 인해 normalization 대상 텍스트에 상한선을 둔다.

| 항목 | 값 | 근거 |
|------|-----|------|
| 기본 상한선 | **8,000자** | EXAONE 3.5 7.8b 기준 ~32k context에서 프롬프트 + 출력 여유 포함 안전 범위 |
| 환경변수 | `DPE_NORMALIZATION_MAX_CHARS` | 모델 교체 시 조정 가능 |

content 길이가 상한선을 초과하면 normalization을 수행하지 않고 fallback으로 처리한다.

```
content 길이 > DPE_NORMALIZATION_MAX_CHARS
    → normalization_applied = false
    → chunk_strategy = "sliding-window" (plain_text 기준)
    → 원본 텍스트 그대로 반환
```

요약/삭제 없이 구조만 추가하는 것이 normalization 목표이므로,
부분 텍스트만 normalization하는 것보다 전체를 원본으로 보존하는 편이 낫다.

---

## Document Metadata Contract

backend ↔ UCE 사이에 명시적 metadata 전달.

```json
{
  "document_id": "att_123",
  "structure_type": "markdown",
  "structure_confidence": 0.91,
  "chunk_strategy": "heading-aware",
  "normalization_applied": true,
  "normalization_model": "exaone3.5:7.8b",
  "retrieval_hints": ["heading", "entity"],
  "source_format": "txt",
  "metadata_version": 1
}
```

### Chunk Strategy 정의

| strategy | 적용 대상 |
|----------|----------|
| `heading-aware` | markdown, normalized IR |
| `sliding-window` | plain_text fallback |
| `log-window` | log 문서 |
| `table-row` | csv, table |
| `json-object` | json |
| `semantic-window` | mixed fallback |

---

## 환경변수

```env
DPE_ENABLED=true
DPE_BASE_URL=http://dpe:8200
DPE_TIMEOUT_SECONDS=30
DPE_NORMALIZATION_ENABLED=false
DPE_NORMALIZATION_MIN_CONFIDENCE=0.55
```

backend는 `DPE_ENABLED=true`일 때만 파일 업로드 시 DPE를 호출한다.
`false`이면 기존 직접 저장 로직 그대로 동작 (하위 호환).

---

## UCE 변경사항

**없음.**

DPE가 normalized markdown을 생성하므로
UCE는 기존 heading-aware retrieval을 그대로 사용한다.

단, 향후 UCE가 `chunk_strategy`, `retrieval_hints` metadata를
retrieval boosting에 활용할 수 있도록
`rag_chunks` 각 항목에 metadata 필드 추가는 검토 가능.
(이번 범위 외)

---

## 이번 범위 제외

- semantic graph
- auto taxonomy
- long-term memory
- answer generation retry
- vector DB redesign
- multi-stage reasoning
- latent topic clustering

**범위: document ingestion stabilization에 집중.**

---

## 기대 효과

| 케이스 | 현재 | DPE 적용 후 |
|--------|------|------------|
| `.md` 파일 업로드 | heading-aware retrieval 정상 | 동일 |
| `.txt`로 저장된 markdown | plain_text로 처리, retrieval 품질 저하 | structure detection → markdown으로 처리 |
| 비정형 log/report | retrieval 품질 붕괴 | normalization → heading-aware retrieval |
| excel-derived text | retrieval 거의 불가 | normalization → 구조화 후 retrieval |

---

## 향후 확장 가능성

DPE와 UCE는 짝꿍 구조로 함께 진화한다.

```
DPE: upload-time intelligence
UCE: query-time intelligence
```

장기적으로:
- DPE가 생성한 metadata를 UCE retrieval boosting에 활용
- DPE normalization 품질 피드백 루프
- chunk strategy 자동 최적화
