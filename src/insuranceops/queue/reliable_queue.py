"""Reliable queue primitives using Redis lists.

Queue keys:
    queue:tasks:ready                - main ready list (consumed via BRPOPLPUSH)
    queue:tasks:inflight:<worker_id> - per-worker inflight list
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

QUEUE_READY = "queue:tasks:ready"
QUEUE_INFLIGHT_PREFIX = "queue:tasks:inflight:"


def _inflight_key(worker_id: str) -> str:
    """Return the inflight list key for a worker."""
    return f"{QUEUE_INFLIGHT_PREFIX}{worker_id}"


async def enqueue(client: redis.Redis, payload: dict[str, Any]) -> int:
    """Push a task payload onto the ready queue.

    Args:
        client: Async Redis client.
        payload: Task payload dict (will be JSON-serialized).

    Returns:
        New length of the ready queue.
    """
    data = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    length: int = await client.lpush(QUEUE_READY, data)  # type: ignore[misc]
    return length


async def claim(client: redis.Redis, worker_id: str, timeout: int = 5) -> dict[str, Any] | None:
    """Claim a task from the ready queue via BRPOPLPUSH.

    Atomically moves a task from the ready queue to the worker's inflight list.
    Blocks up to `timeout` seconds if the queue is empty.

    Args:
        client: Async Redis client.
        worker_id: Unique worker identifier.
        timeout: Blocking timeout in seconds.

    Returns:
        Parsed task payload dict, or None if timeout elapsed.
    """
    result = await client.brpoplpush(QUEUE_READY, _inflight_key(worker_id), timeout=timeout)  # type: ignore[misc]
    if result is None:
        return None
    return json.loads(result)


async def ack(client: redis.Redis, worker_id: str, payload_bytes: bytes) -> int:
    """Acknowledge a completed task by removing it from the inflight list.

    Args:
        client: Async Redis client.
        worker_id: Worker that processed the task.
        payload_bytes: The raw bytes of the task (as received from claim).

    Returns:
        Number of elements removed (should be 1).
    """
    removed: int = await client.lrem(_inflight_key(worker_id), 1, payload_bytes)  # type: ignore[arg-type]
    return removed


async def get_inflight(client: redis.Redis, worker_id: str) -> list[bytes]:
    """Get all tasks in the worker's inflight list.

    Args:
        client: Async Redis client.
        worker_id: Worker identifier.

    Returns:
        List of raw task bytes currently inflight.
    """
    items: list[bytes] = await client.lrange(_inflight_key(worker_id), 0, -1)  # type: ignore[misc]
    return items


async def move_to_ready(client: redis.Redis, worker_id: str, payload_bytes: bytes) -> None:
    """Move a task from inflight back to the ready queue.

    Used by the reaper when a task exceeds visibility timeout.

    Args:
        client: Async Redis client.
        worker_id: Worker that held the task.
        payload_bytes: The raw bytes of the task.
    """
    await client.lrem(_inflight_key(worker_id), 1, payload_bytes)  # type: ignore[arg-type]
    await client.lpush(QUEUE_READY, payload_bytes)  # type: ignore[misc]
