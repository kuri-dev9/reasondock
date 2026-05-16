# chat_demo → RCA 통합 시스템 설계 문서

작성 기준: 현재 chat_demo 코드 및 proj_x 코드 분석 + XDR Spec(LTE-Call-KPI) 기반  
작성일: 2026-05-16

---

## 1. 현재 상태 분석 (AS-IS)

### 확인된 인프라
| 컴포넌트 | 현황 |
|---|---|
| MySQL 8.4 | **Docker 컨테이너** (`mysql84`) — 확인됨 |
| Ollama | 로컬 직접 실행 (Docker 외부, `localhost:11434`) |
| Backend FastAPI | 로컬 venv 실행 (`localhost:8000`) |
| Frontend React | 로컬 npm 실행 (`localhost:3000`) |

### 현재 Backend 구조
```
backend/app/
├── main.py          ← FastAPI 앱, CORS, 라우터 등록
├── config.py        ← DB URL, Ollama URL (pydantic-settings)
├── database.py      ← SQLAlchemy async engine
├── models.py        ← Conversation, Message, Attachment, KnowledgeDocument
├── schemas.py       ← Pydantic 요청/응답 스키마
├── vector_store.py  ← BM25+TF-IDF 하이브리드 검색 (pickle 기반)
├── tokenizer.py     ← 한국어 토크나이저
├── chunker.py       ← 텍스트 청킹
├── file_parser.py   ← 파일 텍스트 추출
└── routes/
    ├── chat.py          ← 핵심 채팅 + 2단계 RAG
    ├── conversations.py ← CRUD + 검색 + export/import
    ├── knowledge.py     ← 지식 문서 업로드 + 백그라운드 처리
    ├── attachments.py   ← 대화별 파일 첨부
    └── models.py        ← Ollama 모델 목록 조회
```

### proj_x에서 가져올 것
- `adapters/base.py` → `ModelAdapter` Protocol (완성된 추상화)
- `adapters/ollama.py` → OllamaAdapter (완성, 테스트됨)
- `adapters/openai.py` → OpenAIAdapter (완성, 테스트됨)
- `adapters/anthropic.py` → AnthropicAdapter (완성, 테스트됨)

---

## 2. XDR Spec 분석 (LTE-Call-KPI)

### 파일 포맷
```
파일명: LTE-CALL-KPI_R1_YYYYMMDD_HHMM.dat
구분자: 0x1E (ASCII Record Separator, 터미널에서 ^^ 로 표시)
레코드: 필드 수 = 154개 (No.1 ~ No.148 + Reserved No.149~154)
파일 크기: 1GB ~ 5GB
```

### 필드 구조 (섹션별)
```
[Summary]       No.1~2    : SummaryCreateTime, OngoingFlag
[User]          No.3~11   : IMSI, MDN, IMEI, ServiceCode, PayCode, Gender, Age, Vendor, Model
[Equipment]     No.12~33  : PGW_ID, SGW_ID, MME_ID, eNB_ID, Cell_ID, PDN_Type, IP 등
[Call Flow]     No.34~48  : call_type, call_start/end_time, call_duration, APN 등
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
[Interval]      No.119~134: interval_*, initial_access/core/paging_duration 등
[DCNR]          No.135~138: ue_dcnr, initial_nr_conn_time 등
[추가 필드]     No.139~148: ModifyBearer_count, spid, equip_nw, eNB_PLMN 등
```

### RCA 핵심 필드
```python
RCA_CORE_FIELDS = {
    # 분류
    "call_type":                      # Attach/Service/TAU/Detach/HO
    "attempt_flag":
    "success_flag":
    "drop_flag":

    # 장비 식별
    "MME_ID":
    "First_eNB_ID":
    "Last_eNB_ID":
    "SGW_ID":
    "APN":

    # 시간
    "call_start_time":
    "call_end_time":
    "call_duration_time":             # microsecond

    # 핵심 에러 (RCA 1순위)
    "first_error_interface_protocol": # S6a/S1AP/S11/NAS-EMM 등
    "first_error_message":
    "first_error_cause":              # TIMEOUT=900 포함
    "last_error_interface_protocol":
    "last_error_message":
    "last_error_cause":

    # 인터페이스별 에러 (RCA 2순위)
    "s1ap_error_Cause":
    "emm_error_Cause":
    "s11_error_Cause":                # Cause>=64
    "s6a_error_Cause":                # 3000~6000, 13000~16000
    "AuthenticationInformation_Cause":  # TIMEOUT=900
    "UpdateLocation_Cause":

    # 성능
    "initial_access_duration":        # microsecond
    "initial_core_duration":          # microsecond
    "initial_paging_duration":        # microsecond
}
```

