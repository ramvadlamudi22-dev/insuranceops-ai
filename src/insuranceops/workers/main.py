"""Worker process entrypoint.

Runs the main worker loop alongside the reaper, scheduler, and outbox relay
as concurrent async tasks.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import uuid

from insuranceops.config import Settings
from insuranceops.observability.logging import configure_logging, get_logger
from insuranceops.queue.redis_client import create_redis_pool
from insuranceops.storage.db import create_engine, create_session_factory
from insuranceops.workers.loop import worker_loop
from insuranceops.workers.outbox_relay import outbox_relay_loop
from insuranceops.workers.reaper import reaper_loop
from insuranceops.workers.scheduler import scheduler_loop

logger = get_logger("worker.main")


def parse_args() -> argparse.Namespace:
    """Parse worker CLI arguments."""
    parser = argparse.ArgumentParser(description="InsuranceOps Worker Process")
    parser.add_argument(
        "--worker-id",
        default=None,
        help="Unique worker ID (default: auto-generated UUID)",
    )
    parser.add_argument(
        "--no-reaper",
        action="store_true",
        help="Disable the reaper task",
    )
    parser.add_argument(
        "--no-scheduler",
        action="store_true",
        help="Disable the scheduler task",
    )
    parser.add_argument(
        "--no-outbox",
        action="store_true",
        help="Disable the outbox relay task",
    )
    return parser.parse_args()


async def run_worker(args: argparse.Namespace) -> None:
    """Run the worker with all background tasks."""
    settings = Settings()
    configure_logging(settings.LOG_LEVEL)

    worker_id = args.worker_id or str(uuid.uuid4())
    logger.info("worker_starting", worker_id=worker_id)

    # Setup connections
    engine = create_engine(settings.DATABASE_URL)
    session_factory = create_session_factory(engine)
    redis_client = await create_redis_pool(settings.REDIS_URL)

    # Shutdown signal
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("shutdown_signal_received")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # Start concurrent tasks
    tasks: list[asyncio.Task] = []

    tasks.append(
        asyncio.create_task(
            worker_loop(
                redis_client=redis_client,
                session_factory=session_factory,
                worker_id=worker_id,
                shutdown_event=shutdown_event,
                visibility_timeout_s=settings.WORKER_VISIBILITY_TIMEOUT_S,
            ),
            name="worker_loop",
        )
    )

    if not args.no_reaper:
        tasks.append(
            asyncio.create_task(
                reaper_loop(
                    redis_client=redis_client,
                    session_factory=session_factory,
                    shutdown_event=shutdown_event,
                    visibility_timeout_s=settings.WORKER_VISIBILITY_TIMEOUT_S,
                ),
                name="reaper_loop",
            )
        )

    if not args.no_scheduler:
        tasks.append(
            asyncio.create_task(
                scheduler_loop(
                    redis_client=redis_client,
                    session_factory=session_factory,
                    shutdown_event=shutdown_event,
                ),
                name="scheduler_loop",
            )
        )

    if not args.no_outbox:
        tasks.append(
            asyncio.create_task(
                outbox_relay_loop(
                    redis_client=redis_client,
                    session_factory=session_factory,
                    shutdown_event=shutdown_event,
                ),
                name="outbox_relay_loop",
            )
        )

    logger.info("worker_ready", worker_id=worker_id, task_count=len(tasks))

    # Wait for shutdown
    await shutdown_event.wait()

    # Cancel all tasks
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)

    # Cleanup
    await redis_client.aclose()
    await engine.dispose()

    logger.info("worker_stopped", worker_id=worker_id)


def main() -> None:
    """CLI entrypoint for the worker process."""
    args = parse_args()
    asyncio.run(run_worker(args))


if __name__ == "__main__":
    main()
