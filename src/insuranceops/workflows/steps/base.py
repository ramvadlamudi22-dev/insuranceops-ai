"""Step handler protocol and data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class StepResult:
    """Result returned by a step handler.

    Attributes:
        status: Outcome of the step execution.
        output: Optional output data to store as output_ref.
        error_code: Machine-readable error code on failure.
        error_detail: Human-readable error description on failure.
    """

    status: Literal["succeeded", "failed_retryable", "failed_terminal", "escalate"]
    output: dict[str, Any] | None = None
    error_code: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True, slots=True)
class StepContext:
    """Context passed to a step handler for execution.

    Attributes:
        workflow_run_id: The workflow run being processed.
        step_id: The step being executed.
        step_attempt_id: The current attempt of this step.
        step_name: Name of the step.
        workflow_name: Name of the workflow.
        document_ids: List of document IDs associated with the workflow run.
        correlation_id: Correlation ID for tracing.
        previous_outputs: Outputs from previously completed steps, keyed by step_name.
    """

    workflow_run_id: UUID
    step_id: UUID
    step_attempt_id: UUID
    step_name: str
    workflow_name: str
    document_ids: list[UUID] = field(default_factory=list)
    correlation_id: str = ""
    previous_outputs: dict[str, Any] = field(default_factory=dict)


class StepHandler(Protocol):
    """Protocol for step handlers.

    Each step in a workflow has a handler that implements the
    actual processing logic for that step.
    """

    async def handle(self, context: StepContext, session: AsyncSession) -> StepResult:
        """Execute the step logic.

        Args:
            context: Context with workflow run details and previous outputs.
            session: Active async database session.

        Returns:
            StepResult indicating success, failure, or escalation.
        """
        ...
