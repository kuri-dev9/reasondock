from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import time
from typing import Any

from app.rca.analyzer import aggregate_records, build_candidates, render_markdown
from app.rca.causal import build_causal_chain
from app.rca.confidence import build_confidence_findings
from app.rca.evidence_graph import build_evidence_graph
from app.rca.parser import parse_xdr_file
from app.rca.procedure import analyze_procedures
from app.rca.semantic import enrich_records, summarize_semantics
from app.rca.spec_loader import load_lte_call_kpi_spec
from app.rca.structured_result import build_structured_reasoning_result


def _json_size_bytes(data: dict[str, Any]) -> int:
    return len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def analyze_xdr_file(path: Path, filename: str) -> dict[str, Any]:
    started = time.perf_counter()
    stage_ms: dict[str, int] = {}
    input_bytes = path.stat().st_size if path.exists() else 0

    stage_started = time.perf_counter()
    fields = load_lte_call_kpi_spec()
    stage_ms["spec_load"] = int((time.perf_counter() - stage_started) * 1000)

    stage_started = time.perf_counter()
    parsed = parse_xdr_file(path, fields)
    stage_ms["parse"] = int((time.perf_counter() - stage_started) * 1000)
    parse_stats = asdict(parsed.stats)

    if parsed.stats.total_lines == 0:
        raise ValueError("XDR 파일에 분석할 레코드가 없습니다")
    if parsed.stats.parsed_records == 0:
        raise ValueError(f"파싱 가능한 레코드가 없습니다: {parse_stats}")

    skipped_ratio = parsed.stats.skipped_records / parsed.stats.total_lines
    if skipped_ratio > 0.5:
        raise ValueError(f"파싱 실패율이 너무 높습니다: {skipped_ratio:.1%}")

    stage_started = time.perf_counter()
    summary = aggregate_records(parsed.records, parse_stats, filename)
    summary["rca_candidates"] = build_candidates(summary)
    stage_ms["aggregate_and_candidates"] = int((time.perf_counter() - stage_started) * 1000)

    stage_started = time.perf_counter()
    semantic_events = enrich_records(parsed.records)
    summary["semantic_failures"] = summarize_semantics(semantic_events)
    stage_ms["semantic"] = int((time.perf_counter() - stage_started) * 1000)

    stage_started = time.perf_counter()
    summary["procedure_analysis"] = analyze_procedures(semantic_events)
    summary["causal_chain"] = build_causal_chain(semantic_events)
    summary["evidence_graph"] = build_evidence_graph(semantic_events, summary["causal_chain"])
    summary["confidence_findings"] = build_confidence_findings(
        summary["semantic_failures"],
        summary["procedure_analysis"],
        summary["causal_chain"],
    )
    summary.update(build_structured_reasoning_result(summary, semantic_events))
    stage_ms["reasoning_layers"] = int((time.perf_counter() - stage_started) * 1000)

    summary["input_fingerprint"] = {
        "filename": filename,
        "file_size_bytes": input_bytes,
        "mtime_ns": path.stat().st_mtime_ns if path.exists() else None,
    }
    compact_json_bytes = _json_size_bytes({key: value for key, value in summary.items() if key != "markdown"})
    total_ms = int((time.perf_counter() - started) * 1000)
    summary["processing_metrics"] = {
        "input_xdr_bytes": input_bytes,
        "structured_summary_json_bytes": compact_json_bytes,
        "xdr_to_summary_ratio": round(compact_json_bytes / input_bytes, 6) if input_bytes else None,
        "estimated_reduction_ratio": round(1 - (compact_json_bytes / input_bytes), 6) if input_bytes else None,
        "total_engine_ms": total_ms,
        "stage_ms": stage_ms,
        "records_per_second": round(parsed.stats.parsed_records / (total_ms / 1000), 2) if total_ms > 0 else None,
        "parsed_records": parsed.stats.parsed_records,
        "skipped_records": parsed.stats.skipped_records,
    }
    summary["markdown"] = render_markdown(summary)
    return summary