### 주요 Enum 코드 매핑 (Semantic Extractor용)
```python
CALL_TYPE = {
    1:"Attach_MO", 2:"Attach_MT", 3:"Service_MO", 4:"Service_MT",
    5:"TAU", 6:"Paging", 7:"ExtService_MO", 8:"ExtService_MT",
    9:"Detach_MO", 10:"S1HO_InterMME"
}

ERROR_INTERFACE = {
    1:"S6a_Diameter", 2:"S1MME_S1AP", 3:"S11_GTPv2C",
    4:"S10_GTPv2C", 5:"S1MME_NAS-EMM", 6:"S1MME_NAS-ESM",
    7:"S3_GTPv1C", 8:"S13_Diameter"
}

TIMEOUT_CODE = 900

# 에러 판단 조건
S6A_ERROR  = lambda c: (3000 <= c < 6000) or (13000 <= c < 16000)
S11_ERROR  = lambda c: c >= 64
S3_ERROR   = lambda c: c >= 192   # Call Error 반영 안 함
```

---

## 3. 목표 구조 (TO-BE)

### 전체 아키텍처
```
Frontend (React)
    │
    ├─ [일반 Chat]  →  POST /api/conversations/{id}/chat  (기존 유지)
    │
    └─ [RCA 분석]   →  POST /api/rca/jobs               (파일 업로드 + Job 생성)
                        GET  /api/rca/jobs/{job_id}/stream (SSE 진행상황)

Backend (FastAPI) — Docker
    ├── routes/chat.py           ← 기존 유지 (adapter layer 추가)
    ├── routes/rca.py            ← 신규
    │
    ├── adapters/                ← proj_x에서 이식
    │   ├── base.py
    │   ├── ollama.py
    │   ├── openai.py
    │   └── anthropic.py
    │
    └── rca/                     ← 전체 신규
        ├── pipeline.py
        ├── upload_manager.py
        ├── xdr_parser.py
        ├── semantic_extractor.py
        ├── aggregator.py
        ├── rca_analyzer.py
        ├── summary_generator.py
        ├── prompt_builder.py
        └── spec_loader.py

MySQL — Docker (기존 mysql84 유지)
Ollama — 로컬 직접 실행 유지 (host.docker.internal로 접근)
```

### Docker Compose 목표 구성
```yaml
version: "3.9"

services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      DATABASE_URL: mysql+aiomysql://root:PASSWORD@mysql:3306/chat_demo
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
    depends_on:
      - mysql

  mysql:
    image: mysql:8.4
    container_name: mysql84
    environment:
      MYSQL_ROOT_PASSWORD: PASSWORD
    volumes:
      - mysql_data:/var/lib/mysql
    ports: ["3306:3306"]

volumes:
  mysql_data:
  xdr_uploads:
  rca_results:
  knowledge_data:
```

---

## 4. 수정/추가 항목 정리

### 수정 (기존 코드 변경)
| 파일 | 변경 내용 |
|---|---|
| `config.py` | OpenAI key, Anthropic key, 모델명 설정 추가 |
| `routes/models.py` | Ollama 전용 → provider별 통합 모델 목록 |
| `main.py` | rca 라우터 등록 |
| `models.py` | RcaJob, RcaResult ORM 테이블 추가 |
| `routes/chat.py` | adapter layer 경유로 변경, RCA 결과 컨텍스트 주입 |

### 신규 추가
```
backend/app/
├── adapters/           ← proj_x에서 복사
└── rca/                ← 전체 신규
routes/rca.py           ← 신규 엔드포인트
```

### 변경 없음
- `vector_store.py`, `chunker.py`, `tokenizer.py`, `file_parser.py`
- `routes/conversations.py`, `routes/knowledge.py`, `routes/attachments.py`

