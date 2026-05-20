# ReasonDock RCA 통합 시스템 설계 문서

작성 기준: reasondock 코드 분석 + XDR Spec(LTE-Call-KPI) 기반
최종 수정: 2026-05-20

---

## 1. 현재 상태 분석 (AS-IS)

### 확인된 인프라
| 컴포넌트 | 현황 |
|---|---|
| MySQL 8.4 | Docker 컨테이너 (`mysql84`) |
| Ollama | 로컬 직접 실행 (Docker 외부, `localhost:11434`) |
| Backend FastAPI | 로컬 venv 실행 (`localhost:8000`) |
| Frontend React | 로컬 npm 실행 (`localhost:3000`) |

### 현재 Backend 구조 (reasondock 기준)
```
backend/app/
├── main.py
├── config.py          ← DB URL, Ollama URL만 존재 (provider 확장 필요)
├── database.py
├── models.py          ← RcaJob, RcaResult 이미 존재
├── schemas.py
├── vector_store.py
├── tokenizer.py
├── chunker.py
├── file_parser.py
├── rca/
│   ├── pipeline.py        ← xDR → summary JSON 까지만 담당 (LLM 호출 없음이 목표)
│   ├── analyzer.py        ← 집계 + RCA 후보 생성
│   ├── parser.py          ← 0x1E RS 구분자 파싱
│   ├── prompt_builder.py  ← summary → LLM 프롬프트 조립
│   └── spec_loader.py     ← 154 필드 스키마
└── routes/
    ├── chat.py        ← httpx로 Ollama 직접 호출 (개선 필요)
    ├── rca.py         ← httpx로 Ollama 직접 호출 중복 존재 (제거 필요)
    ├── conversations.py
    ├── knowledge.py
    ├── attachments.py
    └── models.py
```

### 현재 구조의 핵심 문제
```
routes/chat.py  → httpx로 Ollama 직접 호출
routes/rca.py   → httpx로 Ollama 또 직접 호출  ← 중복, 잘못된 위치

문제:
  - LLM 호출 코드가 두 군데로 분산
  - 모델 변경/추가 시 두 곳 모두 수정 필요
  - thinking 처리, timeout, retry 등 각자 구현
  - RCA 모듈이 LLM을 알아야 하는 구조 → 책임 분리 위반
```

---

## 2. 설계 철학 및 역할 분리

### 핵심 원칙

```
RCA Pipeline = 데이터 정제/가공 전담
LLM 호출     = 한 곳(services/llm.py)에서만

xDR 5GB
  ↓ [rca/pipeline.py]  파싱 → 집계 → RCA 후보 → summary JSON 생성
  ↓ [rca/prompt_builder.py]  summary → 프롬프트 조립
  ↓ [services/llm.py]  LLM 호출 (chat.py, rca.py 모두 여기서)
  ↓ LLM 응답
```

RCA Pipeline의 책임 범위: **"xDR 파일 → summary JSON"** 까지만.
LLM을 모르는 모듈이어야 한다.

### MCP와의 관계
이 구조에서 RCA Pipeline 전체는 개념적으로 하나의 Tool이다.

```
Tool: xdr_rca_analyze
  input:  xDR 파일
  output: structured RCA summary JSON

LLM: summary JSON을 받아 reasoning/설명 생성
```

현재 단계에서 MCP 프로토콜 형식을 따를 필요는 없다.
Ollama(gemma4:26b)는 tool_use가 불안정하므로 Pipeline 주도 구조가 더 적합하다.

---

## 3. 목표 구조 (TO-BE)

### 전체 아키텍처
```
Frontend (React)
    │
    ├─ [일반 Chat]  →  POST /api/conversations/{id}/chat
    └─ [RCA 분석]   →  POST /api/rca/jobs

Backend (FastAPI)
    ├── routes/chat.py       ← services/llm.py 경유
    ├── routes/rca.py        ← pipeline 호출 후 services/llm.py 경유
    ├── services/
    │   └── llm.py           ← ★ LLM 호출 단일 진입점
    ├── adapters/            ← provider 추상화
    └── rca/                 ← 데이터 정제/가공 전담 (LLM 호출 없음)
        ├── pipeline.py      ← xDR → summary JSON 오케스트레이션
        ├── parser.py        ← 0x1E RS 파싱
        ├── analyzer.py      ← 집계 + RCA 후보 생성
        ├── prompt_builder.py ← summary → 프롬프트 (LLM은 모름)
        └── spec_loader.py
```

