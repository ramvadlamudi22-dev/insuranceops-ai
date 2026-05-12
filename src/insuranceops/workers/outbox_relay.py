"""Outbox relay: drains tasks_outbox rows into Redis.

Polls the tasks_outbox table for rows where enqueued_at IS NULL and
scheduled_for <= now(). For immediate tasks, pushes to ready list.
For future tasks, adds to delayed ZSET. Updates enqueued_at on success.

Acquires a Postgres advisory lock so only one relay runs across all processes.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from insuranceops.observability.logging import get_logger
from insuranceops.observability.metrics import (
    outbox_drain_batch_seconds,
    outbox_drain_lag_seconds,
    queue_tasks_enqueued_total,
)
from insuranceops.queue.delayed_queue import schedule as schedule_delayed
from insuranceops.queue.reliable_queue import enqueue
from insuranceops.storage.repositories.outbox import OutboxRepository

logger = get_logger("worker.outbox_relay")

RELAY_INTERVAL_S = 2
# Postgres advisory lock ID for the outbox relay
OUTBOX_RELAY_LOCK_ID = 8675310


async def outbox_relay_loop(
    redis_client: redis.Redis,
    session_factory: async_sessionmaker[AsyncSession],
    shutdown_event: asyncio.Event,
) -> None:
    """Continuously drain the outbox into Redis."""
    logger.info("outbox_relay_started")

    while not shutdown_event.is_set():
        try:
            await _relay_batch(redis_client, session_factory)
        except Exception as e:
            logger.error("outbox_relay_error", error=str(e))

        # Wait with check for shutdown
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=RELAY_INTERVAL_S)
            break
        except asyncio.TimeoutError:
            pass

    logger.info("outbox_relay_stopped")


async def _relay_batch(
    redis_client: redis.Redis,
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Process one batch of outbox entries."""
    batch_start = time.perf_counter()
    relayed = 0

    async with session_factory() as session:
        # Try to acquire advisory lock
        result = await session.execute(
            text(f"SELECT pg_try_advisory_lock({OUTBOX_RELAY_LOCK_ID})")
        )
        acquired = result.scalar()

        if not acquired:
            return 0

        try:
            now = datetime.now(timezone.utc)
            repo = OutboxRepository(session)
            pending = await repo.get_pending(limit=100)

            for entry in pending:
                try:
                    payload = entry.payload
                    # Add claimed_at for reaper timeout tracking
                    payload["claimed_at"] = str(time.time())

                    if entry.scheduled_for <= now:
                        # Immediate: push to ready queue
                        await enqueue(redis_client, payload)
                    else:
                        # Future: add to delayed ZSET
                        await schedule_delayed(
                            redis_client, payload, entry.scheduled_for
                        )

                    # Mark as enqueued
                    await repo.mark_enqueued(entry.outbox_id, now)
                    relayed += 1

                    # Track lag
                    lag_s = (now - entry.created_at).total_seconds()
                    outbox_drain_lag_seconds.observe(lag_s)

                    # Track enqueue metrics
                    workflow_name = payload.get("workflow_name", "unknown")
                    step_name = payload.get("step_name", "unknown")
                    queue_tasks_enqueued_total.labels(
                        workflow_name=workflow_name,
                        step_name=step_name,
                    ).inc()

                except Exception as e:
                    logger.error(
                        "outbox_relay_entry_error",
                        outbox_id=entry.outbox_id,
                        error=str(e),
                    )
                    await repo.increment_attempts(entry.outbox_id, str(e))

            await session.commit()
        finally:
            # Release advisory lock
            await session.execute(
                text(f"SELECT pg_advisory_unlock({OUTBOX_RELAY_LOCK_ID})")
            )
            await session.commit()

    batch_duration = time.perf_counter() - batch_start
    if relayed > 0:
        outbox_drain_batch_seconds.observe(batch_duration)
        logger.info("outbox_relay_batch", relayed=relayed, duration_s=round(batch_duration, 3))

    return relayed
