from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.rca.knowledge_loader import lookup_cause, lookup_procedure, lookup_taxonomy
from app.rca.procedure import procedure_phase


SCHEMA_VERSION = "reasoning-result-v1"
PIPELINE_VERSION = "deterministic-rca-v1"
SEVERITY_ORDER = {"INFO": 0, "LOW": 1, "MINOR": 1, "MEDIUM": 2, "MAJOR": 3, "HIGH": 3, "CRITICAL": 4}
SEVERITY_NORMALIZED = {
    "Info": "INFO",
    "Warning": "LOW",
    "Minor": "LOW",
    "Major": "HIGH",
    "Critical": "CRITICAL",
}


def _iso_us(value: int | None) -> str | None:
    if value is None or value < 0:
        return None
    return datetime.fromtimestamp(value / 1_000_000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _severity_from_signal(summary: dict[str, Any], primary_meta: dict[str, Any] | None) -> str:
    base = "INFO" if summary.get("analysis_mode") == "healthy" else "MEDIUM"
    if primary_meta:
        base = SEVERITY_NORMALIZED.get(str(primary_meta.get("severity_default")), base)
    fail_rate = summary.get("overall", {}).get("fail_rate", 0.0)
    drop_rate = summary.get("overall", {}).get("drop_rate", 0.0)
    if fail_rate >= 0.2 or drop_rate >= 0.05:
        return "CRITICAL" if SEVERITY_ORDER.get(base, 0) >= 3 else "HIGH"
    if fail_rate >= 0.05 or drop_rate > 0:
        return "HIGH" if SEVERITY_ORDER.get(base, 0) >= 2 else "MEDIUM"
    return base


def _classification(summary: dict[str, Any], primary: dict[str, Any] | None) -> str:
    if summary.get("analysis_mode") == "healthy":
        return "NORMAL_SERVICE_WINDOW"
    if primary:
        domain = str(primary.get("domain", "")).lower()
        cause = str(primary.get("cause", "")).lower()
        if "auth" in domain or "auth" in cause or "diameter" in cause:
            return "AUTH_FAILURE_BURST"
        if "bearer" in domain or "gtp" in cause or "session" in cause:
            return "BEARER_SESSION_FAILURE"
        if "mobility" in domain or "emm" in cause:
            return "MOBILITY_MANAGEMENT_FAILURE"
        if "transport" in domain or "timeout" in cause:
            return "TRANSPORT_TIMEOUT_CLUSTER"
    if summary.get("time_anomaly", {}).get("detected"):
        return "TRANSIENT_FAILURE_SPIKE"
    return "UNCLASSIFIED_FAILURE_PATTERN"


def _event_evidence(event: dict[str, Any], index: int) -> dict[str, Any]:
    cause = event.get("cause", {})
    meta = lookup_cause(str(event.get("interface", "")), cause.get("cause_code"))
    phase = procedure_phase(event)
    strength = "explicit_protocol_reject" if cause.get("known") else "kpi_only"
    if str(cause.get("cause_code")) == "900":
        strength = "timeout_only"
    return {
        "id": f"evidence_{index}",
        "source_field": "first_error_interface_protocol/first_error_message/first_error_cause",
        "record_index": event.get("record_index"),
        "timestamp_us": event.get("timestamp_us"),
        "protocol": event.get("interface"),
        "interface": event.get("interface"),
        "message": event.get("message"),
        "cause_code": cause.get("cause_code"),
        "cause": cause.get("semantic"),
        "semantic_role": "explicit_protocol_error",
        "evidence_strength": strength,
        "procedure": event.get("call_type"),
        "procedure_phase": phase,
        "domain": cause.get("domain"),
        "description": cause.get("description"),
        "dictionary_match": meta.get("id") if meta else None,
    }


def _primary_cause(summary: dict[str, Any], events: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    causal_primary = summary.get("causal_chain", {}).get("primary_event")
    primary_event = events[0] if events else None
    if causal_primary and events:
        for event in events:
            label = f"{event['interface']} {event['cause']['semantic']}"
            if label == causal_primary.get("event"):
                primary_event = event
                break
    if not primary_event:
        candidate = (summary.get("rca_candidates") or [None])[0]
        if not candidate:
            return None, None
        return (
            {
                "domain": "Unknown",
                "cause": candidate.get("suspected_cause"),
                "confidence": candidate.get("confidence", 0.0),
                "confidence_tier": "weak_hypothesis",
                "evidence_strength": "kpi_only",
                "source": "rca_candidates",
            },
            None,
        )

    cause = primary_event.get("cause", {})
    meta = lookup_cause(str(primary_event.get("interface", "")), cause.get("cause_code"))
    taxonomy_ids = meta.get("related_taxonomy", []) if meta else []
    taxonomy = lookup_taxonomy(taxonomy_ids[0]) if taxonomy_ids else None
    domain = taxonomy[0] if taxonomy else cause.get("domain", "Unknown")
    confidence = summary.get("causal_chain", {}).get("primary_event", {}).get("confidence")
    if confidence is None:
        confidence = 0.88 if cause.get("known") else 0.45
    tier = "confirmed" if cause.get("known") and confidence >= 0.9 else "suspected" if confidence >= 0.55 else "weak_hypothesis"
    return (
        {
            "domain": domain,
            "cause": cause.get("semantic"),
            "safe_label": cause.get("safe_label"),
            "description": cause.get("description"),
            "confidence": round(float(confidence), 2),
            "confidence_tier": tier,
            "evidence_strength": "explicit_protocol_reject" if cause.get("known") else "kpi_only",
            "source": "causal_chain.primary_event",
            "dictionary_match": meta.get("id") if meta else None,
            "taxonomy": taxonomy_ids,
        },
        meta,
    )


def _alternative_causes(summary: dict[str, Any], primary: dict[str, Any] | None) -> list[dict[str, Any]]:
    alternatives = []
    primary_cause = primary.get("cause") if primary else None
    for candidate in summary.get("rca_candidates", [])[:5]:
        cause = candidate.get("suspected_cause")
        if cause == primary_cause:
            continue
        alternatives.append(
            {
                "domain": "Unknown",
                "cause": cause,
                "confidence": candidate.get("confidence"),
                "evidence": candidate.get("evidence", []),
                "source": "rca_candidates",
            }
        )
    return alternatives


def _recommended_actions(primary_meta: dict[str, Any] | None, summary: dict[str, Any], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = []
    if primary_meta:
        for index, action in enumerate(primary_meta.get("recommended_actions", [])[:6], start=1):
            actions.append(
                {
                    "priority": "High" if index <= 3 else "Medium",
                    "action": action,
                    "reason": f"{primary_meta.get('id')} dictionary mapping",
                    "source": "cause_code_dictionary.release11.v1",
                }
            )
    if events:
        procedure = lookup_procedure(str(events[0].get("call_type", "")))
        if procedure:
            for action in procedure.get("recommended_analysis_order", [])[:4]:
                if any(existing["action"] == action for existing in actions):
                    continue
                actions.append(
                    {
                        "priority": "Medium",
                        "action": action,
                        "reason": f"{procedure.get('name')} procedure analysis order",
                        "source": "procedure_dictionary.release11.v1",
                    }
                )
    if not actions and summary.get("analysis_mode") == "healthy":
        actions.append(
            {
                "priority": "Low",
                "action": "Maintain existing KPI monitoring cadence",
                "reason": "No call failure or drop signal observed in this analysis window",
                "source": "default_healthy_policy",
            }
        )
    return actions


def _blast_radius(summary: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    affected = summary.get("affected_equipment", {})
    imsis = {event.get("session", {}).get("imsi") for event in events if event.get("session", {}).get("imsi")}
    apns = Counter(event.get("session", {}).get("apn") for event in events if event.get("session", {}).get("apn"))
    return {
        "affected_cells": affected.get("enb", []),
        "affected_mme": affected.get("mme", []),
        "affected_sgw": affected.get("sgw", []),
        "affected_apn": [{"key": key, "count": count} for key, count in apns.most_common(5)],
        "estimated_ue_count": len(imsis),
        "estimation_basis": "unique IMSI count from semantic failure events",
    }


def _data_quality(summary: dict[str, Any]) -> dict[str, Any]:
    parse = summary.get("file_info", {}).get("parse", {})
    total = parse.get("total_lines") or summary.get("overall", {}).get("total") or 0
    parsed = parse.get("parsed_records") or 0
    skipped = parse.get("skipped_records") or 0
    bad_counts = parse.get("bad_field_counts") or {}
    parse_ratio = round(parsed / total, 4) if total else 0.0
    return {
        "total_lines": total,
        "parsed_records": parsed,
        "skipped_records": skipped,
        "parse_success_ratio": parse_ratio,
        "bad_field_count_distribution": bad_counts,
        "quality_level": "High" if parse_ratio >= 0.98 else "Medium" if parse_ratio >= 0.9 else "Low",
    }


def build_structured_reasoning_result(summary: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    primary, primary_meta = _primary_cause(summary, events)
    severity = _severity_from_signal(summary, primary_meta)
    evidence = [_event_evidence(event, index) for index, event in enumerate(events[:50], start=1)]
    cleanup_signals = [
        effect
        for effect in summary.get("causal_chain", {}).get("secondary_effects", [])
        if "cleanup" in str(effect.get("relation", "")).lower() or "release" in str(effect.get("event", "")).lower()
    ]
    confidence_score = primary.get("confidence", 1.0 if summary.get("analysis_mode") == "healthy" else 0.0) if primary else 1.0
    missing_evidence = []
    if not events and summary.get("analysis_mode") != "healthy":
        missing_evidence.append("No semantic failure events were available for root-cause selection")
    if _data_quality(summary)["quality_level"] != "High":
        missing_evidence.append("Some records were skipped or malformed during xDR parsing")

    return {
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "status": "NORMAL" if summary.get("analysis_mode") == "healthy" else "DEGRADED",
        "severity": severity,
        "incident_classification": _classification(summary, primary),
        "analysis_window": {
            "start_us": summary.get("file_info", {}).get("period", {}).get("start_us"),
            "end_us": summary.get("file_info", {}).get("period", {}).get("end_us"),
            "start": _iso_us(summary.get("file_info", {}).get("period", {}).get("start_us")),
            "end": _iso_us(summary.get("file_info", {}).get("period", {}).get("end_us")),
        },
        "primary_cause": primary,
        "alternative_causes": _alternative_causes(summary, primary),
        "evidence": evidence,
        "counter_evidence": [],
        "cleanup_signals": cleanup_signals,
        "excluded_signals": [
            {
                "signal": "normal_detach_cleanup",
                "reason": "Detach records with detach_flag=1 and success_flag=1 are excluded from failure RCA candidates",
            }
        ],
        "blast_radius": _blast_radius(summary, events),
        "confidence_score": round(float(confidence_score), 2),
        "root_cause_tree": summary.get("causal_chain", {}),
        "recommended_actions": _recommended_actions(primary_meta, summary, events),
        "uncertainty": {
            "level": "Low" if confidence_score >= 0.8 and not missing_evidence else "Medium" if confidence_score >= 0.5 else "High",
            "missing_evidence": missing_evidence,
        },
        "data_quality": _data_quality(summary),
        "deterministic_trace": {
            "selected_by": "procedure phase priority + timestamp ordering + dictionary match",
            "rule_modules": [
                "semantic.enrich_records",
                "procedure.analyze_procedures",
                "causal.build_causal_chain",
                "confidence.build_confidence_findings",
                "evidence_graph.build_evidence_graph",
                "structured_result.build_structured_reasoning_result",
            ],
            "dictionary_sources": [
                "cause_code_dictionary.release11.v1",
                "procedure_dictionary.release11.v1",
                "taxonomy.v1",
            ],
        },
        "llm_explanation_status": "pending",
        "operator_validation": {
            "status": "not_reviewed",
            "reviewer": None,
            "comment": None,
            "updated_at": None,
        },
        "followup_questions": [
            "동일 원인 후보가 특정 IMSI, APN, MME, eNB에 반복 집중되는지 확인하세요.",
            "장비 로그와 성능 카운터를 대조해 xDR 기반 원인 후보를 검증하세요.",
        ],
    }

