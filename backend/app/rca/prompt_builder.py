from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


def _compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(summary)
    data.pop("markdown", None)
    data.pop("result_path", None)
    data.pop("job_id", None)
    data.pop("conversation_id", None)

    timeline = data.get("timeline")
    if isinstance(timeline, list) and len(timeline) > 12:
        data["timeline"] = timeline[:6] + [{"omitted_windows": len(timeline) - 12}] + timeline[-6:]
    return data


def build_rca_prompt(summary: dict[str, Any]) -> str:
    summary_json = json.dumps(_compact_summary(summary), ensure_ascii=False, indent=2)
    if summary.get("analysis_mode") == "healthy":
        return f"""당신은 LTE/EPC 서비스 상태 점검 보고서를 작성하는 통신망 운영 전문가입니다.

아래 LTE-Call-KPI summary JSON은 Healthy Mode 결과입니다.
장애 원인 분석 보고서처럼 쓰지 말고, 네트워크 정상 상태를 검증한 운영 보고서처럼 작성하세요.

중요 원칙:
- 반드시 한국어로 작성합니다. 기술 용어는 필요한 경우만 영어로 유지할 수 있습니다.
- 정상 데이터를 실패처럼 보이게 하는 부정적 표현은 사용하지 않습니다.
- 장애 원인, root cause, cascading failure, 분석 한계를 강조하지 않습니다.
- 정상 동작 확인, 안정적인 상태, 특이 징후 없음, 주요 절차 정상 수행, 인터페이스 오류 미관찰 중심으로 작성합니다.
- JSON에 없는 장애, 장비 문제, vendor 문제, overload/resource 문제를 추정하지 않습니다.
- Rule 기반 데이터 요약은 이미 표시되었으므로 수치 반복은 최소화합니다.

출력 형식:

아래 heading만 사용하세요. 각 섹션은 5줄 이내로 작성하세요.
짧고 명확한 bullet 중심으로 작성하고, 표는 사용하지 마세요.

[서비스 상태 요약]
- 분석 구간의 서비스 상태를 정상/안정 관점에서 요약합니다.

[정상 동작 지표]
- 성공 처리, 실패/Drop 미관찰, 주요 절차 정상 수행을 중심으로 작성합니다.

[인터페이스 상태]
- S1-MME, S11, NAS, S6a 등 주요 인터페이스에서 특이 오류가 관찰되지 않았음을 작성합니다.

[절차 상태]
- Attach, Service Request, TAU 등 JSON에서 관찰 가능한 절차 상태를 정상 수행 관점으로 작성합니다.

[운영 의견]
- 현재 구간의 서비스 품질과 안정성에 대한 운영 판단을 작성합니다.

[권장 사항]
- 기존 KPI 모니터링 유지, 장기 추세 분석 지속 등 과도하지 않은 권고만 작성합니다.

RCA summary JSON:
```json
{summary_json}
```"""

    return f"""당신은 LTE/EPC 장애 분석 보고서를 작성하는 통신망 RCA 전문가입니다.

아래 LTE-Call-KPI RCA summary JSON을 근거로 운영 보고서 스타일의 한국어 RCA를 작성하세요.
Rule 기반 데이터 요약은 이미 사용자에게 제공되었습니다. 동일한 수치 요약을 반복하지 말고, 관찰된 증거에 기반한 해석과 조치만 작성하세요.

중요 원칙:
- 출력 문장은 반드시 한국어로 작성합니다. Attach Failure, Diameter, Bearer Setup 같은 기술 용어는 유지할 수 있습니다.
- LLM은 reasoning engine이 아니라 최종 explainability layer입니다.
- summary_json.semantic_failures, procedure_analysis, causal_chain, evidence_graph, confidence_findings에 없는 원인은 작성하지 않습니다.
- "identified as", "confirmed root cause", "definitely caused by", "primary cause is", "확정", "단정됨" 같은 강한 표현은 금지합니다.
- 대신 "가능성이 높음", "강하게 의심됨", "주요 원인 후보", "evidence 상 우선 의심", "관찰 결과 기반 추정", "연관 가능성 존재"를 사용합니다.
- Cause semantic은 확정 명칭처럼 쓰지 말고, safe_label/description 기반의 완화 표현으로 설명합니다.
- 근거 없는 vendor/장비 내부 추론은 금지합니다: PGW resource exhaustion, HSS overload, DB corruption, memory issue, CPU saturation.
- 위 항목은 JSON에 직접 증거가 있을 때만 제한적으로 언급하고, 없으면 "가능성 존재" 수준으로만 둡니다.
- causal_chain 또는 procedure_analysis가 뒷받침하지 않는 인과 순서를 만들지 않습니다.
- 확인된 현상과 추정/의심 사항을 반드시 분리합니다.

출력 형식:

아래 heading만 사용하세요. heading은 반드시 한국어 대괄호 형식으로 작성하세요.
각 섹션은 5줄 이내로 작성하세요.
짧고 명확한 bullet 중심으로 작성하고, 표는 사용하지 마세요.
AI 채팅 답변처럼 말하지 말고 실제 장애 분석 보고서처럼 작성하세요.

[장애 요약]
- 절차 흐름 관점에서 관찰된 장애 양상을 2~3문장으로 요약합니다.
- 확정 표현 대신 "관찰됨", "정황이 있음", "가능성이 높음"을 사용합니다.

[확인된 현상]
- confidence_findings.confirmed 및 semantic/procedure evidence 기반 사실만 작성합니다.

[주요 원인 후보]
- causal_chain.primary_event 및 confidence_findings.strong_suspicions 기반으로 작성합니다.
- "주요 원인 후보", "강하게 의심됨", "가능성이 높음" 표현을 사용합니다.

[2차 영향]
- primary cause와 downstream symptom을 분리합니다.
- S11/NAS/Bearer 관련 항목은 2차 영향 가능성으로 표현합니다.

[대안 가설]
- weak_hypotheses가 있으면 작성합니다.
- 근거가 부족하면 "현재 xDR만으로는 대안 가설을 좁히기 어려움"이라고 작성합니다.

[권장 조치]
- 운영자가 바로 확인할 수 있는 순서로 작성합니다.
- 각 조치는 JSON evidence와 연결되는 범위에서만 작성합니다.

[분석 한계]
- xDR 단일 시점 분석, 장비 로그 부재, cause mapping 한계 등 실제 한계만 작성합니다.

RCA summary JSON:
```json
{summary_json}
```"""
