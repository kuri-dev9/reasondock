---
marp: true
theme: default
paginate: true
---

# Routing 개요

백엔드는 오케스트레이션 계층이다.

---

# Routing이 중요한 이유

같은 채팅창에서도 요청 의미는 다르다.

- 일반 질문
- 문서 QA
- xDR 조사
- SQL 직접 결과
- RCA reasoning

백엔드 routing이 이 모드를 명확히 구분한다.

---

# 현재 Routing Map

```mermaid
flowchart TD
  User[사용자 Action] --> Backend[Backend]
  Backend --> Type{유형}
  Type --> Chat[Chat]
  Type --> Knowledge[Knowledge Upload]
  Type --> Dataset[xDR Dataset]
  Type --> Schema[xDR Schema]
  Type --> RCA[RCA Job]
```

---

# Chat Routing

```mermaid
flowchart TD
  Chat[Chat Request] --> Dataset{활성 Dataset?}
  Dataset -->|예| QIE[QIE Investigation]
  Dataset -->|아니오| RAG[Knowledge RAG]
  QIE --> Related{xDR 관련?}
  Related -->|예| XDR[xDR Context]
  Related -->|아니오| RAG
  XDR --> Prompt[Prompt Assembly]
  RAG --> Prompt
  Prompt --> UCE{UCE On?}
  UCE -->|예| Pack[UCE Pack]
  UCE -->|아니오| Legacy[Legacy Prompt]
```

---

# Dataset Binding

현재 규칙:

- 명시적으로 선택한 dataset 우선
- 없으면 conversation primary dataset 사용
- global fallback 없음

이유:

- 다른 조사 데이터가 섞이는 것을 방지
- 대화 상태를 예측 가능하게 유지

---

# Routing 결과

| 결과 | 주요 경로 |
|---|---|
| 일반 채팅 | Backend → LLM |
| 문서 QA | RAG → UCE/LLM |
| xDR 조사 | QIE → DuckDB |
| 직접 결과 | QIE → renderer |
| RCA reasoning | QIE facts → RCA → LLM |

---

# 목표 Routing 구조

```mermaid
flowchart LR
  Backend --> General[general_chat]
  Backend --> Doc[document_grounded_chat]
  Backend --> XDR[xdr_investigation]
  Backend --> Direct[direct_render]
  Backend --> RCA[rca_reasoning]
```
