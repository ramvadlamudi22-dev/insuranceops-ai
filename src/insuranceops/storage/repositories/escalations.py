"""Escalation repository."""

from __future__ import annotations

from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.storage.models import EscalationCaseModel


class EscalationRepository:
    """Repository for EscalationCase CRUD operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, escalation_id: UUID) -> Optional[EscalationCaseModel]:
        """Get an escalation case by its ID."""
        result = await self._session.execute(
            select(EscalationCaseModel).where(
                EscalationCaseModel.escalation_id == escalation_id
            )
        )
        return result.scalar_one_or_none()

    async def create(self, model: EscalationCaseModel) -> EscalationCaseModel:
        """Insert a new escalation case."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def claim(self, escalation_id: UUID, actor: str) -> bool:
        """Attempt to atomically claim an open escalation. Returns True if successful."""
        stmt = (
            update(EscalationCaseModel)
            .where(
                EscalationCaseModel.escalation_id == escalation_id,
                EscalationCaseModel.state == "open",
            )
            .values(state="claimed", claimed_by=actor)
        )
        result = await self._session.execute(stmt)
        return result.rowcount == 1  # type: ignore[union-attr]

    async def list_open(self, limit: int = 50, offset: int = 0) -> Sequence[EscalationCaseModel]:
        """List open escalation cases ordered by creation time."""
        result = await self._session.execute(
            select(EscalationCaseModel)
            .where(EscalationCaseModel.state == "open")
            .order_by(EscalationCaseModel.created_at)
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def get_by_run_and_step(
        self, workflow_run_id: UUID, step_id: UUID
    ) -> Optional[EscalationCaseModel]:
        """Get escalation case by workflow run and step."""
        result = await self._session.execute(
            select(EscalationCaseModel).where(
                EscalationCaseModel.workflow_run_id == workflow_run_id,
                EscalationCaseModel.step_id == step_id,
            )
        )
        return result.scalar_one_or_none()
