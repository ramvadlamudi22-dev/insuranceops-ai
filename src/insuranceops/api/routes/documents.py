"""Document routes."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.api.deps import get_db_session
from insuranceops.api.schemas.documents import DocumentIngestResponse
from insuranceops.security.auth import ApiKeyPrincipal
from insuranceops.security.rbac import requires_role
from insuranceops.storage.models import DocumentModel
from insuranceops.storage.repositories.documents import DocumentRepository

router = APIRouter(prefix="/v1/documents", tags=["documents"])


@router.post(
    "",
    response_model=DocumentIngestResponse,
    status_code=201,
)
async def ingest_document(
    request: Request,
    file: UploadFile,
    session: AsyncSession = Depends(get_db_session),
    principal: ApiKeyPrincipal = Depends(requires_role("operator", "supervisor")),
) -> DocumentIngestResponse:
    """Upload a document via multipart form, compute content_hash, store payload."""
    content = await file.read()
    content_hash = hashlib.sha256(content).digest()
    size_bytes = len(content)
    content_type = file.content_type or "application/octet-stream"
    document_id = uuid.uuid4()
    now = datetime.now(UTC)

    # Store payload via the payload store
    from insuranceops.storage.payloads.local import LocalPayloadStore

    settings = request.app.state.settings
    payload_store = LocalPayloadStore(settings.PAYLOAD_STORAGE_PATH)
    payload_ref = payload_store.write(content_hash, content)

    # Check for duplicate by content_hash
    repo = DocumentRepository(session)
    existing = await repo.get_by_content_hash(content_hash)
    is_duplicate = len(existing) > 0

    model = DocumentModel(
        document_id=document_id,
        content_hash=content_hash,
        content_type=content_type,
        size_bytes=size_bytes,
        payload_ref=payload_ref,
        ingested_at=now,
        ingested_by=principal.actor_string,
        api_key_id=uuid.UUID(principal.api_key_id),
    )
    await repo.create(model)

    return DocumentIngestResponse(
        document_id=document_id,
        content_hash=content_hash.hex(),
        size_bytes=size_bytes,
        content_type=content_type,
        ingested_at=now,
        is_duplicate=is_duplicate,
    )


@router.get(
    "/{document_id}/content",
)
async def get_document_content(
    request: Request,
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    principal: ApiKeyPrincipal = Depends(requires_role("operator", "supervisor")),
) -> Response:
    """Return raw document bytes with correct Content-Type."""
    repo = DocumentRepository(session)
    doc = await repo.get_by_id(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    from insuranceops.storage.payloads.local import LocalPayloadStore

    settings = request.app.state.settings
    payload_store = LocalPayloadStore(settings.PAYLOAD_STORAGE_PATH)
    content = payload_store.read(doc.payload_ref)

    return Response(
        content=content,
        media_type=doc.content_type,
    )
