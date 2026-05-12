"""Delayed queue using Redis sorted sets.

Tasks scheduled for future execution are stored in a ZSET scored by
epoch milliseconds. A scheduler periodically promotes mature tasks to
the ready list.

Queue key:
    queue:tasks:delayed - sorted set scored by due timestamp (epoch ms)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import redis.asyncio as redis

QUEUE_DELAYED = "queue:tasks:delayed"
QUEUE_READY = "queue:tasks:ready"


def _epoch_ms(dt: datetime) -> float:
    """Convert datetime to epoch milliseconds."""
    return dt.timestamp() * 1000.0


async def schedule(client: redis.Redis, payload: dict[str, Any], run_at: datetime) -> int:
    """Schedule a task for future execution.

    Args:
        client: Async Redis client.
        payload: Task payload dict.
        run_at: When the task should become ready.

    Returns:
        Number of elements added (1 if new, 0 if updated).
    """
    data = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    score = _epoch_ms(run_at)
    added: int = await client.zadd(QUEUE_DELAYED, {data: score})
    return added


async def mature_tasks(client: redis.Redis, now: datetime, batch_size: int = 200) -> int:
    """Move tasks that are due from the delayed ZSET to the ready list.

    Uses ZPOPMIN in a loop for atomic removal from the sorted set,
    preventing duplicate enqueue when multiple schedulers run concurrently.

    Args:
        client: Async Redis client.
        now: Current time (tasks with score <= now are mature).
        batch_size: Maximum tasks to promote in one call.

    Returns:
        Number of tasks promoted to the ready list.
    """
    max_score = _epoch_ms(now)
    promoted = 0

    while promoted < batch_size:
        # ZPOPMIN atomically removes the lowest-scored element
        results = await client.zpopmin(QUEUE_DELAYED, count=1)
        if not results:
            break

        item, score = results[0]
        if score > max_score:
            # Item is not yet mature; put it back and stop
            await client.zadd(QUEUE_DELAYED, {item: score})
            break

        # Push to ready queue
        await client.lpush(QUEUE_READY, item)
        promoted += 1

    return promoted
