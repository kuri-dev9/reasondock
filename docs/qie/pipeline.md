# QIE Investigation Pipeline

---

## 1. Dataset Ingestion Pipeline

```
.dat 파일 업로드 (데이터셋 패널)
    ↓
QIE Ingestion
    ├ parser.py — \x1e 구분자 파싱 → list[dict]
    ├ duckdb_store.py — xdr_{dataset_id} 테이블 생성 + 레코드 삽입
    ├ dataset_manager.py — 메타데이터 저장 (MySQL rca_datasets)
    └ 원본 파일 삭제 (DuckDB 저장 성공 후에만)
```

---

## 2. Investigation Pipeline

```
사용자 자연어 질문
    ↓
QIE Activation Gating
    ├ dataset 연결 여부 확인
    ├ relevance.py — schema/alias 기반 xDR 관련성 scoring
    └ is_xdr_related 판단
         ↓ True
    QIE Planner (query_planner.py)
         ├ taxonomy hints 로드 (DB)
         ├ LLM → SQL 생성
         └ QueryPlan 반환
              ↓
    QIE Executor
         ├ DuckDB SQL 실행
         ├ 결과 정규화 (타입 변환 등)
         └ rows 반환
              ↓
    QIE Renderer
         ├ rows → LLM 입력 포맷 변환
         └ xdr_context 문자열 생성
              ↓ (선택적)
    RCA Analysis
         ├ 인과 추론 필요 여부 판단
         ├ cause_dictionary, causal chain 분석
         └ RCA 결과 생성
              ↓
    UCE Context Compression (ON/OFF)
         ├ xdr_context + document context + conversation
         ├ GroundingPolicy = XDR_ANALYSIS
         └ compressed prompt 생성
              ↓
    LLM Response
```

---

## 3. Routing 판단 기준

| 조건 | Routing 결과 | Grounding Policy |
|------|-------------|-----------------|
| dataset 없음 | 일반 대화 | GENERAL |
| dataset 있음 + `is_xdr_related=false` | 일반 대화 | GENERAL |
| dataset 있음 + `is_xdr_related=true` | dataset 조사 | XDR_ANALYSIS |
| document context 있음 | 문서 QA | DOCUMENT_GROUNDED |

---

## 4. 주요 버그 및 수정 내역

### table name mismatch

- **문제**: planner가 `LTE_CALL_KPI_...` 생성, 실제는 `xdr_LTE_CALL_KPI_...`
- **수정**: executor에서 `xdr_` prefix 자동 추가

### numeric/text mismatch

- **문제**: planner가 `success_flag = 0`, 실제는 `'0'` (VARCHAR)
- **수정**: schema 기반 타입 인식 후 quote 처리

### timeout

- **문제**: gemma4:26b 같은 큰 모델에서 120초 초과
- **수정**: `settings.dpe_timeout_seconds` 사용
