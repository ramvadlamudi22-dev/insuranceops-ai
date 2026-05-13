"""Tests for domain state machines: WorkflowRun and EscalationCase transitions."""

from __future__ import annotations

import pytest

from insuranceops.domain.escalations import EscalationState
from insuranceops.domain.escalations import validate_transition as validate_escalation
from insuranceops.domain.workflow_runs import WorkflowRunState
from insuranceops.domain.workflow_runs import validate_transition as validate_run


class TestWorkflowRunValidTransitions:
    """All valid transitions succeed without raising."""

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (WorkflowRunState.pending, WorkflowRunState.running),
            (WorkflowRunState.running, WorkflowRunState.completed),
            (WorkflowRunState.running, WorkflowRunState.failed),
            (WorkflowRunState.running, WorkflowRunState.cancelled),
            (WorkflowRunState.running, WorkflowRunState.awaiting_human),
            (WorkflowRunState.awaiting_human, WorkflowRunState.running),
            (WorkflowRunState.awaiting_human, WorkflowRunState.cancelled),
        ],
    )
    def test_workflow_run_valid_transitions(
        self, current: WorkflowRunState, target: WorkflowRunState
    ) -> None:
        validate_run(current, target)  # should not raise


class TestWorkflowRunInvalidTransitions:
    """Invalid transitions raise ValueError."""

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (WorkflowRunState.completed, WorkflowRunState.running),
            (WorkflowRunState.failed, WorkflowRunState.running),
            (WorkflowRunState.pending, WorkflowRunState.completed),
            (WorkflowRunState.cancelled, WorkflowRunState.running),
            (WorkflowRunState.cancelled, WorkflowRunState.pending),
        ],
    )
    def test_workflow_run_invalid_transitions(
        self, current: WorkflowRunState, target: WorkflowRunState
    ) -> None:
        with pytest.raises(ValueError, match="Invalid WorkflowRun state transition"):
            validate_run(current, target)


class TestStepStateValues:
    """All expected states exist in the enum."""

    @pytest.mark.parametrize(
        "state_value",
        ["pending", "running", "awaiting_human", "completed", "failed", "cancelled"],
    )
    def test_step_state_values(self, state_value: str) -> None:
        assert WorkflowRunState(state_value) is not None


class TestEscalationValidTransitions:
    """All valid escalation transitions succeed without raising."""

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (EscalationState.open, EscalationState.claimed),
            (EscalationState.claimed, EscalationState.resolved),
            (EscalationState.claimed, EscalationState.rejected),
            (EscalationState.open, EscalationState.expired),
            (EscalationState.claimed, EscalationState.expired),
        ],
    )
    def test_escalation_valid_transitions(
        self, current: EscalationState, target: EscalationState
    ) -> None:
        validate_escalation(current, target)  # should not raise


class TestEscalationInvalidTransitions:
    """Invalid escalation transitions raise ValueError."""

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (EscalationState.resolved, EscalationState.open),
            (EscalationState.rejected, EscalationState.open),
            (EscalationState.rejected, EscalationState.claimed),
            (EscalationState.expired, EscalationState.open),
            (EscalationState.expired, EscalationState.claimed),
        ],
    )
    def test_escalation_invalid_transitions(
        self, current: EscalationState, target: EscalationState
    ) -> None:
        with pytest.raises(ValueError, match="Invalid EscalationCase state transition"):
            validate_escalation(current, target)
