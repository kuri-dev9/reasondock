# RCA Engine 아키텍처

작성 기준: 2026-05-24

---

## 개요

RCA(Root Cause Analysis) Engine은
QIE가 수집한 데이터를 기반으로 인과 추론을 수행하는 전문 분석 엔진이다.

---

## RCA vs QIE 역할 분리

| 역할 | 담당 |
|------|------|
| 데이터 수집/저장 | QIE |
| SQL 실행/집계 | QIE |
| 사실 확인 ("S6a 실패 17건") | QIE |
| 인과 추론 ("HSS 동기화 지연이 원인") | RCA |
| 결론/권고 생성 | RCA + LLM |

---

## RCA 파이프라인

```
QIE Investigation 결과 (query rows)
    ↓
RCA Engine
    ├ cause_dictionary.py — 원인 코드 해석
    ├ causal.py — 인과 체인 구성
    ├ evidence_graph.py — 증거 관계 분석
    ├ confidence.py — 신뢰도 계산
    └ structured_result.py — 구조화된 결과 생성
    ↓
UCE Context Compression
    ↓
LLM Final Reasoning
```

---

## RCA 활성화 조건

모든 xDR 조사가 RCA를 거치지 않는다.

**RCA가 필요한 경우:**

- "왜" 질문 (원인 분석)
- "RCA 분석해줘" 명시
- 실패율이 임계값 초과 시 자동 트리거 (향후)

**RCA가 불필요한 경우:**

- 단순 통계 조회 ("실패 건수 보여줘")
- 집계 요청 ("IMSI별 집계")
- 목록 조회

---

## 1회성 RCA 리포트 (기존 유지)

현재 `/api/rca/jobs` 엔드포인트를 통한 1회성 리포트 생성 흐름은 유지한다.
이는 파일 업로드 시 전체 데이터셋에 대한 자동 분석 리포트 생성이다.

---

## 향후 방향

QIE + RCA 통합 파이프라인:

- 인터랙티브 조사 중 필요 시 RCA 자동 호출
- 특정 패턴 감지 시 RCA 자동 트리거
- RCA 결과를 UCE context로 전달