### LLM 호출 흐름 (변경 후)
```
[일반 Chat]
  routes/chat.py
    → services/llm.py.stream_chat(model, messages)
    → adapters.get_adapter(model).chat(...)
    → SSE streaming 응답

[RCA 분석]
  routes/rca.py
    → rca/pipeline.py         (xDR → summary JSON)
    → rca/prompt_builder.py   (summary → messages)
    → services/llm.py.chat(model, messages)   ← 동일한 진입점
    → 결과 저장 → conversation 메시지 삽입
```

### Docker Compose 목표
```yaml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      DATABASE_URL: mysql+aiomysql://root:PASSWORD@mysql:3306/reasondock
      OLLAMA_BASE_URL: http://host.docker.internal:11434
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      OPENAI_MODEL: openai/gpt-4o
      ANTHROPIC_MODEL: anthropic/claude-sonnet-4-5
      DEFAULT_OLLAMA_MODEL: gemma4:26b
    volumes:
      - xdr_uploads:/app/xdr_uploads
      - rca_results:/app/rca_results
      - knowledge_data:/app/knowledge_data
    depends_on: [mysql]

  mysql:
    image: mysql:8.4
    container_name: mysql84
    volumes: [mysql_data:/var/lib/mysql]
    ports: ["3306:3306"]

volumes:
  mysql_data:
  xdr_uploads:
  rca_results:
  knowledge_data:
```

---

## 4. services/llm.py 설계 (신규 핵심 모듈)

```
책임: 모든 LLM 호출의 단일 진입점
     - provider 분기 (Ollama / OpenAI / Anthropic)
     - streaming / non-streaming 모두 지원
     - thinking 필드 처리 (gemma4 thinking 모드 대응)
     - timeout, error handling 통일
     - chat.py, rca.py 양쪽에서 사용

주요 함수:
  async def stream_chat(model, messages, options) → AsyncGenerator[Event]
    - chat.py에서 사용 (SSE streaming)
    - Event: {type: "thinking"|"token"|"done"|"error", content: str}

  async def chat(model, messages, options) → str
    - rca.py에서 사용 (non-streaming, 결과 전체 반환)
    - thinking only 응답 시 → LLMError("thinking_only") 발생
    - 빈 응답 시 → LLMError("empty_response", done_reason, eval_count) 발생

에러 진단 정보 보존:
  - done_reason (stop / length / ...)
  - eval_count (실제 생성 토큰 수)
  - thinking 내용 유무
  - raw 응답 일부 (디버깅용)
```

---

## 5. XDR Spec 분석 (LTE-Call-KPI)

### 파일 포맷
```
파일명: LTE-CALL-KPI_R1_YYYYMMDD_HHMM.dat
구분자: 0x1E (ASCII Record Separator)
필드 수: 154개
파일 크기: 1GB ~ 5GB
인코딩: 텍스트 기반 (0x1E로 구분된 ASCII 값)
```

### 필드 구조 (섹션별)
```
[Summary]       No.1~2    : SummaryCreateTime, OngoingFlag
[User]          No.3~11   : IMSI, MDN, IMEI, ServiceCode, PayCode, Gender, Age, Vendor, Model
[Equipment]     No.12~33  : PGW_ID, SGW_ID, MME_ID, eNB_ID, Cell_ID, PDN_Type, IP 등
[Call Flow]     No.34~44  : call_type, call_start/end_time, call_duration, APN 등
[S6a Diameter]  No.45~51  : s6a_error_*, AuthenticationInformation_Cause, UpdateLocation_Cause
[S13 Diameter]  No.52~56  : s13_error_*, MEIdentityCheck_Cause
[S1-MME S1AP]   No.57~67  : s1ap_error_*, UEContextRelease_Cause
[NAS-EMM]       No.68~75  : emm_error_*, DetachRequest_*
[NAS-ESM]       No.76~78  : esm_error_*
[S11 GTPv2C]    No.79~81  : s11_error_*
[S10 GTPv2C]    No.82~84  : s10_error_*
[S3 GTPv1C]     No.85~87  : s3_error_*
[SGd SMS]       No.88~93  : sms_*_error_cause
[KPI Flags]     No.94~110 : attempt_flag, success_flag, drop_flag 등
[Error]         No.111~118: first_error_*, last_error_*
[Interval]      No.119~134: initial_access/core/paging_duration 등
[DCNR]          No.135~138: ue_dcnr, initial_nr_conn_time 등
[추가]          No.139~148: ModifyBearer_count, spid, equip_nw, eNB_PLMN 등
```

