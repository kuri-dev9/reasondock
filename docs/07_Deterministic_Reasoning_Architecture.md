# 7. Deterministic Reasoning Architecture

작성 기준: reasondock RCA 설계 철학 + proj_lte_rca 구조 분석  
최종 수정: 2026-05-20

---

## 7.1 이 문서의 목적

ReasonDock은 단순한 Chat/RAG 시스템이 아니다.

이 문서는 ReasonDock이 지향하는 핵심 설계 방향,  
즉 **Deterministic Reasoning + LLM Explainability** 구조를 정의한다.

> **핵심 명제**  
> "LLM이 원인을 판단하는 시스템이 아니라,  
> RCA Engine이 판단하고 LLM이 설명하는 시스템이다."

---

## 7.2 왜 이 구조를 선택했는가

### 전통적 LLM-중심 RCA의 문제

LLM이 직접 장애 원인을 추론하는 구조는 다음과 같은 한계를 가진다.

| 문제 | 설명 |
|------|------|
| Hallucination | LLM은 증거 없이도 그럴듯한 원인을 생성할 수 있다 |
| 비재현성 | 동일 입력에 대해 매번 다른 결론을 낼 수 있다 |
| 모델 의존성 | 모델 교체 시 RCA 결과가 달라질 수 있다 |
| 블랙박스 | 왜 그 결론에 도달했는지 추적이 불가능하다 |
| 운영 신뢰도 저하 | 운영자가 AI 판단을 검증할 수단이 없다 |

### ReasonDock의 접근

```
Raw Data
  → Semantic Analysis      (원시 필드를 의미 이벤트로 변환)
  → Procedure Analysis     (절차 흐름 컨텍스트 파악)
  → Causal Inference       (원인/결과/파급 효과 분리)
  → Confidence Separation  (확실성 수준 분류)
  → Evidence Organization  (증거 구조화)
  → Action Recommendation  (운영 가이드 생성)
  → LLM Explainability     (운영자 친화적 자연어 설명)
```

이 구조에서 LLM의 역할은 **마지막 단계**에만 한정된다.  
원인 판정, 심각도 판단, 증거 상관관계, 신뢰도 계산은 모두 RCA Engine이 수행한다.

### 선택의 이유

- **Hallucination 감소**: LLM은 구조화된 RCA 결과를 받아 설명만 한다. 원인을 창작하지 않는다.
- **재현성 확보**: 동일 입력에 대해 동일 RCA 결과가 보장된다. (deterministic pipeline)
- **모델 교체 안정성**: LLM을 교체해도 RCA 판단 로직은 변하지 않는다.
- **Explainability 강화**: 각 판단 근거가 structured evidence로 추적 가능하다.
- **운영 신뢰도 향상**: 운영자가 AI의 판단 근거를 검증할 수 있다.

---

## 7.3 역할 분리 원칙

### RCA Engine의 책임

RCA Engine은 다음 항목을 **단독으로** 결정한다.

- 장애 원인 판정 (primary cause, alternative causes)
- 심각도 판단 (severity scoring)
- 증거 상관관계 분석 (evidence correlation)
- 신뢰도 계산 (confidence scoring)
- 운영 액션 추천 (action recommendation)
- 파급 범위 추정 (blast radius)

### LLM의 책임

LLM은 다음 항목만 담당한다.

- RCA Engine의 판단 결과를 자연어로 설명
- 운영자 친화적 보고서 형식으로 변환
- 요약 및 강조 표현

LLM은 원인을 판단하지 않는다.  
LLM은 Engine의 판단을 **번역**한다.

### 구조적 경계

```
┌─────────────────────────────────────────────────┐
│              RCA Engine (Deterministic)          │
│                                                  │
│  Semantic Layer → Procedure Layer → Causal Layer │
│       ↓                                          │
│  Confidence Tiering → Evidence Graph             │
│       ↓                                          │
│  Action Recommendation (knowledge mapping)       │
└─────────────────────┬───────────────────────────┘
                      │ structured RCA result (JSON)
                      ▼
┌─────────────────────────────────────────────────┐
│              LLM (Explainability Layer)          │
│                                                  │
│  자연어 설명 생성                                  │
│  운영자 친화적 보고서                               │
│  요약 및 강조 표현                                  │
└─────────────────────────────────────────────────┘
```

---

## 7.4 Structured Reasoning Pipeline

현재 RCA 구조는 단순한 rule 기반 로그 분석기가 아니다.  
다음 5개 계층으로 구성된 **Structured Reasoning Pipeline**이다.

