"""Document repository."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.storage.models import DocumentModel


class DocumentRepository:
    """Repository for Document CRUD operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, document_id: UUID) -> DocumentModel | None:
        """Get a document by its ID."""
        result = await self._session.execute(
            select(DocumentModel).where(DocumentModel.document_id == document_id)
        )
        return result.scalar_one_or_none()

    async def get_by_content_hash(self, content_hash: bytes) -> Sequence[DocumentModel]:
        """Get documents matching a content hash."""
        result = await self._session.execute(
            select(DocumentModel).where(DocumentModel.content_hash == content_hash)
        )
        return result.scalars().all()

    async def create(self, model: DocumentModel) -> DocumentModel:
        """Insert a new document."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def list_recent(self, limit: int = 50, offset: int = 0) -> Sequence[DocumentModel]:
        """List documents ordered by ingestion time descending."""
        result = await self._session.execute(
            select(DocumentModel)
            .order_by(DocumentModel.ingested_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()
