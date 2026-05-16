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
    return f"""You are an LTE/EPC network RCA expert.

Analyze the provided LTE-Call-KPI RCA summary JSON.
The raw xDR records are not provided. Do not invent fields, causes, vendors, node names, packet details, or timeline values that are not present in the JSON.

Strict grounding rules:
- Copy all numeric IDs, message codes, cause codes, counts, and ratios exactly from the JSON.
- Do not change equipment IDs. If JSON says eNB 20011, never write 20111.
- Do not mention timeline peak values unless they exist in summary_json.time_anomaly.windows or summary_json.timeline.
- Do not infer causal order between S1AP, S6a, and S11 failures unless timestamp/order evidence is present.
- Most xDR fields are numeric codes. If a mapping is not provided, keep raw labels such as MESSAGE_9 or CAUSE_64.
- Prefer the rule-based rca_candidates as the starting point.
- Separate confirmed evidence from inferred interpretation.
- Use cautious Korean phrasing such as "가능성", "추정", and "확인 필요" for interpretations not directly proven by the JSON.
- Before final answer, verify that every equipment ID, cause code, and count matches the JSON.

Return the answer in Korean.

Output format:

## RCA 결론
- 가장 가능성 높은 Root Cause:
- 신뢰도:
- 한 줄 요약:

## 핵심 근거
- 실패율:
- 주요 실패 패턴:
- 영향 장비:
- 시간대 이상 여부:

## 장애 메커니즘 추정

## 확인 필요 항목

## 즉시 조치 권고

## 데이터 정합성 확인
- 인용한 장비 ID:
- 인용한 Message/Cause:
- 인용한 건수/비율:

## 한계

RCA summary JSON:
```json
{summary_json}
```"""
