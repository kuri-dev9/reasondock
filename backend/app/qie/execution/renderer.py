"""Result-first rendering: convert DuckDB rows to markdown without LLM."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.qie.planner.query_planner import QueryPlan

_DIRECT_RENDER_INTENTS = {
    "group_by_error_stats",
    "failure_analysis",
    "cause_analysis",
    "interface_filter",
}


def can_direct_render(plan: QueryPlan, rows: list[dict]) -> bool:
    """Return True when rows can be rendered as markdown without LLM."""
    return (
        plan.intent in _DIRECT_RENDER_INTENTS
        and 0 < len(rows) <= 50
    )


def direct_render_markdown(rows: list[dict], plan: QueryPlan, dataset_id: str) -> str:
    """Convert query result rows to a markdown table. No LLM call."""
    if not rows:
        return f"[{dataset_id}] 조건에 해당하는 레코드가 없습니다."
    headers = list(rows[0].keys())
    header_row = "| " + " | ".join(headers) + " |"
    sep_row = "| " + " | ".join(["---"] * len(headers)) + " |"
    data_rows = [
        "| " + " | ".join(str(v) if v is not None else "-" for v in row.values()) + " |"
        for row in rows
    ]
    table = "\n".join([header_row, sep_row] + data_rows)
    return f"**{plan.description}** ({len(rows)}건)\n\n{table}"
