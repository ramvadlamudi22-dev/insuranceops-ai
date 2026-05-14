"""Validate step handler: runs the configured validator on extraction results.

Integrates AI review routing: after validation, evaluates field confidence
scores against configured thresholds to determine if human review is needed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.ai.review import ReviewThresholds, evaluate_review_routing
from insuranceops.observability.logging import get_logger
from insuranceops.workflows.extractors.base import ExtractionField, ExtractionResult, Provenance
from insuranceops.workflows.steps.base import StepContext, StepResult
from insuranceops.workflows.validators.base import ReferenceData
from insuranceops.workflows.validators.rules import RuleBasedValidator

logger = get_logger("workflow.steps.validate")


def _reconstruct_extraction_result(extract_output: dict[str, Any]) -> ExtractionResult:
    """Reconstruct an ExtractionResult from the serialized output of the extract step."""
    fields: dict[str, ExtractionField] = {}
    raw_fields = extract_output.get("fields", {})

    for field_name, field_data in raw_fields.items():
        provenance_list = [
            Provenance(
                page=p.get("page"),
                offset_start=p.get("offset_start"),
                offset_end=p.get("offset_end"),
                text_snippet=p.get("text_snippet"),
            )
            for p in field_data.get("provenance", [])
        ]
        fields[field_name] = ExtractionField(
            name=field_data["name"],
            value=field_data["value"],
            confidence=field_data["confidence"],
            provenance=provenance_list,
        )

    return ExtractionResult(
        fields=fields,
        extractor_name=extract_output.get("extractor_name", "unknown"),
        extractor_version=extract_output.get("extractor_version", "unknown"),
        raw_text=None,
    )


class ValidateStepHandler:
    """Validates extraction results using the configured Validator.

    Loads ExtractionResult from the previous extract step output,
    runs the validator, and returns:
    - succeeded on pass (with review routing evaluation)
    - escalate on fail_correctable (with reason)
    - failed_terminal on fail_terminal

    After validation passes, evaluates confidence-based review routing
    to determine if the extraction warrants human review before proceeding.
    """

    def __init__(self) -> None:
        self._validator = RuleBasedValidator()
        self._review_thresholds = ReviewThresholds()

    async def handle(self, context: StepContext, session: AsyncSession) -> StepResult:
        """Validate extracted data against business rules.

        Args:
            context: Step context with previous_outputs containing extract step output.
            session: Active database session.

        Returns:
            StepResult with validation outcome.
        """
        extract_output = context.previous_outputs.get("extract")
        if extract_output is None:
            return StepResult(
                status="failed_terminal",
                error_code="MISSING_EXTRACT_OUTPUT",
                error_detail="No extract step output found in previous_outputs.",
            )

        # Reconstruct ExtractionResult from serialized output
        extraction_result = _reconstruct_extraction_result(extract_output)

        # Run validation with empty reference data (Phase 1)
        ref = ReferenceData(snapshot_id=None, data={})
        outcome = self._validator.validate(extraction_result, ref)

        if outcome.status == "pass":
            # Evaluate AI review routing based on field confidences
            field_confidences = {name: f.confidence for name, f in extraction_result.fields.items()}
            review_routing = evaluate_review_routing(
                field_confidences=field_confidences,
                thresholds=self._review_thresholds,
            )

            if review_routing.requires_review:
                # Route to escalation for human review
                logger.info(
                    "validate_review_routing_triggered",
                    reasons=[r.value for r in review_routing.reasons],
                    overall_confidence=round(review_routing.overall_confidence, 3),
                    suggested_action=review_routing.suggested_action,
                )
                return StepResult(
                    status="escalate",
                    output={
                        "validation_status": "pass_with_review",
                        "review_routing": {
                            "requires_review": True,
                            "reasons": [r.value for r in review_routing.reasons],
                            "overall_confidence": review_routing.overall_confidence,
                            "suggested_action": review_routing.suggested_action,
                        },
                        "validator_name": self._validator.name,
                        "validator_version": self._validator.version,
                    },
                    error_code="REVIEW_REQUIRED",
                    error_detail=(
                        f"Extraction passed validation but requires human review: "
                        f"{', '.join(r.value for r in review_routing.reasons)}"
                    ),
                )

            return StepResult(
                status="succeeded",
                output={
                    "validation_status": "pass",
                    "review_routing": {
                        "requires_review": False,
                        "overall_confidence": review_routing.overall_confidence,
                    },
                    "validator_name": self._validator.name,
                    "validator_version": self._validator.version,
                },
            )
        elif outcome.status == "fail_correctable":
            reasons_serialized = [
                {
                    "code": r.code,
                    "field": r.field_name,
                    "message": r.message,
                    "detail": r.detail,
                }
                for r in outcome.reasons
            ]
            return StepResult(
                status="escalate",
                output={
                    "validation_status": "fail_correctable",
                    "reasons": reasons_serialized,
                    "overrides_requested": outcome.overrides_requested,
                    "validator_name": self._validator.name,
                    "validator_version": self._validator.version,
                },
                error_code="VALIDATION_FAIL_CORRECTABLE",
                error_detail=(
                    f"Validation failed with {len(outcome.reasons)} correctable "
                    f"issue(s): {', '.join(r.code for r in outcome.reasons)}"
                ),
            )
        else:
            # fail_terminal
            reasons_serialized = [
                {
                    "code": r.code,
                    "field": r.field_name,
                    "message": r.message,
                    "detail": r.detail,
                }
                for r in outcome.reasons
            ]
            return StepResult(
                status="failed_terminal",
                output={
                    "validation_status": "fail_terminal",
                    "reasons": reasons_serialized,
                    "validator_name": self._validator.name,
                    "validator_version": self._validator.version,
                },
                error_code="VALIDATION_FAIL_TERMINAL",
                error_detail=(
                    f"Validation failed terminally: {', '.join(r.code for r in outcome.reasons)}"
                ),
            )
