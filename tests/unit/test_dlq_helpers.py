"""Tests for DLQ helper functions (dlq_count, get_dlq_entry, drop_from_dlq).

These tests use a mock Redis client to exercise the logic without
requiring a running Redis instance.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from insuranceops.queue.dlq import (
    QUEUE_DLQ,
    QUEUE_READY,
    dlq_count,
    drop_from_dlq,
    get_dlq_entry,
    list_dlq,
    move_to_dlq,
    requeue_from_dlq,
)


@pytest.fixture()
def mock_redis():
    """Create a mock async Redis client."""
    client = AsyncMock()
    return client


@pytest.fixture()
def sample_payload_bytes() -> bytes:
    """A realistic DLQ task payload."""
    payload = {
        "workflow_run_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "step_id": "11111111-2222-3333-4444-555555555555",
        "step_attempt_id": "66666666-7777-8888-9999-aaaaaaaaaaaa",
        "step_name": "extract",
        "handler_name": "extract",
        "workflow_name": "claim_intake",
        "attempt_number": 3,
        "max_attempts": 3,
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


class TestDlqCount:
    """Tests for dlq_count()."""

    @pytest.mark.asyncio
    async def test_returns_zero_when_empty(self, mock_redis):
        mock_redis.llen.return_value = 0
        result = await dlq_count(mock_redis)
        assert result == 0
        mock_redis.llen.assert_called_once_with(QUEUE_DLQ)

    @pytest.mark.asyncio
    async def test_returns_count(self, mock_redis):
        mock_redis.llen.return_value = 5
        result = await dlq_count(mock_redis)
        assert result == 5


class TestGetDlqEntry:
    """Tests for get_dlq_entry()."""

    @pytest.mark.asyncio
    async def test_returns_entry_at_index(self, mock_redis, sample_payload_bytes):
        mock_redis.lrange.return_value = [sample_payload_bytes]
        result = await get_dlq_entry(mock_redis, 0)
        assert result == sample_payload_bytes
        mock_redis.lrange.assert_called_once_with(QUEUE_DLQ, 0, 0)

    @pytest.mark.asyncio
    async def test_returns_none_for_out_of_range_index(self, mock_redis):
        mock_redis.lrange.return_value = []
        result = await get_dlq_entry(mock_redis, 99)
        assert result is None
        mock_redis.lrange.assert_called_once_with(QUEUE_DLQ, 99, 99)

    @pytest.mark.asyncio
    async def test_returns_entry_at_nonzero_index(self, mock_redis, sample_payload_bytes):
        mock_redis.lrange.return_value = [sample_payload_bytes]
        result = await get_dlq_entry(mock_redis, 3)
        assert result == sample_payload_bytes
        mock_redis.lrange.assert_called_once_with(QUEUE_DLQ, 3, 3)


class TestDropFromDlq:
    """Tests for drop_from_dlq()."""

    @pytest.mark.asyncio
    async def test_returns_true_when_entry_removed(self, mock_redis, sample_payload_bytes):
        mock_redis.lrem.return_value = 1
        result = await drop_from_dlq(mock_redis, sample_payload_bytes)
        assert result is True
        expected_str = sample_payload_bytes.decode("utf-8")
        mock_redis.lrem.assert_called_once_with(QUEUE_DLQ, 1, expected_str)

    @pytest.mark.asyncio
    async def test_returns_false_when_entry_not_found(self, mock_redis, sample_payload_bytes):
        mock_redis.lrem.return_value = 0
        result = await drop_from_dlq(mock_redis, sample_payload_bytes)
        assert result is False

    @pytest.mark.asyncio
    async def test_does_not_push_to_ready(self, mock_redis, sample_payload_bytes):
        """drop_from_dlq should NOT push to the ready queue."""
        mock_redis.lrem.return_value = 1
        await drop_from_dlq(mock_redis, sample_payload_bytes)
        mock_redis.lpush.assert_not_called()


class TestRequeueFromDlq:
    """Tests for requeue_from_dlq()."""

    @pytest.mark.asyncio
    async def test_returns_true_and_pushes_to_ready(self, mock_redis, sample_payload_bytes):
        mock_redis.lrem.return_value = 1
        result = await requeue_from_dlq(mock_redis, sample_payload_bytes)
        assert result is True
        mock_redis.lpush.assert_called_once_with(QUEUE_READY, sample_payload_bytes)

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self, mock_redis, sample_payload_bytes):
        mock_redis.lrem.return_value = 0
        result = await requeue_from_dlq(mock_redis, sample_payload_bytes)
        assert result is False
        mock_redis.lpush.assert_not_called()


class TestListDlq:
    """Tests for list_dlq()."""

    @pytest.mark.asyncio
    async def test_returns_entries(self, mock_redis, sample_payload_bytes):
        mock_redis.lrange.return_value = [sample_payload_bytes, sample_payload_bytes]
        result = await list_dlq(mock_redis, start=0, count=10)
        assert len(result) == 2
        mock_redis.lrange.assert_called_once_with(QUEUE_DLQ, 0, 9)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_entries(self, mock_redis):
        mock_redis.lrange.return_value = []
        result = await list_dlq(mock_redis, start=0, count=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_respects_start_offset(self, mock_redis, sample_payload_bytes):
        mock_redis.lrange.return_value = [sample_payload_bytes]
        await list_dlq(mock_redis, start=5, count=3)
        mock_redis.lrange.assert_called_once_with(QUEUE_DLQ, 5, 7)


class TestMoveToDlq:
    """Tests for move_to_dlq()."""

    @pytest.mark.asyncio
    async def test_pushes_to_dlq(self, mock_redis, sample_payload_bytes):
        mock_redis.lpush.return_value = 1
        result = await move_to_dlq(mock_redis, sample_payload_bytes)
        assert result == 1
        mock_redis.lpush.assert_called_once_with(QUEUE_DLQ, sample_payload_bytes)
