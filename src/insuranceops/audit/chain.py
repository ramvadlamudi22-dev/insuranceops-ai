"""Audit event chain: append events with cryptographic hash linking.

Within the current transaction:
1. SELECT last event_hash FOR UPDATE on workflow_runs row (serialize chain writes)
2. Compute seq_in_run from last event
3. Compute prev_event_hash and new event_hash
4. INSERT audit_event
5. Increment metrics
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.domain.audit import compute_event_hash
from insuranceops.observability.metrics import audit_events_appended_total
from insuranceops.storage.models import AuditEventModel
from insuranceops.storage.repositories.audit import AuditRepository


def uuid7() -> UUID:
    """Generate a UUID v7 per RFC 9562.

    Layout (128 bits):
      - bits  0-47: unix_ts_ms (48-bit unsigned millisecond timestamp)
      - bits 48-51: ver (0b0111)
      - bits 52-63: rand_a (12 random bits)
      - bits 64-65: var (0b10)
      - bits 66-127: rand_b (62 random bits)

    Returns:
        A time-sortable UUID version 7.
    """
    timestamp_ms = int(time.time() * 1000)
    rand_bytes = os.urandom(10)  # 80 bits of randomness

    # Build the 128-bit UUID
    # First 48 bits: timestamp
    uuid_int = (timestamp_ms & 0xFFFFFFFFFFFF) << 80
    # Next 4 bits: version = 7
    uuid_int |= 0x7 << 76
    # Next 12 bits: rand_a (from first 12 bits of rand_bytes)
    rand_a = (rand_bytes[0] << 4) | (rand_bytes[1] >> 4)
    uuid_int |= (rand_a & 0xFFF) << 64
    # Next 2 bits: variant = 0b10
    uuid_int |= 0b10 << 62
    # Next 62 bits: rand_b
    rand_b = int.from_bytes(rand_bytes[2:], "big") & 0x3FFFFFFFFFFFFFFF
    uuid_int |= rand_b

    return UUID(int=uuid_int)


async def append_audit_event(
    session: AsyncSession,
    workflow_run_id: UUID,
    event_type: str,
    actor: str,
    payload: dict[str, Any],
    step_id: UUID | None = None,
    step_attempt_id: UUID | None = None,
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
            "SELECT workflow_run_id FROM workflow_runs WHERE workflow_run_id = :wrid FOR UPDATE"
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
    audit_event_id = uuid7()
    occurred_at = datetime.now(UTC)

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
