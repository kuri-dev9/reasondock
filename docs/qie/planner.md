# QIE Query Planner

---

## 개요

자연어 질문을 DuckDB SQL로 변환하는 2단계 파이프라인.

---

## Stage 1: Rule-based Activation (LLM 없음)

`qie/planner/relevance.py`

schema의 field_name, group, alias를 기반으로
query가 xDR 조사 관련인지 빠르게 판단.

**scoring:**

- field_name 매칭: +1.0
- alias 매칭: +0.8
- group 매칭: +0.6
- generic token 단독: ×0.3 penalty

**threshold:** 1.5 이상이면 xDR 관련

**not_xdr 패턴:**

- 인사 (안녕, hello)
- 감탄 (고마워, ㅋㅋ)
- 일반 잡담 (날씨, 뉴스)

---

## Stage 2: LLM SQL Generation

`qie/planner/query_planner.py`

Stage 1에서 `is_xdr_related=True`일 때만 실행.

**입력:**

- 사용자 자연어 질문
- schema hint (주요 필드 정보)
- taxonomy hint (DB에서 로드한 alias 매핑)
- dataset_id

**출력: QueryPlan**

```python
@dataclass
class QueryPlan:
    is_xdr_related: bool
    confidence: float
    intent: str      # failure_analysis|imsi_lookup|cause_analysis|not_xdr 등
    description: str # 한국어 설명
    sql: str         # 생성된 DuckDB SQL
```

---

## SQL 생성 규칙

- SQL은 반드시 한 줄 (줄바꿈 금지)
- `LIMIT` 반드시 포함, 최대 500
- `attempt_flag='1' AND success_flag='0'` → 실패 레코드
- `call_start_time` / `call_end_time`은 BIGINT (microsecond epoch)
- 테이블명은 planner가 `dataset_id`만 사용, executor가 `xdr_` prefix 추가

---

## taxonomy hint 구조

DB의 `XdrFieldSchema` + `XdrFieldKeyword`에서 로드:

```
"가입자", "단말", "UE"        → IMSI
"인터페이스", "프로토콜"       → first_error_interface_protocol
"원인", "장애원인"             → first_error_cause
```
