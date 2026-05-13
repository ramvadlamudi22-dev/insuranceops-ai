"""Extract step handler: runs the configured extractor on document content."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.storage.payloads.local import LocalPayloadStore
from insuranceops.storage.repositories.documents import DocumentRepository
from insuranceops.workflows.extractors.stub import StubExtractor
from insuranceops.workflows.steps.base import StepContext, StepResult


class ExtractStepHandler:
    """Loads document content and runs the configured Extractor.

    Stores the ExtractionResult as output and returns succeeded
    or failed_retryable/failed_terminal based on extractor outcome.
    """

    def __init__(self, payload_store_path: str = "/data/payloads") -> None:
        self._extractor = StubExtractor()
        self._payload_store = LocalPayloadStore(payload_store_path)

    async def handle(self, context: StepContext, session: AsyncSession) -> StepResult:
        """Extract structured data from documents.

        Args:
            context: Step context with document_ids and previous outputs.
            session: Active database session.

        Returns:
            StepResult with extraction output on success, or error on failure.
        """
        doc_repo = DocumentRepository(session)

        all_fields: dict[str, Any] = {}

        for doc_id in context.document_ids:
            doc = await doc_repo.get_by_id(doc_id)
            if doc is None:
                return StepResult(
                    status="failed_terminal",
                    error_code="DOCUMENT_NOT_FOUND",
                    error_detail=f"Document {doc_id} not found during extraction.",
                )

            # Load content from payload store
            try:
                content = self._payload_store.read(doc.payload_ref)
            except FileNotFoundError:
                return StepResult(
                    status="failed_retryable",
                    error_code="PAYLOAD_NOT_FOUND",
                    error_detail=(
                        f"Payload not found for document {doc_id} (ref: {doc.payload_ref})."
                    ),
                )
            except OSError as e:
                return StepResult(
                    status="failed_retryable",
                    error_code="PAYLOAD_READ_ERROR",
                    error_detail=f"Error reading payload for document {doc_id}: {e}",
                )

            # Run the extractor
            try:
                extraction_result = self._extractor.extract(
                    content=content,
                    content_type=doc.content_type,
                    metadata=doc.metadata_ if hasattr(doc, "metadata_") else {},
                )
            except Exception as e:
                return StepResult(
                    status="failed_retryable",
                    error_code="EXTRACTION_ERROR",
                    error_detail=f"Extractor failed for document {doc_id}: {e}",
                )

            # Merge fields from this document
            for field_name, field_value in extraction_result.fields.items():
                all_fields[field_name] = {
                    "name": field_value.name,
                    "value": field_value.value,
                    "confidence": field_value.confidence,
                    "provenance": [
                        {
                            "page": p.page,
                            "offset_start": p.offset_start,
                            "offset_end": p.offset_end,
                            "text_snippet": p.text_snippet,
                        }
                        for p in field_value.provenance
                    ],
                }

        output = {
            "fields": all_fields,
            "extractor_name": self._extractor.name,
            "extractor_version": self._extractor.version,
        }

        return StepResult(
            status="succeeded",
            output=output,
        )
