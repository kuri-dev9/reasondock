# xDR Pipeline

## Dataset Naming Model

xDR dataset identifiers are separated into logical and physical names.

| Name | Purpose | Example |
|---|---|---|
| `dataset_id` | Stable registry key used by APIs and conversation binding | `LTE_CALL_KPI_R1_20260518_1100` |
| `dataset_name` | UI/UX display identifier. Defaults to `dataset_id` | `LTE_CALL_KPI_R1_20260518_1100` |
| `physical_table_name` | Actual DuckDB table name used in SQL | `xdr_LTE_CALL_KPI_R1_20260518_1100` |

The planner must always use `physical_table_name` in `FROM` and `JOIN` clauses.
It must never use `dataset_id` or `dataset_name` as a SQL table name.

## Data Flow

1. Upload `.dat` xDR file.
2. Generate `dataset_id` from the filename.
3. Create the DuckDB physical table as `physical_table_name = "xdr_" + dataset_id`.
4. Store dataset registry metadata in `rca_dataset_meta`.
5. Store MySQL `RcaDataset` and conversation binding metadata.
6. At chat time, resolve the active dataset from `ConversationDataset`.
7. Load `dataset_name` and `physical_table_name` from DuckDB metadata.
8. Pass `physical_table_name` and selected schema metadata to the query planner.
9. Execute generated SQL against DuckDB.
10. Send only query results, not the full xDR dataset, to the LLM/UCE path.

## DuckDB Storage Strategy

Physical storage is permissive and TEXT-oriented.

This is intentional for telecom xDR data because source records often contain
mixed, blank, vendor-specific, or code-like values. The physical table is optimized
for safe ingestion and later filtering, not for semantic typing.

Semantic schema metadata is maintained separately in the xDR schema registry.
The query planner relies on schema metadata, not DuckDB inferred types.

## Safety Rule

LLM-generated SQL must be storage-safe:

- Use `physical_table_name` for table references.
- Use schema metadata for literal generation.
- Keep query results bounded with `LIMIT`.
- Do not pass whole xDR records to the LLM.
