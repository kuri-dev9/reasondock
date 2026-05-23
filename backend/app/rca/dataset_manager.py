"""Async wrappers around duckdb_store for dataset lifecycle management.

All heavy DuckDB work is dispatched via asyncio.to_thread() so it never
blocks the FastAPI event loop.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.rca import duckdb_store
from app.rca.spec_loader import FieldSpec

logger = logging.getLogger(__name__)


async def create_dataset(
    *,
    dataset_id: str,
    job_id: int | None,
    conversation_id: int | None,
    filename: str,
    file_size: int,
    records: list[dict[str, Any]],
    fields: tuple[FieldSpec, ...],
    period_start: int | None = None,
    period_end: int | None = None,
) -> str:
    """Store parsed xDR records in DuckDB and return the dataset_id."""

    def _sync():
        duckdb_store.create_xdr_table(dataset_id, fields)
        inserted = duckdb_store.insert_records(dataset_id, records)
        duckdb_store.store_meta(
            dataset_id,
            job_id=job_id,
            conversation_id=conversation_id,
            filename=filename,
            file_size=file_size,
            record_count=len(records),
            parsed_records=inserted,
            period_start=period_start,
            period_end=period_end,
        )
        return inserted

    inserted = await asyncio.to_thread(_sync)
    logger.info("Dataset %s stored — %d records", dataset_id, inserted)
    return dataset_id


async def store_summary(dataset_id: str, summary: dict) -> None:
    await asyncio.to_thread(duckdb_store.store_summary, dataset_id, summary)


async def get_dataset_info(dataset_id: str) -> dict | None:
    return await asyncio.to_thread(duckdb_store.get_meta, dataset_id)


async def get_summary(dataset_id: str) -> dict | None:
    return await asyncio.to_thread(duckdb_store.get_summary, dataset_id)


async def list_datasets(conversation_id: int | None = None) -> list[dict]:
    return await asyncio.to_thread(duckdb_store.list_datasets, conversation_id)


async def delete_dataset(dataset_id: str) -> None:
    await asyncio.to_thread(duckdb_store.delete_dataset, dataset_id)
    logger.info("Dataset %s deleted from DuckDB", dataset_id)


async def query_dataset(dataset_id: str, sql: str, limit: int = 1000) -> list[dict]:
    return await asyncio.to_thread(duckdb_store.query, dataset_id, sql, limit)
