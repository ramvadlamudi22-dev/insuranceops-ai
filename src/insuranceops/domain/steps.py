"""Step domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class StepState(Enum):
    """Valid states for a Step."""

    queued = "queued"
    in_progress = "in_progress"
    succeeded = "succeeded"
    failed_retryable = "failed_retryable"
    failed_terminal = "failed_terminal"
    skipped = "skipped"


@dataclass(slots=True)
class Step:
    """A unit of work inside a WorkflowRun."""

    step_id: UUID
    workflow_run_id: UUID
    step_name: str
    step_index: int
    max_attempts: int
    escalate_on_failure: bool
    state: StepState
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.step_index < 0:
            raise ValueError(f"step_index must be >= 0, got {self.step_index}")
        if self.max_attempts < 1 or self.max_attempts > 10:
            raise ValueError(f"max_attempts must be between 1 and 10, got {self.max_attempts}")
