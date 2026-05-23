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

# Rule-based pre-filter patterns (LLM-free, fast)
_XDR_STRONG_PATTERNS = [
    r"\bIMSI\b", r"\bIMEI\b", r"\bMME\b", r"\beNB\b",
    r"\bS1AP\b", r"\bGTP\b", r"\bNAS\b", r"\bS6a\b",
    r"\bS11\b", r"\bS1\b", r"\bTAC\b", r"\bEPS\b",
    r"attach", r"detach", r"handover", r"paging",
    r"bearer", r"session",
    r"실패\s*원인", r"장애\s*원인", r"drop\s*cause",
    r"실패율", r"성공률", r"kpi", r"cause\s*code",
    r"release\s*cause", r"error\s*code",
    r"단말별", r"기지국별", r"MME별", r"eNB별",
    r"IMSI별", r"시간대별",
    r"집계", r"분포", r"통계", r"상위\s*\d+",
    r"타임라인", r"시계열",
]

_NOT_XDR_PATTERNS = [
    r"^(안녕|hello|hi|hey)\b",
    r"^(고마워|감사|thanks|thank you)\b",
    r"^(잘\s*가|bye|goodbye)\b",
    r"^(ㅋ+|ㅎ+|ㅠ+|ㅜ+)",
    r"^(오케이|ok|okay|알겠|알았)\b",
    r"(날씨|주식|뉴스|맛집|영화|음악|스포츠)",
    r"(삼성전자|애플|구글|테슬라)\s*(주가|뉴스|소식|협상)",
]

_XDR_TERM_KEYWORDS = [
    "단말", "가입자", "인터페이스", "프로토콜", "원인",
    "실패", "장애", "attach", "detach", "bearer",
    "epc", "lte", "5g", "nr", "volte",
    "호", "콜", "call", "failure", "error",
]


def _is_xdr_related_rule(user_message: str) -> tuple[bool, float]:
    """Rule-based xDR relevance check. No LLM, fast."""
    msg_lower = user_message.lower()

    for pattern in _NOT_XDR_PATTERNS:
        if re.search(pattern, user_message, re.IGNORECASE):
            return False, 0.95

    matched = [p for p in _XDR_STRONG_PATTERNS if re.search(p, user_message, re.IGNORECASE)]
    if matched:
        confidence = min(0.95, 0.6 + 0.1 * len(matched))
        return True, round(confidence, 2)

    term_hits = [t for t in _XDR_TERM_KEYWORDS if t in msg_lower]
    if len(term_hits) >= 2:
        return True, 0.65
    if len(term_hits) == 1:
        return True, 0.45

    return False, 0.80


@dataclass
class QueryPlan:
    is_xdr_related: bool
    confidence: float
    intent: str
    description: str
    sql: str


@dataclass(frozen=True)
class DatasetMeta:
    dataset_id: str
    dataset_name: str
    physical_table_name: str


@dataclass(frozen=True)
class FieldTaxonomy:
    field_name: str
    description: str
    db_type: str
    semantic_db_type: str
    category: str | None
    role: str | None
    importance: str
    active: bool
    capabilities: tuple[str, ...]
    keywords: tuple[str, ...]


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def sql_literal(field: FieldTaxonomy, value: str | int | float | bool | None) -> str:
    if value is None:
        return "NULL"
    db_type = field.db_type.lower()
    if db_type in {"int", "integer", "bigint", "uint", "double", "float", "real", "decimal"}:
        return str(value)
    if db_type in {"bool", "boolean"}:
        if isinstance(value, bool):
            return "true" if value else "false"
        return "true" if str(value).lower() in {"1", "true", "yes", "y"} else "false"
    text = str(value).replace("'", "''")
    return f"'{text}'"