---

## 5. Backend Flow 재구성

### RCA Flow (대화 스레드 중심)
```
사용자: xDR 파일 업로드 버튼 클릭
    → POST /api/rca/jobs
      body: multipart { file, conversation_id, spec_file(optional) }
      → 파일 스트림 저장 (upload_manager)
      → DB에 RcaJob 생성 (status=queued)
      → BackgroundTask로 pipeline 시작
      → 응답: { job_id, status }

    → Frontend SSE 구독
      GET /api/rca/jobs/{job_id}/stream
      → 실시간 진행상황:
          {"step": "parsing",     "progress": 20, "msg": "레코드 파싱 중..."}
          {"step": "extracting",  "progress": 40, "msg": "의미 데이터 추출 중..."}
          {"step": "aggregating", "progress": 60, "msg": "장애 패턴 집계 중..."}
          {"step": "analyzing",   "progress": 75, "msg": "RCA 후보 분석 중..."}
          {"step": "llm",         "progress": 85, "msg": "LLM 추론 중..."}
          {"step": "done",        "progress": 100, "rca_result": {...}}

    → 완료 시:
      RCA 결과를 conversation의 assistant 메시지로 자동 저장
      → 대화 스레드에서 결과 확인
      → 이후 일반 채팅으로 후속 질문 가능 (RCA 요약이 context에 자동 포함)
```

### Timeout 전략
```
파일 업로드:      무제한 (스트림 저장)
Parsing + Agg:   10분 (asyncio.timeout 600)
LLM 추론:        10분 (asyncio.timeout 600)
SSE keep-alive:  30초마다 heartbeat 전송
전체 Job:        30분 hard limit → 초과 시 status=timeout
```

---

## 6. RCA Pipeline 모듈 상세

### 모듈 간 인터페이스 원칙
- 각 모듈은 **한 가지 책임**만 가진다
- 모듈 간 데이터는 **Polars DataFrame** 또는 **dict**로 통일
- 외부 의존성(LLM, DB)은 **pipeline.py에서만** 주입

### upload_manager.py
```
책임: 대용량 파일 스트림 저장
입력: FastAPI UploadFile
출력: 저장 경로 (Path)
핵심:
  - 8MB 청크 단위 저장 (메모리 전체 로드 금지)
  - 저장 경로: xdr_uploads/{job_id}/{filename}
```

### spec_loader.py
```
책임: spec 엑셀 → 런타임 파싱 스키마
입력: .xlsx 경로 (없으면 내장 기본 스키마 사용)
출력: FieldSpec 리스트 [{index, name, type, enum_map, description}]
핵심:
  - 기본 스키마는 LTE-Call-KPI 154 필드 하드코딩
  - 사용자 업로드 spec이 있으면 오버라이드
  - 파일 hash 기반 캐시
```

### xdr_parser.py
```
책임: raw .dat 파일 → Polars DataFrame
입력: 파일 경로, FieldSpec
출력: pl.DataFrame
핵심:
  - 0x1E(RS) 구분자로 필드 분리
  - 줄바꿈(\n)으로 레코드 분리
  - 64MB 청크 단위 처리
  - timeval → datetime 변환
  - 파싱 에러 레코드는 skip + 카운트
  - Polars LazyFrame 사용 (지연 평가)
  - 500K 레코드마다 parquet 중간 저장 (5GB 대응)

메모리 계산:
  레코드 1개 × 154 필드 ≈ 1.5KB
  500,000 레코드 ≈ 750MB RAM
  → 500K 단위 flush로 RAM 1GB 이내 유지
```

### semantic_extractor.py
```
책임: 숫자/코드 → 의미 문자열 변환
입력: pl.DataFrame (원시)
출력: pl.DataFrame (semantic 컬럼 추가)
변환:
  - call_type → call_type_name (Attach_MO, Service_MO 등)
  - first/last_error_interface_protocol → interface_name
  - first/last_error_cause: 900 → "TIMEOUT", else → "CAUSE_{code}"
  - success_flag + attempt_flag → result_class (success/fail/drop)
  - call_duration_time (microsec) → duration_ms
  - initial_access_duration → access_ms
```

