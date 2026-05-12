"""AuditEvent domain model with hash chain computation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


def canonical_json(payload: dict[str, Any]) -> str:
    """Serialize payload to canonical JSON (sorted keys, no whitespace)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_event_hash(
    audit_event_id: UUID,
    workflow_run_id: UUID,
    actor: str,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: datetime,
    prev_event_hash: bytes | None,
) -> bytes:
    """Compute the SHA-256 hash of an audit event.

    Formula:
        event_hash = sha256(
            audit_event_id_bytes ||
            workflow_run_id_bytes ||
            actor_bytes ||
            event_type_bytes ||
            canonical_json(payload)_bytes ||
            occurred_at_iso_bytes ||
            coalesce(prev_event_hash, b'')
        )
    """
    h = hashlib.sha256()
    h.update(audit_event_id.bytes)
    h.update(workflow_run_id.bytes)
    h.update(actor.encode("utf-8"))
    h.update(event_type.encode("utf-8"))
    h.update(canonical_json(payload).encode("utf-8"))
    h.update(occurred_at.isoformat().encode("utf-8"))
    h.update(prev_event_hash if prev_event_hash is not None else b"")
    return h.digest()


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An append-only record of a state transition or human action."""

    audit_event_id: UUID
    workflow_run_id: UUID
    event_type: str
    actor: str
    payload: dict[str, Any]
    occurred_at: datetime
    seq_in_run: int
    prev_event_hash: bytes | None
    event_hash: bytes
    step_id: UUID | None = None
    step_attempt_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.seq_in_run < 1:
            raise ValueError(f"seq_in_run must be >= 1, got {self.seq_in_run}")
        if len(self.event_hash) != 32:
            raise ValueError(f"event_hash must be exactly 32 bytes, got {len(self.event_hash)}")
        if self.prev_event_hash is not None and len(self.prev_event_hash) != 32:
            raise ValueError(
                f"prev_event_hash must be exactly 32 bytes or None, got {len(self.prev_event_hash)}"
            )

    def verify_hash(self) -> bool:
        """Verify the event_hash matches the computed hash from row content."""
        expected = compute_event_hash(
            audit_event_id=self.audit_event_id,
            workflow_run_id=self.workflow_run_id,
            actor=self.actor,
            event_type=self.event_type,
            payload=self.payload,
            occurred_at=self.occurred_at,
            prev_event_hash=self.prev_event_hash,
        )
        return self.event_hash == expected