### RCA 핵심 필드
```
분류:      call_type, attempt_flag, success_flag, drop_flag
장비:      MME_ID, First_eNB_ID, Last_eNB_ID, SGW_ID, APN
시간:      call_start_time, call_end_time, call_duration_time (microsecond)
에러(1순위): first_error_interface_protocol, first_error_message, first_error_cause (TIMEOUT=900)
            last_error_interface_protocol, last_error_message, last_error_cause
에러(2순위): s1ap_error_Cause, emm_error_Cause, s11_error_Cause (>=64)
            s6a_error_Cause (3000~6000, 13000~16000), AuthenticationInformation_Cause
성능:      initial_access_duration, initial_core_duration, initial_paging_duration (microsecond)
```

### Enum 코드 매핑
```python
CALL_TYPE = {
    "1":"Attach_MO", "2":"Attach_MT", "3":"Service_MO", "4":"Service_MT",
    "5":"TAU", "6":"Paging", "7":"ExtService_MO", "8":"ExtService_MT",
    "9":"Detach_MO", "10":"S1HO_InterMME"
}
ERROR_INTERFACE = {
    "1":"S6a_Diameter", "2":"S1MME_S1AP", "3":"S11_GTPv2C",
    "4":"S10_GTPv2C",  "5":"S1MME_NAS-EMM", "6":"S1MME_NAS-ESM",
    "7":"S3_GTPv1C",   "8":"S13_Diameter"
}
TIMEOUT_CODE = 900
```

---

## 6. RCA Pipeline 모듈 상세

### 책임 범위 원칙
- `rca/` 패키지는 LLM을 모른다
- LLM 호출은 `services/llm.py` 에서만
- 모듈 간 데이터: dict 또는 dataclass

### parser.py (현재 존재, 유지)
```
책임: .dat 파일 → list[dict[str, str]]
구분자: 0x1E
출력: ParsedXdr(records, stats)
stats: total_lines, parsed_records, skipped_records, bad_field_counts
```

### analyzer.py (현재 존재, 유지)
```
책임: records → 집계 통계 + RCA 후보
집계: 전체 KPI, call_type별, top_failures, 장비별, 시계열, APN별
RCA 후보: Rule 기반 (TIMEOUT 폭증 / MME 집중 / eNB 집중 / S6a / S11 / NAS-EMM / 시간대 급증)
제외: Detach 정상 cleanup
```

### prompt_builder.py (현재 존재, 유지)
```
책임: summary dict → LLM messages 리스트
입력: summary dict (analyzer 출력)
출력: [{"role": "system", "content": ...}, {"role": "user", "content": ...}]
LLM을 직접 호출하지 않음
```

### pipeline.py (수정 필요)
```
책임: xDR → summary dict 반환까지만
     LLM을 호출하지 않는다
     LLM 호출은 routes/rca.py에서 services/llm.py 경유로 수행
현재: analyze_xdr_file() → summary dict 반환 (LLM 호출 없음) ← 이미 올바름
확인: pipeline.py 자체는 LLM을 호출하지 않으므로 변경 불필요
LLM 호출 제거 대상: routes/rca.py 의 _generate_llm_rca() → services/llm.py 로 이동
```

---

## 7. DB 스키마 (현재 구현 완료)

```python
# models.py에 이미 존재
RcaJob:    id, conversation_id, filename, file_size, file_path,
           status, progress, current_step, error_message,
           result_path, total_records, parsed_records,
           created_at, updated_at

RcaResult: id, job_id, conversation_id,
           summary_json (JSON), llm_response (Text),
           created_at
```

---

## 8. API 엔드포인트 (routes/rca.py)

```
POST   /api/rca/jobs              파일 업로드 + 분석 + 결과 반환 (동기)
GET    /api/rca/jobs              Job 목록
GET    /api/rca/jobs/{job_id}     Job 상태
GET    /api/rca/results/{job_id}  RCA 결과 JSON
```

---

## 9. LLM Provider 통합 (adapters/)

### provider 분기
```python
# adapters/__init__.py
def get_adapter(model: str) -> ModelAdapter:
    if model.startswith("openai/"):   return OpenAIAdapter()
    if model.startswith("anthropic/"): return AnthropicAdapter()
    return OllamaAdapter()
```

### config.py 확장 필요
```python
class Settings(BaseSettings):
    database_url: str
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str = ""
    openai_model: str = "openai/gpt-4o"
    anthropic_api_key: str = ""
    anthropic_model: str = "anthropic/claude-sonnet-4-5"
    default_ollama_model: str = "gemma4:26b"
```