### aggregator.py
```
책임: DataFrame → 집계 통계 + 이상 패턴 탐지
입력: semantic DataFrame
출력: AggResult dict

집계 항목:
  1. 전체 KPI: total, attempt, success, fail, drop, fail_rate
  2. call_type별 분포
  3. 실패 원인 Top-10 (first_error 기준, TIMEOUT 우선 플래그)
  4. 장비별 실패 집중도: MME Top-5, eNB Top-5, SGW Top-5
  5. 시간대별 패턴: 15분 버킷, 급증 구간 탐지 (평균 대비 2σ)
  6. APN별 분포

Polars 패턴:
  lf.group_by().agg().sort().head()  — Top-N
  lf.with_columns(dt.truncate("15m")).group_by("bucket")  — 시계열
```

### rca_analyzer.py
```
책임: 집계 결과 → Rule 기반 RCA 후보 생성
입력: AggResult dict
출력: RcaCandidate 리스트

Rule 우선순위:
  Rule 1: first_error TIMEOUT 폭증
    → suspected_cause = "transport_reachability"
  Rule 2: 특정 MME 실패 집중
    → suspected_cause = "MME_node_issue"
  Rule 3: 특정 eNB 실패 집중
    → suspected_cause = "eNB_radio_issue"
  Rule 4: S6a Diameter 에러 (3000~6000, 13000~16000)
    → suspected_cause = "HSS_authentication_failure"
  Rule 5: S11 GTP 에러 (cause >= 64)
    → suspected_cause = "SGW_PGW_bearer_issue"
  Rule 6: NAS-EMM 에러
    → suspected_cause = "NAS_signaling_issue"
  Rule 7: 시간대 급증 패턴
    → suspected_cause = "transient_network_event"

제외 처리:
  - Detach 정상 (success_flag=1 + DetachRequest) → cleanup, RCA 제외
```

### summary_generator.py
```
책임: RCA 후보 → LLM 입력용 구조화 요약
입력: AggResult + RcaCandidate 리스트
출력: RcaSummary dict (JSON 직렬화 가능)

출력 형태:
{
  "file_info":        {"filename", "period", "total_records"},
  "overall":          {"attempt", "success", "fail", "fail_rate"},
  "top_call_types":   [...],
  "top_failures":     [{"interface", "cause", "count", "ratio"}],
  "affected_equipment": {
    "mme": [{"id", "fail_count"}],
    "enb": [{"id", "fail_count"}]
  },
  "time_anomaly":     {"detected", "peak_window", "peak_rate"},
  "rca_candidates":   [{"rank", "suspected_cause", "confidence", "evidence"}]
}

핵심: LLM은 raw xDR이 아닌 이 JSON만 입력받는다
```

### prompt_builder.py
```
책임: RcaSummary → 최종 LLM 프롬프트 조립
입력: RcaSummary dict
출력: messages 리스트 [{role, content}]

시스템 프롬프트:
  "You are an LTE network expert specializing in RCA.
   Analyze the xDR statistical summary and:
   1. Identify the most probable root cause
   2. Explain the failure mechanism
   3. Suggest investigation steps
   4. Recommend immediate actions"
```

### pipeline.py
```
책임: 전체 파이프라인 오케스트레이션
입력: job_id, file_path, spec_path, conversation_id, progress_callback
흐름:
  1. spec_loader.load()            → progress 10
  2. xdr_parser.parse()            → progress 30
  3. semantic_extractor.extract()  → progress 45
  4. aggregator.aggregate()        → progress 60
  5. rca_analyzer.analyze()        → progress 75
  6. summary_generator.generate()  → progress 80
  7. prompt_builder.build()        → progress 85
  8. llm.chat()                    → progress 95
  9. DB 저장 + conversation 메시지 삽입 → progress 100

에러 처리:
  - 각 단계 try/except → job status=error
  - 파싱 에러율 > 50% → early fail
```

---

## 7. DB 스키마 추가 (models.py)

