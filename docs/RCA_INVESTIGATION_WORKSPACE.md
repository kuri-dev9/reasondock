# RCA Investigation Workspace 아키텍처 설계

작성 기준: 2026-05-22
상태: TO-BE 설계 (구현 전)

---

## 1. 설계 철학

### AS-IS (현재)

```
xDR 업로드 → 파싱 → 집계 → LLM 리포트 → 정적 결과 (1회성)
```

문제점:
- 재조회 불가 (원본 파일 분석 후 삭제)
- 인터랙티브 조사 불가
- IMSI 추적, 시계열 분석, 장비별 조회 등 불가
- LLM이 집계 결과만 받음 (원본 레코드 접근 불가)

### TO-BE (목표)

```
xDR 업로드
    ↓
DuckDB 영구 저장 (데이터셋)
    ↓
경량 통계 자동 생성 (조사 진입점)
    ↓
인터랙티브 조사 모드
    ↓
Query Planning → DuckDB 동적 쿼리
    ↓
UCE 의미 압축
    ↓
LLM 추론
```

### 핵심 철학

**xDR 전체를 LLM에 넣지 않는다.**
- xDR은 수백만 레코드의 반복 데이터 → 토큰 예산 초과
- DuckDB에 저장하고, 필요한 데이터만 동적으로 추출
- LLM은 필터링/압축된 서브셋만 받음

**데이터셋은 영구 보존한다.**
- 원본 `.dat` 파일은 DuckDB 저장 완료 후 삭제
- DuckDB 파싱 결과는 삭제하지 않음 (명시적 삭제 요청 시에만)
- 멀티 데이터셋 공존 (시간대 비교, 이력 분석 가능)

**기존 1회성 RCA 흐름은 유지한다.**
- `POST /api/rca/jobs` 하위 호환 유지
- 기존 RCA Engine (analyzer.py, causal.py 등) 그대로 활용

---

## 2. 데이터 흐름

```
.dat 파일 업로드
    ↓
parser.py — \x1e 구분자로 필드 분리 → list[dict]
    ↓
duckdb_store.py — DuckDB 테이블 저장 (dataset_id 기반)
    ↓
원본 .dat 파일 삭제 (DuckDB 저장 성공 확인 후에만)
    ↓
aggregate_records() → 경량 통계 생성 → DuckDB summary 테이블 저장
    ↓
RcaDataset 상태: READY
    ↓
[사용자 조사 시작]
    ↓
Query Planning Layer (사용자 자연어 → SQL 변환)
    ↓
DuckDB 동적 쿼리 실행 (IMSI 조회, 인터페이스 필터, 시간대 분석 등)
    ↓
UCE 의미 압축 (반복 레코드 제거, 인과관계 보존)
    ↓
LLM 추론 및 설명
```

---

## 3. DuckDB 설계

### 선택 이유

- Python 내장 (`pip install duckdb`) — 외부 서버 불필요
- Docker 컨테이너에서 완전 동작
- `list[dict]` → DuckDB 테이블 직접 변환 가능
- SQL 기반 동적 쿼리 지원
- 파일 기반 영구 저장

### 파일 위치

```
/app/rca_datasets/
    rca_datasets.duckdb      ← 메인 DuckDB 파일 (Docker volume 마운트)
```

### 테이블 구조

```sql
-- 데이터셋 메타 테이블
CREATE TABLE IF NOT EXISTS rca_dataset_meta (
    dataset_id      VARCHAR PRIMARY KEY,
    job_id          INTEGER,
    conversation_id INTEGER,
    filename        VARCHAR,
    file_size       BIGINT,
    record_count    INTEGER,
    parsed_records  INTEGER,
    period_start    BIGINT,        -- epoch microseconds
    period_end      BIGINT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status          VARCHAR DEFAULT 'READY'
);

-- xDR 레코드 테이블
-- 테이블명: xdr_{dataset_id} (특수문자 _ 치환)
-- 컬럼: LTE-Call-KPI spec 154 필드 전체 (VARCHAR, timeval은 BIGINT)

-- 집계 통계 테이블
CREATE TABLE IF NOT EXISTS rca_summary (
    dataset_id      VARCHAR PRIMARY KEY,
    summary_json    JSON,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### dataset_id 생성 규칙

```python
# 파일명: LTE-CALL-KPI_R1_20260518_1100.dat
# dataset_id: LTE_CALL_KPI_R1_20260518_1100
# 테이블명: xdr_LTE_CALL_KPI_R1_20260518_1100

import re
def make_dataset_id(filename: str) -> str:
    base = Path(filename).stem      # 확장자 제거
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", base)
    return safe
```

### 동적 쿼리 예시

```sql
-- IMSI 추적
SELECT * FROM xdr_{dataset_id}
WHERE IMSI = '450050123456789'
ORDER BY call_start_time;

