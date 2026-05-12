"""Step repository."""

from __future__ import annotations

from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.storage.models import StepModel


class StepRepository:
    """Repository for Step CRUD operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, step_id: UUID) -> Optional[StepModel]:
        """Get a step by its ID."""
        result = await self._session.execute(
            select(StepModel).where(StepModel.step_id == step_id)
        )
        return result.scalar_one_or_none()

    async def create(self, model: StepModel) -> StepModel:
        """Insert a new step."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def create_many(self, models: Sequence[StepModel]) -> Sequence[StepModel]:
        """Insert multiple steps."""
        self._session.add_all(models)
        await self._session.flush()
        return models

    async def list_by_workflow_run(self, workflow_run_id: UUID) -> Sequence[StepModel]:
        """List steps for a workflow run ordered by step_index."""
        result = await self._session.execute(
            select(StepModel)
            .where(StepModel.workflow_run_id == workflow_run_id)
            .order_by(StepModel.step_index)
        )
        return result.scalars().all()

    async def get_by_run_and_name(
        self, workflow_run_id: UUID, step_name: str
    ) -> Optional[StepModel]:
        """Get a step by workflow run ID and step name."""
        result = await self._session.execute(
            select(StepModel).where(
                StepModel.workflow_run_id == workflow_run_id,
                StepModel.step_name == step_name,
            )
        )
        return result.scalar_one_or_none()