```python
class RcaJob(Base):
    __tablename__ = "rca_jobs"
    id:              int (PK)
    conversation_id: int (FK → conversations.id)
    filename:        str
    file_size:       int
    file_path:       str
    spec_path:       str | None
    status:          str   # queued/parsing/extracting/aggregating
                           # analyzing/llm/done/error/timeout
    progress:        int   # 0~100
    current_step:    str | None
    error_message:   str | None
    result_path:     str | None
    total_records:   int | None
    parsed_records:  int | None
    created_at:      datetime
    updated_at:      datetime

class RcaResult(Base):
    __tablename__ = "rca_results"
    id:              int (PK)
    job_id:          int (FK → rca_jobs.id)
    conversation_id: int (FK)
    summary_json:    JSON
    llm_response:    Text
    created_at:      datetime
```

---

## 8. API 엔드포인트 (routes/rca.py)

```
POST   /api/rca/jobs                    파일 업로드 + Job 생성
GET    /api/rca/jobs                    Job 목록 조회
GET    /api/rca/jobs/{job_id}           Job 상태 조회 (폴링용)
GET    /api/rca/jobs/{job_id}/stream    SSE 진행상황 스트림
GET    /api/rca/results/{job_id}        RCA 최종 결과
DELETE /api/rca/jobs/{job_id}           Job + 파일 삭제
```

---

## 9. LLM Provider 통합

### adapters/ (proj_x에서 그대로 이식)
```python
# adapters/__init__.py
def get_adapter(model: str) -> ModelAdapter:
    if model.startswith("openai/"):
        return OpenAIAdapter()
    elif model.startswith("anthropic/"):
        return AnthropicAdapter()
    else:
        return OllamaAdapter()
```

### 모델 목록 API 응답 변경
```json
[
  {"provider": "ollama",    "name": "gemma4:26b",                  "display": "Gemma4 26B (Local)",  "available": true},
  {"provider": "openai",    "name": "openai/gpt-4o",               "display": "GPT-4o",              "available": true},
  {"provider": "anthropic", "name": "anthropic/claude-sonnet-4-5", "display": "Claude Sonnet",       "available": false}
]
```
`available`: API key 설정 여부 — false 시 UI에서 비활성화

### Chat flow 변경
```python
# 기존: httpx로 Ollama 직접 호출
# 변경: adapter 경유

adapter = get_adapter(model)
async for token in adapter.chat(messages, model, {}):
    yield sse_token(token)
```

---

## 10. Frontend 변경 (최소화 원칙)

### 추가 UI
```
ChatInput:
  - "xDR 분석" 버튼 추가 (.dat 파일 선택)
  - 모델 선택 드롭다운: provider별 통합 목록 (key 없으면 greyed out)

ChatMessage:
  - system role 메시지 렌더링 (진행상황 표시)
  - RCA 결과 구조화 카드 렌더링 (선택)
```

### RCA 대화 흐름 (UI 관점)
```
[사용자] xDR 파일 업로드
[시스템] 파일 업로드 완료. RCA 분석을 시작합니다.
[시스템] 레코드 파싱 중... (20%)
[시스템] 장애 패턴 집계 중... (60%)
[시스템] LLM 추론 중... (85%)
[AI]     RCA 분석 결과: S1AP TIMEOUT이 전체 실패의 78%...
[사용자] MME01 장애 시 조치 방법은?
[AI]     (RCA 결과를 context로 활용하여 답변)
```

---

## 11. Production 위험 포인트

### 🔴 고위험 (반드시 해결)

**1. BackgroundTask 신뢰성**
```
문제: uvicorn 재시작 시 처리 중인 job 소실
해결: DB에 status 저장 (설계 반영됨)
     재시작 시 status=parsing/extracting → queued 리셋
     장기적으로는 Celery or ARQ 도입 검토
```

**2. 업로드 파일 무한 누적**
```
문제: 1~5GB .dat 파일이 누적되면 디스크 포화
해결: job 완료 후 원본 .dat 자동 삭제 (결과 JSON만 보관)
     업로드 디렉토리 용량 상한 설정
```

**3. Polars OOM (5GB 파일)**
```
문제: 5GB 파일 처리 시 Polars + DataFrame 동시 존재 → OOM
해결: LazyFrame streaming (설계 반영됨)
     500K 레코드마다 parquet 중간 저장 후 GC
```

