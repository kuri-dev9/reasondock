# QIE Schema & Taxonomy

---

## 개요

xDR 필드 스키마와 alias(taxonomy)를 관리한다.
query planner가 자연어 → SQL 변환 시 참고한다.

---

## MySQL 테이블

### xdr_field_schema

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INT | PK |
| field_name | VARCHAR(100) | 실제 DuckDB 컬럼명 (unique) |
| description | VARCHAR(255) | 필드 설명 (편집 가능) |
| is_active | TINYINT | planner hint 사용 여부 |
| is_custom | TINYINT | 0=spec 기반(읽기전용), 1=사용자 추가 |

### xdr_field_keywords

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | INT | PK |
| field_id | INT | xdr_field_schema.id FK |
| keyword | VARCHAR(100) | alias 키워드 |

---

## 편집 규칙

- `is_custom=0` 필드: field_name 변경/삭제 불가
- `is_custom=1` 필드: 모두 편집 가능
- keyword: 모든 필드에서 추가/삭제 가능

---

## 기본 taxonomy 예시

| field_name | aliases |
|------------|---------|
| IMSI | 단말, 단말별, UE, 가입자 |
| first_error_interface_protocol | 인터페이스, 프로토콜, interface |
| first_error_cause | 원인, 장애원인, cause |
| MME_ID | MME, MME별 |
| eNB_ID | eNB, 기지국 |

---

## Relevance Scoring

schema/alias 기반 xDR 관련성 판단:

- field_name 매칭: +1.0
- alias 매칭: +0.8
- generic token penalty 적용
- threshold 1.5 이상 → xDR 조사 활성화
