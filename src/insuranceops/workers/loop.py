"""Main worker loop: claim-process-ACK pattern.

Per SYSTEM_ARCHITECTURE.md section 14.2:
1. BRPOPLPUSH from ready to inflight
2. Parse payload, load StepAttempt/Step/WorkflowRun from DB
3. Validate state (abort if already succeeded/terminal)
4. Execute step handler
5. Write outcome + AuditEvent in single transaction
6. ACK from Redis (LREM from inflight)
7. Handle errors: retryable -> reschedule, terminal -> DLQ/escalate
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from insuranceops.audit.chain import append_audit_event
from insuranceops.observability.logging import bind_context, get_logger
from insuranceops.observability.metrics import (
    queue_tasks_acked_total,
    step_attempt_duration_seconds,
    step_attempts_total,
)
from insuranceops.queue.dlq import move_to_dlq
from insuranceops.queue.reliable_queue import QUEUE_INFLIGHT_PREFIX, ack
from insuranceops.storage.models import StepAttemptModel, StepModel, WorkflowRunModel
from insuranceops.storage.repositories.step_attempts import StepAttemptRepository
from insuranceops.storage.repositories.steps import StepRepository
from insuranceops.storage.repositories.workflow_runs import WorkflowRunRepository

logger = get_logger("worker.loop")

# Heartbeat key pattern
HEARTBEAT_PREFIX = "queue:workers:heartbeat:"
HEARTBEAT_TTL_S = 30
HEARTBEAT_INTERVAL_S = 10


async def worker_loop(
    redis_client: redis.Redis,
    session_factory: async_sessionmaker[AsyncSession],
    worker_id: str,
    shutdown_event: asyncio.Event,
    visibility_timeout_s: int = 60,
) -> None:
    """Main worker loop: claim tasks and process them."""
    logger.info("worker_loop_started", worker_id=worker_id)
    last_heartbeat = 0.0

    while not shutdown_event.is_set():
        # Heartbeat
        now = time.time()
        if now - last_heartbeat > HEARTBEAT_INTERVAL_S:
            await redis_client.set(
                f"{HEARTBEAT_PREFIX}{worker_id}",
                str(int(now)),
                ex=HEARTBEAT_TTL_S,
            )
            last_heartbeat = now

        # Claim task with short timeout so we can check shutdown
        result = await redis_client.brpoplpush(
            "queue:tasks:ready",
            f"{QUEUE_INFLIGHT_PREFIX}{worker_id}",
            timeout=2,
        )

        if result is None:
            continue

        payload_bytes: bytes = result
        try:
            payload = json.loads(payload_bytes)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("invalid_task_payload", error=str(e))
            await move_to_dlq(redis_client, payload_bytes)
            await ack(redis_client, worker_id, payload_bytes)
            continue

        # Process the task
        await _process_task(
            redis_client=redis_client,
            session_factory=session_factory,
            worker_id=worker_id,
            payload=payload,
            payload_bytes=payload_bytes,
        )

    logger.info("worker_loop_stopped", worker_id=worker_id)


async def _process_task(
    redis_client: redis.Redis,
    session_factory: async_sessionmaker[AsyncSession],
    worker_id: str,
    payload: dict[str, Any],
    payload_bytes: bytes,
) -> None:
    """Process a single claimed task."""
    workflow_run_id_str = payload.get("workflow_run_id")
    step_id_str = payload.get("step_id")
    step_attempt_id_str = payload.get("step_attempt_id")
    step_name = payload.get("step_name", "unknown")
    workflow_name = payload.get("workflow_name", "unknown")

    bind_context(
        workflow_run_id=workflow_run_id_str or "",
        step_id=step_id_str or "",
        step_attempt_id=step_attempt_id_str or "",
        actor=f"worker:main:{worker_id}",
    )

    logger.info("task_claimed", step_name=step_name, workflow_name=workflow_name)
    start_time = time.perf_counter()

    try:
        async with session_factory() as session:
            # Load entities
            step_attempt_id = UUID(step_attempt_id_str) if step_attempt_id_str else None
            step_id = UUID(step_id_str) if step_id_str else None
            workflow_run_id = UUID(workflow_run_id_str) if workflow_run_id_str else None

            if not all([step_attempt_id, step_id, workflow_run_id]):
                logger.error("task_missing_ids", payload=payload)
                await move_to_dlq(redis_client, payload_bytes)
                await ack(redis_client, worker_id, payload_bytes)
                return

            attempt_repo = StepAttemptRepository(session)
            step_repo = StepRepository(session)
            run_repo = WorkflowRunRepository(session)

            attempt = await attempt_repo.get_by_id(step_attempt_id)
            step = await step_repo.get_by_id(step_id)
            run = await run_repo.get_by_id(workflow_run_id)

            if not all([attempt, step, run]):
                logger.error("task_entities_not_found")
                await move_to_dlq(redis_client, payload_bytes)
                await ack(redis_client, worker_id, payload_bytes)
                return

            # Validate state - skip if already terminal
            if attempt.state in ("succeeded", "failed_terminal", "skipped"):
                logger.warn("task_already_terminal", state=attempt.state)
                await ack(redis_client, worker_id, payload_bytes)
                return

            # Mark attempt as in_progress
            attempt.state = "in_progress"
            attempt.started_at = datetime.now(timezone.utc)
            await session.flush()

            # Execute step handler
            outcome = await _execute_step_handler(
                step_name=step.step_name,
                workflow_run_id=workflow_run_id,
                step_id=step_id,
                step_attempt_id=step_attempt_id,
                payload=payload,
            )

            now = datetime.now(timezone.utc)

            # Write outcome
            if outcome["status"] == "success":
                attempt.state = "succeeded"
                attempt.ended_at = now
                attempt.output_ref = outcome.get("output_ref")
                step.state = "succeeded"
                step.ended_at = now

                await append_audit_event(
                    session=session,
                    workflow_run_id=workflow_run_id,
                    event_type="step_attempt.succeeded",
                    actor=f"worker:main:{worker_id}",
                    payload={"step_name": step_name, "outcome": "success"},
                    step_id=step_id,
                    step_attempt_id=step_attempt_id,
                )

                step_attempts_total.labels(
                    workflow_name=workflow_name, step_name=step_name, outcome="success"
                ).inc()

            elif outcome["status"] == "fail_retryable":
                attempt.state = "failed_retryable"
                attempt.ended_at = now
                attempt.error_code = outcome.get("error_code", "UNKNOWN")
                attempt.error_detail = outcome.get("error_detail", "")
                step.state = "failed_retryable"

                await append_audit_event(
                    session=session,
                    workflow_run_id=workflow_run_id,
                    event_type="step_attempt.failed_retryable",
                    actor=f"worker:main:{worker_id}",
                    payload={
                        "step_name": step_name,
                        "error_code": outcome.get("error_code"),
                        "error_detail": outcome.get("error_detail"),
                    },
                    step_id=step_id,
                    step_attempt_id=step_attempt_id,
                )

                step_attempts_total.labels(
                    workflow_name=workflow_name,
                    step_name=step_name,
                    outcome="fail_retryable",
                ).inc()

            elif outcome["status"] == "fail_terminal":
                attempt.state = "failed_terminal"
                attempt.ended_at = now
                attempt.error_code = outcome.get("error_code", "UNKNOWN")
                attempt.error_detail = outcome.get("error_detail", "")
                step.state = "failed_terminal"
                step.ended_at = now

                await append_audit_event(
                    session=session,
                    workflow_run_id=workflow_run_id,
                    event_type="step_attempt.failed_terminal",
                    actor=f"worker:main:{worker_id}",
                    payload={
                        "step_name": step_name,
                        "error_code": outcome.get("error_code"),
                        "error_detail": outcome.get("error_detail"),
                    },
                    step_id=step_id,
                    step_attempt_id=step_attempt_id,
                )

                step_attempts_total.labels(
                    workflow_name=workflow_name,
                    step_name=step_name,
                    outcome="fail_terminal",
                ).inc()

            await session.commit()

        # ACK from Redis after successful DB commit
        await ack(redis_client, worker_id, payload_bytes)

        duration = time.perf_counter() - start_time
        step_attempt_duration_seconds.labels(
            workflow_name=workflow_name, step_name=step_name
        ).observe(duration)
        queue_tasks_acked_total.labels(
            workflow_name=workflow_name,
            step_name=step_name,
            outcome=outcome["status"],
        ).inc()

        logger.info(
            "task_completed",
            outcome=outcome["status"],
            duration_s=round(duration, 3),
        )

    except Exception as e:
        logger.error(
            "task_processing_error",
            error=str(e),
            traceback=traceback.format_exc(),
        )
        # On unhandled error, leave in inflight for reaper to pick up
        # This ensures at-least-once delivery


async def _execute_step_handler(
    step_name: str,
    workflow_run_id: UUID,
    step_id: UUID,
    step_attempt_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Execute the appropriate step handler via the handler registry.

    Builds a StepContext from the payload and dispatches to the registered
    handler based on the handler_name field in the task payload.

    Returns:
        Dict with 'status' key: 'success', 'fail_retryable', or 'fail_terminal'
    """
    from insuranceops.workflows.steps.base import StepContext, StepResult
    from insuranceops.workflows.steps.handler_registry import get_handler

    handler_name = payload.get("handler_name", step_name)

    # Build StepContext from task payload
    document_ids_raw = payload.get("document_ids", [])
    document_ids = [UUID(d) if isinstance(d, str) else d for d in document_ids_raw]

    context = StepContext(
        workflow_run_id=workflow_run_id,
        step_id=step_id,
        step_attempt_id=step_attempt_id,
        step_name=step_name,
        workflow_name=payload.get("workflow_name", "unknown"),
        document_ids=document_ids,
        correlation_id=payload.get("correlation_id", ""),
    )

    try:
        handler = get_handler(handler_name)
    except KeyError:
        logger.error("handler_not_found", handler_name=handler_name)
        return {
            "status": "fail_terminal",
            "error_code": "HANDLER_NOT_FOUND",
            "error_detail": f"No handler registered for '{handler_name}'",
        }

    try:
        # Handlers that need a session will get one via their own mechanism;
        # pass None since the worker session is managed at _process_task level.
        result: StepResult = await handler.handle(context, None)  # type: ignore[arg-type]
    except Exception as e:
        logger.error("handler_exception", handler_name=handler_name, error=str(e))
        return {
            "status": "fail_retryable",
            "error_code": "HANDLER_EXCEPTION",
            "error_detail": str(e),
        }

    # Map StepResult to the dict format expected by _process_task
    if result.status == "succeeded":
        return {
            "status": "success",
            "output_ref": result.output,
        }
    elif result.status == "failed_retryable":
        return {
            "status": "fail_retryable",
            "error_code": result.error_code,
            "error_detail": result.error_detail,
        }
    elif result.status == "escalate":
        return {
            "status": "fail_terminal",
            "error_code": result.error_code or "ESCALATION_REQUESTED",
            "error_detail": result.error_detail,
        }
    else:
        # failed_terminal
        return {
            "status": "fail_terminal",
            "error_code": result.error_code,
            "error_detail": result.error_detail,
        }
