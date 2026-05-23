"""Query Planning layer: natural language → DuckDB SQL.

Rules:
- LLM calls via app.services.llm.chat() only (no direct httpx/requests)
- No model name hardcoding — model is passed as a parameter
- No DuckDB connections here — use duckdb_store.query_records()
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import XdrFieldSchema
from app.rca.spec_loader import FieldSpec
from app.routes.xdr_schema import ensure_defaults

logger = logging.getLogger(__name__)


@dataclass
class QueryPlan:
    intent: str
    sql: str
    description: str


@dataclass(frozen=True)
class FieldTaxonomy:
    field_name: str
    description: str
    collect_type: str
    category: str | None
    role: str | None
    importance: str
    active: bool
    capabilities: tuple[str, ...]
    keywords: tuple[str, ...]


async def _load_field_taxonomy(
    db: AsyncSession | None,
    fields: tuple[FieldSpec, ...],
    schema_id: int | None = None,
) -> list[FieldTaxonomy]:
    field_map = {f.name: f for f in fields}
    if db is None:
        return [
            FieldTaxonomy(
                field_name=field.name,
                description=field.description,
                collect_type=field.collect_type,
                category=field.section,
                role=None,
                importance="low",
                active=False,
                capabilities=(),
                keywords=(),
            )
            for field in fields
        ]

    await ensure_defaults(db)
    if schema_id is None:
        from app.routes.xdr_schema import active_schema_id
        schema_id = await active_schema_id(db)
    result = await db.execute(
        select(XdrFieldSchema)
        .where(
            XdrFieldSchema.schema_id == schema_id,
        )
        .options(selectinload(XdrFieldSchema.keywords))
        .order_by(XdrFieldSchema.is_active.desc(), XdrFieldSchema.spec_no, XdrFieldSchema.id)
    )
    taxonomy = []
    for row in result.scalars().all():
        spec = field_map.get(row.field_name)
        taxonomy.append(
            FieldTaxonomy(
                field_name=row.field_name,
                description=row.description or (spec.description if spec else ""),
                collect_type=row.db_type or (spec.collect_type if spec else "string"),
                category=row.category or row.spec_section or (spec.section if spec else None),
                role=row.role,
                importance=row.importance or "low",
                active=row.is_active,
                capabilities=tuple(_field_capabilities(row)),
                keywords=tuple(keyword.keyword for keyword in row.keywords),
            )
        )
    return taxonomy


def _field_capabilities(field: XdrFieldSchema) -> list[str]:
    names = [
        "groupable",
        "filterable",
        "searchable",
        "joinable",
        "pii",
        "sortable",
        "time_series",
        "categorical",
        "boolean_like",
    ]
    return [name for name in names if getattr(field, name, False)]


def _build_schema_hint(taxonomy: list[FieldTaxonomy]) -> str:
    lines = []
    active_items = sorted(
        [item for item in taxonomy if item.active],
        key=lambda item: (item.category is None, item.category or "", item.field_name),
    )
    for field in active_items:
        description = field.description[:60]
        aliases = ", ".join(field.keywords) if field.keywords else "-"
        capabilities = ", ".join(field.capabilities) if field.capabilities else "-"
        lines.append(
            f"  {field.field_name} ({field.collect_type}): {description} | "
            f"role={field.role or 'unknown'} | category={field.category or '-'} | "
            f"importance={field.importance} | capabilities={capabilities} | aliases: {aliases}"
        )
    return "\n".join(lines)


def _build_inactive_hint(taxonomy: list[FieldTaxonomy], limit: int = 80) -> str:
    inactive = [item for item in taxonomy if not item.active]
    if not inactive:
        return "-"
    lines = [
        f"  {field.field_name} | category={field.category or '-'} | role={field.role or 'unknown'}"
        for field in inactive[:limit]
    ]
    if len(inactive) > limit:
        lines.append(f"  ... inactive fields {len(inactive) - limit} more")
    return "\n".join(lines)


def _build_semantic_rules(taxonomy: list[FieldTaxonomy]) -> str:
    active_fields = {field.field_name for field in taxonomy if field.active}
    rules = []
    if {"attempt_flag", "success_flag"} <= active_fields:
        rules.extend(
            [
                "- attempt_flag='1' AND success_flag='0' → 실패 레코드",
                "- attempt_flag='1' AND success_flag='1' → 성공 레코드",
            ]
        )
    timestamp_fields = [field.field_name for field in taxonomy if field.active and field.role == "timestamp"]
    if timestamp_fields:
        rules.append(f"- 시간/추이 질문은 timestamp role 컬럼을 우선 사용: {', '.join(timestamp_fields[:5])}")
    return "\n".join(rules)


async def plan_query(
    user_message: str,
    dataset_id: str,
    model: str,
    fields: tuple[FieldSpec, ...],
    db: AsyncSession | None = None,
    schema_id: int | None = None,
) -> QueryPlan | None:
    """Convert user natural language message to DuckDB SQL.

    Returns None if the question is not xDR-related or if LLM call fails.
    """
    from app.services.llm import chat as llm_chat

    taxonomy = await _load_field_taxonomy(db, fields, schema_id=schema_id)
    schema_hint = _build_schema_hint(taxonomy)
    inactive_hint = _build_inactive_hint(taxonomy)
    semantic_rules = _build_semantic_rules(taxonomy)
    table = f"xdr_{dataset_id}"

    system_prompt = f"""당신은 텔레콤 xDR 데이터 분석 전문가입니다.
