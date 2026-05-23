# xDR Schema Registry

## Purpose

The xDR schema registry is the semantic metadata layer for LTE xDR fields.
It is separate from DuckDB physical storage.

The registry provides the planner with:

- `field_name`
- `db_type`
- `aliases`
- `category`
- `role`
- capabilities such as `groupable`, `filterable`, `time_series`

## Physical Type vs Semantic Type

DuckDB physical storage may store fields as permissive TEXT.
The schema registry still preserves semantic field information for planning.

| Layer | Meaning |
|---|---|
| Physical storage type | Actual DuckDB column storage strategy, currently TEXT-oriented |
| Planner `db_type` | SQL literal generation type used by the planner |
| Semantic type | Domain/spec type such as `uint`, `timeval`, `VARCHAR2` |

Planner SQL literal generation must use the planner `db_type`.
For current xDR datasets, this is storage-safe TEXT unless a field is explicitly
exposed as another SQL-safe planner type.

## Schema-Aware SQL Generation

All SQL literals must be generated using schema metadata.

Examples:

```sql
-- TEXT
success_flag = '0'

-- TEXT search
IMSI LIKE '%123%'

-- INTEGER
retry_count = 3

-- BOOLEAN
enabled = true
```

The planner must never infer literal type from the natural language query alone.
It must not assume that a numeric-looking value should be emitted as a numeric
literal unless the field metadata says that is safe.

## Candidate Field Selection

Chat runtime performs lightweight activation before planner execution.

It selects candidate fields using:

- field name
- aliases
- category
- role
- description
- small query synonym expansion

Only selected candidate fields are passed into the planner. This prevents planner
context explosion while keeping the schema-aware metadata needed for SQL generation.