-- 인터페이스별 실패 집계
SELECT first_error_interface_protocol, COUNT(*) as cnt
FROM xdr_{dataset_id}
WHERE attempt_flag = '1' AND success_flag = '0'
GROUP BY first_error_interface_protocol
ORDER BY cnt DESC;

-- 시간대별 실패율 (15분 버킷)
SELECT
    (call_start_time / (15 * 60 * 1000000)) * (15 * 60 * 1000000) as bucket,
    COUNT(*) as total,
    SUM(CASE WHEN success_flag='0' AND attempt_flag='1' THEN 1 ELSE 0 END) as fail
FROM xdr_{dataset_id}
GROUP BY bucket
ORDER BY bucket;

-- MME별 실패 집계
SELECT MME_ID, COUNT(*) as fail_count
FROM xdr_{dataset_id}
WHERE attempt_flag='1' AND success_flag='0'
  AND first_error_interface_protocol IN ('2', '5')
GROUP BY MME_ID
ORDER BY fail_count DESC
LIMIT 10;
```

---

## 4. MySQL DB 스키마 변경

### 신규 테이블: rca_datasets

```sql
CREATE TABLE rca_datasets (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    dataset_id      VARCHAR(255) NOT NULL UNIQUE,
    job_id          INT,
    conversation_id INT,
    filename        VARCHAR(255),
    file_size       BIGINT DEFAULT 0,
    record_count    INT DEFAULT 0,
    parsed_records  INT DEFAULT 0,
    period_start    BIGINT NULL,
    period_end      BIGINT NULL,
    status          VARCHAR(20) DEFAULT 'PROCESSING',
    error_message   LONGTEXT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);
```

### models.py 추가

```python
class RcaDataset(Base):
    __tablename__ = "rca_datasets"

    id              : Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dataset_id      : Mapped[str] = mapped_column(String(255), unique=True)
    job_id          : Mapped[Optional[int]] = mapped_column(nullable=True)
    conversation_id : Mapped[Optional[int]] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    filename        : Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size       : Mapped[int] = mapped_column(default=0)
    record_count    : Mapped[int] = mapped_column(default=0)
    parsed_records  : Mapped[int] = mapped_column(default=0)
    period_start    : Mapped[Optional[int]] = mapped_column(nullable=True)
    period_end      : Mapped[Optional[int]] = mapped_column(nullable=True)
    status          : Mapped[str] = mapped_column(String(20), default="PROCESSING")
    error_message   : Mapped[Optional[str]] = mapped_column(LONG_TEXT, nullable=True)
    created_at      : Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

---

## 5. 신규 모듈 구조

```
backend/app/rca/
    duckdb_store.py      ← DuckDB 저장/조회 담당
    query_planner.py     ← 사용자 쿼리 → DuckDB SQL 변환
    dataset_manager.py   ← 데이터셋 생명주기 관리
```

### duckdb_store.py

```python
# 핵심 함수 (모두 동기 함수 — DuckDB는 async 미지원)
def get_connection() -> duckdb.DuckDBPyConnection
def create_xdr_table(dataset_id: str, fields: tuple[FieldSpec, ...]) -> None
def insert_records(dataset_id: str, records: list[dict]) -> int
def query(dataset_id: str, sql: str, limit: int = 1000) -> list[dict]
def store_summary(dataset_id: str, summary: dict) -> None
def get_summary(dataset_id: str) -> dict | None
def delete_dataset(dataset_id: str) -> None
def list_datasets() -> list[dict]
```

주의:
- DuckDB 연결은 이 모듈에서만 생성
- FastAPI async 환경에서는 `asyncio.to_thread()` 로 wrapping

### query_planner.py

```python
@dataclass
class QueryPlan:
    intent: str          # "imsi_lookup", "interface_filter", "cause_analysis" 등
    sql: str             # 실행할 DuckDB SQL
    description: str     # 사용자에게 보여줄 쿼리 설명

async def plan_query(
    user_message: str,
    dataset_id: str,
    model: str,
) -> QueryPlan:
    # 초기: LLM 기반 플래너
    # 향후: 룰 기반으로 전환 가능한 구조 유지
```

룰 기반 전환 예시 (향후):
```python
INTENT_RULES = [
    (r"IMSI\s+(\d{15})",       "imsi_lookup"),
    (r"attach\s*(flow|실패)",   "attach_flow"),
    (r"S6a",                   "s6a_analysis"),
    (r"MME.*(장애|실패)",       "mme_failure"),
    (r"시간대|타임라인",         "timeline_analysis"),
]
```

### dataset_manager.py

```python
async def create_dataset(
    job_id: int,
    conversation_id: int,
    filename: str,
    records: list[dict],
    fields: tuple[FieldSpec, ...],
) -> str:   # dataset_id 반환

async def get_dataset_info(dataset_id: str) -> dict
async def list_datasets(conversation_id: int | None = None) -> list[dict]
async def delete_dataset(dataset_id: str) -> None
```

