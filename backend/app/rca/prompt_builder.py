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
Your job is to summarize evidence-constrained causal RCA.

The raw xDR records are not provided. Do not invent fields, causes, vendors, node names, packet details, or timeline values that are not present in the JSON.

Strict grounding rules:
- Treat summary_json.semantic_failures, procedure_analysis, causal_chain, evidence_graph, and confidence_findings as the only reasoning substrate.
- LLM is an explainability layer, not the reasoning engine.
- Clearly separate confirmed facts, likely root cause, secondary effects, and alternative hypotheses.
- Vendor speculation is forbidden unless vendor evidence exists in the JSON.
- Unsupported overload/resource exhaustion claims are forbidden.
- If cause mapping is unknown, preserve raw cause labels and mark the limit.
- Mention numeric values and equipment IDs only when essential; copy them exactly from JSON.
- Do not create causal ordering not supported by causal_chain or procedure_analysis.

Return the answer in Korean.

Required output format:

Use exactly the following headings. Do not add other top-level headings.
Each section must be no more than 5 lines.
Use short bullets. Do not include tables. Do not write a data recap.

## Confirmed Findings
- Only facts from confidence_findings.confirmed and semantic/procedure evidence.

## Likely Root Cause
- Use causal_chain.primary_event and confidence_findings.strong_suspicions.
- State confidence carefully.

## Secondary Effects
- Separate downstream symptoms from primary cause.

## Alternative Hypotheses
- Use weak_hypotheses or explicitly say evidence is insufficient.

## Recommended Actions
- Recommend checks in priority order, tied to evidence.

## Limitations
- State what cannot be confirmed from this xDR-only evidence.

RCA summary JSON:
```json
{summary_json}
```"""
