"""Shared test fixtures for the InsuranceOps AI test suite."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from random import Random

import pytest


@dataclass(frozen=True)
class Clock:
    """Frozen clock for deterministic tests."""

    _fixed: datetime

    def now_utc(self) -> datetime:
        """Return the fixed UTC datetime."""
        return self._fixed


@pytest.fixture()
def frozen_clock() -> Clock:
    """Provide a fixed datetime at 2025-01-15T10:00:00Z."""
    return Clock(_fixed=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC))


@pytest.fixture()
def uuid_factory():
    """Return sequential deterministic UUIDs.

    Each call to the returned function produces the next UUID in a
    deterministic sequence: 00000000-0000-4000-8000-000000000001, etc.
    """
    counter = 0

    def _next() -> uuid.UUID:
        nonlocal counter
        counter += 1
        return uuid.UUID(f"00000000-0000-4000-8000-{counter:012d}")

    return _next


@pytest.fixture()
def sample_document_bytes() -> bytes:
    """Return sample claim document content for testing."""
    return (
        b"Claim Number: CLM-2025-001234\n"
        b"Policy Number: POL-12345678\n"
        b"Claimant: Jane Smith\n"
        b"Date of Loss: 01/15/2025\n"
        b"Claim Type: auto\n"
        b"Description: Vehicle collision at intersection of Main St and 5th Ave.\n"
    )


@pytest.fixture()
def sample_invalid_document_bytes() -> bytes:
    """Return document content with missing/invalid fields for testing."""
    return (
        b"Subject: Insurance Inquiry\nDate: unknown\nNotes: Customer called about their policy.\n"
    )


@pytest.fixture()
def random_seed() -> Random:
    """Provide a deterministic Random instance seeded with 42."""
    return Random(42)
