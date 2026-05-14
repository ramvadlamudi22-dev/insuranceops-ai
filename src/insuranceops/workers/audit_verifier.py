"""Scheduled audit-chain verifier.

Periodically selects a random sample of terminal workflow runs and
verifies their audit event hash chains using the existing verify_chain()
function. On mismatch, logs at CRITICAL and increments the
audit_chain_mismatches_total metric.

This is a read-only background task. It does not modify any state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from insuranceops.audit.verifier import VerificationResult, verify_chain
from insuranceops.observability.logging import get_logger
from insuranceops.storage.models import WorkflowRunModel

logger = get_logger("worker.audit_verifier")

# Terminal states eligible for verification
_TERMINAL_STATES = ("completed", "failed", "cancelled")


async def audit_verifier_loop(
    session_factory: async_sessionmaker[AsyncSession],
    shutdown_event: asyncio.Event,
    interval_s: int = 3600,
    sample_size: int = 10,
) -> None:
    """Periodically verify audit chains for a sample of terminal workflow runs.

    Args:
        session_factory: Async session factory for database access.
        shutdown_event: Event that signals graceful shutdown.
        interval_s: Seconds between verification cycles.
        sample_size: Number of workflow runs to verify per cycle.
    """
    logger.info(
        "audit_verifier_started",
        interval_s=interval_s,
        sample_size=sample_size,
    )

    while not shutdown_event.is_set():
        try:
            verified, failed = await _verify_sample(session_factory, sample_size)
            if failed > 0:
                logger.critical(
                    "audit_verifier_mismatches_detected",
                    verified=verified,
                    failed=failed,
                )
            elif verified > 0:
                logger.info("audit_verifier_cycle_complete", verified=verified, failed=0)
            else:
                logger.debug("audit_verifier_no_runs_to_verify")
        except Exception as e:
            logger.error("audit_verifier_error", error=str(e))

        # Wait with check for shutdown
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval_s)
            break  # shutdown requested
        except TimeoutError:
            pass  # normal timeout, continue loop

    logger.info("audit_verifier_stopped")


async def _verify_sample(
    session_factory: async_sessionmaker[AsyncSession],
    sample_size: int,
) -> tuple[int, int]:
    """Verify a random sample of terminal workflow runs.

    Returns:
        Tuple of (verified_count, failed_count).
    """
    verified = 0
    failed = 0

    async with session_factory() as session:
        run_ids = await _sample_terminal_runs(session, sample_size)

    for run_id in run_ids:
        async with session_factory() as session:
            result = await verify_chain(session, run_id)

        if result.is_valid:
            verified += 1
        else:
            failed += 1
            logger.critical(
                "audit_chain_mismatch",
                workflow_run_id=str(run_id),
                detail=result.detail,
                first_mismatch_index=result.first_mismatch_index,
            )

    return verified, failed


async def _sample_terminal_runs(
    session: AsyncSession,
    sample_size: int,
) -> Sequence[UUID]:
    """Select a random sample of terminal workflow run IDs.

    Args:
        session: Active async session.
        sample_size: Maximum number of runs to select.

    Returns:
        Sequence of workflow_run_id values.
    """
    result = await session.execute(
        select(WorkflowRunModel.workflow_run_id)
        .where(WorkflowRunModel.state.in_(_TERMINAL_STATES))
        .order_by(func.random())
        .limit(sample_size)
    )
    return list(result.scalars().all())


async def verify_batch(
    session_factory: async_sessionmaker[AsyncSession],
    sample_size: int | None = None,
    state_filter: str | None = None,
) -> list[tuple[UUID, VerificationResult]]:
    """On-demand batch verification for opsctl.

    Args:
        session_factory: Async session factory.
        sample_size: Max runs to verify (None = all matching, capped at 1000).
        state_filter: Filter by state (None = all terminal states).

    Returns:
        List of (workflow_run_id, VerificationResult) tuples.
    """
    effective_limit = min(sample_size or 1000, 1000)
    states = (state_filter,) if state_filter else _TERMINAL_STATES

    async with session_factory() as session:
        result = await session.execute(
            select(WorkflowRunModel.workflow_run_id)
            .where(WorkflowRunModel.state.in_(states))
            .order_by(WorkflowRunModel.created_at.desc())
            .limit(effective_limit)
        )
        run_ids = list(result.scalars().all())

    results: list[tuple[UUID, VerificationResult]] = []
    for run_id in run_ids:
        async with session_factory() as session:
            vr = await verify_chain(session, run_id)
        results.append((run_id, vr))

    return results
