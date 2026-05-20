from __future__ import annotations

from typing import Any


EVIDENCE_STRENGTH_SCORES = {
    "explicit_protocol_reject": 1.0,
    "timeout_only": 0.55,
    "cleanup_signal": 0.25,
    "kpi_only": 0.35,
}

TIER_THRESHOLDS = {
    "confirmed": 0.85,
    "suspected": 0.60,
    "weak_hypothesis": 0.0,
}


def is_healthy(summary: dict[str, Any]) -> bool:
    overall = summary.get("overall", {})
    return (
        summary.get("analysis_mode") == "healthy"
        and overall.get("fail_rate", 1.0) == 0.0
        and overall.get("drop_rate", 1.0) == 0.0
        and summary.get("status") == "NORMAL"
        and not summary.get("time_anomaly", {}).get("detected", False)
    )


def should_invoke_llm(summary: dict[str, Any]) -> tuple[bool, str]:
    """LLM 호출 여부 결정.

    정책:
    - healthy (fail_rate=0%, drop_rate=0%, 이상 없음) → bypass
    - 그 외 모든 실패/이상 케이스 → LLM 호출
    """
    if is_healthy(summary):
        return False, "analysis_mode=healthy, fail_rate=0.0"

    primary = summary.get("primary_cause") or {}
    tier = primary.get("confidence_tier", "unknown")
    score = float(summary.get("confidence_score") or 0.0)
    fail_rate = summary.get("overall", {}).get("fail_rate", 0.0)

    return True, f"tier={tier}, score={score:.2f}, fail_rate={fail_rate:.2%}, invoke_reason=non_healthy"
