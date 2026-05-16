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
The rule-based data summary has already been shown to the user before your response.
Do not repeat that data summary.
Your job is to write only interpretation and operational judgment.

The raw xDR records are not provided. Do not invent fields, causes, vendors, node names, packet details, or timeline values that are not present in the JSON.

Strict grounding rules:
- Mention numeric values and equipment IDs only when essential to the interpretation or priority decision.
- If you mention a numeric ID, message code, cause code, count, ratio, or candidate name, copy it exactly from the JSON.
- Do not write numbers, equipment names, vendors, or root causes that are not in the JSON.
- Do not mention timeline peak values unless they exist in summary_json.time_anomaly.windows or summary_json.timeline.
- Most xDR fields are numeric codes. If a mapping is not provided, keep raw labels such as MESSAGE_9 or CAUSE_64.
- You may explain possible meanings of message/cause codes from telecom experience, but clearly mark them as experience-based assumptions when no mapping table exists.
- You may infer which interface is more likely to be upstream, but separate observed evidence from inference.
- Use cautious Korean phrasing such as "가능성", "추정", and "확인 필요" unless the JSON directly proves it.

Return the answer in Korean.

Required output format:

Use exactly the following headings. Do not add other top-level headings.
Each section must be no more than 5 lines.
Use short bullets. Do not include tables. Do not write a data recap.

## 장애 메커니즘
- Interpret causal relationships across the observed failure patterns.
- State which interface is more likely to be the preceding cause, if the JSON supports it.
- Explain possible meanings of cause/message codes. If no mapping exists, mark it as experience-based.

## 원인 분류
- Classify the case as closest to one of: hardware fault, configuration error, traffic surge, transport network, or insufficient evidence.
- Explain why this category is more plausible than the others.

## 조치 우선순위
- State what should be checked first, second, and third with the reason.
- Avoid generic checklists; make the priority specific to this data.

## 한계
- State only what cannot be confirmed from this data alone.

RCA summary JSON:
```json
{summary_json}
```"""
