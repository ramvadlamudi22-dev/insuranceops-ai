"""Scheduler: promotes mature delayed tasks to the ready queue.

Acquires a Postgres advisory lock so only one scheduler runs across
all worker processes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from insuranceops.observability.logging import get_logger
from insuranceops.queue.delayed_queue import mature_tasks

logger = get_logger("worker.scheduler")

SCHEDULER_INTERVAL_S = 5
# Postgres advisory lock ID for the scheduler (arbitrary but fixed)
SCHEDULER_LOCK_ID = 8675309


async def scheduler_loop(
    redis_client: redis.Redis,
    session_factory: async_sessionmaker[AsyncSession],
    shutdown_event: asyncio.Event,
) -> None:
    """Periodically promote mature tasks from delayed queue to ready."""
    logger.info("scheduler_started")

    while not shutdown_event.is_set():
        try:
            async with session_factory() as session:
                # Try to acquire advisory lock (non-blocking)
                result = await session.execute(
                    text(f"SELECT pg_try_advisory_lock({SCHEDULER_LOCK_ID})")
                )
                acquired = result.scalar()

                if acquired:
                    try:
                        now = datetime.now(timezone.utc)
                        promoted = await mature_tasks(
                            redis_client, now, batch_size=200
                        )
                        if promoted > 0:
                            logger.info("scheduler_promoted", count=promoted)
                    finally:
                        # Release advisory lock
                        await session.execute(
                            text(f"SELECT pg_advisory_unlock({SCHEDULER_LOCK_ID})")
                        )
                        await session.commit()
                else:
                    logger.debug("scheduler_lock_held_by_other")

        except Exception as e:
            logger.error("scheduler_error", error=str(e))

        # Wait with check for shutdown
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=SCHEDULER_INTERVAL_S)
            break
        except asyncio.TimeoutError:
            pass

    logger.info("scheduler_stopped")