**4. SSE 끊김 시 진행상황 유실**
```
문제: 브라우저 탭 닫기 / 네트워크 이상 → 재접속 시 상태 불명
해결: progress를 DB에 10초마다 저장
     재접속 시 GET /api/rca/jobs/{id} 로 현재 상태 복원
```

### 🟡 중위험 (초기 구현 후 개선)

**5. LLM 세마포어 병목**
```
문제: Chat 응답과 RCA LLM 호출이 동일 세마포어를 공유
해결: Chat용 / RCA용 세마포어 분리
     Chat: Semaphore(3), RCA: Semaphore(1)
```

**6. MySQL 마이그레이션 도구 부재**
```
현황: Alembic 미사용 (CLAUDE.md 명시)
해결: RcaJob/RcaResult 추가 시 테이블 생성 SQL 스크립트 관리
     이번 기회에 Alembic 도입 권장
```

### 🟢 Docker 자원 영향

```
현재 MySQL이 Docker에 있음 (mysql84 확인됨)

신규 Docker 추가:
  backend container: ~512MB RAM (평시)
  Polars 처리 시:   ~4~8GB RAM 피크 (5GB 파일 기준)

Ollama는 Docker 외부 유지:
  이유: GPU 접근, 모델 파일 크기
  연결: host.docker.internal:11434 (Mac/Windows)
       host network mode (Linux)

주의사항:
  1. Docker 네트워크 오버헤드 (backend ↔ mysql)
     → 같은 bridge network에 두면 영향 최소
  2. Volume mount I/O (Mac 환경)
     → Mac에서 host mount는 Linux 대비 30~50% 느림
     → named volume 사용 권장
  3. Polars 멀티코어 활용
     → Docker CPU limit 없이 두는 것이 처리 속도에 유리

권장 docker-compose resource 설정:
  backend:
    deploy:
      resources:
        limits:
          memory: 12G
        reservations:
          memory: 2G
```

---

## 12. 구현 단계별 계획

### Phase 1: 기반 정비 (1~2일)
- [ ] `adapters/` 디렉토리 생성 — proj_x에서 복사
- [ ] `config.py` 확장 — OpenAI/Anthropic key, 모델명
- [ ] `routes/models.py` 수정 — provider 통합 목록
- [ ] `models.py` 확장 — RcaJob, RcaResult 테이블
- [ ] `docker-compose.yml` 작성 — backend 컨테이너화
- [ ] `routes/chat.py` — adapter layer 적용

### Phase 2: xDR Parser + Aggregator (3~5일)
- [ ] `rca/spec_loader.py` — 내장 스키마 (154 필드)
- [ ] `rca/xdr_parser.py` — RS 파싱, Polars LazyFrame
- [ ] `rca/semantic_extractor.py` — enum 코드 변환
- [ ] `rca/aggregator.py` — Polars 집계

### Phase 3: RCA 로직 + LLM 연동 (2~3일)
- [ ] `rca/rca_analyzer.py` — Rule 기반 후보
- [ ] `rca/summary_generator.py` — 구조화 요약
- [ ] `rca/prompt_builder.py` — 프롬프트 조립
- [ ] `rca/pipeline.py` — 전체 오케스트레이션

### Phase 4: API + Frontend (2~3일)
- [ ] `routes/rca.py` — 업로드, Job 관리, SSE
- [ ] Frontend: xDR 업로드 버튼, 진행상황 표시
- [ ] Frontend: 모델 선택 UI 개선 (provider 통합)

---

## 13. 미확인 사항 (확인 필요)

1. **xDR 필드 인코딩 방식**: spec의 "timeval", "uint", "string" 타입이
   텍스트 기반(0x1E로 구분된 ASCII 숫자)인지, 순수 바이너리(고정 바이트)인지
   → 실제 .dat 파일 샘플 확인 필요

2. **OngoingFlag 처리**: 0=Start, 1=Interim, 2=End 레코드 중
   RCA 분석 시 End(2)만 사용할지, 전체 사용할지?

3. **Interval 레코드**: 하나의 Call에 대해 여러 레코드(Start→Interim→End)가 있는지?

4. **RCA 결과 보존 기간**: 완료된 Job과 결과 파일을 얼마나 보관할지?
