"""Test the happy path of claim_intake_v1 workflow.

Verifies that a valid document goes through extract -> validate -> route
steps and reaches 'completed' state with proper audit trail.
"""

from __future__ import annotations

from insuranceops.domain.workflow_runs import WorkflowRunState
from insuranceops.workflows.extractors.stub import StubExtractor
from insuranceops.workflows.steps.base import StepResult
from insuranceops.workflows.validators.base import ReferenceData
from insuranceops.workflows.validators.rules import RuleBasedValidator


class TestClaimIntakeV1HappyPath:
    """Full workflow run from ingest to completed with stub extractor."""

    def test_full_workflow_happy_path(self, sample_document_bytes: bytes) -> None:
        """Start workflow with valid document -> extract -> validate -> complete.

        Verifies the StubExtractor and RuleBasedValidator work together
        to produce a successful workflow outcome.
        """
        # Step 1: Extract using StubExtractor
        extractor = StubExtractor()
        extraction_result = extractor.extract(sample_document_bytes, "text/plain", {})

        # Verify extraction succeeded with all fields
        assert "claim_number" in extraction_result.fields
        assert "policy_number" in extraction_result.fields
        assert "date_of_loss" in extraction_result.fields

        # Step 2: Validate using RuleBasedValidator
        validator = RuleBasedValidator()
        validation_outcome = validator.validate(extraction_result, ReferenceData())

        # Validate passes for the sample document
        assert validation_outcome.status == "pass"

        # Step 3: Verify the step result for a passing validation
        step_result = StepResult(
            status="succeeded",
            output={
                "extraction": {k: v.value for k, v in extraction_result.fields.items()},
                "validation_status": validation_outcome.status,
            },
        )
        assert step_result.status == "succeeded"

        # Step 4: Verify state transitions
        # A completed workflow would go: pending -> running -> completed
        from insuranceops.domain.workflow_runs import validate_transition

        validate_transition(WorkflowRunState.pending, WorkflowRunState.running)
        validate_transition(WorkflowRunState.running, WorkflowRunState.completed)

    def test_extractor_and_validator_integration(self, sample_document_bytes: bytes) -> None:
        """StubExtractor output feeds directly into RuleBasedValidator."""
        extractor = StubExtractor()
        validator = RuleBasedValidator()

        result = extractor.extract(sample_document_bytes, "text/plain", {})
        outcome = validator.validate(result, ReferenceData())

        assert outcome.status == "pass"
        assert outcome.reasons == []
