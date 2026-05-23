"""DuckDB storage layer for xDR datasets.

All functions here are synchronous — DuckDB does not support async.
Call from async context via asyncio.to_thread().
DuckDB connections must only be created in this module.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import duckdb

from app.rca.spec_loader import FieldSpec


_DB_PATH = Path("/app/rca_datasets/rca_datasets.duckdb")
_SCHEMA_INIT = """
CREATE TABLE IF NOT EXISTS rca_dataset_meta (
    dataset_id      VARCHAR PRIMARY KEY,
    dataset_name    VARCHAR,
    physical_table_name VARCHAR,
    job_id          INTEGER,
    conversation_id INTEGER,
    filename        VARCHAR,
    file_size       BIGINT,
    record_count    INTEGER,
    parsed_records  INTEGER,
    period_start    BIGINT,
    period_end      BIGINT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status          VARCHAR DEFAULT 'READY'
);

CREATE TABLE IF NOT EXISTS rca_summary (
    dataset_id  VARCHAR PRIMARY KEY,
    summary_json JSON,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _get_connection() -> duckdb.DuckDBPyConnection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(_DB_PATH))
    conn.execute(_SCHEMA_INIT)
    _ensure_meta_columns(conn)
    return conn


def _ensure_meta_columns(conn: duckdb.DuckDBPyConnection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info('rca_dataset_meta')").fetchall()
    }
    if "dataset_name" not in existing:
        conn.execute("ALTER TABLE rca_dataset_meta ADD COLUMN dataset_name VARCHAR")
    if "physical_table_name" not in existing:
        conn.execute("ALTER TABLE rca_dataset_meta ADD COLUMN physical_table_name VARCHAR")
    conn.execute(
        """
        UPDATE rca_dataset_meta
        SET dataset_name = dataset_id
        WHERE dataset_name IS NULL
        """
    )
    rows = conn.execute(
        "SELECT dataset_id FROM rca_dataset_meta WHERE physical_table_name IS NULL"
    ).fetchall()
    for (dataset_id,) in rows:
        conn.execute(
            "UPDATE rca_dataset_meta SET physical_table_name = ? WHERE dataset_id = ?",
            [physical_table_name_for_dataset(dataset_id), dataset_id],
        )


def make_dataset_id(filename: str) -> str:
    base = Path(filename).stem
    return re.sub(r"[^a-zA-Z0-9_]", "_", base)


def _table_name(dataset_id: str) -> str:
    return physical_table_name_for_dataset(dataset_id)


def physical_table_name_for_dataset(dataset_id: str) -> str:
    return f"xdr_{dataset_id}"


def _col_type(field: FieldSpec) -> str:
    return "VARCHAR"


def create_xdr_table(dataset_id: str, fields: tuple[FieldSpec, ...]) -> None:
    col_defs = ",\n    ".join(f'"{f.name}" {_col_type(f)}' for f in fields)
    table = _table_name(dataset_id)
    with _get_connection() as conn:
        # 기존 테이블 DROP 후 재생성 (재업로드 시 중복 방지)
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(f'CREATE TABLE "{table}" (\n    {col_defs}\n)')


def insert_records(dataset_id: str, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    table = _table_name(dataset_id)
    cols = list(records[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(f'"{c}"' for c in cols)
    sql = f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders})'
    rows = [[r.get(c) for c in cols] for r in records]
    with _get_connection() as conn:
        conn.executemany(sql, rows)
    return len(rows)


def store_meta(
    dataset_id: str,
    *,
    job_id: int | None,
    conversation_id: int | None,
    filename: str,
    file_size: int,
    record_count: int,
    parsed_records: int,
    period_start: int | None,
    period_end: int | None,
) -> None:
    sql = """
    INSERT INTO rca_dataset_meta
        (dataset_id, dataset_name, physical_table_name, job_id, conversation_id, filename, file_size,
         record_count, parsed_records, period_start, period_end, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'READY')
    ON CONFLICT (dataset_id) DO UPDATE SET
        dataset_name = excluded.dataset_name,
        physical_table_name = excluded.physical_table_name,
        job_id = excluded.job_id,
        conversation_id = excluded.conversation_id,
        filename = excluded.filename,
        file_size = excluded.file_size,
        record_count = excluded.record_count,
        parsed_records = excluded.parsed_records,
        period_start = excluded.period_start,
        period_end = excluded.period_end,
        status = 'READY'
    """
    with _get_connection() as conn:
        conn.execute(
            sql,
            [
                dataset_id, dataset_id, physical_table_name_for_dataset(dataset_id),
                job_id, conversation_id, filename, file_size,
                record_count, parsed_records, period_start, period_end,
            ],
        )


def store_summary(dataset_id: str, summary: dict) -> None:
    sql = """
    INSERT INTO rca_summary (dataset_id, summary_json)
    VALUES (?, ?)
    ON CONFLICT (dataset_id) DO UPDATE SET
        summary_json = excluded.summary_json
    """
    with _get_connection() as conn:
        conn.execute(sql, [dataset_id, json.dumps(summary, ensure_ascii=False)])


def get_summary(dataset_id: str) -> dict | None:
    with _get_connection() as conn:
        row = conn.execute(
            "SELECT summary_json FROM rca_summary WHERE dataset_id = ?", [dataset_id]
        ).fetchone()
    if row is None:
        return None
    raw = row[0]
    return json.loads(raw) if isinstance(raw, str) else raw


def query(dataset_id: str, sql: str, limit: int = 1000) -> list[dict]:
    with _get_connection() as conn:
        rel = conn.execute(sql)
        cols = [desc[0] for desc in rel.description]
        rows = rel.fetchmany(limit)
    return [dict(zip(cols, row)) for row in rows]


# alias for external callers expecting query_records
query_records = query


def delete_dataset(dataset_id: str) -> None:
    table = _table_name(dataset_id)
    with _get_connection() as conn:
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute("DELETE FROM rca_dataset_meta WHERE dataset_id = ?", [dataset_id])
        conn.execute("DELETE FROM rca_summary WHERE dataset_id = ?", [dataset_id])


def list_datasets(conversation_id: int | None = None) -> list[dict]:
    sql = "SELECT * FROM rca_dataset_meta"
    params: list = []
    if conversation_id is not None:
        sql += " WHERE conversation_id = ?"
        params.append(conversation_id)
    sql += " ORDER BY created_at DESC"
    with _get_connection() as conn:
        rel = conn.execute(sql, params)
        cols = [desc[0] for desc in rel.description]
        rows = rel.fetchall()
    return [dict(zip(cols, row)) for row in rows]


def get_meta(dataset_id: str) -> dict | None:
    with _get_connection() as conn:
        rel = conn.execute(
            "SELECT * FROM rca_dataset_meta WHERE dataset_id = ?", [dataset_id]
        )
        cols = [desc[0] for desc in rel.description]
        row = rel.fetchone()
    if row is None:
        return None
    return dict(zip(cols, row))
