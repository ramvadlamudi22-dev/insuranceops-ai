"""Document domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Document:
    """An immutable ingested document artifact."""

    document_id: UUID
    content_hash: bytes
    content_type: str
    size_bytes: int
    payload_ref: str
    ingested_at: datetime
    ingested_by: str

    def __post_init__(self) -> None:
        if len(self.content_hash) != 32:
            raise ValueError(
                f"content_hash must be exactly 32 bytes (SHA-256), got {len(self.content_hash)}"
            )
        if self.size_bytes < 0:
            raise ValueError(f"size_bytes must be non-negative, got {self.size_bytes}")
        if not self.content_type:
            raise ValueError("content_type must not be empty")
        if not self.payload_ref:
            raise ValueError("payload_ref must not be empty")
        if not self.ingested_by:
            raise ValueError("ingested_by must not be empty")
