---
marp: true
theme: default
paginate: true
---

# ReasonDock 플랫폼 개요

로컬 LLM 챗봇에서  
구조화된 조사 플랫폼으로

---

# ReasonDock은 무엇이 되고 있는가

- 채팅 UX는 그대로 유지
- 구조화 데이터 조사를 1급 기능으로 확장
- 사실 확인은 SQL과 DuckDB가 담당
- LLM은 판단의 출처가 아니라 계획과 설명을 담당

```mermaid
flowchart LR
  Chatbot[LLM 챗봇] --> RAG[채팅 + RAG]
  RAG --> Investigation[구조화 조사 플랫폼]
```

---

# 아키텍처 철학

작업 성격에 맞는 엔진을 사용한다.

- 사실 확인: 결정적 로직
- 구조화 데이터: SQL + DuckDB
- 컨텍스트: UCE
- 문서 구조화: DPE
- 원인 분석: RCA
- 설명과 표현: LLM

---

# 현재 플랫폼 구조

```mermaid
graph TD
  UI[React 프론트엔드] --> Backend[FastAPI 백엔드]
  Backend --> MySQL[(MySQL)]
  Backend --> RAG[Knowledge RAG]
  RAG --> Index[(BM25 + TF-IDF 인덱스)]
  Backend --> QIE[QIE]
  QIE --> DuckDB[(DuckDB xDR)]
  Backend --> UCE[UCE]
  Backend --> DPE[DPE]
  Backend --> RCA[RCA Engine]
  Backend --> LLM[services/llm.py]
  LLM --> Providers[Ollama / OpenAI / Anthropic]
```

---

# 엔진별 책임

| 엔진 | 책임 |
|---|---|
| Backend | 라우팅, 저장, 오케스트레이션 |
| QIE | 데이터셋 조사, SQL, DuckDB |
| UCE | 컨텍스트 압축, 프롬프트 구성 |
| DPE | 문서 구조 분석, Markdown IR |
| RCA | 구조화 증거 기반 원인 분석 |
| LLM | 계획 보조와 자연어 설명 |

---

# 백엔드가 전체 흐름을 조율한다

```mermaid
flowchart TD
  Request[사용자 요청] --> Backend[Backend Router]
  Backend --> Route{요청 유형}
  Route --> Chat[채팅]
  Route --> Knowledge[지식 문서]
  Route --> Dataset[xDR 데이터셋]
  Route --> Schema[xDR 스키마]
  Chat --> QIE{활성 데이터셋?}
  QIE -->|있음| Investigation[QIE 조사]
  QIE -->|없음| RAG[문서 RAG]
  Investigation --> Context[컨텍스트 구성]
  RAG --> Context
  Context --> UCE{UCE 사용?}
  UCE -->|예| PromptPack[UCE Prompt Pack]
  UCE -->|아니오| LegacyPrompt[Legacy Prompt]
  PromptPack --> LLM[LLM]
  LegacyPrompt --> LLM
```

---

# QIE가 필요한 이유

구조화 데이터는 모델이 추측하면 안 된다.

- 자연어 → SQL
- DuckDB 실행
- 제한된 결과 row
- 백엔드 markdown 렌더링
- 필요한 경우에만 reasoning 수행

---

# QIE 조사 흐름

```mermaid
flowchart TD
  Query[자연어 질문] --> Activate[관련성 판단]
  Activate --> Fields[후보 필드 선택]
  Fields --> Planner[작은 Planner 또는 Rule]
  Planner --> SQL[Schema-aware SQL]
  SQL --> DuckDB[(DuckDB)]
  DuckDB --> Rows[조회 결과]
  Rows --> Render{단순 결과?}
  Render -->|예| Markdown[백엔드 표 렌더링]
  Render -->|아니오| UCE[UCE + LLM 설명]
```

---

# UCE가 필요한 이유

LLM에는 더 많은 컨텍스트가 아니라  
더 정리된 컨텍스트가 필요하다.

- 대화 상태 추적
- 생략된 후속 질문 보강
- 관련 컨텍스트 선별
- 토큰 압축
- 구조화된 prompt pack 생성

