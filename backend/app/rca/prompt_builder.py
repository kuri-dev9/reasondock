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
The rule-based RCA summary has already been shown to the user. Do not repeat the numeric summary, equipment list, top failures, counts, or ratios.
Your job is only:
1. Interpret the likely failure mechanism behind the observed pattern.
2. Judge the priority of next actions.

The raw xDR records are not provided. Do not invent fields, causes, vendors, node names, packet details, or timeline values that are not present in the JSON.

Strict grounding rules:
- Do not repeat numeric values or equipment IDs unless they are essential for prioritization.
- If you mention a numeric ID, message code, cause code, count, or ratio, copy it exactly from the JSON.
- Do not change equipment IDs.
- Do not mention timeline peak values unless they exist in summary_json.time_anomaly.windows or summary_json.timeline.
- Do not infer causal order between S1AP, S6a, and S11 failures unless timestamp/order evidence is present.
- Most xDR fields are numeric codes. If a mapping is not provided, keep raw labels such as MESSAGE_9 or CAUSE_64.
- Prefer the rule-based rca_candidates as the starting point.
- Separate confirmed evidence from inferred interpretation.
- Use cautious Korean phrasing such as "가능성", "추정", and "확인 필요" for interpretations not directly proven by the JSON.
- Do not write unsupported numbers, equipment names, vendors, causes, or recovery actions.

Return the answer in Korean.
Write no more than 20 lines total.

Required output format:

Use exactly the following headings. Do not add other top-level headings.
Use short bullets. Do not include tables.

## 장애 메커니즘 해석
- Only explain mechanisms supported by top_failures, affected_equipment, timeline, or rca_candidates.
- Do not mention interfaces that are not present in top_failures.
- Focus on why this pattern is plausible, not on restating the pattern.

## 조치 우선순위
- Prioritize where to check first and why.
- Avoid generic checklists. Keep it actionable and ordered.

## 한계
- State only limitations that materially affect this RCA.

RCA summary JSON:
```json
{summary_json}
```"""
