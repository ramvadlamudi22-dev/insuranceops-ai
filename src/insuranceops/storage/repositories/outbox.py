"""Outbox repository for the transactional outbox pattern."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.storage.models import TasksOutboxModel


class OutboxRepository:
    """Repository for tasks_outbox operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, model: TasksOutboxModel) -> TasksOutboxModel:
        """Insert a new outbox entry."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def get_pending(
        self, limit: int = 100, now: Optional[datetime] = None
    ) -> Sequence[TasksOutboxModel]:
        """Get undelivered outbox entries ready for relay."""
        query = (
            select(TasksOutboxModel)
            .where(TasksOutboxModel.enqueued_at.is_(None))
            .order_by(TasksOutboxModel.outbox_id)
            .limit(limit)
        )
        if now is not None:
            query = query.where(TasksOutboxModel.scheduled_for <= now)
        result = await self._session.execute(query)
        return result.scalars().all()

    async def mark_enqueued(self, outbox_id: int, enqueued_at: datetime) -> bool:
        """Mark an outbox entry as successfully enqueued."""
        stmt = (
            update(TasksOutboxModel)
            .where(TasksOutboxModel.outbox_id == outbox_id)
            .values(enqueued_at=enqueued_at)
        )
        result = await self._session.execute(stmt)
        return result.rowcount == 1  # type: ignore[union-attr]

    async def increment_attempts(
        self, outbox_id: int, error: str
    ) -> None:
        """Increment the attempt counter and record the error."""
        stmt = (
            update(TasksOutboxModel)
            .where(TasksOutboxModel.outbox_id == outbox_id)
            .values(
                attempts=TasksOutboxModel.attempts + 1,
                last_error=error,
            )
        )
        await self._session.execute(stmt)

    async def get_by_workflow_run(
        self, workflow_run_id: UUID
    ) -> Sequence[TasksOutboxModel]:
        """Get outbox entries for a workflow run."""
        result = await self._session.execute(
            select(TasksOutboxModel)
            .where(TasksOutboxModel.workflow_run_id == workflow_run_id)
            .order_by(TasksOutboxModel.outbox_id)
        )
        return result.scalars().all()
