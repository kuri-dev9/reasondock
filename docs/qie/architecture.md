# QIE (Query Investigation Engine) 아키텍처

작성 기준: 2026-05-24
상태: 설계 확정 / 구현 진행 예정

---

## 개요

QIE는 업로드된 파일을 조사 가능한 dataset으로 변환하고
자연어 기반으로 investigation을 수행하는 엔진이다.

현재 backend 내부 `app/qie/` 레이어로 구현되며
향후 독립 컨테이너로 분리 예정이다.

---

## QIE가 담당하는 것

- dataset ingestion (파일 → DuckDB 저장)
- dataset registry (메타데이터 관리)
- schema registry (xDR 필드 스키마)
- taxonomy management (alias/keyword 관리)
- NL → SQL planning
- SQL execution (DuckDB)
- 결과 집계 및 렌더링 메타데이터 생성
- routing (일반 대화 / dataset 조사 / 문서 QA 판단)

## QIE가 담당하지 않는 것

- LLM 추론 (→ RCA / LLM 직접 호출)
- context 압축 (→ UCE)
- document preprocessing (→ DPE)
- RCA 인과 분석 (→ RCA Engine)

---

## 전체 파이프라인

```
사용자 프롬프트
    ↓
QIE Routing
    ├ 일반 대화 ──────────────────→ UCE → LLM
    ├ 문서 QA ────────────────────→ UCE → LLM
    └ dataset 조사
          ↓
      QIE SQL Planning (NL → SQL)
          ↓
      QIE SQL Execution (DuckDB)
          ↓
      RCA Analysis (인과 추론, 선택적)
          ↓
      UCE Context Compression (ON/OFF)
          ↓
      LLM Final Response
```

---

## 디렉토리 구조 (목표)

```
backend/app/qie/
    __init__.py
    datasets/
        __init__.py
        duckdb_store.py      # DuckDB 저장/조회 (현 rca/duckdb_store.py 이동)
        dataset_manager.py   # 데이터셋 생명주기 (현 rca/dataset_manager.py 이동)
        ingestion.py         # 파일 → DuckDB 파이프라인
    planner/
        __init__.py
        query_planner.py     # NL → SQL (현 rca/query_planner.py 이동)
        relevance.py         # xDR relevance detection (현 rca/xdr_relevance.py 이동)
        activation.py        # routing/activation gating
    execution/
        __init__.py
        executor.py          # SQL 실행 + 결과 정규화
        renderer.py          # 결과 → LLM 입력 포맷 변환
    schema/
        __init__.py
        spec_loader.py       # xDR spec 로딩 (현 rca/spec_loader.py 이동)
        schema_registry.py   # XdrFieldSchema 관리
    taxonomy/
        __init__.py
        taxonomy_manager.py  # XdrFieldKeyword 관리
    pipeline/
        __init__.py
        investigation.py     # 전체 investigation 파이프라인 오케스트레이터
    models/
        __init__.py
        dataset.py           # RcaDataset, ConversationDataset ORM 참조
```

---

## 현재 구현 상태

| 모듈 | 현재 위치 | 목표 위치 | 상태 |
|------|----------|----------|------|
| DuckDB 저장/조회 | `rca/duckdb_store.py` | `qie/datasets/duckdb_store.py` | 이동 예정 |
| 데이터셋 관리 | `rca/dataset_manager.py` | `qie/datasets/dataset_manager.py` | 이동 예정 |
| NL→SQL planner | `rca/query_planner.py` | `qie/planner/query_planner.py` | 이동 예정 |
| xDR relevance | `rca/xdr_relevance.py` | `qie/planner/relevance.py` | 이동 예정 |
| spec loader | `rca/spec_loader.py` | `qie/schema/spec_loader.py` | 이동 예정 |
| schema API | `routes/xdr_schema.py` | `qie/schema/ + route` | 이동 예정 |
| dataset API | `routes/rca.py` 일부 | `qie/ + route` | 분리 예정 |

---

## 설계 원칙

- **LLM 최소화** — SQL 실행, 집계, 통계는 backend에서 직접 처리
- **Query First** — NL → SQL → 결과 먼저. LLM 분석은 필요 시에만
- **Structured Investigation 우선** — 데이터 기반 사실 확인이 핵심
- **RCA는 specialization** — QIE 위에서 동작하는 인과 추론 레이어
- **향후 컨테이너 분리 대비** — HTTP API 형태로 내부 호출 구조 유지
