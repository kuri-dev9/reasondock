# QIE Debugging Guide

---

## Debug 패널 항목

채팅 debug 패널에서 QIE 관련 항목:

| 항목 | 설명 |
|------|------|
| xDR 데이터셋 | 활성 dataset_id |
| xDR Pipeline | ACTIVATED / SKIPPED |
| xDR Planner 신뢰도 | relevance score % |
| xDR 쿼리 의도 | failure_analysis 등 |
| xDR 쿼리 설명 | 한국어 설명 |
| xDR SQL | 생성된 SQL |
| xDR 결과 건수 | 쿼리 결과 행 수 |
| Grounding Policy | general / xdr_analysis / document_grounded |

---

## RCA 조사 파이프라인 패널

1. 데이터셋 선택
2. 쿼리 플래너 결과 (intent, 설명)
3. 생성된 SQL
4. 쿼리 실행 메타데이터 (실행 시간, 결과 건수)
5. 원시 쿼리 결과 (테이블)
6. UCE 압축 현황
7. 최종 컨텍스트

---

## 주요 문제 진단

### xDR Pipeline이 SKIPPED되는 경우

1. relevance score가 threshold 미만
   → taxonomy에 alias 추가 (데이터셋 → xDR 스키마 탭)
2. not_xdr 패턴에 매칭
   → 질문을 더 구체적으로 (IMSI, 장애, 실패 등 키워드 포함)

### SQL 실행 오류

1. table not found
   → dataset_id 확인, `xdr_` prefix 자동 추가 여부 확인
2. type mismatch (numeric vs string)
   → executor의 타입 정규화 로직 확인

### LLM timeout

1. `DPE_TIMEOUT_SECONDS` 설정 확인 (`.env`)
2. 모델 크기에 따라 값 조정 (gemma4:26b → 1200초 권장)

---

## 로그 확인

**backend:**

```bash
docker logs chat_demo_backend 2>&1 | grep -E "(xDR|QIE|dataset)" | tail -20
```

**DPE:**

```bash
docker logs dpe 2>&1 | grep -E "(normalization|실패)" | tail -10
```

**UCE:**

```bash
docker logs uce 2>&1 | tail -20
```
