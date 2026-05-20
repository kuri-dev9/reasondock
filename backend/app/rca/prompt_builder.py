from __future__ import annotations

import json
from typing import Any


def _top_equipment(summary: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {
        key: value[:1]
        for key, value in summary.get("affected_equipment", {}).items()
        if isinstance(value, list)
    }


def build_llm_context(summary: dict[str, Any]) -> dict[str, Any]:
    primary = summary.get("primary_cause") or {}
    overall = summary.get("overall") or {}
    time_anomaly = summary.get("time_anomaly") or {}
    confidence_findings = summary.get("confidence_findings") or {}
    blast_radius = summary.get("blast_radius") or {}
    data_quality = summary.get("data_quality") or {}
    analysis_window = summary.get("analysis_window") or {}

    return {
        "status": summary.get("status"),
        "severity": summary.get("severity"),
        "classification": summary.get("incident_classification"),
        "window": {
            "start": analysis_window.get("start"),
            "end": analysis_window.get("end"),
        },
        "kpi": {
            "total": overall.get("total"),
            "attempt": overall.get("attempt"),
            "success": overall.get("success"),
            "fail": overall.get("fail"),
            "drop": overall.get("drop"),
            "fail_rate": overall.get("fail_rate"),
            "drop_rate": overall.get("drop_rate"),
        },
        "primary_cause": {
            "domain": primary.get("domain"),
            "cause": primary.get("cause"),
            "safe_label": primary.get("safe_label"),
            "confidence": primary.get("confidence"),
            "confidence_tier": primary.get("confidence_tier"),
        },
        "alternative_causes": summary.get("alternative_causes", [])[:2],
        "top_failures": summary.get("top_failures", [])[:3],
        "top_equipment": _top_equipment(summary),
        "confirmed": confidence_findings.get("confirmed", [])[:3],
        "strong_suspicions": confidence_findings.get("strong_suspicions", [])[:2],
        "weak_hypotheses": confidence_findings.get("weak_hypotheses", [])[:1],
        "recommended_actions": summary.get("recommended_actions", [])[:4],
        "time_anomaly": time_anomaly.get("detected", False),
        "anomaly_windows": time_anomaly.get("windows", [])[:3],
        "uncertainty": summary.get("uncertainty"),
        "ue_count": blast_radius.get("estimated_ue_count"),
        "data_quality": data_quality.get("quality_level"),
    }


def build_rca_prompt(summary: dict[str, Any]) -> list[dict[str, str]]:
    ctx_json = json.dumps(build_llm_context(summary), ensure_ascii=False, indent=2)
    system = (
        "당신은 LTE/EPC 통신망 RCA 전문가입니다.\n"
        "아래 구조화된 RCA 컨텍스트를 받아 한국어 운영 보고서만 생성합니다.\n"
        "규칙:\n"
        "- 반드시 한국어로 작성합니다. 기술 용어(Diameter, S6a, MME 등)는 영어 유지 가능.\n"
        "- RCA 컨텍스트에 없는 원인, 장비 문제, 추측은 작성하지 않습니다.\n"
        "- '확정', '단정됨' 표현 금지. '가능성이 높음', '강하게 의심됨' 사용.\n"
        "- Rule 기반 수치 요약(fail_rate, 건수 등)은 반복하지 않습니다.\n"
        "- 보고서는 7개 섹션만 사용합니다:\n"
        "  [장애 요약], [확인된 현상], [주요 원인 후보],\n"
        "  [2차 영향], [대안 가설], [권장 조치], [분석 한계]\n"
        "- 각 섹션은 5줄 이내 bullet 형식으로 작성합니다.\n"
        "- 표(table)는 사용하지 않습니다."
    )
    user = f"RCA 컨텍스트:\n```json\n{ctx_json}\n```"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