### 7.4.1 Semantic Layer

Raw 필드 값을 **의미 기반 이벤트**로 변환하는 계층.

원시 데이터는 숫자 코드나 프로토콜 약어로만 표현된다.  
이 계층은 이를 RCA 추론이 가능한 의미 단위로 변환한다.

```
원시값:  first_error_interface_protocol = 1
         first_error_cause = 19
         ↓ (Semantic Layer)
의미:    Diameter S6a 인터페이스에서 Authentication Reject 발생
```

변환 대상 예시:

| 원시 필드 | 원시 값 | 의미 이벤트 |
|-----------|---------|------------|
| `first_error_interface_protocol` | `1` | `S6a_Diameter` |
| `first_error_cause` | `19` | `Authentication Reject` |
| `call_type` | `1` | `Attach_MO` |
| `emm_error_Cause` | `8` | `EPS Services Not Allowed` |

이 변환 없이는 절차 분석과 인과 추론이 불가능하다.

### 7.4.2 Procedure Layer

개별 이벤트가 아니라 **절차 흐름(Context)**을 이해하는 계층.

LTE/EPC 장애는 단일 이벤트가 아니라 절차 흐름 위에서 발생한다.  
동일한 에러 코드도 어떤 절차(Attach / TAU / Service Request)에서 발생했느냐에 따라 의미가 다르다.

```
분석 대상 절차 흐름:
  Attach Flow        → UE 등록 시도 전체 흐름
  Service Request    → 데이터 세션 재개 시도
  TAU (Tracking Area Update) → 위치 등록 업데이트
  Paging Flow        → 네트워크 시작 호 수신
  Detach Flow        → 정상/비정상 분리 구분
  Session Flow       → PDN/Bearer 설정 흐름
```

예시:

```
call_type = 1 (Attach_MO)
first_error_interface = S6a
first_error_cause = Authentication Reject
→ Procedure Layer 판단: Attach 절차 중 HSS 인증 실패
→ 이전 절차(Service Request)와의 연속 실패 여부 확인
```

### 7.4.3 Causal Layer

원인 / 결과 / 파급 효과를 **분리**하는 계층.

장애 로그에는 실제 원인뿐 아니라 그 결과로 발생한 cleanup 신호들이 섞여 있다.  
이를 구분하지 않으면 결과 신호(예: UE Context Release)를 원인으로 잘못 판정하게 된다.

```
구분 대상:
  Root Cause     → 최초 장애를 발생시킨 이벤트
  Propagation    → Root Cause로 인해 연쇄된 이벤트
  Cleanup Signal → 장애 후 정리 과정에서 발생한 신호 (원인이 아님)
```

예시:

```
S6a Authentication Reject  → Root Cause (명시적 거부 신호)
S1AP UE Context Release    → Cleanup Signal (인증 실패 후 세션 정리)
NAS EMM Attach Reject      → Propagation (인증 거부에 따른 연쇄)
```

Causal Layer 없이는 cleanup 신호를 원인으로 잘못 판정하는 오류가 발생한다.

### 7.4.4 Confidence Layer

RCA 결론의 **확실성 수준**을 분류하는 계층.

하나의 장애에 대해 증거 강도에 따라 세 수준의 결론을 관리한다.

| 수준 | 설명 | 기준 |
|------|------|------|
| `confirmed` | 명시적 프로토콜 reject 등 강한 증거 | 직접적 에러 코드, 명확한 실패 신호 |
| `suspected` | 정황 증거, 패턴 기반 | 통계적 상관, 간접 신호 |
| `weak_hypothesis` | 가능성은 있으나 증거 부족 | 유사 증상, 배제하지 않은 가설 |

이 분류를 통해 운영자는 어느 결론을 먼저 확인해야 하는지 우선순위를 알 수 있다.

확실하지 않은 결론을 `confirmed`로 표현하는 것은 엄격히 금지된다.

### 7.4.5 Evidence Graph

이벤트 간 관계를 **그래프 형태**로 구조화하는 개념.

단순 목록 형태의 증거 나열이 아니라,  
이벤트 간의 인과관계, 시간 순서, 프로토콜 경계를 구조화한다.

```
(S6a Auth Reject) ──causes──▶ (Attach Reject)
(S6a Auth Reject) ──causes──▶ (UE Context Release)
(S6a Auth Reject) ──source──▶ evidence_strength: explicit_protocol_reject
(UE Context Release) ──role──▶ cleanup_signal
```

