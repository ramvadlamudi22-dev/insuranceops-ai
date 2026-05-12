"""WorkflowRun domain model with state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class WorkflowRunState(Enum):
    """Valid states for a WorkflowRun."""

    pending = "pending"
    running = "running"
    awaiting_human = "awaiting_human"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


TERMINAL_STATES = frozenset(
    {
        WorkflowRunState.completed,
        WorkflowRunState.failed,
        WorkflowRunState.cancelled,
    }
)

VALID_TRANSITIONS: dict[WorkflowRunState, frozenset[WorkflowRunState]] = {
    WorkflowRunState.pending: frozenset({WorkflowRunState.running}),
    WorkflowRunState.running: frozenset(
        {
            WorkflowRunState.awaiting_human,
            WorkflowRunState.completed,
            WorkflowRunState.failed,
            WorkflowRunState.cancelled,
        }
    ),
    WorkflowRunState.awaiting_human: frozenset(
        {
            WorkflowRunState.running,
            WorkflowRunState.cancelled,
        }
    ),
    WorkflowRunState.completed: frozenset(),
    WorkflowRunState.failed: frozenset(),
    WorkflowRunState.cancelled: frozenset(),
}


def validate_transition(current: WorkflowRunState, target: WorkflowRunState) -> None:
    """Validate a state transition. Raises ValueError if the transition is invalid."""
    allowed = VALID_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ValueError(
            f"Invalid WorkflowRun state transition: {current.value} -> {target.value}. "
            f"Allowed targets from {current.value}: "
            f"{sorted(s.value for s in allowed) if allowed else 'none (terminal state)'}"
        )


@dataclass(slots=True)
class WorkflowRun:
    """A single execution of a Workflow against one or more Documents."""

    workflow_run_id: UUID
    workflow_name: str
    workflow_version: str
    state: WorkflowRunState
    version: int
    created_at: datetime
    updated_at: datetime
    deadline_at: datetime
    created_by: str
    current_step_id: UUID | None = None
    reference_data_snapshot_id: UUID | None = None
    last_error_code: str | None = None
    last_error_detail: str | None = None

    def transition_to(self, target: WorkflowRunState) -> None:
        """Transition the WorkflowRun to a new state.

        Validates the transition, updates state, and increments version.
        Raises ValueError on invalid transitions.
        """
        validate_transition(self.state, target)
        self.state = target
        self.version += 1

    @property
    def is_terminal(self) -> bool:
        """Return True if the WorkflowRun is in a terminal state."""
        return self.state in TERMINAL_STATES
