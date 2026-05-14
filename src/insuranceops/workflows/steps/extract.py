"""Extract step handler: runs the configured extractor on document content.

Integrates the AI ingestion pipeline for OCR and optional AI enhancement
while preserving the deterministic StubExtractor as the primary extraction
path. AI enhancement is additive and fail-safe.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.ai.execution_metadata import AIExecutionMetadata, aggregate_step_metadata
from insuranceops.ai.mock_provider import MockAIProvider, MockOCRProvider
from insuranceops.ai.providers import OCRResult
from insuranceops.observability.logging import get_logger
from insuranceops.storage.payloads.local import LocalPayloadStore
from insuranceops.storage.repositories.documents import DocumentRepository
from insuranceops.workflows.extractors.stub import StubExtractor
from insuranceops.workflows.steps.base import StepContext, StepResult

logger = get_logger("workflow.steps.extract")

# Content types that benefit from OCR preprocessing
_OCR_CONTENT_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg", "image/tiff"})


class ExtractStepHandler:
    """Loads document content and runs the configured Extractor.

    Integrates AI capabilities:
    - OCR for PDF/image documents (via OCRProvider)
    - Optional AI enhancement for low-confidence fields
    - Execution metadata tracking for audit trail

    Stores the ExtractionResult as output and returns succeeded
    or failed_retryable/failed_terminal based on extractor outcome.
    """

    def __init__(self, payload_store_path: str = "/data/payloads") -> None:
        self._extractor = StubExtractor()
        self._payload_store = LocalPayloadStore(payload_store_path)
        self._ocr_provider = MockOCRProvider()
        self._ai_provider = MockAIProvider()

    async def handle(self, context: StepContext, session: AsyncSession) -> StepResult:
        """Extract structured data from documents with AI assistance.

        Args:
            context: Step context with document_ids and previous outputs.
            session: Active database session.

        Returns:
            StepResult with extraction output on success, or error on failure.
        """
        doc_repo = DocumentRepository(session)
        ai_executions: list[AIExecutionMetadata] = []

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

            # OCR preprocessing for binary document types
            ocr_result: OCRResult | None = None
            effective_content = content
            effective_content_type = doc.content_type

            if doc.content_type in _OCR_CONTENT_TYPES:
                ocr_start = time.perf_counter()
                try:
                    ocr_result = await self._ocr_provider.extract_text(content, doc.content_type)
                    effective_content = ocr_result.full_text.encode("utf-8")
                    effective_content_type = "text/plain"

                    ai_executions.append(
                        AIExecutionMetadata(
                            execution_id=uuid.uuid4(),
                            workflow_run_id=context.workflow_run_id,
                            step_name=context.step_name,
                            operation_type="ocr",
                            provider_name=self._ocr_provider.name,
                            model="ocr",
                            prompt_version="n/a",
                            input_hash=hashlib.sha256(content).hexdigest()[:16],
                            confidence=min((p.confidence for p in ocr_result.pages), default=1.0),
                            latency_ms=(time.perf_counter() - ocr_start) * 1000,
                        )
                    )
                    logger.info(
                        "extract_ocr_complete",
                        document_id=str(doc_id),
                        pages=ocr_result.total_pages,
                    )
                except Exception as e:
                    # Fail-safe: if OCR fails, try extracting from raw bytes
                    logger.warning(
                        "extract_ocr_failed_fallback",
                        document_id=str(doc_id),
                        error=str(e),
                    )

            # Run the deterministic extractor
            try:
                extraction_result = self._extractor.extract(
                    content=effective_content,
                    content_type=effective_content_type,
                    metadata=doc.metadata_ if hasattr(doc, "metadata_") else {},
                )
            except Exception as e:
                return StepResult(
                    status="failed_retryable",
                    error_code="EXTRACTION_ERROR",
                    error_detail=f"Extractor failed for document {doc_id}: {e}",
                )

            # Track extraction execution metadata
            ai_executions.append(
                AIExecutionMetadata(
                    execution_id=uuid.uuid4(),
                    workflow_run_id=context.workflow_run_id,
                    step_name=context.step_name,
                    operation_type="extraction",
                    provider_name=self._extractor.name,
                    model=self._extractor.name,
                    prompt_version=self._extractor.version,
                    input_hash=hashlib.sha256(effective_content).hexdigest()[:16],
                    output_hash=hashlib.sha256(
                        str(sorted(extraction_result.fields.keys())).encode()
                    ).hexdigest()[:16],
                    confidence=min(
                        (f.confidence for f in extraction_result.fields.values()),
                        default=0.0,
                    ),
                    latency_ms=0.0,
                )
            )

            # Optional AI enhancement for low-confidence extractions
            min_confidence = min(
                (f.confidence for f in extraction_result.fields.values()), default=0.0
            )
            if min_confidence < 0.8 or len(extraction_result.fields) < 3:
                ai_start = time.perf_counter()
                try:
                    prompt = (
                        f"Verify extraction from insurance document. "
                        f"Fields: {list(extraction_result.fields.keys())}. "
                        f"Min confidence: {min_confidence:.2f}"
                    )
                    ai_response = await self._ai_provider.generate(
                        prompt, temperature=0.0, max_tokens=256
                    )
                    ai_executions.append(
                        AIExecutionMetadata(
                            execution_id=uuid.uuid4(),
                            workflow_run_id=context.workflow_run_id,
                            step_name=context.step_name,
                            operation_type="ai_enhancement",
                            provider_name=self._ai_provider.name,
                            model=ai_response.model,
                            prompt_version=ai_response.prompt_version,
                            latency_ms=(time.perf_counter() - ai_start) * 1000,
                            token_usage=ai_response.usage,
                        )
                    )
                except Exception as e:
                    # Fail-safe: AI enhancement failure does not block extraction
                    logger.warning(
                        "extract_ai_enhancement_failed",
                        document_id=str(doc_id),
                        error=str(e),
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

        # Aggregate AI execution metadata
        step_metadata = aggregate_step_metadata(context.step_attempt_id, ai_executions)

        output: dict[str, Any] = {
            "fields": all_fields,
            "extractor_name": self._extractor.name,
            "extractor_version": self._extractor.version,
            "ai_metadata": step_metadata.to_output_ref()["ai_metadata"],
        }

        return StepResult(
            status="succeeded",
            output=output,
        )
