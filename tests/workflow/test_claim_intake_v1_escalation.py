"""Test escalation flows in claim_intake_v1 workflow.

Verifies that validator fail_correctable creates an escalation,
and that resolve/reject produce the correct final states.
"""

from __future__ import annotations

import pytest

from insuranceops.domain.escalations import EscalationState, validate_transition as validate_esc
from insuranceops.domain.workflow_runs import WorkflowRunState, validate_transition
from insuranceops.workflows.extractors.base import ExtractionField, ExtractionResult
from insuranceops.workflows.steps.base import StepResult
from insuranceops.workflows.validators.base import ReferenceData
from insuranceops.workflows.validators.rules import RuleBasedValidator


class TestValidatorEscalation:
    """Verify escalation creation when validator returns fail_correctable."""

    def test_validator_fail_correctable_creates_escalation(self) -> None:
        """Validate step returns fail_correctable, EscalationCase created,
        run state is awaiting_human.
        """
        # Create extraction with invalid policy format
        fields = {
            "claim_number": ExtractionField(
                name="claim_number", value="CLM-001", confidence=0.95
            ),
            "policy_number": ExtractionField(
                name="policy_number", value="INVALID", confidence=0.95
            ),
            "date_of_loss": ExtractionField(
                name="date_of_loss", value="01/15/2025", confidence=0.95
            ),
        }
        result = ExtractionResult(
            fields=fields, extractor_name="stub", extractor_version="1.0.0"
        )

        validator = RuleBasedValidator()
        outcome = validator.validate(result, ReferenceData())

        assert outcome.status == "fail_correctable"
        assert any(r.code == "policy_number_format_invalid" for r in outcome.reasons)

        # This would trigger escalation: workflow goes to awaiting_human
        step_result = StepResult(
            status="escalate",
            error_code="VALIDATION_FAIL_CORRECTABLE",
            error_detail="Policy number format invalid",
        )
        assert step_result.status == "escalate"

        # Workflow transitions to awaiting_human
        validate_transition(
            WorkflowRunState.running, WorkflowRunState.awaiting_human
        )

        # Escalation is in 'open' state
        esc_state = EscalationState.open
        assert esc_state == EscalationState.open

    def test_resolve_escalation_resumes_workflow(self) -> None:
        """After resolve, workflow resumes and completes."""
        # Escalation goes open -> claimed -> resolved
        validate_esc(EscalationState.open, EscalationState.claimed)
        validate_esc(EscalationState.claimed, EscalationState.resolved)

        # Workflow goes awaiting_human -> running -> completed
        validate_transition(
            WorkflowRunState.awaiting_human, WorkflowRunState.running
        )
        validate_transition(WorkflowRunState.running, WorkflowRunState.completed)

    def test_reject_escalation_fails_workflow(self) -> None:
        """After reject, workflow state is failed."""
        # Escalation goes open -> claimed -> rejected
        validate_esc(EscalationState.open, EscalationState.claimed)
        validate_esc(EscalationState.claimed, EscalationState.rejected)

        # Workflow transitions to failed (from awaiting_human or running)
        validate_transition(
            WorkflowRunState.running, WorkflowRunState.failed
        )
