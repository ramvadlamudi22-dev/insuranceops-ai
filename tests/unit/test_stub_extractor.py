"""Tests for the stub regex-based extractor."""

from __future__ import annotations

from insuranceops.workflows.extractors.stub import StubExtractor


class TestStubExtractor:
    """Verify deterministic regex extraction from claim documents."""

    def test_extract_valid_claim(self, sample_document_bytes: bytes) -> None:
        """Full claim text returns all 5 fields with correct values."""
        extractor = StubExtractor()
        result = extractor.extract(sample_document_bytes, "text/plain", {})

        assert "claim_number" in result.fields
        assert "policy_number" in result.fields
        assert "claimant_name" in result.fields
        assert "date_of_loss" in result.fields
        assert "claim_type" in result.fields

        assert result.fields["claim_number"].value == "CLM-2025-001234"
        assert result.fields["policy_number"].value == "POL-12345678"
        assert result.fields["date_of_loss"].value == "01/15/2025"

    def test_extract_deterministic(self, sample_document_bytes: bytes) -> None:
        """Same input twice produces identical ExtractionResult."""
        extractor = StubExtractor()
        result1 = extractor.extract(sample_document_bytes, "text/plain", {})
        result2 = extractor.extract(sample_document_bytes, "text/plain", {})

        assert result1.fields.keys() == result2.fields.keys()
        for key in result1.fields:
            assert result1.fields[key].value == result2.fields[key].value
            assert result1.fields[key].confidence == result2.fields[key].confidence

    def test_extract_missing_fields(self) -> None:
        """Partial text returns only matched fields."""
        extractor = StubExtractor()
        partial = b"Claim Number: CLM-999\nSome other text"
        result = extractor.extract(partial, "text/plain", {})

        assert "claim_number" in result.fields
        assert "policy_number" not in result.fields
        assert "date_of_loss" not in result.fields

    def test_extract_empty_content(self) -> None:
        """Empty bytes returns empty fields dict."""
        extractor = StubExtractor()
        result = extractor.extract(b"", "text/plain", {})

        assert result.fields == {}

    def test_extract_confidence_values(self, sample_document_bytes: bytes) -> None:
        """All extracted fields have confidence 0.95."""
        extractor = StubExtractor()
        result = extractor.extract(sample_document_bytes, "text/plain", {})

        for field in result.fields.values():
            assert field.confidence == 0.95

    def test_extract_provenance(self, sample_document_bytes: bytes) -> None:
        """Fields include provenance with correct offsets."""
        extractor = StubExtractor()
        result = extractor.extract(sample_document_bytes, "text/plain", {})

        for field in result.fields.values():
            assert len(field.provenance) == 1
            prov = field.provenance[0]
            assert prov.offset_start is not None
            assert prov.offset_end is not None
            assert prov.offset_start < prov.offset_end
            assert prov.text_snippet is not None