---

## 6. API 엔드포인트

### 기존 유지 (하위 호환)

```
POST   /api/rca/jobs                      파일 업로드 + 분석 (1회성 리포트)
GET    /api/rca/jobs                      Job 목록
GET    /api/rca/jobs/{job_id}             Job 상태
GET    /api/rca/jobs/{job_id}/stream      SSE 스트리밍
GET    /api/rca/results/{job_id}          RCA 결과 JSON
```

### 신규 추가

```
# 데이터셋 관리
GET    /api/rca/datasets                          데이터셋 목록
GET    /api/rca/datasets/{dataset_id}             데이터셋 상태/메타
DELETE /api/rca/datasets/{dataset_id}             데이터셋 삭제 (DuckDB + MySQL)

# 조사
POST   /api/rca/datasets/{dataset_id}/query       자연어 쿼리 (SSE 스트리밍)
GET    /api/rca/datasets/{dataset_id}/summary     경량 통계 조회
```

### POST /api/rca/datasets/{dataset_id}/query 요청

```json
{
    "message": "IMSI 450050123456789 의 실패 이력을 보여줘",
    "conversation_id": 42,
    "use_uce": true
}
```

SSE 스트리밍 응답:
```
data: {"step": "planning", "progress": 10}
data: {"step": "query_plan", "intent": "imsi_lookup", "description": "IMSI 조회 실행"}
data: {"step": "executing", "progress": 30}
data: {"step": "result_ready", "row_count": 15}
data: {"step": "llm", "progress": 60}
data: {"step": "llm_token", "token": "해당 IMSI는..."}
data: {"step": "done", "progress": 100, "message_id": 123}
```

---

## 7. Frontend 변경

### 조사 모드 표시

데이터셋이 있는 대화에서 상단 또는 사이드바에:
```
🔍 RCA 조사 모드 | 현재 데이터셋: LTE-CALL-KPI_R1_20260518_1100
```

### 데이터셋 패널 (신규)

- 데이터셋 목록 (파일명, 레코드 수, 기간, 실패율)
- 조사 시작 버튼
- 삭제 버튼

### 채팅 UI

기존 채팅 UI 그대로. 데이터셋 컨텍스트 자동 주입.

---

## 8. UCE 역할

인터랙티브 조사에서 UCE가 해야 할 것:
- DuckDB 쿼리 결과의 반복 레코드 제거
- 텔레콤 프로토콜 시퀀스 무결성 보존
- 인과관계 체인 우선 보존
- 중요 RCA 신호 우선순위화

UCE가 하지 말아야 할 것:
- 일반 요약 (텔레콤 도메인 세부사항 손실 위험)
- 공격적 추상화

---

## 9. 구현 단계

### Phase 1: DuckDB 기반 마련

- [ ] `duckdb` backend requirements.txt 추가
- [ ] `rca/duckdb_store.py` 구현
- [ ] `rca/dataset_manager.py` 구현
- [ ] `models.py`에 `RcaDataset` 추가
- [ ] DB 마이그레이션: `rca_datasets` 테이블
- [ ] `docker-compose.yml`에 `rca_datasets` volume 추가

### Phase 2: 업로드 → DuckDB 저장 연동

- [ ] `routes/rca.py` 업로드 시 DuckDB 저장 추가
- [ ] 원본 파일 삭제 로직 유지
- [ ] `/api/rca/datasets` GET 엔드포인트
- [ ] Frontend 데이터셋 목록 표시

### Phase 3: 인터랙티브 조사

- [ ] `rca/query_planner.py` (LLM 기반 초기 버전)
- [ ] `/api/rca/datasets/{dataset_id}/query` SSE 엔드포인트
- [ ] Frontend 조사 모드 UI

### Phase 4: UCE 연동 + 최적화

- [ ] 쿼리 결과 → UCE 압축 연동
- [ ] 룰 기반 쿼리 플래너 부분 전환

---

## 10. 필수 코딩 규칙 (MUST FOLLOW)

1. **LLM 호출은 `llm.py`만** — `duckdb_store.py`, `query_planner.py`, `dataset_manager.py`는 LLM 호출 없음
2. **모델명 하드코딩 금지** — `settings.default_ollama_model` 사용
3. **DuckDB 연결은 `duckdb_store.py`에서만** — 다른 모듈 직접 연결 금지
4. **dataset_id 형식** — 파일명 기반, 특수문자 `_`로 치환
5. **원본 파일 삭제** — DuckDB 저장 성공 확인 후에만 삭제
6. **기존 RCA 흐름 유지** — `POST /api/rca/jobs` 하위 호환 필수
7. **asyncio.to_thread()** — DuckDB 동기 함수를 async 환경에서 호출 시 반드시 사용
