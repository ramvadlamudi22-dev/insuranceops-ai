"""Audit event chain: append events with cryptographic hash linking.

Within the current transaction:
1. SELECT last event_hash FOR UPDATE on workflow_runs row (serialize chain writes)
2. Compute seq_in_run from last event
3. Compute prev_event_hash and new event_hash
4. INSERT audit_event
5. Increment metrics
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.domain.audit import compute_event_hash
from insuranceops.observability.metrics import audit_events_appended_total
from insuranceops.storage.models import AuditEventModel
from insuranceops.storage.repositories.audit import AuditRepository


async def append_audit_event(
    session: AsyncSession,
    workflow_run_id: UUID,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
    step_id: Optional[UUID] = None,
    step_attempt_id: Optional[UUID] = None,
) -> AuditEventModel:
    """Append a new audit event to the hash chain for a workflow run.

    This function serializes concurrent writes to the same workflow run's
    chain using a row-level lock on the workflow_runs table.

    Args:
        session: Active async session (within a transaction).
        workflow_run_id: The workflow run this event belongs to.
        event_type: Type of event (e.g., "workflow_run.started").
        actor: Actor string (e.g., "api_key:operator:abc-123").
        payload: Event payload dict.
        step_id: Optional step ID if event relates to a step.
        step_attempt_id: Optional step attempt ID.

    Returns:
        The created AuditEventModel instance.
    """
    # Lock the workflow run row to serialize chain writes
    await session.execute(
        text(
            "SELECT workflow_run_id FROM workflow_runs "
            "WHERE workflow_run_id = :wrid FOR UPDATE"
        ).bindparams(wrid=workflow_run_id)
    )

    # Get the latest event in the chain
    repo = AuditRepository(session)
    latest = await repo.get_latest_for_run(workflow_run_id)

    if latest is not None:
        seq_in_run = latest.seq_in_run + 1
        prev_event_hash = latest.event_hash
    else:
        seq_in_run = 1
        prev_event_hash = None

    # Generate IDs and timestamp
    audit_event_id = uuid.uuid4()
    occurred_at = datetime.now(timezone.utc)

    # Compute the event hash using the canonical formula
    event_hash = compute_event_hash(
        audit_event_id=audit_event_id,
        workflow_run_id=workflow_run_id,
        actor=actor,
        event_type=event_type,
        payload=payload,
        occurred_at=occurred_at,
        prev_event_hash=prev_event_hash,
    )

    # Create and insert the audit event
    model = AuditEventModel(
        audit_event_id=audit_event_id,
        workflow_run_id=workflow_run_id,
        step_id=step_id,
        step_attempt_id=step_attempt_id,
        event_type=event_type,
        actor=actor,
        payload=payload,
        occurred_at=occurred_at,
        seq_in_run=seq_in_run,
        prev_event_hash=prev_event_hash,
        event_hash=event_hash,
    )

    await repo.append(model)

    # Increment metric
    audit_events_appended_total.labels(event_type=event_type).inc()

    return model
