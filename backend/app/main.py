from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

from app.database import engine, Base
from app.routes import conversations, chat, models, attachments, knowledge, rca, normalize, xdr_schema


async def _ensure_longtext_columns(conn):
    if conn.dialect.name != "mysql":
        return
    statements = [
        "ALTER TABLE messages MODIFY content LONGTEXT NOT NULL",
        "ALTER TABLE attachments MODIFY content_text LONGTEXT NOT NULL",
        "ALTER TABLE knowledge_documents MODIFY summary LONGTEXT NULL",
        "ALTER TABLE knowledge_documents MODIFY error_message LONGTEXT NULL",
        "ALTER TABLE rca_jobs MODIFY error_message LONGTEXT NULL",
        "ALTER TABLE rca_results MODIFY llm_response LONGTEXT NULL",
    ]
    for statement in statements:
        await conn.execute(text(statement))
    try:
        await conn.execute(text("ALTER TABLE messages ADD COLUMN metrics JSON NULL"))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN dpe_metadata JSON NULL"))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN normalized_content LONGTEXT NULL"))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text("ALTER TABLE knowledge_documents MODIFY normalized_content LONGTEXT NULL"))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN uce_denoised_content LONGTEXT NULL AFTER normalized_content"))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text("ALTER TABLE knowledge_documents ADD COLUMN dpe_ir_status VARCHAR(20) NULL DEFAULT 'RAW_ONLY' AFTER uce_denoised_content"))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text("ALTER TABLE rca_datasets MODIFY period_start BIGINT NULL"))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text("ALTER TABLE rca_datasets MODIFY period_end BIGINT NULL"))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text("ALTER TABLE rca_jobs ADD COLUMN schema_id INT NULL"))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text("ALTER TABLE rca_datasets ADD COLUMN schema_id INT NULL"))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text("ALTER TABLE xdr_field_schema ADD COLUMN schema_id INT NULL"))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text(
            "INSERT INTO xdr_schema_profiles (name, description, is_default, is_active) "
            "SELECT '기본 xDR 스키마', 'spec 기반 기본 xDR field taxonomy', 1, 1 "
            "WHERE NOT EXISTS (SELECT 1 FROM xdr_schema_profiles)"
        ))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text(
            "UPDATE xdr_field_schema "
            "SET schema_id = (SELECT id FROM xdr_schema_profiles ORDER BY is_default DESC, id ASC LIMIT 1) "
            "WHERE schema_id IS NULL"
        ))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text("ALTER TABLE xdr_field_schema DROP INDEX field_name"))
    except SQLAlchemyError:
        pass
    try:
        await conn.execute(text(
            "ALTER TABLE xdr_field_schema "
            "ADD CONSTRAINT uq_xdr_schema_field_name UNIQUE (schema_id, field_name)"
        ))
    except SQLAlchemyError:
        pass
    xdr_field_columns = [
        ("spec_no", "INT NULL"),
        ("spec_index", "INT NULL"),
        ("spec_sheet", "VARCHAR(100) NULL"),
        ("spec_section", "VARCHAR(100) NULL"),
        ("tree_path", "JSON NULL"),
        ("category", "VARCHAR(100) NULL"),
        ("role", "VARCHAR(80) NULL"),
        ("db_type", "VARCHAR(50) NULL"),
        ("size", "INT NULL"),
        ("importance", "VARCHAR(20) NOT NULL DEFAULT 'low'"),
        ("groupable", "BOOL NOT NULL DEFAULT 0"),
        ("filterable", "BOOL NOT NULL DEFAULT 0"),
        ("searchable", "BOOL NOT NULL DEFAULT 0"),
        ("joinable", "BOOL NOT NULL DEFAULT 0"),
        ("pii", "BOOL NOT NULL DEFAULT 0"),
        ("sortable", "BOOL NOT NULL DEFAULT 0"),
        ("time_series", "BOOL NOT NULL DEFAULT 0"),
        ("categorical", "BOOL NOT NULL DEFAULT 0"),
        ("boolean_like", "BOOL NOT NULL DEFAULT 0"),
        ("semantic_metadata", "JSON NULL"),
    ]
    for column_name, column_type in xdr_field_columns:
        try:
            await conn.execute(text(f"ALTER TABLE xdr_field_schema ADD COLUMN {column_name} {column_type}"))
        except SQLAlchemyError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_longtext_columns(conn)
    yield
    await engine.dispose()


app = FastAPI(title="Chat Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(models.router)
app.include_router(attachments.router)
app.include_router(knowledge.router)
app.include_router(rca.router)
app.include_router(normalize.router)
app.include_router(xdr_schema.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
