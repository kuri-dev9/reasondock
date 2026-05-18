from __future__ import annotations

from collections import Counter
from typing import Any


PROCEDURE_PHASES: dict[str, list[str]] = {
    "Attach_MO": [
        "attach_request",
        "authentication",
        "security_mode",
        "session_creation",
        "attach_accept",
    ],
    "Attach_MT": [
        "attach_request",
        "authentication",
        "security_mode",
        "session_creation",
        "attach_accept",
    ],
    "Service_MO": [
        "service_request",
        "context_setup",
        "bearer_resume",
    ],
    "Service_MT": [
        "paging",
        "service_request",
        "context_setup",
        "bearer_resume",
    ],
    "TAU": [
        "tau_request",
        "authentication",
        "context_update",
        "tau_accept",
    ],
    "S1HO_InterMME": [
        "handover_required",
        "context_transfer",
        "path_switch",
        "handover_complete",
    ],
}


def procedure_phase(event: dict[str, Any]) -> str:
    interface = event["interface"]
    domain = event["cause"]["domain"]
    if interface == "S6a_Diameter" or domain == "authentication":
        return "authentication"
    if interface == "S1MME_NAS-EMM":
        return "nas_reject"
    if interface == "S11_GTPv2C" or domain == "bearer_session":
        return "session_creation"
    if interface == "S1MME_S1AP":
        return "access_signaling"
    if interface == "S10_GTPv2C":
        return "context_transfer"
    return "unknown"


def phase_order(call_type: str, phase: str) -> int:
    phases = PROCEDURE_PHASES.get(call_type, [])
    if phase in phases:
        return phases.index(phase)
    fallback_order = {
        "access_signaling": 0,
        "authentication": 1,
        "security_mode": 2,
        "nas_reject": 3,
        "session_creation": 4,
        "context_transfer": 4,
        "unknown": 99,
    }
    return fallback_order.get(phase, 99)


def analyze_procedures(events: list[dict[str, Any]]) -> dict[str, Any]:
    annotated = []
    phase_counts = Counter()
    call_type_counts = Counter()
    failed_phase_counts = Counter()
    for event in events:
        phase = procedure_phase(event)
        item = {
            "record_index": event["record_index"],
            "timestamp_us": event["timestamp_us"],
            "call_type": event["call_type"],
            "interface": event["interface"],
            "phase": phase,
            "phase_order": phase_order(event["call_type"], phase),
            "semantic": event["cause"]["semantic"],
            "domain": event["cause"]["domain"],
        }
        annotated.append(item)
        phase_counts[phase] += 1
        call_type_counts[event["call_type"]] += 1
        failed_phase_counts[(event["call_type"], phase)] += 1

    likely_failed_phases = [
        {
            "call_type": call_type,
            "phase": phase,
            "count": count,
        }
        for (call_type, phase), count in failed_phase_counts.most_common(10)
    ]
    return {
        "events": annotated[:50],
        "phase_counts": [{"phase": key, "count": count} for key, count in phase_counts.most_common()],
        "call_type_counts": [{"call_type": key, "count": count} for key, count in call_type_counts.most_common()],
        "likely_failed_phases": likely_failed_phases,
    }
