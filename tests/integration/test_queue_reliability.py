"""Integration tests for the reliable queue primitives.

Requires: Redis (via service containers or compose.test.yml).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from insuranceops.queue.delayed_queue import QUEUE_DELAYED, mature_tasks, schedule
from insuranceops.queue.dlq import QUEUE_DLQ, move_to_dlq
from insuranceops.queue.reliable_queue import (
    QUEUE_READY,
    ack,
    claim,
    enqueue,
    get_inflight,
)


@pytest.fixture()
async def redis_client():
    """Create a test Redis client and flush test keys after each test."""
    import redis.asyncio as redis

    client = redis.Redis.from_url("redis://localhost:6379/1", decode_responses=False)
    # Clean up queue keys before test
    await client.delete(QUEUE_READY, QUEUE_DELAYED, QUEUE_DLQ)
    yield client
    # Clean up after test
    await client.delete(QUEUE_READY, QUEUE_DELAYED, QUEUE_DLQ)
    keys = await client.keys("queue:tasks:inflight:*")
    if keys:
        await client.delete(*keys)
    await client.aclose()


@pytest.mark.integration
class TestQueueReliability:
    """Verify queue enqueue/claim/ACK cycle and edge cases."""

    async def test_enqueue_and_claim(self, redis_client) -> None:
        """Enqueued task can be claimed by worker."""
        payload = {"task_id": "test-1", "action": "process"}
        await enqueue(redis_client, payload)

        claimed = await claim(redis_client, "worker-1", timeout=1)
        assert claimed is not None
        assert claimed["task_id"] == "test-1"

    async def test_ack_removes_from_inflight(self, redis_client) -> None:
        """ACK removes task from inflight list."""
        payload = {"task_id": "test-2", "action": "process"}
        await enqueue(redis_client, payload)

        claimed = await claim(redis_client, "worker-1", timeout=1)
        assert claimed is not None

        # Get the raw bytes from inflight
        inflight = await get_inflight(redis_client, "worker-1")
        assert len(inflight) == 1

        # ACK the task
        removed = await ack(redis_client, "worker-1", inflight[0])
        assert removed == 1

        # Inflight should be empty
        inflight_after = await get_inflight(redis_client, "worker-1")
        assert len(inflight_after) == 0

    async def test_unclaimed_stays_in_ready(self, redis_client) -> None:
        """Task remains in ready queue until claimed."""
        payload = {"task_id": "test-3", "action": "wait"}
        await enqueue(redis_client, payload)

        # Check ready queue length
        length = await redis_client.llen(QUEUE_READY)
        assert length == 1

        # Try claiming with a very short timeout - should still get it
        claimed = await claim(redis_client, "worker-1", timeout=1)
        assert claimed is not None
        assert claimed["task_id"] == "test-3"

    async def test_delayed_task_matures(self, redis_client) -> None:
        """Task scheduled for past is moved to ready by scheduler."""
        payload = {"task_id": "test-4", "action": "delayed"}
        past = datetime(2020, 1, 1, tzinfo=UTC)
        await schedule(redis_client, payload, run_at=past)

        # Mature tasks with current time
        now = datetime.now(UTC)
        promoted = await mature_tasks(redis_client, now)
        assert promoted == 1

        # Should now be claimable
        claimed = await claim(redis_client, "worker-1", timeout=1)
        assert claimed is not None
        assert claimed["task_id"] == "test-4"

    async def test_dlq_on_max_attempts(self, redis_client) -> None:
        """Task exceeding max attempts goes to DLQ."""
        payload = {"task_id": "test-5", "action": "fail"}
        payload_bytes = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")

        # Simulate moving to DLQ after max attempts
        await move_to_dlq(redis_client, payload_bytes)

        # Verify it's in the DLQ
        dlq_items = await redis_client.lrange(QUEUE_DLQ, 0, -1)
        assert len(dlq_items) == 1
        assert json.loads(dlq_items[0]) == payload