사용자 질문을 DuckDB SQL로 변환하세요.

테이블명: {table}
주요 컬럼:
{schema_hint}

알려진 비활성 컬럼(존재 인지만 하고 우선 사용하지 않음):
{inactive_hint}

규칙:
{semantic_rules}
- active=true 컬럼을 우선 사용
- role/category/importance/capabilities/aliases를 함께 참고해 사용자 표현과 실제 컬럼을 매핑
- 비활성 컬럼은 사용자가 명시적으로 해당 field_name을 요구한 경우에만 보조적으로 사용
- groupable=false 컬럼은 GROUP BY에 사용하지 말 것
- filterable=false 컬럼은 WHERE 조건에 우선 사용하지 말 것
- sortable/time_series capability가 있는 시간 컬럼을 timeline/추이 질문에 우선 사용
- SQL은 반드시 한 줄(single line)로 작성, 줄바꾸음 금지
- LIMIT은 반드시 포함, 최대 500
- xDR 조사와 무관한 질문이면 intent를 "not_xdr"로 설정

반드시 아래 JSON만 출력 (다른 텍스트 없이):
{{
  "intent": "failure_analysis|imsi_lookup|interface_filter|timeline|cause_analysis|not_xdr",
  "sql": "SELECT ...",
  "description": "한국어로 쿼리 설명"
}}"""

    try:
        response = await llm_chat(
            model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            options={"temperature": 0.1, "num_predict": 512},
            timeout=60.0,
        )
        # LLM 응답에서 JSON 추출 — 잘못된 \escape 보정 포함
        plan = None
        for match in re.finditer(r'\{.*?\}', response, re.DOTALL):
            raw = match.group()
            try:
                plan = json.loads(raw)
                break
            except json.JSONDecodeError:
                # \escape 보정 후 재시도
                try:
                    cleaned = re.sub(r'(?<!\\)\\(?!["\\bfnrtu/\n\r\t])', r'\\\\', raw)
                    plan = json.loads(cleaned)
                    break
                except json.JSONDecodeError:
                    continue
        if plan is None:
            return None
        if plan.get("intent") == "not_xdr":
            return None
        sql = plan.get("sql", "").strip()
        if not sql or not sql.upper().startswith("SELECT"):
            return None
        return QueryPlan(
            intent=plan.get("intent", "unknown"),
            sql=sql,
            description=plan.get("description", ""),
        )
    except Exception as exc:
        logger.warning("Query planning 실패: %s", exc)
        return None


async def execute_plan(
    plan: QueryPlan,
    dataset_id: str,
    max_rows: int = 200,
) -> list[dict]:
    """Execute the DuckDB query via asyncio.to_thread()."""
    from app.rca.duckdb_store import query_records
    try:
        return await asyncio.to_thread(query_records, dataset_id, plan.sql, max_rows)
    except Exception as exc:
        logger.warning("DuckDB 쿼리 실행 실패 (dataset_id=%s): %s", dataset_id, exc)
        return []


def format_results(
    rows: list[dict],
    plan: QueryPlan,
    dataset_id: str,
) -> str:
    """Convert query rows to LLM-ready prompt text."""
    if not rows:
        return (
            f"[xDR 조사 결과: {dataset_id}]\n"
            "쿼리 조건에 해당하는 레코드가 없습니다.\n"
            "[LLM 지시] 데이터가 없음을 한국어로 간단히 안내하세요."
        )

    header = (
        f"[xDR 조사 결과: {dataset_id}]\n"
        f"조회 의도: {plan.description}\n"
        f"건수: {len(rows)}건\n"
        "[LLM 지시] 아래 데이터를 반드시 markdown 표(| 컬럼 | ... |) 형식으로 정리하여 답변하세요. "
        "IMSI 등 해시값은 그대로 표시하되 인덱스 번호(1, 2, 3...)를 앞에 붙여 구분하세요. "
        "건수(cnt)가 같으면 protocol/cause 기준으로 그룹핑하여 설명하세요.\n\n"
    )
    if len(rows) <= 20:
        rows_text = json.dumps(rows, ensure_ascii=False, indent=2)
    else:
        rows_text = json.dumps(rows[:20], ensure_ascii=False, indent=2)
        rows_text += f"\n... (총 {len(rows)}건 중 상위 20건 표시)"
    return header + rows_text
