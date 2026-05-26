# QIE Dataset Registry

---

## 개요

업로드된 xDR 파일을 DuckDB에 저장하고
메타데이터를 MySQL에 관리한다.

---

## MySQL 테이블

### rca_datasets

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INT | PK |
| dataset_id | VARCHAR(255) | 파일명 기반 unique ID |
| job_id | INT | 연결된 RCA job |
| conversation_id | INT | 최초 업로드 대화 |
| filename | VARCHAR(255) | 원본 파일명 |
| file_size | BIGINT | 파일 크기 |
| record_count | INT | 전체 레코드 수 |
| parsed_records | INT | 실제 파싱된 레코드 수 |
| period_start | BIGINT | 시작 시간 (microsecond epoch) |
| period_end | BIGINT | 종료 시간 (microsecond epoch) |
| status | VARCHAR(20) | PROCESSING / READY / ERROR |
| created_at | DATETIME | 생성 시간 |

### conversation_datasets

대화와 데이터셋의 N:M 관계.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INT | PK |
| conversation_id | INT | 대화 ID |
| dataset_id | VARCHAR(255) | 데이터셋 ID |
| is_primary | TINYINT | 주 데이터셋 여부 |
| attached_at | DATETIME | 연결 시간 |

---

## DuckDB 테이블

파일: `/app/rca_datasets/rca_datasets.duckdb`

### rca_dataset_meta

데이터셋 메타 정보.

### xdr_{dataset_id}

실제 xDR 레코드. dataset_id별 별도 테이블.
컬럼: LTE-Call-KPI spec 154 필드 (VARCHAR, timeval은 BIGINT)

### rca_summary

집계 통계 (JSON).

---

## dataset_id 생성 규칙

파일명 기반, 특수문자 → `_` 치환:

```
LTE-CALL-KPI_R1_20260518_1100.dat
→ LTE_CALL_KPI_R1_20260518_1100
```

---

## 파일 삭제 정책

- DuckDB 저장 성공 확인 후에만 원본 파일 삭제
- DuckDB 저장 실패 시 원본 보존
