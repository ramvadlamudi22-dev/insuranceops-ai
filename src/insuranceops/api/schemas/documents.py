"""Document schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    """Response model for a document."""

    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    content_hash: str  # hex-encoded
    size_bytes: int
    content_type: str
    ingested_at: datetime


class DocumentIngestResponse(BaseModel):
    """Response model for document ingestion."""

    document_id: UUID
    content_hash: str
    size_bytes: int
    content_type: str
    ingested_at: datetime
    is_duplicate: bool = False
