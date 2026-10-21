from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    only_valid: bool = True


class SourceItem(BaseModel):
    document_id: str
    title: str
    chunk_id: str
    page: int | None = None
    section: str | None = None
    score: float
    content: str
    effective_date: str | None = None
    validity: str = "unknown"


class QueryResponse(BaseModel):
    answer: str
    confidence: str
    sources: list[SourceItem]
    elapsed_ms: int
    llm_provider: str


class DocumentResponse(BaseModel):
    id: str
    title: str
    filename: str
    file_type: str
    chunk_count: int
    created_at: datetime
    status: str
    error: str | None = None


class DocumentContentItem(BaseModel):
    id: str
    page: int | None = None
    section: str | None = None
    content: str


class DocumentContentResponse(BaseModel):
    document_id: str
    chunks: list[DocumentContentItem]


class DirectoryIngestResponse(BaseModel):
    processed: int
    succeeded: int
    failed: int
    documents: list[DocumentResponse]
    errors: list[dict[str, Any]]
