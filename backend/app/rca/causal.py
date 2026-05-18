from __future__ import annotations

from collections import Counter
from typing import Any

from app.rca.procedure import phase_order, procedure_phase


UPSTREAM_DOMAINS = {"authentication", "transport", "mobility_management"}
DOWNSTREAM_DOMAINS = {"bearer_session"}


def _event_label(event: dict[str, Any]) -> str:
    return f"{event['interface']} {event['cause']['semantic']}"


def _relation(primary: dict[str, Any], secondary: dict[str, Any]) -> str:
    if primary["cause"]["domain"] == "authentication" and secondary["interface"] in {"S1MME_NAS-EMM", "S11_GTPv2C"}:
        return "authentication_failure_downstream_effect"
    if primary["cause"]["domain"] == "transport" and secondary["interface"] != primary["interface"]:
        return "transport_failure_downstream_effect"
    if primary["cause"]["domain"] == "mobility_management" and secondary["interface"] == "S11_GTPv2C":
        return "mobility_reject_cleanup_effect"
    return "observed_after"


def build_causal_chain(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {"primary_event": None, "secondary_effects": [], "chain": []}

    domain_counts = Counter(event["cause"]["domain"] for event in events)
    interface_counts = Counter(event["interface"] for event in events)

    def priority(event: dict[str, Any]) -> tuple[int, int, int]:
        domain = event["cause"]["domain"]
        domain_score = 0 if domain in UPSTREAM_DOMAINS else 1 if domain not in DOWNSTREAM_DOMAINS else 2
        return (
            domain_score,
            phase_order(event["call_type"], procedure_phase(event)),
            event["timestamp_us"] if event["timestamp_us"] >= 0 else 10**30,
        )

    primary = sorted(events, key=priority)[0]
    primary_phase = procedure_phase(primary)
    chain = [
        {
            "step": 1,
            "event": _event_label(primary),
            "timestamp_us": primary["timestamp_us"],
            "interface": primary["interface"],
            "phase": primary_phase,
            "confidence": 0.75 if primary["cause"]["known"] else 0.62,
            "evidence": "Earliest upstream-domain failure selected by procedure phase and timestamp ordering.",
        }
    ]
    secondary_effects = []
    step = 2
    for event in events:
        if event is primary:
            continue
        event_phase = procedure_phase(event)
        is_downstream = (
            priority(primary) <= priority(event)
            and (
                event["cause"]["domain"] in DOWNSTREAM_DOMAINS
                or event_phase in {"nas_reject", "session_creation"}
            )
        )
        if not is_downstream:
            continue
        relation = _relation(primary, event)
        item = {
            "step": step,
            "event": _event_label(event),
            "timestamp_us": event["timestamp_us"],
            "interface": event["interface"],
            "phase": event_phase,
            "caused_by": 1,
            "relation": relation,
            "confidence": 0.64 if relation != "observed_after" else 0.45,
        }
        chain.append(item)
        secondary_effects.append(item)
        step += 1
        if step > 8:
            break

    return {
        "primary_event": chain[0],
        "secondary_effects": secondary_effects,
        "chain": chain,
        "domain_counts": [{"domain": key, "count": count} for key, count in domain_counts.most_common()],
        "interface_counts": [{"interface": key, "count": count} for key, count in interface_counts.most_common()],
    }
