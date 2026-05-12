"""Extractor protocol and data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass(frozen=True, slots=True)
class Provenance:
    """Source location of an extracted field value.

    Attributes:
        page: Page number (if applicable).
        offset_start: Start character offset in the raw text.
        offset_end: End character offset in the raw text.
        text_snippet: The matched text snippet.
    """

    page: Optional[int] = None
    offset_start: Optional[int] = None
    offset_end: Optional[int] = None
    text_snippet: Optional[str] = None


@dataclass(frozen=True, slots=True)
class ExtractionField:
    """A single extracted field with confidence and provenance.

    Attributes:
        name: Field name (e.g., "claim_number").
        value: Extracted value.
        confidence: Confidence score between 0.0 and 1.0.
        provenance: List of source locations for this extraction.
    """

    name: str
    value: Any
    confidence: float
    provenance: list[Provenance] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Result of running an extractor on document content.

    Attributes:
        fields: Mapping of field name to ExtractionField.
        extractor_name: Name of the extractor that produced this result.
        extractor_version: Version of the extractor.
        raw_text: The raw text that was extracted from (if applicable).
    """

    fields: dict[str, ExtractionField]
    extractor_name: str
    extractor_version: str
    raw_text: Optional[str] = None


class Extractor(Protocol):
    """Protocol for document content extractors.

    Extractors are responsible for parsing document content and
    extracting structured fields with confidence scores.
    """

    @property
    def name(self) -> str:
        """Extractor name."""
        ...

    @property
    def version(self) -> str:
        """Extractor version."""
        ...

    def extract(
        self, content: bytes, content_type: str, metadata: dict[str, Any]
    ) -> ExtractionResult:
        """Extract structured fields from document content.

        Args:
            content: Raw document bytes.
            content_type: MIME type of the content.
            metadata: Additional metadata about the document.

        Returns:
            ExtractionResult with extracted fields.
        """
        ...
