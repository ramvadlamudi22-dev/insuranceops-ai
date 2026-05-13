"""Complete step handler: signals workflow completion."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.workflows.steps.base import StepContext, StepResult


class CompleteStepHandler:
    """Signals the workflow orchestrator to transition to completed state.

    This is the final step in a workflow. When it returns succeeded,
    the orchestrator marks the WorkflowRun as completed.
    """

    async def handle(self, context: StepContext, session: AsyncSession) -> StepResult:
        """Signal workflow completion.

        Args:
            context: Step context (unused).
            session: Active database session (unused).

        Returns:
            StepResult with succeeded status.
        """
        return StepResult(
            status="succeeded",
            output={"completed": True},
        )
