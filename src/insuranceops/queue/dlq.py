"""Dead letter queue operations.

Tasks that fail all retry attempts are moved to the DLQ for manual inspection.

Queue key:
    queue:tasks:dlq - dead letter queue list
"""

from __future__ import annotations

import redis.asyncio as redis

QUEUE_DLQ = "queue:tasks:dlq"
QUEUE_READY = "queue:tasks:ready"


async def move_to_dlq(client: redis.Redis, payload_bytes: bytes) -> int:
    """Move a failed task to the dead letter queue.

    Args:
        client: Async Redis client.
        payload_bytes: Raw task payload bytes.

    Returns:
        New length of the DLQ.
    """
    length: int = await client.lpush(QUEUE_DLQ, payload_bytes)  # type: ignore[misc]
    return length


async def list_dlq(client: redis.Redis, start: int = 0, count: int = 50) -> list[bytes]:
    """List entries in the dead letter queue.

    Args:
        client: Async Redis client.
        start: Start index (0-based).
        count: Number of entries to return.

    Returns:
        List of raw task payload bytes from the DLQ.
    """
    items: list[bytes] = await client.lrange(QUEUE_DLQ, start, start + count - 1)  # type: ignore[misc]
    return items


async def requeue_from_dlq(client: redis.Redis, payload_bytes: bytes) -> bool:
    """Move a task from the DLQ back to the ready queue.

    Args:
        client: Async Redis client.
        payload_bytes: The exact bytes of the DLQ entry to requeue.

    Returns:
        True if the item was found in DLQ and requeued, False otherwise.
    """
    value_str = payload_bytes.decode("utf-8") if isinstance(payload_bytes, bytes) else payload_bytes
    removed: int = await client.lrem(QUEUE_DLQ, 1, value_str)  # type: ignore[misc]
    if removed > 0:
        await client.lpush(QUEUE_READY, payload_bytes)  # type: ignore[misc]
        return True
    return False


async def dlq_count(client: redis.Redis) -> int:
    """Return the number of entries in the dead letter queue.

    Args:
        client: Async Redis client.

    Returns:
        Number of entries in the DLQ.
    """
    length: int = await client.llen(QUEUE_DLQ)  # type: ignore[misc]
    return length


async def get_dlq_entry(client: redis.Redis, index: int) -> bytes | None:
    """Get a single DLQ entry by index.

    Args:
        client: Async Redis client.
        index: 0-based index into the DLQ list.

    Returns:
        Raw task payload bytes at the given index, or None if index is out of range.
    """
    items: list[bytes] = await client.lrange(QUEUE_DLQ, index, index)  # type: ignore[misc]
    if not items:
        return None
    return items[0]


async def drop_from_dlq(client: redis.Redis, payload_bytes: bytes) -> bool:
    """Remove a task from the DLQ without requeueing.

    Args:
        client: Async Redis client.
        payload_bytes: The exact bytes of the DLQ entry to remove.

    Returns:
        True if the item was found and removed, False otherwise.
    """
    value_str = payload_bytes.decode("utf-8") if isinstance(payload_bytes, bytes) else payload_bytes
    removed: int = await client.lrem(QUEUE_DLQ, 1, value_str)  # type: ignore[misc]
    return removed > 0