---

# UCE 컨텍스트 파이프라인

```mermaid
flowchart TD
  Input[현재 메시지 + 상태] --> Intent[Intent 분석]
  Intent --> Rewrite[Query Rewrite]
  Rewrite --> Retrieve[Context Retrieval]
  Retrieve --> Rank[Ranking]
  Rank --> Compress[Compression]
  Compress --> Policy[Grounding Policy]
  Policy --> Prompt[Prompt Pack]
```

---

# DPE가 필요한 이유

문서 검색 품질은 업로드 시점의 구조에 달려 있다.

- 문서 구조 감지
- 낮은 신뢰도 텍스트를 Markdown IR로 정규화
- 엔티티와 섹션 보존
- UCE의 heading-aware retrieval 품질 개선

---

# DPE 문서 처리 흐름

```mermaid
flowchart TD
  Text[추출된 텍스트] --> Detect[구조 감지]
  Detect --> NeedNorm{정규화 필요?}
  NeedNorm -->|아니오| Metadata[메타데이터 + 전략]
  NeedNorm -->|예| Denoise[선택적 UCE Denoise]
  Denoise --> Normalize[Backend /api/normalize]
  Normalize --> IR[Markdown IR]
  Metadata --> Store[Backend 저장]
  IR --> Store
```

---

# RCA의 역할 변화

RCA는 더 이상 기반 계층이 아니다.

QIE가 기반이다.  
RCA는 원인 분석 전문 계층이다.

```mermaid
flowchart TD
  QIE[QIE Facts] --> Need{원인 분석 필요?}
  Need -->|아니오| Result[SQL 결과]
  Need -->|예| RCA[RCA Engine]
  RCA --> Evidence[증거 + 신뢰도]
  Evidence --> Explain[선택적 LLM 설명]
```

---

# LLM 오케스트레이션 전략

작업 난이도와 비용에 맞게 모델을 나눈다.

```mermaid
flowchart TD
  Rule[Rule Engine] --> Planner[Small Planner Model]
  Planner --> SQL[SQL Plan]
  SQL --> DuckDB[(DuckDB 실행)]
  DuckDB --> Simple{단순 통계?}
  Simple -->|예| Direct[LLM 없이 응답]
  Simple -->|아니오| Large[선택적 Large Reasoning Model]
```

---

# 현재 / 리팩토링 / 미래

| 계층 | 현재 | 리팩토링 | 미래 |
|---|---|---|---|
| QIE | 백엔드 모듈 | 라우트 정리 | 1급 조사 엔진 |
| DPE | 서비스 + 수동 IR | 업로드 정책 결정 | 품질 피드백 |
| UCE | 선택형 미들웨어 | rewrite 책임 정리 | 더 강한 상태 추적 |
| RCA | 1회성 + 전문 분석 | QIE와 정렬 | 원인 분석 계층 |
| LLM | 공통 서비스 | 모델 역할 분리 | 대형 모델 최소화 |

---

# 목표 아키텍처

```mermaid
graph TD
  UI[조사 UI] --> Orchestrator[Backend Orchestrator]
  Orchestrator --> QIE[QIE]
  Orchestrator --> DPE[DPE]
  Orchestrator --> UCE[UCE]
  QIE --> DuckDB[(DuckDB)]
  QIE --> Direct[Direct Renderer]
  QIE --> RCA{RCA 필요?}
  RCA -->|예| RCAEngine[RCA Engine]
  RCAEngine --> Facts[구조화 증거]
  Direct --> Response[응답]
  Facts --> UCE
  UCE --> LLM[LLM 설명 계층]
  LLM --> Response
```

---

# 전략적 방향

- 구조화 조사는 싸고 결정적으로
- 대형 LLM에는 원본 데이터를 넣지 않기
- reasoning 전에 SQL로 사실 확인
- RCA는 count가 아니라 cause를 담당
- UCE는 모든 prompt를 의도적으로 만들기
- DPE는 문서를 검색 가능한 형태로 만들기

