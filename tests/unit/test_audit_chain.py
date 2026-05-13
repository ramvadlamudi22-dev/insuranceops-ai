"""Tests for audit event hash computation and chain integrity."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from insuranceops.domain.audit import canonical_json, compute_event_hash


class TestComputeEventHash:
    """Verify event hash computation is deterministic and sensitive to inputs."""

    def test_compute_event_hash_deterministic(self) -> None:
        """Same inputs produce same hash."""
        kwargs = dict(
            audit_event_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
            workflow_run_id=uuid.UUID("00000000-0000-4000-8000-000000000010"),
            actor="worker:orchestrator",
            event_type="workflow_run.started",
            payload={"key": "value"},
            occurred_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
            prev_event_hash=None,
        )
        h1 = compute_event_hash(**kwargs)
        h2 = compute_event_hash(**kwargs)
        assert h1 == h2
        assert len(h1) == 32

    def test_compute_event_hash_different_inputs(self) -> None:
        """Different event_type produces different hash."""
        base = dict(
            audit_event_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
            workflow_run_id=uuid.UUID("00000000-0000-4000-8000-000000000010"),
            actor="worker:orchestrator",
            payload={"key": "value"},
            occurred_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
            prev_event_hash=None,
        )
        h1 = compute_event_hash(event_type="workflow_run.started", **base)
        h2 = compute_event_hash(event_type="workflow_run.completed", **base)
        assert h1 != h2

    def test_first_event_prev_hash_is_none(self) -> None:
        """First event uses b'' for prev_event_hash in computation."""
        h = compute_event_hash(
            audit_event_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
            workflow_run_id=uuid.UUID("00000000-0000-4000-8000-000000000010"),
            actor="worker:orchestrator",
            event_type="workflow_run.started",
            payload={},
            occurred_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
            prev_event_hash=None,
        )
        assert isinstance(h, bytes)
        assert len(h) == 32


class TestChainLinkage:
    """Verify chain linkage between events."""

    def test_chain_linkage(self) -> None:
        """Second event's prev_event_hash equals first event's event_hash."""
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        run_id = uuid.UUID("00000000-0000-4000-8000-000000000010")

        first_hash = compute_event_hash(
            audit_event_id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
            workflow_run_id=run_id,
            actor="worker:orchestrator",
            event_type="workflow_run.started",
            payload={},
            occurred_at=ts,
            prev_event_hash=None,
        )

        second_hash = compute_event_hash(
            audit_event_id=uuid.UUID("00000000-0000-4000-8000-000000000002"),
            workflow_run_id=run_id,
            actor="worker:orchestrator",
            event_type="step.advanced",
            payload={"step": "extract"},
            occurred_at=ts,
            prev_event_hash=first_hash,
        )

        # Second hash is different from first
        assert second_hash != first_hash
        # Both are 32 bytes
        assert len(second_hash) == 32


class TestCanonicalJson:
    """Verify canonical JSON serialization."""

    def test_canonical_json_sorted_keys(self) -> None:
        """Keys are sorted alphabetically."""
        result = canonical_json({"b": 2, "a": 1})
        assert result == '{"a":1,"b":2}'

    def test_canonical_json_no_whitespace(self) -> None:
        """No spaces in output."""
        result = canonical_json({"key": "value", "nested": {"x": 1}})
        assert " " not in result


class TestTamperDetection:
    """Verify that modifying any field in an event makes recomputed hash mismatch."""

    def test_tamper_detection(self) -> None:
        """Changing any field in an event makes recomputed hash mismatch stored hash."""
        ts = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        event_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
        run_id = uuid.UUID("00000000-0000-4000-8000-000000000010")

        original_hash = compute_event_hash(
            audit_event_id=event_id,
            workflow_run_id=run_id,
            actor="worker:orchestrator",
            event_type="workflow_run.started",
            payload={"data": "original"},
            occurred_at=ts,
            prev_event_hash=None,
        )

        # Tamper with payload
        tampered_hash = compute_event_hash(
            audit_event_id=event_id,
            workflow_run_id=run_id,
            actor="worker:orchestrator",
            event_type="workflow_run.started",
            payload={"data": "tampered"},
            occurred_at=ts,
            prev_event_hash=None,
        )

        assert original_hash != tampered_hash
