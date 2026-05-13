"""Route step handler: Phase 1 passthrough."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.workflows.steps.base import StepContext, StepResult


class RouteStepHandler:
    """Phase 1 passthrough routing handler.

    In future phases, this step would route the claim to downstream
    systems (e.g., claims management, fraud detection). For Phase 1,
    it simply returns succeeded.
    """

    async def handle(self, context: StepContext, session: AsyncSession) -> StepResult:
        """Pass through to the next step.

        Args:
            context: Step context (unused in Phase 1).
            session: Active database session (unused in Phase 1).

        Returns:
            StepResult with succeeded status.
        """
        return StepResult(
            status="succeeded",
            output={"routed": True, "destination": "passthrough"},
        )
