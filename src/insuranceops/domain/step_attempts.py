"""StepAttempt domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class StepAttemptState(Enum):
    """Valid states for a StepAttempt."""

    queued = "queued"
    in_progress = "in_progress"
    succeeded = "succeeded"
    failed_retryable = "failed_retryable"
    failed_terminal = "failed_terminal"
    skipped = "skipped"


class StepAttemptOrigin(Enum):
    """Who initiated this attempt."""

    system = "system"
    human = "human"
    reaper = "reaper"
    replay = "replay"


@dataclass(slots=True)
class StepAttempt:
    """One try of a Step."""

    step_attempt_id: UUID
    step_id: UUID
    step_attempt_number: int
    state: StepAttemptState
    origin: StepAttemptOrigin
    created_at: datetime
    extractor_name: str | None = None
    extractor_version: str | None = None
    validator_name: str | None = None
    validator_version: str | None = None
    input_ref: str | None = None
    output_ref: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    scheduled_for: datetime | None = None

    def __post_init__(self) -> None:
        if self.step_attempt_number < 1:
            raise ValueError(f"step_attempt_number must be >= 1, got {self.step_attempt_number}")
