"""Document ingestion pipeline with AI-assisted extraction.

Orchestrates the document processing flow:
1. Receive document bytes
2. Run OCR if needed (PDF, images)
3. Run structured extraction
4. Compute confidence scores
5. Persist extraction results with metadata

This module does NOT modify the existing document upload API.
It provides the AI-enhanced extraction pipeline that step handlers call.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

from insuranceops.ai.providers import AIProvider, OCRProvider, OCRResult, ProviderResponse
from insuranceops.observability.logging import get_logger
from insuranceops.workflows.extractors.base import ExtractionField, ExtractionResult

logger = get_logger("ai.ingestion")

# Content types that require OCR before text extraction
_OCR_REQUIRED_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/tiff",
    }
)


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Result of the AI-assisted ingestion pipeline.

    Attributes:
        extraction: Structured extraction result (fields, confidence).
        ocr_result: OCR output if OCR was performed, None otherwise.
        ai_enhancement: AI provider response if enhancement was applied.
        content_hash: SHA-256 of the input document bytes.
        pipeline_latency_ms: Total pipeline execution time.
        requires_review: Whether confidence is below threshold.
    """

    extraction: ExtractionResult
    ocr_result: OCRResult | None
    ai_enhancement: ProviderResponse | None
    content_hash: str
    pipeline_latency_ms: float
    requires_review: bool


async def run_ingestion_pipeline(
    content: bytes,
    content_type: str,
    metadata: dict[str, Any],
    *,
    ocr_provider: OCRProvider,
    ai_provider: AIProvider | None = None,
    confidence_threshold: float = 0.8,
    enable_ai_enhancement: bool = True,
) -> IngestionResult:
    """Run the full AI-assisted document ingestion pipeline.

    Steps:
    1. Hash content for deduplication tracking
    2. OCR if content type requires it
    3. Regex-based structured extraction
    4. Optional AI enhancement for low-confidence fields
    5. Determine if manual review is needed

    Args:
        content: Raw document bytes.
        content_type: MIME type of the document.
        metadata: Document metadata dict.
        ocr_provider: OCR provider for text extraction.
        ai_provider: Optional AI provider for field enhancement.
        confidence_threshold: Below this score, flag for review.
        enable_ai_enhancement: Whether to call AI for low-confidence fields.

    Returns:
        IngestionResult with extraction, metadata, and review flag.
    """
    start = time.perf_counter()

    # Step 1: Content hash
    content_hash = hashlib.sha256(content).hexdigest()

    # Step 2: OCR if needed
    ocr_result: OCRResult | None = None
    if content_type in _OCR_REQUIRED_TYPES:
        logger.info("ingestion_ocr_start", content_type=content_type, size_bytes=len(content))
        ocr_result = await ocr_provider.extract_text(content, content_type, metadata=metadata)
        text_content = ocr_result.full_text.encode("utf-8")
        effective_content_type = "text/plain"
        logger.info(
            "ingestion_ocr_complete",
            pages=ocr_result.total_pages,
            latency_ms=round(ocr_result.latency_ms, 1),
        )
    else:
        text_content = content
        effective_content_type = content_type

    # Step 3: Structured extraction (reuse existing stub extractor)
    from insuranceops.workflows.extractors.stub import StubExtractor

    extractor = StubExtractor()
    extraction = extractor.extract(text_content, effective_content_type, metadata)

    # Step 4: AI enhancement for low-confidence or missing fields
    ai_enhancement: ProviderResponse | None = None
    if enable_ai_enhancement and ai_provider is not None:
        low_confidence_fields = [
            f for f in extraction.fields.values() if f.confidence < confidence_threshold
        ]
        if low_confidence_fields or len(extraction.fields) < 3:
            prompt = _build_enhancement_prompt(
                text_content.decode("utf-8", errors="replace"),
                extraction,
                low_confidence_fields,
            )
            ai_enhancement = await ai_provider.generate(
                prompt, model=None, temperature=0.0, max_tokens=512
            )
            logger.info(
                "ingestion_ai_enhancement",
                model=ai_enhancement.model,
                latency_ms=round(ai_enhancement.latency_ms, 1),
            )

    # Step 5: Determine review requirement
    min_confidence = min(
        (f.confidence for f in extraction.fields.values()),
        default=0.0,
    )
    requires_review = min_confidence < confidence_threshold or len(extraction.fields) < 3

    pipeline_latency_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "ingestion_pipeline_complete",
        fields_extracted=len(extraction.fields),
        min_confidence=round(min_confidence, 3),
        requires_review=requires_review,
        latency_ms=round(pipeline_latency_ms, 1),
    )

    return IngestionResult(
        extraction=extraction,
        ocr_result=ocr_result,
        ai_enhancement=ai_enhancement,
        content_hash=content_hash,
        pipeline_latency_ms=pipeline_latency_ms,
        requires_review=requires_review,
    )


def _build_enhancement_prompt(
    text: str,
    extraction: ExtractionResult,
    low_confidence_fields: list[ExtractionField],
) -> str:
    """Build a prompt for AI-enhanced field extraction.

    Args:
        text: Document text content.
        extraction: Current extraction result.
        low_confidence_fields: Fields with confidence below threshold.

    Returns:
        Formatted prompt string for the AI provider.
    """
    existing = "\n".join(
        f"  - {name}: {f.value} (confidence: {f.confidence:.2f})"
        for name, f in extraction.fields.items()
    )

    low_conf = "\n".join(
        f"  - {f.name}: {f.value} (confidence: {f.confidence:.2f})" for f in low_confidence_fields
    )

    return (
        "You are an insurance document extraction assistant.\n"
        "Given the following document text, verify and improve the extracted fields.\n\n"
        f"Document text (first 2000 chars):\n{text[:2000]}\n\n"
        f"Currently extracted fields:\n{existing}\n\n"
        f"Low-confidence fields needing verification:\n{low_conf or '(none)'}\n\n"
        "Expected fields: claim_number, policy_number, claimant_name, "
        "date_of_loss, claim_type, description.\n\n"
        "Return corrections or confirmations for each field."
    )