def like_literal(value: str) -> str:
    return "'%" + value.replace("'", "''") + "%'"


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
                db_type="TEXT",
                semantic_db_type=field.collect_type,
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
    requested_field_names = set(field_map)
    query = select(XdrFieldSchema).where(XdrFieldSchema.schema_id == schema_id)
    if requested_field_names:
        query = query.where(XdrFieldSchema.field_name.in_(requested_field_names))
    result = await db.execute(
        query
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
                db_type="TEXT",
                semantic_db_type=row.db_type or (spec.collect_type if spec else "string"),
                category=row.category or row.spec_section or (spec.section if spec else None),
                role=row.role,
                importance=row.importance or "low",
                active=row.is_active,
                capabilities=tuple(_field_capabilities(row)),
                keywords=tuple(keyword.keyword for keyword in row.keywords),
            )
        )
    return taxonomy


load_field_taxonomy = _load_field_taxonomy


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
            f"  {field.field_name} (db_type={field.db_type}, semantic_type={field.semantic_db_type}): {description} | "
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


def _normalize_dataset_meta(dataset_id: str, dataset_meta: DatasetMeta | dict | None) -> DatasetMeta:
    if isinstance(dataset_meta, DatasetMeta):
        return dataset_meta
    if isinstance(dataset_meta, dict):
        dataset_name = str(dataset_meta.get("dataset_name") or dataset_meta.get("dataset_id") or dataset_id)
        physical_table_name = str(dataset_meta.get("physical_table_name") or f"xdr_{dataset_id}")
        return DatasetMeta(dataset_id=dataset_id, dataset_name=dataset_name, physical_table_name=physical_table_name)
    return DatasetMeta(dataset_id=dataset_id, dataset_name=dataset_id, physical_table_name=f"xdr_{dataset_id}")


def _replace_dataset_table_references(sql: str, meta: DatasetMeta) -> str:
    physical = quote_identifier(meta.physical_table_name)
    names = {meta.dataset_id, meta.dataset_name, meta.physical_table_name}
    for name in sorted(names, key=len, reverse=True):
        if not name:
            continue
        quoted_name = quote_identifier(name)
        pattern = rf"(?i)\b(FROM|JOIN)\s+(?:{re.escape(quoted_name)}|{re.escape(name)})(?=\s|$)"
        sql = re.sub(pattern, lambda m: f"{m.group(1)} {physical}", sql)
    return sql


def _normalize_schema_literals(sql: str, taxonomy: list[FieldTaxonomy]) -> str:
    by_name = {field.field_name: field for field in taxonomy}
    for field_name, field in by_name.items():
        if field.db_type.lower() not in {"text", "varchar", "string", "char"}:
            continue
        quoted_field = quote_identifier(field_name)
        pattern = rf"(?i)((?:\b{re.escape(field_name)}\b|{re.escape(quoted_field)})\s*(?:=|<>|!=|<|>|<=|>=)\s*)(-?\d+(?:\.\d+)?)\b"
        sql = re.sub(
            pattern,
            lambda m: f"{m.group(1)}{sql_literal(field, m.group(2))}",
            sql,
        )
    return sql


def normalize_generated_sql(sql: str, *, dataset_meta: DatasetMeta, taxonomy: list[FieldTaxonomy]) -> str:
    normalized = " ".join(sql.strip().split())
    normalized = _replace_dataset_table_references(normalized, dataset_meta)
    normalized = _normalize_schema_literals(normalized, taxonomy)
    return normalized


def build_error_stats_fallback_plan(
    *,
    taxonomy: list[FieldTaxonomy],
    dataset_meta: DatasetMeta,
    group_field: str,
) -> QueryPlan | None:
    fields = {field.field_name: field for field in taxonomy}
    required = [group_field, "success_flag", "first_error_interface_protocol", "first_error_cause"]
    if any(name not in fields for name in required):
        return None
    table = quote_identifier(dataset_meta.physical_table_name)
    group_col = quote_identifier(group_field)
    success_col = quote_identifier("success_flag")
    iface_col = quote_identifier("first_error_interface_protocol")
    cause_col = quote_identifier("first_error_cause")
    sql = (
        f"SELECT {group_col}, {iface_col}, {cause_col}, COUNT(*) as cnt "
        f"FROM {table} "
        f"WHERE {success_col} = {sql_literal(fields['success_flag'], '0')} "
        f"GROUP BY {group_col}, {iface_col}, {cause_col} "
        "ORDER BY cnt DESC LIMIT 50"
    )
    return QueryPlan(
        is_xdr_related=True,
        confidence=1.0,
        intent="group_by_error_stats",
        description="Rule-based schema-aware fallback pattern matched",
        sql=sql,
    )


