"""Test replay determinism for the claim_intake_v1 workflow.

Verifies that running the workflow twice with the same frozen clock
and deterministic UUIDs produces identical AuditEvent hashes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from insuranceops.domain.audit import compute_event_hash
from insuranceops.workflows.extractors.stub import StubExtractor
from insuranceops.workflows.validators.base import ReferenceData
from insuranceops.workflows.validators.rules import RuleBasedValidator


def _run_workflow_and_collect_hashes(
    document_bytes: bytes,
    frozen_time: datetime,
    run_id: uuid.UUID,
    event_ids: list[uuid.UUID],
) -> list[bytes]:
    """Simulate a workflow run and collect audit event hashes."""
    # Step 1: Extract
    extractor = StubExtractor()
    extraction = extractor.extract(document_bytes, "text/plain", {})

    # Step 2: Validate
    validator = RuleBasedValidator()
    outcome = validator.validate(extraction, ReferenceData())

    # Generate audit events deterministically
    events: list[bytes] = []
    prev_hash = None

    # Event 1: workflow_run.started
    h = compute_event_hash(
        audit_event_id=event_ids[0],
        workflow_run_id=run_id,
        actor="worker:orchestrator",
        event_type="workflow_run.started",
        payload={
            "workflow_name": "claim_intake_v1",
            "document_count": 1,
        },
        occurred_at=frozen_time,
        prev_event_hash=prev_hash,
    )
    events.append(h)
    prev_hash = h

    # Event 2: step.started (extract)
    h = compute_event_hash(
        audit_event_id=event_ids[1],
        workflow_run_id=run_id,
        actor="worker:orchestrator",
        event_type="step.started",
        payload={"step_name": "extract"},
        occurred_at=frozen_time,
        prev_event_hash=prev_hash,
    )
    events.append(h)
    prev_hash = h

    # Event 3: step.completed (extract)
    h = compute_event_hash(
        audit_event_id=event_ids[2],
        workflow_run_id=run_id,
        actor="worker:orchestrator",
        event_type="step.completed",
        payload={
            "step_name": "extract",
            "status": "succeeded",
            "field_count": len(extraction.fields),
        },
        occurred_at=frozen_time,
        prev_event_hash=prev_hash,
    )
    events.append(h)
    prev_hash = h

    # Event 4: step.completed (validate)
    h = compute_event_hash(
        audit_event_id=event_ids[3],
        workflow_run_id=run_id,
        actor="worker:orchestrator",
        event_type="step.completed",
        payload={
            "step_name": "validate",
            "status": outcome.status,
        },
        occurred_at=frozen_time,
        prev_event_hash=prev_hash,
    )
    events.append(h)
    prev_hash = h

    # Event 5: workflow_run.completed
    h = compute_event_hash(
        audit_event_id=event_ids[4],
        workflow_run_id=run_id,
        actor="worker:orchestrator",
        event_type="workflow_run.completed",
        payload={"final_step": "validate"},
        occurred_at=frozen_time,
        prev_event_hash=prev_hash,
    )
    events.append(h)

    return events


class TestReplayDeterminism:
    """Verify that replaying the workflow produces identical audit events."""

    def test_replay_produces_same_audit_events(
        self, sample_document_bytes: bytes, frozen_clock, uuid_factory
    ) -> None:
        """Run workflow twice with frozen clock and deterministic UUIDs,
        compare AuditEvent hashes - they must match byte-for-byte.
        """
        frozen_time = frozen_clock.now_utc()
        run_id = uuid.UUID("00000000-0000-4000-8000-000000000100")

        # Generate deterministic event IDs for both runs
        event_ids = [uuid.UUID(f"00000000-0000-4000-8000-{i:012d}") for i in range(1, 6)]

        # Run 1
        hashes_1 = _run_workflow_and_collect_hashes(
            sample_document_bytes, frozen_time, run_id, event_ids
        )

        # Run 2 (same inputs)
        hashes_2 = _run_workflow_and_collect_hashes(
            sample_document_bytes, frozen_time, run_id, event_ids
        )

        # All hashes must match
        assert len(hashes_1) == len(hashes_2) == 5
        for i, (h1, h2) in enumerate(zip(hashes_1, hashes_2, strict=True)):
            assert h1 == h2, f"Hash mismatch at event index {i}"
