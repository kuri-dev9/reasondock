from __future__ import annotations

from typing import Any


def build_confidence_findings(
    semantic_summary: dict[str, Any],
    procedure_analysis: dict[str, Any],
    causal_chain: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    confirmed: list[dict[str, Any]] = []
    strong_suspicions: list[dict[str, Any]] = []
    weak_hypotheses: list[dict[str, Any]] = []

    for item in semantic_summary.get("top_semantics", [])[:5]:
        confirmed.append(
            {
                "statement": f"{item['semantic']} observed",
                "evidence": f"{item['count']} event(s) in semantic enrichment",
                "confidence": 0.95,
            }
        )

    for item in procedure_analysis.get("likely_failed_phases", [])[:3]:
        confirmed.append(
            {
                "statement": f"{item['call_type']} failed around {item['phase']} phase",
                "evidence": f"{item['count']} event(s) mapped to procedure phase",
                "confidence": 0.82,
            }
        )

    primary = causal_chain.get("primary_event")
    if primary:
        strong_suspicions.append(
            {
                "statement": f"Primary root cause is closest to {primary['event']}",
                "evidence": primary["evidence"],
                "confidence": primary["confidence"],
            }
        )

    for item in causal_chain.get("secondary_effects", [])[:3]:
        strong_suspicions.append(
            {
                "statement": f"{item['event']} is likely secondary",
                "evidence": f"{item['relation']} after causal step {item['caused_by']}",
                "confidence": item["confidence"],
            }
        )

    if semantic_summary.get("unknown_cause_count"):
        weak_hypotheses.append(
            {
                "statement": "Some cause codes require mapping confirmation",
                "evidence": f"{semantic_summary['unknown_cause_count']} unknown cause event(s)",
                "confidence": 0.35,
            }
        )

    return {
        "confirmed": confirmed,
        "strong_suspicions": strong_suspicions,
        "weak_hypotheses": weak_hypotheses,
    }
