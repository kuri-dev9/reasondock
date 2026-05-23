# Query Planner

## Goal

The xDR query planner converts a natural language investigation request into
DuckDB SQL. It must be schema-aware and storage-safe.

It is not allowed to treat LLM SQL as trusted SQL text.

## Planner Execution Flow

1. Resolve active dataset from the conversation binding.
2. Load dataset metadata:
   - `dataset_id`
   - `dataset_name`
   - `physical_table_name`
3. Select candidate schema fields at runtime.
4. Load field taxonomy for those candidate fields only.
5. Build a compact planner prompt containing:
   - physical table name
   - field names
   - planner `db_type`
   - semantic type
   - aliases
   - category
   - role
6. Generate SQL via LLM through `app/services/llm.py`.
7. Normalize generated SQL:
   - replace logical table references with `physical_table_name`
   - normalize literals according to field `db_type`
8. Execute the final SQL through `duckdb_store.query()`.
9. Return bounded query result rows to the chat/UCE context.

## Dataset Naming Rule

The planner receives both logical and physical dataset metadata.

```text
dataset_name          = LTE_CALL_KPI_R1_20260518_1100
physical_table_name   = xdr_LTE_CALL_KPI_R1_20260518_1100
```

Planner SQL must always use:

```sql
FROM "xdr_LTE_CALL_KPI_R1_20260518_1100"
```

Planner SQL must never use:

```sql
FROM LTE_CALL_KPI_R1_20260518_1100
```

## Schema-Aware Literal Rule

All literals are generated from field metadata.

The planner prompt explicitly instructs:

- `db_type=TEXT` values must be quoted.
- `LIKE` values must be string literals.
- numeric literals are allowed only when metadata exposes the field as numeric.
- boolean literals are allowed only when metadata exposes the field as boolean.

Post-processing also applies schema-aware normalization for common LLM mistakes,
for example:

```sql
success_flag = 0
```

becomes:

```sql
success_flag = '0'
```

when `success_flag` has planner `db_type=TEXT`.

## Rule-Based Fallback

Rule fallback SQL uses the same planner helpers as LLM-generated SQL.
It must not hand-build SQL with logical dataset names or untyped literals.

Fallback SQL must:

- quote the physical table name
- quote identifiers
- generate WHERE literals through schema-aware literal helpers
- include `LIMIT`

## Debug Output

The chat debug panel must expose:

- active dataset id
- dataset name
- physical table name
- selected schema fields
- field db_types
- generated SQL
- query execution result count
- raw query result preview
