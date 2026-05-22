# DPE Roadmap
> Version: 0.1
> Last Updated: 2026-05-21

---

## Current Position

DPE는 설계 확정 상태이며 구현 대기 중이다.

UCE(Universal Context Engine)와 짝꿍 구조로 함께 진화한다.

```text
DPE: upload-time intelligence   → 문서 구조 분석 + normalization
UCE: query-time intelligence    → retrieval + compression + prompt assembly
```

---

## Phase 1 — Core Structure Detection

**목표**: DPE가 파일 업로드 시점에 structure detection을 수행하고, backend에 structured metadata를 반환하는 독립 서비스로 동작하는지 검증한다.

normalization은 Phase 1에 포함하지 않는다. Phase 1은 구조 감지와 서비스 통합만 검증한다.

| 항목 | 설명 | 상태 |
|------|------|------|
| FastAPI 앱 (`/process`, `/health`, `/status`) | DPE 서비스 기본 구조 | 🔲 미구현 |
| `structure_detector.py` | 확장자 힌트 + content sniffing + confidence 계산 | 🔲 미구현 |
| `processor.py` | 오케스트레이터 (normalization 없이 구조 감지 + 전략 결정) | 🔲 미구현 |
| `Dockerfile` + `requirements.txt` | Docker 컨테이너 기반 실행 | 🔲 미구현 |
| backend `config.py` 변경 | DPE 설정 추가 | 🔲 미구현 |
| backend `dpe_client.py` | HTTP 클라이언트 + fallback | 🔲 미구현 |
| backend `knowledge.py` 변경 | process_document에 DPE 통합 | 🔲 미구현 |
| backend `attachments.py` 변경 | upload_attachment에 DPE 통합 | 🔲 미구현 |
| backend `models.py` 변경 | dpe_metadata 컬럼 추가 | 🔲 미구현 |
| `docker-compose.yml` 통합 | dpe 서비스 추가 | 🔲 미구현 |
| smoke test | /health, /status, /process 기본 동작 확인 | 🔲 미구현 |

Phase 1의 핵심 검증:

```text
DPE_ENABLED=true 상태에서 파일 업로드 시 DPE가 structure_type과
chunk_strategy를 반환하고, backend가 이를 dpe_metadata로 DB에 저장한다.
DPE_ENABLED=false이면 기존 동작과 완전히 동일하다.
```

---

## Phase 2 — LLM Normalization

**목표**: 비정형 문서(plain_text, mixed, log)에 대해 LLM normalization을 적용하고, UCE가 heading-aware retrieval을 사용할 수 있는 markdown IR을 생성한다.

Phase 1이 안정화된 이후 진행한다.

| 항목 | 설명 | 상태 |
|------|------|------|
| backend `routes/normalize.py` | DPE가 호출하는 LLM normalize 엔드포인트 | 🔲 미구현 |
| DPE `normalizer.py` | backend /api/normalize 호출 | 🔲 미구현 |
| DPE `adapters/backend_client.py` | httpx 기반 normalize 클라이언트 | 🔲 미구현 |
| processor.py normalization 분기 | confidence < 0.55 + normalization_enabled 시 처리 | 🔲 미구현 |
| normalization 결과 DB 저장 | normalized_content를 content_text로 저장 | 🔲 미구현 |
| normalization smoke test | plain_text 파일 업로드 후 heading 생성 확인 | 🔲 미구현 |

Phase 2의 핵심 검증:

```text
structure_confidence < 0.55인 txt 파일 업로드 시 DPE가 backend를 통해
LLM normalization을 요청하고, 결과로 heading이 있는 markdown IR이
content_text에 저장된다. UCE는 해당 문서에서 heading-aware retrieval이
정상 동작한다.
```

Phase 2 기대 효과:

| 케이스 | Phase 1 | Phase 2 |
|--------|---------|---------|
| `.md` 파일 | heading-aware 정상 | 동일 |
| `.txt`로 저장된 markdown | structure_type: markdown 감지 → heading-aware | 동일 |
| 비정형 log/report | plain_text → sliding-window | normalization → heading-aware |
| excel-derived text | plain_text → sliding-window | normalization → heading-aware |

---

## Phase 2 Known Limits

의도적으로 포함하지 않는 것:

- PDF/OCR (file_parser가 이미 처리, DPE scope 아님)
- HWP/HWPX normalization (구조 감지만 수행)
- normalization 품질 자동 평가
- normalization 재시도 / 품질 피드백 루프
- DPE가 직접 LLM 호출 (항상 backend 경유)

---

## Next Work

구현 우선순위:

1. Phase 1 전체 구현 및 smoke test
2. `DPE_ENABLED=true` 상태에서 지식 문서 업로드 E2E 확인
3. dpe_metadata가 DB에 정상 저장되는지 확인
4. Phase 2: backend `/api/normalize` 구현
5. Phase 2: DPE normalizer 연결 및 통합 테스트

---

## Long-Term Direction

DPE가 지켜야 할 원칙:

```text
DPE는 답변을 생성하지 않는다.
DPE는 LLM을 직접 호출하지 않는다.
DPE는 DB를 소유하지 않는다.
DPE의 역할은 단 하나: UCE가 항상 markdown처럼 보이는 문서를 받도록 보장한다.
```

DPE가 되지 않는 것:
- 문서 요약 생성기 (요약은 knowledge.py의 `generate_summary()` 담당)
- 벡터 DB / 검색 엔진
- LLM 프록시
- 파일 저장소

DPE와 UCE의 장기 협력:
- DPE가 생성한 `chunk_strategy`, `retrieval_hints` metadata를 UCE retrieval boosting에 활용
- DPE normalization 품질 피드백 루프 (Phase 3 이후 검토)
- chunk strategy 자동 최적화 (Phase 3 이후 검토)
