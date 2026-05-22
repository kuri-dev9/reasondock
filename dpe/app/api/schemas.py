from pydantic import BaseModel, Field


class ProcessOptions(BaseModel):
    normalization_enabled: bool = False
    normalization_model: str | None = None
    backend_normalize_url: str = "http://backend:8000/api/normalize"


class ProcessRequest(BaseModel):
    document_id: str
    filename: str
    content: str = ""
    options: ProcessOptions = Field(default_factory=ProcessOptions)


class DocumentProcessResult(BaseModel):
    document_id: str
    normalized_content: str
    structure_type: str
    structure_confidence: float
    chunk_strategy: str
    normalization_applied: bool
    normalization_model: str | None
    normalization_skipped_reason: str | None = None
    retrieval_hints: list[str]
    metadata_version: int = 1
    content_type: str = "text"
    denoised_content: str | None = None
