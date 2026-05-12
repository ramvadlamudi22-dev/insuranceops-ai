"""Tests for the rule-based validator."""

from __future__ import annotations

from insuranceops.workflows.extractors.base import ExtractionField, ExtractionResult
from insuranceops.workflows.validators.base import ReferenceData
from insuranceops.workflows.validators.rules import RuleBasedValidator


def _make_result(fields: dict[str, str]) -> ExtractionResult:
    """Helper to create an ExtractionResult with given field name->value pairs."""
    extraction_fields = {}
    for name, value in fields.items():
        extraction_fields[name] = ExtractionField(
            name=name,
            value=value,
            confidence=0.95,
            provenance=[],
        )
    return ExtractionResult(
        fields=extraction_fields,
        extractor_name="test",
        extractor_version="1.0.0",
    )


class TestRuleBasedValidator:
    """Verify deterministic rule-based validation logic."""

    def test_validate_pass(self) -> None:
        """Valid ExtractionResult with all fields correct returns status='pass'."""
        result = _make_result(
            {
                "claim_number": "CLM-2025-001234",
                "policy_number": "POL-12345678",
                "date_of_loss": "01/15/2025",
                "claimant_name": "Jane Smith",
            }
        )
        validator = RuleBasedValidator()
        outcome = validator.validate(result, ReferenceData())

        assert outcome.status == "pass"
        assert outcome.reasons == []

    def test_validate_missing_claim_number(self) -> None:
        """Returns fail_terminal with code 'claim_number_missing'."""
        result = _make_result(
            {
                "policy_number": "POL-12345678",
                "date_of_loss": "01/15/2025",
            }
        )
        validator = RuleBasedValidator()
        outcome = validator.validate(result, ReferenceData())

        assert outcome.status == "fail_terminal"
        assert len(outcome.reasons) == 1
        assert outcome.reasons[0].code == "claim_number_missing"

    def test_validate_invalid_policy_format(self) -> None:
        """Present but wrong format returns fail_correctable."""
        result = _make_result(
            {
                "claim_number": "CLM-2025-001234",
                "policy_number": "INVALID-FORMAT",
                "date_of_loss": "01/15/2025",
            }
        )
        validator = RuleBasedValidator()
        outcome = validator.validate(result, ReferenceData())

        assert outcome.status == "fail_correctable"
        assert any(r.code == "policy_number_format_invalid" for r in outcome.reasons)

    def test_validate_missing_policy_number(self) -> None:
        """Returns fail_terminal with code 'policy_number_missing'."""
        result = _make_result(
            {
                "claim_number": "CLM-2025-001234",
                "date_of_loss": "01/15/2025",
            }
        )
        validator = RuleBasedValidator()
        outcome = validator.validate(result, ReferenceData())

        assert outcome.status == "fail_terminal"
        assert len(outcome.reasons) == 1
        assert outcome.reasons[0].code == "policy_number_missing"

    def test_validate_invalid_date(self) -> None:
        """Unparseable date returns fail_correctable with code 'date_of_loss_invalid'."""
        result = _make_result(
            {
                "claim_number": "CLM-2025-001234",
                "policy_number": "POL-12345678",
                "date_of_loss": "not-a-date",
            }
        )
        validator = RuleBasedValidator()
        outcome = validator.validate(result, ReferenceData())

        assert outcome.status == "fail_correctable"
        assert any(r.code == "date_of_loss_invalid" for r in outcome.reasons)

    def test_validate_multiple_issues(self) -> None:
        """Accumulates all fail_correctable reasons."""
        result = _make_result(
            {
                "claim_number": "CLM-2025-001234",
                "policy_number": "INVALID",
                "date_of_loss": "not-a-date",
            }
        )
        validator = RuleBasedValidator()
        outcome = validator.validate(result, ReferenceData())

        assert outcome.status == "fail_correctable"
        codes = {r.code for r in outcome.reasons}
        assert "policy_number_format_invalid" in codes
        assert "date_of_loss_invalid" in codes

    def test_validate_deterministic(self) -> None:
        """Same inputs always produce same ValidationOutcome."""
        result = _make_result(
            {
                "claim_number": "CLM-2025-001234",
                "policy_number": "POL-12345678",
                "date_of_loss": "01/15/2025",
            }
        )
        validator = RuleBasedValidator()
        outcome1 = validator.validate(result, ReferenceData())
        outcome2 = validator.validate(result, ReferenceData())

        assert outcome1.status == outcome2.status
        assert outcome1.reasons == outcome2.reasons
