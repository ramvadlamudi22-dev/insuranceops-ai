"""Audit chain verifier.

Walks all AuditEvents for a workflow run in order and recomputes each
event_hash, comparing to the stored value to detect tampering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.domain.audit import compute_event_hash
from insuranceops.observability.metrics import audit_chain_mismatches_total
from insuranceops.storage.repositories.audit import AuditRepository


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Result of chain verification."""

    is_valid: bool
    first_mismatch_index: Optional[int] = None
    detail: Optional[str] = None


async def verify_chain(
    session: AsyncSession, workflow_run_id: UUID
) -> VerificationResult:
    """Verify the integrity of the audit event chain for a workflow run.

    Loads all AuditEvents ordered by (occurred_at, seq_in_run), recomputes
    each event_hash, and compares to the stored value.

    Args:
        session: Active async session.
        workflow_run_id: The workflow run whose chain to verify.

    Returns:
        VerificationResult indicating whether the chain is intact.
    """
    repo = AuditRepository(session)
    events = await repo.list_by_workflow_run(workflow_run_id)

    if not events:
        return VerificationResult(is_valid=True, detail="No events in chain")

    prev_event_hash: Optional[bytes] = None

    for idx, event in enumerate(events):
        # Verify chain linkage: each event's prev_event_hash should match
        # the previous event's event_hash
        if event.prev_event_hash != prev_event_hash:
            audit_chain_mismatches_total.inc()
            return VerificationResult(
                is_valid=False,
                first_mismatch_index=idx,
                detail=(
                    f"Event at index {idx} (seq_in_run={event.seq_in_run}): "
                    f"prev_event_hash does not match previous event's event_hash"
                ),
            )

        # Recompute the event hash
        expected_hash = compute_event_hash(
            audit_event_id=event.audit_event_id,
            workflow_run_id=event.workflow_run_id,
            actor=event.actor,
            event_type=event.event_type,
            payload=event.payload,
            occurred_at=event.occurred_at,
            prev_event_hash=event.prev_event_hash,
        )

        if event.event_hash != expected_hash:
            audit_chain_mismatches_total.inc()
            return VerificationResult(
                is_valid=False,
                first_mismatch_index=idx,
                detail=(
                    f"Event at index {idx} (seq_in_run={event.seq_in_run}): "
                    f"computed event_hash does not match stored value"
                ),
            )

        prev_event_hash = event.event_hash

    return VerificationResult(is_valid=True, detail=f"All {len(events)} events verified")