이 구조화를 통해:
- LLM이 원인과 결과를 혼동 없이 설명할 수 있다
- 운영자가 근거를 추적할 수 있다
- 향후 knowledge graph 기반 확장이 가능하다

---

## 7.5 Action Recommendation Layer

운영 가이드를 LLM이 즉흥적으로 생성하는 방식을 사용하지 않는다.

RCA Engine 내부의 **cause_dictionary + action_dictionary + knowledge mapping**을 통해  
원인 코드에 대한 운영 가이드를 deterministic하게 생성한다.

### 구조

```
원인 코드 (예: S6A_AUTH_FAILURE)
  ↓
cause_dictionary lookup
  ↓
action_dictionary mapping
  ↓
운영 가이드 생성 (구조화된 항목)
```

### 예시

```
원인:  S6A_AUTH_FAILURE (Diameter S6a 인증 실패)

운영 가이드:
  Priority: High
  1. HSS Diameter 인터페이스 연결 상태 확인
  2. AuthenticationInformation 요청/응답 latency 측정
  3. MME-HSS session 상태 확인 (active session 수)
  4. 동일 IMSI 구간 반복 실패 여부 확인
  5. HSS 가입자 프로파일 정합성 검증
```

이 가이드는 LLM이 생성한 것이 아니다.  
cause_dictionary에 정의된 지식이 action_dictionary를 통해 구조화된 형태로 매핑된 결과다.

### 핵심 원칙

"운영 대응 지식"을 **구조화 가능한 형태**로 관리한다.

특정 원인에 대한 운영 지식이 쌓일수록 action_dictionary가 풍부해지고,  
그 지식은 모델 교체와 무관하게 항상 재현 가능한 형태로 유지된다.

---

## 7.6 RCA 결과 구조 고도화 방향

### 현재 구조

```
통계 요약
  + RCA 후보 (Rule 기반)
  + LLM 설명
```

### 목표 구조

```json
{
  "status": "DEGRADED",
  "severity": "HIGH",
  "incident_classification": "AUTH_FAILURE_BURST",
  "primary_cause": {
    "domain": "Core",
    "cause": "s6a_authentication_failure",
    "confidence": 0.91,
    "evidence_strength": "explicit_protocol_reject"
  },
  "alternative_causes": [
    {
      "domain": "Core",
      "cause": "hss_overload",
      "confidence": 0.34
    }
  ],
  "evidence": [...],
  "counter_evidence": [...],
  "cleanup_signals": [...],
  "blast_radius": {
    "affected_cells": [...],
    "affected_mme": [...],
    "estimated_ue_count": 0
  },
  "confidence_score": 0.91,
  "root_cause_tree": {...},
  "recommended_actions": [
    {
      "priority": "High",
      "action": "HSS Diameter 인터페이스 상태 확인",
      "reason": "명시적 S6a 인증 거부 증거 존재"
    }
  ],
  "uncertainty": {
    "level": "Low",
    "missing_evidence": [...]
  }
}
```

### 추가될 주요 필드

| 필드 | 설명 |
|------|------|
| `incident_classification` | 장애 유형 분류 (AUTH_FAILURE / TIMEOUT / RADIO 등) |
| `severity` | HIGH / MEDIUM / LOW / INFO |
| `blast_radius` | 영향 범위 (eNB, MME, APN, 추정 UE 수) |
| `counter_evidence` | 주요 원인 가설을 반박하는 증거 |
| `confidence_score` | 전체 RCA 신뢰도 (0.0 ~ 1.0) |
| `root_cause_tree` | 원인-결과 계층 구조 |
| `cleanup_signals` | 원인이 아닌 정리 신호 목록 |
| `uncertainty` | 불확실성 수준 및 누락 증거 설명 |

---

## 7.7 현재 모듈과 Reasoning 계층의 매핑

현재 `rca/` 패키지의 각 모듈이 Reasoning 계층에서 담당하는 역할은 다음과 같다.

```
rca/parser.py
  담당: 원시 XDR 파일 파싱 (0x1E 구분자)
  계층: Semantic Layer의 전처리 단계

rca/analyzer.py
  담당: 집계 통계 + Rule 기반 RCA 후보 생성
  계층: Semantic Layer + Causal Layer (초기 구현)
  향후: Procedure Layer, Confidence Layer 확장

rca/prompt_builder.py
  담당: RCA 결과 → LLM 프롬프트 조립
  계층: LLM Explainability Layer의 입력 구성
  원칙: LLM을 직접 호출하지 않음

rca/pipeline.py
  담당: 전체 RCA 흐름 오케스트레이션
  원칙: xDR → summary JSON 반환까지만 담당
         LLM 호출 없음
```

