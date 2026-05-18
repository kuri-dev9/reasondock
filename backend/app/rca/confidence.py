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
                "statement": f"{item['semantic']} 패턴 관찰",
                "evidence": f"semantic enrichment 기준 {item['count']}건 관찰",
                "confidence": 0.95,
            }
        )

    for item in procedure_analysis.get("likely_failed_phases", [])[:3]:
        confirmed.append(
            {
                "statement": f"{item['call_type']} 절차의 {item['phase']} 단계 실패 패턴 관찰",
                "evidence": f"procedure phase mapping 기준 {item['count']}건 관찰",
                "confidence": 0.82,
            }
        )

    primary = causal_chain.get("primary_event")
    if primary:
        strong_suspicions.append(
            {
                "statement": f"{primary['event']} 계열이 주요 원인 후보로 우선 의심됨",
                "evidence": "procedure phase 및 timestamp ordering 기반 우선 의심",
                "confidence": primary["confidence"],
            }
        )

    for item in causal_chain.get("secondary_effects", [])[:3]:
        strong_suspicions.append(
            {
                "statement": f"{item['event']} 계열은 2차 영향 가능성 존재",
                "evidence": f"causal step {item['caused_by']} 이후 {item['relation']} 관계로 관찰",
                "confidence": item["confidence"],
            }
        )

    if semantic_summary.get("unknown_cause_count"):
        weak_hypotheses.append(
            {
                "statement": "일부 cause code는 의미 매핑 확인 필요",
                "evidence": f"unknown cause event {semantic_summary['unknown_cause_count']}건 존재",
                "confidence": 0.35,
            }
        )

    return {
        "confirmed": confirmed,
        "strong_suspicions": strong_suspicions,
        "weak_hypotheses": weak_hypotheses,
    }
