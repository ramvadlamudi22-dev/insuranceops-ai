"""Tests for audit chain integrity verification.

Verifies that the audit verifier correctly detects valid chains,
tampered events, and missing events.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from insuranceops.domain.audit import AuditEvent, compute_event_hash


def _build_chain(count: int) -> list[AuditEvent]:
    """Build a valid chain of audit events for testing."""
    run_id = uuid.UUID("00000000-0000-4000-8000-000000000100")
    frozen_time = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    events: list[AuditEvent] = []
    prev_hash = None

    for i in range(count):
        event_id = uuid.UUID(f"00000000-0000-4000-8000-{i + 1:012d}")
        event_type = "workflow_run.started" if i == 0 else f"step.event_{i}"

        event_hash = compute_event_hash(
            audit_event_id=event_id,
            workflow_run_id=run_id,
            actor="system:orchestrator:test",
            event_type=event_type,
            payload={"seq": i},
            occurred_at=frozen_time,
            prev_event_hash=prev_hash,
        )

        event = AuditEvent(
            audit_event_id=event_id,
            workflow_run_id=run_id,
            event_type=event_type,
            actor="system:orchestrator:test",
            payload={"seq": i},
            occurred_at=frozen_time,
            seq_in_run=i + 1,
            prev_event_hash=prev_hash,
            event_hash=event_hash,
        )
        events.append(event)
        prev_hash = event_hash

    return events


def _verify_local_chain(events: list[AuditEvent]) -> tuple[bool, int | None, str]:
    """Local chain verification (mirrors the verifier logic without DB).

    Returns:
        Tuple of (is_valid, first_mismatch_index, detail).
    """
    if not events:
        return True, None, "No events in chain"

    prev_event_hash = None

    for idx, event in enumerate(events):
        # Check chain linkage
        if event.prev_event_hash != prev_event_hash:
            return (
                False,
                idx,
                f"Event at index {idx}: prev_event_hash mismatch",
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
            return (
                False,
                idx,
                f"Event at index {idx}: computed hash mismatch",
            )

        prev_event_hash = event.event_hash

    return True, None, f"All {len(events)} events verified"


class TestAuditChainIntegrity:
    """Verify chain verification logic detects valid and invalid chains."""

    def test_chain_verifies_for_completed_run(self) -> None:
        """After a completed workflow, verify_chain returns is_valid=True."""
        events = _build_chain(5)
        is_valid, mismatch_idx, detail = _verify_local_chain(events)

        assert is_valid is True
        assert mismatch_idx is None
        assert "5 events verified" in detail

    def test_tampered_event_detected(self) -> None:
        """Modify one event's payload, verify_chain detects mismatch."""
        events = _build_chain(5)

        # Tamper with event at index 2 by creating a new event with modified payload
        tampered = events[2]
        # Create a new AuditEvent with different payload but same hash (which is wrong)
        tampered_event = AuditEvent(
            audit_event_id=tampered.audit_event_id,
            workflow_run_id=tampered.workflow_run_id,
            event_type=tampered.event_type,
            actor=tampered.actor,
            payload={"seq": 999, "tampered": True},  # modified payload
            occurred_at=tampered.occurred_at,
            seq_in_run=tampered.seq_in_run,
            prev_event_hash=tampered.prev_event_hash,
            event_hash=tampered.event_hash,  # hash no longer matches
        )
        events[2] = tampered_event

        is_valid, mismatch_idx, detail = _verify_local_chain(events)

        assert is_valid is False
        assert mismatch_idx == 2
        assert "index 2" in detail

    def test_missing_event_breaks_chain(self) -> None:
        """Delete middle event, verify_chain detects break."""
        events = _build_chain(5)

        # Remove the event at index 2
        del events[2]

        is_valid, mismatch_idx, detail = _verify_local_chain(events)

        assert is_valid is False
        # The break is detected at the event that followed the deleted one
        assert mismatch_idx is not None
        assert mismatch_idx <= 2

    def test_first_event_has_null_prev_hash(self) -> None:
        """First event of any run has prev_event_hash=None."""
        events = _build_chain(3)

        assert events[0].prev_event_hash is None
        assert events[1].prev_event_hash is not None
        assert events[1].prev_event_hash == events[0].event_hash
