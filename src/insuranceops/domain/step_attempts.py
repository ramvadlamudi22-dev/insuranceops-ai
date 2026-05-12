"""StepAttempt domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
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
    extractor_name: Optional[str] = None
    extractor_version: Optional[str] = None
    validator_name: Optional[str] = None
    validator_version: Optional[str] = None
    input_ref: Optional[str] = None
    output_ref: Optional[str] = None
    error_code: Optional[str] = None
    error_detail: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    scheduled_for: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.step_attempt_number < 1:
            raise ValueError(
                f"step_attempt_number must be >= 1, got {self.step_attempt_number}"
            )
