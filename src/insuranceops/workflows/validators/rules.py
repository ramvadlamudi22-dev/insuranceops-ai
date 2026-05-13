"""Rule-based validator implementation."""

from __future__ import annotations

import re
from datetime import datetime

from insuranceops.workflows.extractors.base import ExtractionResult
from insuranceops.workflows.validators.base import (
    ReferenceData,
    ValidationOutcome,
    ValidationReason,
)

_POLICY_NUMBER_PATTERN = re.compile(r"^[A-Z]{2,3}-\d{6,10}$")

# Date formats to try when parsing date_of_loss
_DATE_FORMATS = [
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%m/%d/%y",
    "%m-%d-%y",
    "%d/%m/%y",
    "%d-%m-%y",
]


def _parse_date(value: str) -> bool:
    """Attempt to parse a date string. Returns True if parseable."""
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False


class RuleBasedValidator:
    """Deterministic rule-based validator for claim extraction results.

    Validation rules:
    1. claim_number must be present (fail_terminal if absent).
    2. policy_number must be present (fail_terminal if absent) and
       match the pattern [A-Z]{2,3}-\\d{6,10} (fail_correctable if wrong format).
    3. date_of_loss must be parseable as a date (fail_correctable if unparseable).

    First fail_terminal short-circuits. fail_correctable items accumulate.
    Same ExtractionResult + same ReferenceData always produces the same ValidationOutcome.
    """

    @property
    def name(self) -> str:
        """Validator name."""
        return "rule_based_validator"

    @property
    def version(self) -> str:
        """Validator version."""
        return "1.0.0"

    def validate(self, result: ExtractionResult, ref: ReferenceData) -> ValidationOutcome:
        """Validate extraction result against business rules.

        Args:
            result: The extraction result to validate.
            ref: Reference data (unused in rule-based validation, reserved for future use).

        Returns:
            ValidationOutcome with pass, fail_correctable, or fail_terminal status.
        """
        correctable_reasons: list[ValidationReason] = []

        # Rule 1: claim_number must be present
        if "claim_number" not in result.fields:
            return ValidationOutcome(
                status="fail_terminal",
                reasons=[
                    ValidationReason(
                        code="claim_number_missing",
                        field_name="claim_number",
                        message="Claim number is required but was not found in the document.",
                        detail={},
                    )
                ],
                overrides_requested={},
            )

        # Rule 2: policy_number must be present and match format
        if "policy_number" not in result.fields:
            return ValidationOutcome(
                status="fail_terminal",
                reasons=[
                    ValidationReason(
                        code="policy_number_missing",
                        field_name="policy_number",
                        message="Policy number is required but was not found in the document.",
                        detail={},
                    )
                ],
                overrides_requested={},
            )

        policy_value = str(result.fields["policy_number"].value)
        if not _POLICY_NUMBER_PATTERN.match(policy_value):
            correctable_reasons.append(
                ValidationReason(
                    code="policy_number_format_invalid",
                    field_name="policy_number",
                    message=(
                        f"Policy number '{policy_value}' does not match "
                        f"the expected format [A-Z]{{2,3}}-\\d{{6,10}}."
                    ),
                    detail={"value": policy_value},
                )
            )

        # Rule 3: date_of_loss must be parseable
        if "date_of_loss" in result.fields:
            date_value = str(result.fields["date_of_loss"].value)
            if not _parse_date(date_value):
                correctable_reasons.append(
                    ValidationReason(
                        code="date_of_loss_invalid",
                        field_name="date_of_loss",
                        message=(
                            f"Date of loss '{date_value}' could not be parsed as a valid date."
                        ),
                        detail={"value": date_value},
                    )
                )

        # Determine overall outcome
        if correctable_reasons:
            return ValidationOutcome(
                status="fail_correctable",
                reasons=correctable_reasons,
                overrides_requested={
                    reason.field_name: reason.code
                    for reason in correctable_reasons
                    if reason.field_name is not None
                },
            )

        return ValidationOutcome(
            status="pass",
            reasons=[],
            overrides_requested={},
        )