---

## 7.8 proj_lte_rca와의 관계

`proj_lte_rca`는 ReasonDock RCA 엔진의 설계 원형(prototype)이다.

| 항목 | proj_lte_rca | ReasonDock RCA |
|------|-------------|----------------|
| 목적 | standalone RCA CLI 실험 | Chat 시스템과 통합된 운영 RCA |
| 추론 방식 | LLM이 structured prompt로 추론 | Deterministic Engine + LLM Explainability |
| 지식 관리 | taxonomy.json / cause_dictionary / procedure_dictionary | analyzer.py Rule + action_dictionary (발전 방향) |
| 출력 형식 | 엄격한 JSON schema (rca_output.schema.json) | summary JSON → LLM 설명 (고도화 진행 중) |
| 인프라 | llama.cpp standalone | FastAPI 백엔드 통합 |

proj_lte_rca에서 정의된 다음 개념들은 ReasonDock RCA에서도 핵심 설계 기반으로 유지된다.

- Evidence 구조 (source_field / protocol / interface / message / cause / semantic_role)
- Cleanup Signal과 Root Cause의 분리 원칙
- Confidence Tiering (confirmed / suspected / weak_hypothesis)
- Action Recommendation의 knowledge mapping 방식
- Ambiguity 보존 원칙 (불확실할 때 불확실하다고 표현)

---

## 7.9 Future Vision: 범용 Structured Reasoning Engine

ReasonDock의 RCA 구조는 LTE/xDR 전용 시스템이 아니다.

현재 설계의 핵심 구조인:

```
Raw Data
  → Semantic Extraction
  → Correlation
  → Reasoning
  → Explainable Context
  → LLM Explanation
```

이 파이프라인은 도메인에 독립적이다.

### 확장 가능한 영역

| 도메인 | 적용 예시 |
|--------|-----------|
| Security RCA | 침해 사고 원인 분석, 공격 경로 추적 |
| Infra Incident RCA | 서버/네트워크 장애 원인 분석 |
| Kubernetes Incident | Pod 장애, OOMKill, CrashLoopBackOff 원인 분석 |
| ERP Anomaly | 트랜잭션 이상, 데이터 정합성 오류 분석 |
| Market Event Analysis | 이상 거래 패턴, 가격 이벤트 원인 분석 |

### 공통 확장 구조

각 도메인은 다음 요소를 교체하는 방식으로 확장된다.

```
cause_dictionary      → 도메인별 오류 코드 사전
procedure_dictionary  → 도메인별 프로세스/플로우 정의
taxonomy.json         → 도메인별 원인 분류 체계
evidence_weights      → 도메인별 증거 우선순위
action_dictionary     → 도메인별 운영 가이드
```

Reasoning Pipeline 자체는 변경 없이 재사용된다.

### 전제 조건

이 확장이 가능하려면 현재 설계의 원칙이 유지되어야 한다.

- LLM에 원인 판단을 위임하지 않는다
- Evidence는 항상 source field까지 추적 가능해야 한다
- Confidence는 증거에 기반해서만 산출된다
- Action은 knowledge mapping으로 생성된다

---

## 7.10 설계 원칙 요약

| 원칙 | 내용 |
|------|------|
| Deterministic First | 추론 로직은 재현 가능한 코드로 구현한다 |
| LLM은 Explainer | LLM은 판단하지 않고 설명한다 |
| Evidence Traceability | 모든 결론은 source field까지 추적 가능하다 |
| Ambiguity Preservation | 불확실한 것은 불확실하다고 표현한다 |
| Cleanup vs Root Cause | Cleanup 신호를 원인으로 오판하지 않는다 |
| Knowledge is Structured | 운영 지식은 dictionary 형태로 구조화한다 |
| Model Agnostic | LLM 교체가 RCA 판단 결과에 영향을 주지 않는다 |

---

*관련 문서*  
- [RCA_DESIGN.md](RCA_DESIGN.md) — RCA 통합 시스템 설계 (AS-IS → TO-BE, 모듈 상세, DB/API 스펙)  
- [02_시스템_구성도.md](02_시스템_구성도.md) — 전체 시스템 아키텍처  
- [03_모듈별_상세기능.md](03_모듈별_상세기능.md) — 백엔드 rca/ 패키지 상세
