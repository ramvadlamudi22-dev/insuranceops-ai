"""Validator protocol and data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from insuranceops.workflows.extractors.base import ExtractionResult


@dataclass(frozen=True, slots=True)
class ValidationReason:
    """A single validation failure reason.

    Attributes:
        code: Machine-readable error code (e.g., "claim_number_missing").
        field: The field that failed validation (if applicable).
        message: Human-readable description of the failure.
        detail: Additional context for debugging or display.
    """

    code: str
    field: str | None = None
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    """Result of validation.

    Attributes:
        status: Overall validation status.
        reasons: List of reasons for failure (empty on pass).
        overrides_requested: Fields that can be overridden by a human.
    """

    status: Literal["pass", "fail_correctable", "fail_terminal"]
    reasons: list[ValidationReason] = field(default_factory=list)
    overrides_requested: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReferenceData:
    """Reference data snapshot for validation.

    Attributes:
        snapshot_id: Optional ID of the reference data snapshot.
        data: The reference data dictionary.
    """

    snapshot_id: UUID | None = None
    data: dict[str, Any] = field(default_factory=dict)


class Validator(Protocol):
    """Protocol for extraction result validators.

    Validators check extracted fields against business rules
    and reference data, producing a deterministic outcome.
    """

    @property
    def name(self) -> str:
        """Validator name."""
        ...

    @property
    def version(self) -> str:
        """Validator version."""
        ...

    def validate(self, result: ExtractionResult, ref: ReferenceData) -> ValidationOutcome:
        """Validate an extraction result against reference data.

        Args:
            result: The extraction result to validate.
            ref: Reference data for validation checks.

        Returns:
            ValidationOutcome with status and reasons.
        """
        ...
