"""Stub extractor: deterministic regex-based extraction for Phase 1."""

from __future__ import annotations

import re
from typing import Any

from insuranceops.workflows.extractors.base import (
    ExtractionField,
    ExtractionResult,
    Provenance,
)

# Regex patterns for claim fields
_PATTERNS: dict[str, re.Pattern[str]] = {
    "claim_number": re.compile(r"(?:claim|CLM)[#:\s-]*(\w+)", re.IGNORECASE),
    "policy_number": re.compile(r"(?:policy|POL)[#:\s-]*([A-Z]{2,3}-\d{6,10})", re.IGNORECASE),
    "claimant_name": re.compile(
        r"(?:claimant|insured|name)[:\s]+([A-Za-z\s]{2,50})", re.IGNORECASE
    ),
    "date_of_loss": re.compile(
        r"(?:date of loss|DOL|loss date)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        re.IGNORECASE,
    ),
    "claim_type": re.compile(r"(?:type|claim type)[:\s]+(\w+)", re.IGNORECASE),
}

_CONFIDENCE = 0.95


class StubExtractor:
    """Deterministic regex-based extractor for claim documents.

    Extracts claim fields from text content using predefined regex patterns.
    Same input bytes always produce the same ExtractionResult.
    """

    @property
    def name(self) -> str:
        """Extractor name."""
        return "stub_extractor"

    @property
    def version(self) -> str:
        """Extractor version."""
        return "1.0.0"

    def extract(
        self, content: bytes, content_type: str, metadata: dict[str, Any]
    ) -> ExtractionResult:
        """Extract structured fields from text content using regex patterns.

        Args:
            content: Raw document bytes (decoded as UTF-8).
            content_type: MIME type of the content.
            metadata: Additional metadata about the document.

        Returns:
            ExtractionResult with matched fields. Unmatched fields are omitted.
        """
        text = content.decode("utf-8", errors="replace")
        fields: dict[str, ExtractionField] = {}

        for field_name, pattern in _PATTERNS.items():
            match = pattern.search(text)
            if match is not None:
                value = match.group(1).strip()
                provenance = Provenance(
                    page=None,
                    offset_start=match.start(1),
                    offset_end=match.end(1),
                    text_snippet=match.group(0),
                )
                fields[field_name] = ExtractionField(
                    name=field_name,
                    value=value,
                    confidence=_CONFIDENCE,
                    provenance=[provenance],
                )

        return ExtractionResult(
            fields=fields,
            extractor_name=self.name,
            extractor_version=self.version,
            raw_text=text,
        )
