"""EscalationCase domain model with state machine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID


class EscalationState(Enum):
    """Valid states for an EscalationCase."""

    open = "open"
    claimed = "claimed"
    resolved = "resolved"
    rejected = "rejected"
    expired = "expired"


TERMINAL_STATES = frozenset({
    EscalationState.resolved,
    EscalationState.rejected,
    EscalationState.expired,
})

VALID_TRANSITIONS: dict[EscalationState, frozenset[EscalationState]] = {
    EscalationState.open: frozenset({
        EscalationState.claimed,
        EscalationState.expired,
    }),
    EscalationState.claimed: frozenset({
        EscalationState.resolved,
        EscalationState.rejected,
        EscalationState.expired,
    }),
    EscalationState.resolved: frozenset(),
    EscalationState.rejected: frozenset(),
    EscalationState.expired: frozenset(),
}


def validate_transition(current: EscalationState, target: EscalationState) -> None:
    """Validate an escalation state transition. Raises ValueError if invalid."""
    allowed = VALID_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ValueError(
            f"Invalid EscalationCase state transition: {current.value} -> {target.value}. "
            f"Allowed targets from {current.value}: "
            f"{sorted(s.value for s in allowed) if allowed else 'none (terminal state)'}"
        )


@dataclass(slots=True)
class EscalationCase:
    """A human-in-the-loop work item."""

    escalation_id: UUID
    workflow_run_id: UUID
    step_id: UUID
    state: EscalationState
    reason_code: str
    expires_at: datetime
    created_at: datetime
    reason_detail: Optional[str] = None
    claimed_by: Optional[str] = None
    claimed_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_payload: Optional[dict[str, object]] = None

    def transition_to(self, target: EscalationState) -> None:
        """Transition the EscalationCase to a new state.

        Validates the transition. Raises ValueError on invalid transitions.
        """
        validate_transition(self.state, target)
        self.state = target

    @property
    def is_terminal(self) -> bool:
        """Return True if the EscalationCase is in a terminal state."""
        return self.state in TERMINAL_STATES
