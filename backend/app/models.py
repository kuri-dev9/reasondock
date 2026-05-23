from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, DateTime, ForeignKey, JSON, UniqueConstraint, func
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.database import Base


LONG_TEXT = Text().with_variant(LONGTEXT, "mysql")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), default="새 대화")
    model: Mapped[str] = mapped_column(String(100), default=lambda: settings.default_ollama_model)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    rca_jobs: Mapped[list["RcaJob"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))  # user, assistant
    content: Mapped[str] = mapped_column(LONG_TEXT)
    references: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    metrics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_text: Mapped[str] = mapped_column(LONG_TEXT)
    file_size: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="attachments")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(default=0)
    chunk_count: Mapped[int] = mapped_column(default=0)
    summary: Mapped[Optional[str]] = mapped_column(LONG_TEXT, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="processing")  # processing, ready, error
    error_message: Mapped[Optional[str]] = mapped_column(LONG_TEXT, nullable=True)
    dpe_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    normalized_content: Mapped[Optional[str]] = mapped_column(LONG_TEXT, nullable=True)
    uce_denoised_content: Mapped[Optional[str]] = mapped_column(LONG_TEXT, nullable=True)
    dpe_ir_status: Mapped[str] = mapped_column(String(20), default="RAW_ONLY")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RcaJob(Base):
    __tablename__ = "rca_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(default=0)
    file_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[int] = mapped_column(default=0)
    current_step: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(LONG_TEXT, nullable=True)
    result_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_records: Mapped[Optional[int]] = mapped_column(nullable=True)
    parsed_records: Mapped[Optional[int]] = mapped_column(nullable=True)
    schema_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="rca_jobs")
    result: Mapped[Optional["RcaResult"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class RcaResult(Base):
    __tablename__ = "rca_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("rca_jobs.id", ondelete="CASCADE"))
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    summary_json: Mapped[dict] = mapped_column(JSON)
    llm_response: Mapped[Optional[str]] = mapped_column(LONG_TEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    job: Mapped["RcaJob"] = relationship(back_populates="result")


class ConversationDataset(Base):
    """Many-to-many attachment between conversations and xDR datasets.

    Detaching removes this row only — the dataset itself is preserved.
    """
    __tablename__ = "conversation_datasets"
    __table_args__ = (UniqueConstraint("conversation_id", "dataset_id", name="uq_conv_dataset"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    dataset_id: Mapped[str] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(default=True)
    attached_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RcaDataset(Base):
    __tablename__ = "rca_datasets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(255), unique=True)
    job_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int] = mapped_column(default=0)
    record_count: Mapped[int] = mapped_column(default=0)
    parsed_records: Mapped[int] = mapped_column(default=0)
    period_start: Mapped[Optional[int]] = mapped_column(nullable=True)
    period_end: Mapped[Optional[int]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="PROCESSING")
    error_message: Mapped[Optional[str]] = mapped_column(LONG_TEXT, nullable=True)
    schema_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class XdrSchemaProfile(Base):
    __tablename__ = "xdr_schema_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_default: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    fields: Mapped[list["XdrFieldSchema"]] = relationship(
        back_populates="schema",
        cascade="all, delete-orphan",
    )


class XdrFieldSchema(Base):
    __tablename__ = "xdr_field_schema"
    __table_args__ = (
        UniqueConstraint("schema_id", "field_name", name="uq_xdr_schema_field_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    schema_id: Mapped[int] = mapped_column(ForeignKey("xdr_schema_profiles.id", ondelete="CASCADE"))
    field_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    is_custom: Mapped[bool] = mapped_column(default=False)
    spec_no: Mapped[Optional[int]] = mapped_column(nullable=True)
    spec_index: Mapped[Optional[int]] = mapped_column(nullable=True)
    spec_sheet: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    spec_section: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tree_path: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    db_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    size: Mapped[Optional[int]] = mapped_column(nullable=True)
    importance: Mapped[str] = mapped_column(String(20), default="low")
    groupable: Mapped[bool] = mapped_column(default=False)
    filterable: Mapped[bool] = mapped_column(default=False)
    searchable: Mapped[bool] = mapped_column(default=False)
    joinable: Mapped[bool] = mapped_column(default=False)
    pii: Mapped[bool] = mapped_column(default=False)
    sortable: Mapped[bool] = mapped_column(default=False)
    time_series: Mapped[bool] = mapped_column(default=False)
    categorical: Mapped[bool] = mapped_column(default=False)
    boolean_like: Mapped[bool] = mapped_column(default=False)
    semantic_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    schema: Mapped["XdrSchemaProfile"] = relationship(back_populates="fields")
    keywords: Mapped[list["XdrFieldKeyword"]] = relationship(
        back_populates="field",
        cascade="all, delete-orphan",
    )


class XdrFieldKeyword(Base):
    __tablename__ = "xdr_field_keywords"
    __table_args__ = (
        UniqueConstraint("field_id", "keyword", name="uq_field_keyword"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("xdr_field_schema.id", ondelete="CASCADE"))
    keyword: Mapped[str] = mapped_column(String(100))

    field: Mapped["XdrFieldSchema"] = relationship(back_populates="keywords")
