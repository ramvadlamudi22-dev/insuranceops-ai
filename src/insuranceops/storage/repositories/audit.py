"""Audit repository."""

from __future__ import annotations

from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.storage.models import AuditEventModel


class AuditRepository:
    """Repository for AuditEvent operations (append-only)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, model: AuditEventModel) -> AuditEventModel:
        """Append a new audit event."""
        self._session.add(model)
        await self._session.flush()
        return model

    async def get_by_id(self, audit_event_id: UUID) -> Optional[AuditEventModel]:
        """Get an audit event by its ID."""
        result = await self._session.execute(
            select(AuditEventModel).where(
                AuditEventModel.audit_event_id == audit_event_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_workflow_run(
        self, workflow_run_id: UUID, limit: int = 1000
    ) -> Sequence[AuditEventModel]:
        """List audit events for a workflow run in replay order."""
        result = await self._session.execute(
            select(AuditEventModel)
            .where(AuditEventModel.workflow_run_id == workflow_run_id)
            .order_by(AuditEventModel.occurred_at, AuditEventModel.seq_in_run)
            .limit(limit)
        )
        return result.scalars().all()

    async def get_latest_for_run(
        self, workflow_run_id: UUID
    ) -> Optional[AuditEventModel]:
        """Get the latest audit event for a workflow run by seq_in_run."""
        result = await self._session.execute(
            select(AuditEventModel)
            .where(AuditEventModel.workflow_run_id == workflow_run_id)
            .order_by(AuditEventModel.seq_in_run.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def count_by_workflow_run(self, workflow_run_id: UUID) -> int:
        """Count audit events for a workflow run."""
        from sqlalchemy import func

        result = await self._session.execute(
            select(func.count())
            .select_from(AuditEventModel)
            .where(AuditEventModel.workflow_run_id == workflow_run_id)
        )
        return result.scalar_one()
