"""StepAttempt repository."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.storage.models import StepAttemptModel


class StepAttemptRepository:
    """Repository for StepAttempt CRUD operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, step_attempt_id: UUID) -> StepAttemptModel | None:
        """Get a step attempt by its ID."""
        result = await self._session.execute(
            select(StepAttemptModel).where(StepAttemptModel.step_attempt_id == step_attempt_id)
        )
        return result.scalar_one_or_none()

    async def create(self, model: StepAttemptModel) -> StepAttemptModel:
        """Insert a new step attempt."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def list_by_step(self, step_id: UUID) -> Sequence[StepAttemptModel]:
        """List attempts for a step ordered by attempt number descending."""
        result = await self._session.execute(
            select(StepAttemptModel)
            .where(StepAttemptModel.step_id == step_id)
            .order_by(StepAttemptModel.step_attempt_number.desc())
        )
        return result.scalars().all()

    async def get_latest_for_step(self, step_id: UUID) -> StepAttemptModel | None:
        """Get the latest attempt for a step."""
        result = await self._session.execute(
            select(StepAttemptModel)
            .where(StepAttemptModel.step_id == step_id)
            .order_by(StepAttemptModel.step_attempt_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
