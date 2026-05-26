"""QIE xDR Investigation Pipeline.

Encapsulates all xDR query planning, candidate field scoring, and result
formatting that was previously inlined in app/routes/chat.py.

LLM calls must go through app.services.llm only — no direct httpx/requests.
DuckDB connections only in app.qie.datasets.duckdb_store.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.qie.datasets import dataset_manager
from app.qie.execution.renderer import can_direct_render, direct_render_markdown
from app.qie.planner.query_planner import (
    DatasetMeta,
    QueryPlan,
    build_error_stats_fallback_plan,
    execute_plan,
    format_results,
    load_field_taxonomy,
    plan_query,
)
from app.qie.schema.spec_loader import load_lte_call_kpi_spec
from app.routes.xdr_schema import active_schema_id

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models import ConversationDataset, XdrFieldSchema

logger = logging.getLogger(__name__)

XDR_QUERY_SYNONYMS: dict[str, list[str]] = {
    "에러": ["error", "cause", "실패", "오류", "장애"],
    "오류": ["error", "cause", "실패", "에러", "장애"],
    "장애": ["failure", "error", "cause", "실패", "오류원인", "장애원인"],
    "실패": ["failure", "error", "cause", "success_flag", "first_error"],
    "원인": ["cause", "first_error_cause", "last_error_cause"],
    "가입자": ["imsi", "subscriber", "단말"],
    "단말": ["imsi", "imei", "ue", "terminal"],
    "통계": ["count", "cnt", "group", "집계"],
    "집계": ["count", "cnt", "group", "통계"],
}


def _expand_xdr_query_terms(message: str) -> set[str]:
    terms = set(re.findall(r"[a-z0-9가-힣]+", message.lower()))
    for token in list(terms):
        if token.endswith("별") and len(token) > 1:
            terms.add(token[:-1])
        for key, values in XDR_QUERY_SYNONYMS.items():
            if key in token or token in key:
                terms.update(value.lower() for value in values)
    return {term for term in terms if term}


@dataclass
class InvestigationResult:
    xdr_context: str = ""
    xdr_query_plan: QueryPlan | None = None
    xdr_rows: list[dict] = field(default_factory=list)
    xdr_execution_ms: int | None = None
    xdr_activated: bool = False
    xdr_pipeline_status: str = "SKIPPED (not_xdr)"
    xdr_dataset_meta: DatasetMeta | None = None
    xdr_schema_hints: list[dict] = field(default_factory=list)
    candidate_fields_preview: list[str] = field(default_factory=list)
    all_fields_preview: list[str] = field(default_factory=list)
    field_db_types_preview: dict[str, str] = field(default_factory=dict)
    clear_rag: bool = False
    direct_rendered: bool = False
    rca_context: str = ""
    rca_triggered: bool = False


def should_trigger_rca(plan: QueryPlan, rows: list[dict]) -> bool:
    """Return True when QIE result warrants RCA causal analysis."""
    return plan.intent in ("cause_analysis", "failure_analysis") and len(rows) > 0


def _rca_from_rows(rows: list[dict], dataset_id: str) -> str:
    """Run synchronous RCA analysis on QIE result rows. Call via asyncio.to_thread()."""
    from app.rca.analyzer import aggregate_records, build_candidates, render_markdown
    try:
        summary = aggregate_records(rows, {}, dataset_id)
        summary["rca_candidates"] = build_candidates(summary)
        md = render_markdown(summary)
        return f"[RCA 분석 결과]\n{md}"
    except Exception as exc:
        return f"[RCA 분석 실패: {exc}]"


async def run_investigation(
    *,
    active_dataset: ConversationDataset,
    db: AsyncSession,
    message: str,
    model: str,
    conversation_id: int,
) -> InvestigationResult:
    """Run the full xDR investigation pipeline for a single chat turn.

    Returns InvestigationResult with all xDR outputs. When clear_rag=True
    the caller must clear its rag_context/results/references variables
    (planner failed on an xDR-related query; general RAG fallback suppressed).
    """
    from app.models import XdrFieldSchema

    result = InvestigationResult()

    try:
        meta_dict = await dataset_manager.get_dataset_info(active_dataset.dataset_id)
        result.xdr_dataset_meta = DatasetMeta(
            dataset_id=active_dataset.dataset_id,
            dataset_name=str((meta_dict or {}).get("dataset_name") or active_dataset.dataset_id),
            physical_table_name=str(
                (meta_dict or {}).get("physical_table_name") or f"xdr_{active_dataset.dataset_id}"
            ),
        )
        all_specs = await asyncio.to_thread(load_lte_call_kpi_spec)
        planner_schema_id = active_dataset.schema_id or await active_schema_id(db)

        schema_query = (
            select(XdrFieldSchema)
            .where(XdrFieldSchema.is_active == True)  # noqa: E712
            .options(selectinload(XdrFieldSchema.keywords))
            .where(XdrFieldSchema.schema_id == planner_schema_id)
        )
        schema_result = await db.execute(schema_query)
        schema_fields = list(schema_result.scalars().all())

        result.all_fields_preview = [f.field_name for f in schema_fields]

        query_text = message.lower()
        query_tokens = _expand_xdr_query_terms(message)

        scored_fields = []
        for f in schema_fields:
            score = 0
            field_name_lower = f.field_name.lower() if f.field_name else ""
            description_lower = f.description.lower() if f.description else ""
            semantic_text = " ".join(
                str(v or "").lower()
                for v in (f.description, f.category, f.spec_section, f.role, f.db_type)
            )

            if any(t in field_name_lower for t in query_tokens) or field_name_lower in query_text:
                score += 2
            if any(t in description_lower for t in query_tokens):
                score += 1
            if any(t in semantic_text for t in query_tokens):
                score += 1
            if ("통계" in query_tokens or "집계" in query_tokens or "별" in query_text) and f.groupable:
                score += 0.5
            if (
                any(t in query_text for t in ("에러", "오류", "장애", "실패"))
                and ("error" in field_name_lower or "cause" in field_name_lower or f.role == "cause_code")
            ):
                score += 2

            for k in f.keywords:
                alias = k.keyword.lower()
                if alias in query_text or alias in query_tokens:
                    score += 3

            scored_fields.append((score, f))

        scored_fields.sort(key=lambda x: x[0], reverse=True)
        candidate_schema_fields = [sf for s, sf in scored_fields if s > 0][:15]
        schema_by_name = {f.field_name: f for f in schema_fields}

        essential_names: list[str] = []
        if any(t in query_text for t in ("에러", "오류", "장애", "실패", "failure", "error", "cause")):
            essential_names.extend(
                ["attempt_flag", "success_flag", "first_error_cause", "first_error_interface_protocol"]
            )
        if any(t in query_text for t in ("가입자", "단말", "imsi", "ue")):
            essential_names.append("IMSI")
        if any(t in query_text for t in ("기기", "imei", "terminal")):
            essential_names.append("IMEI")

        existing_candidate_names = {f.field_name for f in candidate_schema_fields}
        for name in essential_names:
            f = schema_by_name.get(name)
            if f is not None and name not in existing_candidate_names:
                candidate_schema_fields.append(f)
                existing_candidate_names.add(name)

        if not candidate_schema_fields:
            candidate_schema_fields = [sf for s, sf in scored_fields][:5]

        candidate_field_names = {f.field_name for f in candidate_schema_fields}
        result.candidate_fields_preview = [f.field_name for f in candidate_schema_fields]

        slimmed_specs = [spec for spec in all_specs if spec.name in candidate_field_names]
        if not slimmed_specs:
            slimmed_specs = all_specs[:5]

        candidate_taxonomy = await load_field_taxonomy(
            db,
            tuple(slimmed_specs),
            schema_id=planner_schema_id,
        )
        result.field_db_types_preview = {f.field_name: f.db_type for f in candidate_taxonomy}

        result.xdr_schema_hints = [
            {
                "field_name": f.field_name,
                "db_type": result.field_db_types_preview.get(f.field_name, "TEXT"),
                "semantic_db_type": f.db_type or "",
                "category": f.category or f.spec_section or "",
                "role": f.role or "",
                "group": f.description or "",
                "aliases": [k.keyword for k in f.keywords],
            }
            for f in candidate_schema_fields
        ]

        xdr_keywords = {
            "통계", "집계", "에러", "오류", "실패", "원인", "장애",
            "가입자", "단말", "imsi", "imei", "추이", "비율", "건수",
            "조회", "분석", "비교",
        }
        is_xdr_related = any(term in query_text for term in xdr_keywords)

        if is_xdr_related:
            try:
                _TIME_KEYWORDS = {"시간", "시각", "추이", "타임라인", "언제", "time", "timeline", "시계열", "최초", "처음", "첫"}
                xdr_query_plan: QueryPlan | None = None
                if (
                    any(t in query_text for t in ("가입자", "imsi", "단말", "imei"))
                    and any(t in query_text for t in ("에러", "오류", "실패", "장애", "원인"))
                    and any(t in query_text for t in ("통계", "집계", "별"))
                    and not any(t in query_text for t in _TIME_KEYWORDS)
                ):
                    group_col = "IMEI" if "imei" in query_text or "기기" in query_text else "IMSI"
                    xdr_query_plan = build_error_stats_fallback_plan(
                        taxonomy=candidate_taxonomy,
                        dataset_meta=result.xdr_dataset_meta,
                        group_field=group_col,
                    )
                if xdr_query_plan is None:
                    xdr_query_plan = await plan_query(
                        user_message=message,
                        dataset_id=active_dataset.dataset_id,
                        model=model,
                        fields=tuple(slimmed_specs),
                        db=db,
                        schema_id=planner_schema_id,
                        dataset_meta=result.xdr_dataset_meta,
                    )
                if not xdr_query_plan.is_xdr_related:
                    raise ValueError(xdr_query_plan.description or "planner returned not_xdr")

                result.xdr_activated = True
                _exec_start = time.perf_counter()
                result.xdr_rows = await execute_plan(xdr_query_plan, active_dataset.dataset_id)
                result.xdr_execution_ms = int((time.perf_counter() - _exec_start) * 1000)

                if can_direct_render(xdr_query_plan, result.xdr_rows):
                    result.xdr_context = direct_render_markdown(
                        result.xdr_rows, xdr_query_plan, active_dataset.dataset_id
                    )
                    result.direct_rendered = True
                else:
                    result.xdr_context = format_results(
                        result.xdr_rows, xdr_query_plan, active_dataset.dataset_id
                    )

                if should_trigger_rca(xdr_query_plan, result.xdr_rows):
                    result.rca_triggered = True
                    result.rca_context = await asyncio.to_thread(
                        _rca_from_rows, result.xdr_rows, active_dataset.dataset_id
                    )

                result.xdr_query_plan = xdr_query_plan
                result.xdr_pipeline_status = "COMPLETED"
                result.clear_rag = True
                logger.info(
                    "xDR pipeline ACTIVATED: conv_id=%s dataset=%s intent=%s rows=%d confidence=%.2f",
                    conversation_id,
                    active_dataset.dataset_id,
                    xdr_query_plan.intent,
                    len(result.xdr_rows),
                    xdr_query_plan.confidence,
                )
            except Exception as exc:
                result.xdr_pipeline_status = "FAILED (planner_error)"
                logger.error("xDR Planner execution failed: %s", exc)

                result.xdr_context = (
                    f"xDR 분석 실패: 데이터 추출 계획을 생성하지 못했습니다. (사유: {exc})"
                )
                result.xdr_activated = False
                result.xdr_query_plan = QueryPlan(
                    is_xdr_related=True,
                    intent="planner_error",
                    sql="",
                    description=str(exc),
                    confidence=0.0,
                )
                result.clear_rag = True
        else:
            logger.info("xDR pipeline SKIPPED: conv_id=%s reason=not_xdr", conversation_id)

    except Exception:
        logger.exception("xDR Query Planning 실패 (conv_id=%s)", conversation_id)

    return result