async def plan_query(
    user_message: str,
    dataset_id: str,
    model: str,
    fields: tuple[FieldSpec, ...],
    db: AsyncSession | None = None,
    schema_id: int | None = None,
    dataset_meta: DatasetMeta | dict | None = None,
) -> QueryPlan:
    """Two-stage xDR query planner. Always returns QueryPlan (never None).

    Stage 1: rule-based pre-filter (no LLM, fast).
    Stage 2: LLM SQL generation (only when is_xdr_related=True).
    """
    # Stage 1: rule-based gate
    is_xdr_related, confidence = _is_xdr_related_rule(user_message)
    if not is_xdr_related:
        return QueryPlan(
            is_xdr_related=False,
            confidence=confidence,
            intent="not_xdr",
            description="xDR 조사와 무관한 질문",
            sql="",
        )

    # Stage 2: LLM SQL generation
    from app.services.llm import chat as llm_chat

    taxonomy = await _load_field_taxonomy(db, fields, schema_id=schema_id)
    meta = _normalize_dataset_meta(dataset_id, dataset_meta)
    schema_hint = _build_schema_hint(taxonomy)
    inactive_hint = _build_inactive_hint(taxonomy)
    semantic_rules = _build_semantic_rules(taxonomy)
    table = quote_identifier(meta.physical_table_name)

    system_prompt = f"""당신은 텔레콤 xDR 데이터 분석 전문가입니다.
사용자 질문을 DuckDB SQL로 변환하세요.

Logical dataset name: {meta.dataset_name}
Physical table name: {table}
주요 컬럼:
{schema_hint}

알려진 비활성 컬럼(존재 인지만 하고 우선 사용하지 않음):
{inactive_hint}

규칙:
{semantic_rules}
- active=true 컬럼을 우선 사용
- FROM/JOIN에는 반드시 Physical table name만 사용할 것: {table}
- dataset_id 또는 logical dataset name을 FROM/JOIN에 직접 사용하지 말 것
- 각 컬럼의 db_type을 기준으로 literal을 생성할 것
- db_type=TEXT/VARCHAR/STRING 컬럼 비교값은 반드시 작은따옴표로 감쌀 것. 예: success_flag = '0'
- LIKE 조건은 문자열 literal만 사용. 예: IMSI LIKE '%123%'
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
        plan_data = None
        for match in re.finditer(r'\{.*?\}', response, re.DOTALL):
            raw = match.group()
            try:
                plan_data = json.loads(raw)
                break
            except json.JSONDecodeError:
                try:
                    cleaned = re.sub(r'(?<!\\)\\(?!["\\bfnrtu/\n\r\t])', r'\\\\', raw)
                    plan_data = json.loads(cleaned)
                    break
                except json.JSONDecodeError:
                    continue

        if plan_data is None or plan_data.get("intent") == "not_xdr":
            return QueryPlan(
                is_xdr_related=False,
                confidence=0.9,
                intent="not_xdr",
                description="LLM이 xDR 조사와 무관하다고 판단",
                sql="",
            )

        sql = plan_data.get("sql", "").strip()
        if not sql or not sql.upper().startswith("SELECT"):
            return QueryPlan(
                is_xdr_related=False,
                confidence=0.5,
                intent="not_xdr",
                description="유효한 SQL 생성 실패",
                sql="",
            )

        sql = normalize_generated_sql(sql, dataset_meta=meta, taxonomy=taxonomy)

        return QueryPlan(
            is_xdr_related=True,
            confidence=confidence,
            intent=plan_data.get("intent", "unknown"),
            description=plan_data.get("description", ""),
            sql=sql,
        )

    except Exception as exc:
        logger.warning("Query planning LLM 실패: %s", exc)
        return QueryPlan(
            is_xdr_related=False,
            confidence=0.0,
            intent="not_xdr",
            description=f"LLM 호출 실패: {exc}",
            sql="",
        )


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