### 모델 목록 API (routes/models.py 변경)
```json
[
  {"provider": "ollama",    "name": "gemma4:26b",                  "display": "Gemma4 26B (Local)", "available": true},
  {"provider": "openai",    "name": "openai/gpt-4o",               "display": "GPT-4o",             "available": false},
  {"provider": "anthropic", "name": "anthropic/claude-sonnet-4-5", "display": "Claude Sonnet",      "available": false}
]
```
available = API key 설정 여부. false 시 UI에서 비활성화.

---

## 10. Frontend 변경 (최소화 원칙)

```
ChatInput:
  - xDR 분석 버튼 추가 (.dat 파일 선택)
  - 모델 선택: provider별 통합 목록, key 없으면 greyed out

ChatMessage:
  - system role 메시지 렌더링 (진행상황 표시용)

RCA 대화 흐름:
  [사용자] xDR 파일 업로드
  [AI]     RCA 분석 결과 (Rule 기반 markdown + LLM 리포트)
  [사용자] 후속 질문
  [AI]     RCA summary를 context로 활용하여 답변
```

---

## 11. Production 위험 포인트

### 🔴 고위험

**LLM 호출 중복 (즉시 해결)**
```
현재: routes/rca.py._generate_llm_rca() 에서 httpx로 Ollama 직접 호출
해결: services/llm.py 로 통합, rca.py에서 직접 httpx 호출 제거
```

**thinking-only 빈 응답 미처리**
```
현재: message.content 비면 /api/generate 재시도 → 그래도 비면 에러
문제: message.thinking 유무, eval_count, done_reason 진단 정보 부족
해결: services/llm.py에서 통합 처리
  - thinking 있고 content 없으면 → LLMError("thinking_only")
  - eval_count=0 이면 → LLMError("empty_response")
  - done_reason="length" 이면 → LLMError("context_exceeded")
```

**BackgroundTask 신뢰성**
```
현재: 동기 처리 (upload → analyze → llm → 저장 한 번에)
문제: uvicorn 재시작 시 처리 중 job 소실 가능
해결: DB status 저장으로 재시작 후 복원 가능 (현재 구조 유지)
```

**업로드 파일 누적**
```
해결: job 완료 후 원본 .dat 자동 삭제 (결과 JSON만 보관)
```

### 🟡 중위험

**LLM 세마포어 미분리**
```
해결: services/llm.py 에서 Chat용 / RCA용 세마포어 분리
     Chat: Semaphore(3), RCA: Semaphore(1)
```

**대용량 파일 메모리**
```
현재: 전체 records를 list로 메모리에 로드
개선: 파일 크기 > 500MB 시 Polars LazyFrame + parquet 중간 저장 전환
```

### 🟢 Docker 자원 영향
```
MySQL: 기존 mysql84 컨테이너 유지
Backend: Docker로 이전 (~512MB 평시, 피크 최대 8GB)
Ollama: Docker 외부 유지 → host.docker.internal:11434

Mac 환경 주의:
  - named volume 사용 (host mount 대비 I/O 30~50% 빠름)
  - Docker CPU limit 없이 유지 (Polars 멀티코어 활용)
```

---

## 12. 구현 단계 (Codex 작업 기준)

### Phase 1: LLM 단일화 (최우선)
- [ ] `services/llm.py` 신규 생성
  - `stream_chat()`: chat.py용 SSE streaming
  - `chat()`: rca.py용 non-streaming
  - thinking / empty / context_exceeded 에러 처리 통합
- [ ] `adapters/` proj_x에서 이식 (base, ollama, openai, anthropic)
- [ ] `routes/chat.py` → services/llm.py 경유로 변경
- [ ] `routes/rca.py` → `_generate_llm_rca()` 제거, services/llm.py 경유로 변경
- [ ] `config.py` 확장 (OpenAI/Anthropic key, 모델명)

### Phase 2: Provider 통합
- [ ] `routes/models.py` → provider별 통합 목록 반환
- [ ] Frontend ModelSelector: provider 통합, key 없으면 비활성화

### Phase 3: xDR 대용량 대응 (필요 시)
- [ ] 파일 크기 임계값 기반 Polars LazyFrame 전환
- [ ] parquet 중간 저장

### Phase 4: Docker 이전
- [ ] `docker-compose.yml` 작성
- [ ] backend Dockerfile 작성
