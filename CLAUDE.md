# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ollama 로컬 LLM 기반 웹 채팅 애플리케이션. FastAPI 백엔드 + React 프론트엔드로 구성되며, BM25+TF-IDF 하이브리드 RAG, SSE 스트리밍, 멀티 세션 대화, 파일 첨부, 지식 저장소, DPE(Document Processing Engine), UCE(Unified Context Engine)를 지원한다.

---

## 필수 코딩 규칙 (MUST FOLLOW)

### 1. LLM 호출 규칙
**반드시 `app/services/llm.py`의 `chat()` 또는 `stream_chat()`을 통해 호출한다.**
- `httpx`나 `requests`로 Ollama API를 직접 호출하지 말 것
- `routes/normalize.py`는 DPE가 호출하는 전용 엔드포인트이며 여기서만 httpx 직접 호출 허용 (간접 LLM 호출)
- 다른 모든 라우트/서비스는 `llm.py`를 통해서만 LLM 접근

### 2. 모델명 하드코딩 금지
**코드 어디에도 모델명(`gemma4:26b`, `exaone3.5:7.8b` 등)을 하드코딩하지 말 것.**
- 항상 `settings.default_ollama_model` 사용
- `config.py`의 `default_ollama_model` 기본값은 `.env`에서 override

### 3. UCE ON/OFF 분리
- **UCE OFF**: `vector_store` 청크 기반 RAG (legacy). 기존 로직 절대 수정 금지
- **UCE ON**: `KnowledgeDocument.normalized_content` (DPE IR) 문서 단위 전달
- UCE ON 로직은 `chat.py`의 `if data.use_uce and settings.uce_enabled:` 블록 안에만 존재

### 4. DPE 아키텍처
- DPE는 문서 정규화 엔진 (Semantic IR 생성)
- DPE normalization 적용 문서: `content_type=dpe_ir`, `normalized_content` 컬럼에 저장
- 청크는 UCE OFF용으로만 사용 (`vector_store`). DPE IR은 `normalized_content`에 별도 저장
- DPE 엔드포인트: `http://dpe:8200/process`
- DPE가 LLM normalization 요청 시만 `backend /api/normalize` 호출

### 5. 서비스 구조
```
Frontend (3000) → Backend (8000) → Ollama (11434)
                              → UCE (8100)
                              → DPE (8200) → Backend /api/normalize → Ollama
```

### 6. RCA 아키텍처
**현재 상태:** 1회성 파싱 + LLM 리포트 (기존 흐름 유지)
**목표:** DuckDB 기반 인터랙티브 조사 워크스페이스

**핵심 규칙:**
- `rca/duckdb_store.py`에서만 DuckDB 연결 생성 — 다른 모듈 직접 연결 금지
- DuckDB 동기 함수를 async 환경에서 호출 시 반드시 `asyncio.to_thread()` 사용
- 원본 `.dat` 파일은 DuckDB 저장 성공 확인 후에만 삭제
- `POST /api/rca/jobs` 기존 1회성 리포트 흐름 하위 호환 필수 유지
- dataset_id: 파일명 기반, 특수문자 `_`로 치환 (예: `LTE_CALL_KPI_R1_20260518_1100`)
- xDR 전체를 LLM에 넣지 않음 — DuckDB에서 필터링된 서브셋만 전달

**신규 모듈 (Phase 1~3 구현 예정):**
- `rca/duckdb_store.py` — DuckDB 저장/조회
- `rca/query_planner.py` — 자연어 → DuckDB SQL 변환 (초기 LLM 기반)
- `rca/dataset_manager.py` — 데이터셋 생명주기 관리

**상세 설계:** `docs/RCA_INVESTIGATION_WORKSPACE.md` 참조

### 7. .env 파일 동기화 규칙
**`.env.linux` 또는 `.env.mac` 수정 시 반드시 두 파일 모두 동시에 수정한다.**
- `OLLAMA_BASE_URL`, `DEFAULT_OLLAMA_MODEL`은 서버별로 다른 값 유지
- 나머지 설정은 두 파일을 항상 동일하게 유지
- 새 환경변수 추가 시 두 파일 모두에 추가

---


## Common Commands

### Backend

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm start          # dev server on port 3000
npm run build      # production build
npx tsc --noEmit   # type check without emitting
```

### Startup Scripts

```bash
./scripts/start-backend.sh    # activates venv + starts uvicorn
./scripts/start-frontend.sh   # PORT=3000 npm start
```

### Database (MySQL 8.4 via Docker)

```bash
docker exec mysql84 mysql -uroot -p<password> -e "CREATE DATABASE IF NOT EXISTS chat_demo CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

테이블은 앱 시작 시 SQLAlchemy `metadata.create_all()`로 자동 생성된다. 컬럼 추가 시 `ALTER TABLE`을 직접 실행해야 한다 (Alembic 미사용).

### Backend Import Check

```bash
cd backend && python -c "from app.models import *; from app.schemas import *; print('OK')"
```

## Architecture

### Backend (FastAPI, Python 3.10+)

- `app/main.py` — 앱 생성, CORS (`localhost:3000`), 라우터 등록, lifespan에서 DB 테이블 생성
- `app/config.py` — `pydantic-settings`로 `.env` 파일에서 `DATABASE_URL`, `OLLAMA_BASE_URL` 로드
- `app/database.py` — SQLAlchemy async 엔진, `get_db()` 의존성
- `app/models.py` — ORM: `Conversation`(system_prompt 포함), `Message`(references JSON), `Attachment`, `KnowledgeDocument`(summary 포함)
- `app/schemas.py` — Pydantic v2 요청/응답 스키마, 검색/내보내기/가져오기 타입 포함

