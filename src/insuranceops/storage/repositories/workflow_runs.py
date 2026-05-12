"""WorkflowRun repository."""

from __future__ import annotations

from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.storage.models import WorkflowRunModel


class WorkflowRunRepository:
    """Repository for WorkflowRun CRUD operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, workflow_run_id: UUID) -> Optional[WorkflowRunModel]:
        """Get a workflow run by its ID."""
        result = await self._session.execute(
            select(WorkflowRunModel).where(
                WorkflowRunModel.workflow_run_id == workflow_run_id
            )
        )
        return result.scalar_one_or_none()

    async def create(self, model: WorkflowRunModel) -> WorkflowRunModel:
        """Insert a new workflow run."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def update_state_optimistic(
        self,
        workflow_run_id: UUID,
        expected_version: int,
        new_state: str,
        new_version: int,
        **kwargs: object,
    ) -> bool:
        """Update state with optimistic locking. Returns True if the row was updated."""
        stmt = (
            update(WorkflowRunModel)
            .where(
                WorkflowRunModel.workflow_run_id == workflow_run_id,
                WorkflowRunModel.version == expected_version,
            )
            .values(state=new_state, version=new_version, **kwargs)
        )
        result = await self._session.execute(stmt)
        return result.rowcount == 1  # type: ignore[union-attr]

    async def list_by_state(
        self, state: str, limit: int = 50, offset: int = 0
    ) -> Sequence[WorkflowRunModel]:
        """List workflow runs by state."""
        result = await self._session.execute(
            select(WorkflowRunModel)
            .where(WorkflowRunModel.state == state)
            .order_by(WorkflowRunModel.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()
