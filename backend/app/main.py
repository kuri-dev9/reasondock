from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text

from app.database import engine, Base
from app.routes import conversations, chat, models, attachments, knowledge, rca, normalize


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


@app.get("/api/health")
async def health():
    return {"status": "ok"}