**Routes:**
- `routes/chat.py` — 핵심 채팅 로직. SSE 스트리밍, 2단계 RAG(요약 매칭 → 청크 검색), 첨부파일 컨텍스트, 시스템 프롬프트 조합, 자동 제목 생성
- `routes/conversations.py` — CRUD + 전문 검색(`/search?q=`), JSON/Markdown 내보내기, JSON 가져오기
- `routes/knowledge.py` — 지식 문서 업로드 시 `BackgroundTasks`로 비동기 처리 (텍스트 추출 → LLM 요약 생성 → 청킹 → 인덱싱)
- `routes/attachments.py` — 대화별 파일 업로드/삭제

**RAG Pipeline (2단계):**
1. **문서 요약 매칭** (`chat.py:_compute_summary_similarity`): 질문과 각 문서의 LLM 생성 요약 간 TF-IDF 코사인 유사도 계산. 임계값 0.01 이상이면 우선 문서로 선정
2. **청크 검색** (`vector_store.py`): BM25Okapi + TF-IDF 코사인 유사도 하이브리드 (가중치 0.5/0.5). 우선 문서의 청크를 상위 배치하고 해당 문서 요약도 컨텍스트에 포함. pickle로 `knowledge_data/index.pkl`에 영속화

**파일 처리:**
- `file_parser.py` — PDF, DOCX, HWP/HWPX(한글), Excel, 코드 등 텍스트 추출
- `chunker.py` — 단락 인식 분할, 500자 청크, 50자 오버랩

### Frontend (React 19, TypeScript)

- `App.tsx` — 전체 상태 관리 허브. conversations, messages, streaming, systemPrompt 등 모든 상태를 useState로 관리
- `api.ts` — REST 호출 + `streamChat()` SSE 클라이언트. `AbortController`로 스트리밍 취소 지원. API_BASE는 `http://localhost:8000/api`로 하드코딩
- `types.ts` — `Conversation`, `Message`, `SearchResult`, `KnowledgeDoc` 등 인터페이스

**Components:**
- `Sidebar.tsx` — 대화 목록 + 디바운스 검색 (300ms) + 내보내기 드롭다운(JSON/Markdown) + 가져오기 버튼
- `ChatMessage.tsx` — react-markdown + remark-gfm + react-syntax-highlighter(Prism) 렌더링, RAG 참조 칩 표시
- `ChatInput.tsx` — 동적 높이 textarea, 파일 첨부 칩, 전송/중지 버튼
- `SystemPromptEditor.tsx` — 모달, 7개 프리셋 템플릿 (번역가, 코드 리뷰어, 영어 선생님, 이동통신 전문가 등) + 직접 편집. 시스템 프롬프트는 대화별로 DB에 영속 저장
- `KnowledgePanel.tsx` — 지식 문서 업로드/삭제 모달, 3초 간격 상태 폴링, 문서 요약 펼침/접기 표시

### Data Flow: Chat Request

1. 프론트엔드 `streamChat()` → `POST /api/conversations/{id}/chat` (SSE)
2. 백엔드에서 대화 로드 (messages + attachments)
3. **1단계 RAG — 요약 매칭**: `KnowledgeDocument.summary`가 있는 문서들의 요약과 질문 간 TF-IDF 코사인 유사도 비교 → 우선 문서 선정
4. **2단계 RAG — 청크 검색**: `vector_store.search()` → 우선 문서 청크를 상위 배치, 요약 컨텍스트도 포함 (최대 7개 청크)
5. 시스템 프롬프트 조합: `[사용자 시스템 프롬프트] + [RAG 컨텍스트(요약+청크)] + [첨부파일 컨텍스트]`
6. Ollama `/api/chat` 스트리밍 호출, 토큰/thinking 이벤트를 SSE로 전달
7. 완료 시 assistant 메시지 DB 저장 (참조 문서에 `matched_summary` 플래그 포함), 첫 메시지면 자동 제목 생성

### Styling

CSS 변수 기반 다크/라이트 테마. `document.documentElement`에 `data-theme` 속성으로 전환. 모든 스타일은 `App.css` 단일 파일에 관리.

## Key Conventions

- 백엔드 전체가 async/await (SQLAlchemy async, httpx async)
- DB 마이그레이션 도구 없음 — 컬럼 추가 시 `ALTER TABLE` SQL 직접 실행 필요
- 프론트엔드 상태는 App.tsx에 집중 (Redux/Zustand 미사용)
- 한국어 UI/UX — 에러 메시지, 프리셋 템플릿, 자동 제목 생성 모두 한국어
- 한글 파일명 내보내기 시 `urllib.parse.quote`로 URL 인코딩 필요 (latin-1 헤더 제약)
- Ollama API: 모델 목록 `/api/tags`, 채팅 `/api/chat`, 단일 생성 `/api/generate`
- 요약 유사도 계산 시 BM25는 문서 1개일 때 음수를 반환할 수 있으므로 TF-IDF 코사인 유사도 단독 사용 (`_compute_summary_similarity`)
- 지식 문서 요약은 `llm.py`의 `chat()`을 통해 `settings.default_ollama_model`로 생성 (텍스트 앞 4000자 기반, 3~5문장)

## Ports

| Service  | Port  |
|----------|---------|
| Frontend | 3000    |
| Backend  | 8000    |
| MySQL    | 3306    |
| Ollama   | 11434   |
| UCE      | 8100    |
| DPE      | 8200    |
