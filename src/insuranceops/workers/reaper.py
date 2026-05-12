"""Reaper: reclaims stuck tasks past visibility timeout.

Periodically scans all inflight lists. For tasks older than
visibility_timeout, moves them back to ready (or to DLQ if max_attempts
exceeded). Emits AuditEvent for reaped tasks.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from insuranceops.observability.logging import get_logger
from insuranceops.observability.metrics import queue_reaper_reclaimed_total
from insuranceops.queue.dlq import move_to_dlq
from insuranceops.queue.reliable_queue import QUEUE_INFLIGHT_PREFIX, move_to_ready

logger = get_logger("worker.reaper")

REAPER_INTERVAL_S = 15


async def reaper_loop(
    redis_client: redis.Redis,
    session_factory: async_sessionmaker[AsyncSession],
    shutdown_event: asyncio.Event,
    visibility_timeout_s: int = 60,
) -> None:
    """Periodically scan inflight lists and reclaim stuck tasks."""
    logger.info("reaper_started")

    while not shutdown_event.is_set():
        try:
            reclaimed = await _reap_stuck_tasks(
                redis_client=redis_client,
                session_factory=session_factory,
                visibility_timeout_s=visibility_timeout_s,
            )
            if reclaimed > 0:
                logger.info("reaper_reclaimed", count=reclaimed)
        except Exception as e:
            logger.error("reaper_error", error=str(e))

        # Wait with check for shutdown
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=REAPER_INTERVAL_S)
            break  # shutdown requested
        except asyncio.TimeoutError:
            pass  # normal timeout, continue loop

    logger.info("reaper_stopped")


async def _reap_stuck_tasks(
    redis_client: redis.Redis,
    session_factory: async_sessionmaker[AsyncSession],
    visibility_timeout_s: int,
) -> int:
    """Scan all inflight lists and move stuck tasks back to ready or DLQ."""
    reclaimed = 0

    # Find all inflight keys
    pattern = f"{QUEUE_INFLIGHT_PREFIX}*"
    keys: list[bytes] = []
    async for key in redis_client.scan_iter(match=pattern, count=100):
        keys.append(key)

    now = time.time()

    for key in keys:
        items: list[bytes] = await redis_client.lrange(key, 0, -1)
        worker_id = key.decode("utf-8").removeprefix(QUEUE_INFLIGHT_PREFIX)

        for item in items:
            try:
                payload = json.loads(item)
            except (json.JSONDecodeError, ValueError):
                # Malformed payload - move to DLQ
                await redis_client.lrem(key, 1, item)
                await move_to_dlq(redis_client, item)
                reclaimed += 1
                continue

            # Check if task has a claimed_at timestamp
            claimed_at = payload.get("claimed_at")
            if claimed_at is None:
                # No timestamp - assume stuck, reclaim
                await move_to_ready(redis_client, worker_id, item)
                reclaimed += 1
                queue_reaper_reclaimed_total.inc()
                continue

            age = now - float(claimed_at)
            if age > visibility_timeout_s:
                # Check attempt count for DLQ threshold
                attempt_number = payload.get("attempt_number", 1)
                max_attempts = payload.get("max_attempts", 3)

                if attempt_number >= max_attempts:
                    # Move to DLQ
                    await redis_client.lrem(key, 1, item)
                    await move_to_dlq(redis_client, item)
                    logger.info(
                        "reaper_moved_to_dlq",
                        worker_id=worker_id,
                        step_name=payload.get("step_name"),
                    )
                else:
                    # Move back to ready
                    await move_to_ready(redis_client, worker_id, item)
                    logger.info(
                        "reaper_reclaimed_task",
                        worker_id=worker_id,
                        step_name=payload.get("step_name"),
                        age_s=round(age, 1),
                    )

                reclaimed += 1
                queue_reaper_reclaimed_total.inc()

    return reclaimed
