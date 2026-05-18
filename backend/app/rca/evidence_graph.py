from __future__ import annotations

from typing import Any

from app.rca.procedure import procedure_phase


def _node_id(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def build_evidence_graph(events: list[dict[str, Any]], causal_chain: dict[str, Any]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add_node(node_id: str, kind: str, label: str, **attrs: Any) -> None:
        nodes.setdefault(node_id, {"id": node_id, "type": kind, "label": label, **attrs})

    for event in events[:50]:
        interface_id = _node_id("interface", event["interface"])
        cause_id = _node_id("cause", event["cause"]["semantic"])
        procedure_id = _node_id("procedure", event["call_type"])
        phase = procedure_phase(event)
        phase_id = _node_id("phase", f"{event['call_type']}:{phase}")
        event_id = _node_id("event", str(event["record_index"]))

        add_node(interface_id, "Interface", event["interface"])
        add_node(cause_id, "Cause", event["cause"]["semantic"], domain=event["cause"]["domain"])
        add_node(procedure_id, "Procedure", event["call_type"])
        add_node(phase_id, "ProcedurePhase", phase)
        add_node(event_id, "FailureEvent", f"{event['interface']} {event['cause']['semantic']}", timestamp_us=event["timestamp_us"])

        for nf, value in event["equipment"].items():
            if not value:
                continue
            nf_id = _node_id("network_function", f"{nf.upper()}:{value}")
            add_node(nf_id, "NetworkFunction", f"{nf.upper()} {value}")
            edges.append({"source": event_id, "target": nf_id, "type": "observed_on"})

        edges.extend(
            [
                {"source": event_id, "target": interface_id, "type": "observed_on_interface"},
                {"source": event_id, "target": cause_id, "type": "has_cause"},
                {"source": event_id, "target": phase_id, "type": "belongs_to_phase"},
                {"source": phase_id, "target": procedure_id, "type": "belongs_to_procedure"},
            ]
        )

    for item in causal_chain.get("chain", [])[1:]:
        edges.append(
            {
                "source": _node_id("causal_step", str(item["step"])),
                "target": _node_id("causal_step", str(item["caused_by"])),
                "type": "caused_by",
                "confidence": item.get("confidence"),
            }
        )
        add_node(_node_id("causal_step", str(item["step"])), "CausalStep", item["event"])
        add_node(_node_id("causal_step", str(item["caused_by"])), "CausalStep", causal_chain["chain"][0]["event"])

    return {"nodes": list(nodes.values()), "edges": edges}
