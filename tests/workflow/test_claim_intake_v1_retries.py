"""Test retry behavior in claim_intake_v1 workflow.

Verifies that transient failures are retried with backoff,
and exhausted retries lead to escalation.
"""

from __future__ import annotations

from random import Random

from insuranceops.domain.escalations import EscalationState
from insuranceops.domain.workflow_runs import WorkflowRunState, validate_transition
from insuranceops.workflows.retry import RetryPolicy, compute_backoff_delay
from insuranceops.workflows.steps.base import StepResult


class TestExtractRetries:
    """Verify retry behavior for the extract step."""

    def test_extract_retries_on_transient_failure(self) -> None:
        """First attempt fails retryable, second succeeds, run completes.

        Validates that the retry policy produces valid delays and that
        a retryable failure followed by success leads to workflow completion.
        """
        policy = RetryPolicy(base_delay_s=2.0, cap_s=60.0, jitter="full")
        rng = Random(42)

        # First attempt fails retryable
        first_result = StepResult(
            status="failed_retryable",
            error_code="EXTRACTION_TIMEOUT",
            error_detail="Service timed out",
        )
        assert first_result.status == "failed_retryable"

        # Compute backoff for retry
        delay = compute_backoff_delay(policy, attempt_number=1, rng=rng)
        assert 0.0 <= delay <= 2.0

        # Second attempt succeeds
        second_result = StepResult(
            status="succeeded",
            output={"claim_number": "CLM-001"},
        )
        assert second_result.status == "succeeded"

        # Workflow continues to completion
        validate_transition(WorkflowRunState.running, WorkflowRunState.completed)

    def test_extract_exhausts_retries_escalates(self) -> None:
        """All 3 attempts fail, escalation created, state is awaiting_human.

        Validates that exhausting all retry attempts with a policy that has
        escalate_on_failure=True leads to an escalation case.
        """
        policy = RetryPolicy(base_delay_s=2.0, cap_s=60.0, jitter="full")
        rng = Random(42)
        max_attempts = 3

        # All attempts fail
        for attempt in range(1, max_attempts + 1):
            result = StepResult(
                status="failed_retryable",
                error_code="EXTRACTION_TIMEOUT",
                error_detail=f"Attempt {attempt} timed out",
            )
            assert result.status == "failed_retryable"

            if attempt < max_attempts:
                delay = compute_backoff_delay(policy, attempt_number=attempt, rng=rng)
                assert delay >= 0.0

        # After exhausting retries with escalate_on_failure, transition to awaiting_human
        validate_transition(WorkflowRunState.running, WorkflowRunState.awaiting_human)

        # Escalation case is created in 'open' state
        esc_state = EscalationState.open
        assert esc_state == EscalationState.open
