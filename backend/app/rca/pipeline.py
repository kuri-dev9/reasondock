from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.rca.analyzer import aggregate_records, build_candidates, render_markdown
from app.rca.causal import build_causal_chain
from app.rca.confidence import build_confidence_findings
from app.rca.evidence_graph import build_evidence_graph
from app.rca.parser import parse_xdr_file
from app.rca.procedure import analyze_procedures
from app.rca.semantic import enrich_records, summarize_semantics
from app.rca.spec_loader import load_lte_call_kpi_spec


def analyze_xdr_file(path: Path, filename: str) -> dict[str, Any]:
    fields = load_lte_call_kpi_spec()
    parsed = parse_xdr_file(path, fields)
    parse_stats = asdict(parsed.stats)

    if parsed.stats.total_lines == 0:
        raise ValueError("XDR 파일에 분석할 레코드가 없습니다")
    if parsed.stats.parsed_records == 0:
        raise ValueError(f"파싱 가능한 레코드가 없습니다: {parse_stats}")

    skipped_ratio = parsed.stats.skipped_records / parsed.stats.total_lines
    if skipped_ratio > 0.5:
        raise ValueError(f"파싱 실패율이 너무 높습니다: {skipped_ratio:.1%}")

    summary = aggregate_records(parsed.records, parse_stats, filename)
    summary["rca_candidates"] = build_candidates(summary)
    semantic_events = enrich_records(parsed.records)
    summary["semantic_failures"] = summarize_semantics(semantic_events)
    summary["procedure_analysis"] = analyze_procedures(semantic_events)
    summary["causal_chain"] = build_causal_chain(semantic_events)
    summary["evidence_graph"] = build_evidence_graph(semantic_events, summary["causal_chain"])
    summary["confidence_findings"] = build_confidence_findings(
        summary["semantic_failures"],
        summary["procedure_analysis"],
        summary["causal_chain"],
    )
    summary["markdown"] = render_markdown(summary)
    return summary
