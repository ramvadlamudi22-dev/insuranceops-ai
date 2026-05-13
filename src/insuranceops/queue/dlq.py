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
    removed: int = await client.lrem(QUEUE_DLQ, 1, payload_bytes)  # type: ignore[arg-type]
    if removed > 0:
        await client.lpush(QUEUE_READY, payload_bytes)  # type: ignore[misc]
        return True
    return False
