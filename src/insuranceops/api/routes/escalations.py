"""Escalation routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.api.deps import get_db_session
from insuranceops.api.schemas.escalations import (
    EscalationClaimResponse,
    EscalationListResponse,
    EscalationResponse,
    RejectRequest,
    ResolveRequest,
)
from insuranceops.audit.chain import append_audit_event
from insuranceops.security.auth import ApiKeyPrincipal
from insuranceops.security.rbac import requires_role
from insuranceops.storage.models import (
    EscalationCaseModel,
    StepAttemptModel,
    WorkflowRunModel,
)

router = APIRouter(prefix="/v1/escalations", tags=["escalations"])


@router.get("", response_model=EscalationListResponse)
async def list_escalations(
    state: Optional[str] = Query(None),
    workflow_name: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    principal: ApiKeyPrincipal = Depends(
        requires_role("operator", "supervisor", "viewer")
    ),
) -> EscalationListResponse:
    """List escalation cases with optional filters and cursor pagination."""
    query = select(EscalationCaseModel).order_by(EscalationCaseModel.created_at)

    if state:
        query = query.where(EscalationCaseModel.state == state)

    if workflow_name:
        query = query.join(
            WorkflowRunModel,
            EscalationCaseModel.workflow_run_id == WorkflowRunModel.workflow_run_id,
        ).where(WorkflowRunModel.workflow_name == workflow_name)

    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            query = query.where(EscalationCaseModel.created_at > cursor_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    query = query.limit(limit + 1)
    result = await session.execute(query)
    cases = list(result.scalars().all())

    has_next = len(cases) > limit
    if has_next:
        cases = cases[:limit]

    next_cursor = cases[-1].created_at.isoformat() if has_next and cases else None

    return EscalationListResponse(
        escalations=[
            EscalationResponse(
                escalation_id=c.escalation_id,
                workflow_run_id=c.workflow_run_id,
                step_id=c.step_id,
                state=c.state,
                reason_code=c.reason_code,
                reason_detail=c.reason_detail,
                claimed_by=c.claimed_by,
                claimed_at=c.claimed_at,
                resolved_by=c.resolved_by,
                resolved_at=c.resolved_at,
                resolution_payload=c.resolution_payload,
                expires_at=c.expires_at,
                created_at=c.created_at,
            )
            for c in cases
        ],
        next_cursor=next_cursor,
    )


@router.post(
    "/{escalation_id}/claim",
    response_model=EscalationClaimResponse,
)
async def claim_escalation(
    escalation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    principal: ApiKeyPrincipal = Depends(requires_role("operator", "supervisor")),
) -> EscalationClaimResponse:
    """Atomically claim an open escalation with optimistic guard."""
    now = datetime.now(timezone.utc)

    # Atomic claim: update only if state is 'open'
    stmt = (
        update(EscalationCaseModel)
        .where(
            EscalationCaseModel.escalation_id == escalation_id,
            EscalationCaseModel.state == "open",
        )
        .values(
            state="claimed",
            claimed_by=principal.actor_string,
            claimed_at=now,
        )
    )
    result = await session.execute(stmt)

    if result.rowcount == 0:  # type: ignore[union-attr]
        # Check if escalation exists at all
        check = await session.execute(
            select(EscalationCaseModel).where(
                EscalationCaseModel.escalation_id == escalation_id
            )
        )
        esc = check.scalar_one_or_none()
        if esc is None:
            raise HTTPException(status_code=404, detail="Escalation not found")
        raise HTTPException(
            status_code=409,
            detail=f"Escalation is in state '{esc.state}' and cannot be claimed",
        )

    await append_audit_event(
        session=session,
        workflow_run_id=(
            await session.execute(
                select(EscalationCaseModel.workflow_run_id).where(
                    EscalationCaseModel.escalation_id == escalation_id
                )
            )
        ).scalar_one(),
        event_type="escalation.claimed",
        actor=principal.actor_string,
        payload={"escalation_id": str(escalation_id)},
    )

    return EscalationClaimResponse(
        escalation_id=escalation_id,
        state="claimed",
        claimed_by=principal.actor_string,
        claimed_at=now,
    )


@router.post(
    "/{escalation_id}/resolve",
    response_model=EscalationResponse,
)
async def resolve_escalation(
    escalation_id: uuid.UUID,
    body: ResolveRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: ApiKeyPrincipal = Depends(requires_role("operator", "supervisor")),
) -> EscalationResponse:
    """Resolve a claimed escalation, create synthetic StepAttempt, resume WorkflowRun."""
    result = await session.execute(
        select(EscalationCaseModel).where(
            EscalationCaseModel.escalation_id == escalation_id
        )
    )
    esc = result.scalar_one_or_none()
    if esc is None:
        raise HTTPException(status_code=404, detail="Escalation not found")

    if esc.state != "claimed":
        raise HTTPException(
            status_code=409,
            detail=f"Escalation in state '{esc.state}' cannot be resolved",
        )
    if esc.claimed_by != principal.actor_string:
        raise HTTPException(
            status_code=403,
            detail="Escalation is claimed by a different actor",
        )

    now = datetime.now(timezone.utc)

    # Update escalation
    esc.state = "resolved"
    esc.resolved_by = principal.actor_string
    esc.resolved_at = now
    esc.resolution_payload = {
        "approve": body.approve,
        "override": body.override,
        "notes": body.notes,
    }

    # Create synthetic step attempt (human resolution)
    step_attempt_id = uuid.uuid4()
    synthetic_attempt = StepAttemptModel(
        step_attempt_id=step_attempt_id,
        step_id=esc.step_id,
        step_attempt_number=99,  # synthetic
        state="succeeded",
        origin="human",
        started_at=now,
        ended_at=now,
        created_at=now,
    )
    session.add(synthetic_attempt)

    # Resume workflow run - transition from awaiting_human back to running
    run_result = await session.execute(
        select(WorkflowRunModel).where(
            WorkflowRunModel.workflow_run_id == esc.workflow_run_id
        )
    )
    run = run_result.scalar_one_or_none()
    if run and run.state == "awaiting_human":
        run.state = "running"
        run.version += 1
        run.updated_at = now

    await session.flush()

    # Audit
    await append_audit_event(
        session=session,
        workflow_run_id=esc.workflow_run_id,
        event_type="escalation.resolved",
        actor=principal.actor_string,
        payload={
            "escalation_id": str(escalation_id),
            "notes": body.notes,
        },
        step_id=esc.step_id,
        step_attempt_id=step_attempt_id,
    )

    from insuranceops.observability.metrics import escalations_resolved_total

    escalations_resolved_total.labels(
        workflow_name="unknown",
        resolution="resolved",
    ).inc()

    return EscalationResponse(
        escalation_id=esc.escalation_id,
        workflow_run_id=esc.workflow_run_id,
        step_id=esc.step_id,
        state=esc.state,
        reason_code=esc.reason_code,
        reason_detail=esc.reason_detail,
        claimed_by=esc.claimed_by,
        claimed_at=esc.claimed_at,
        resolved_by=esc.resolved_by,
        resolved_at=esc.resolved_at,
        resolution_payload=esc.resolution_payload,
        expires_at=esc.expires_at,
        created_at=esc.created_at,
    )


@router.post(
    "/{escalation_id}/reject",
    response_model=EscalationResponse,
)
async def reject_escalation(
    escalation_id: uuid.UUID,
    body: RejectRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: ApiKeyPrincipal = Depends(requires_role("operator", "supervisor")),
) -> EscalationResponse:
    """Reject a claimed escalation, transition WorkflowRun to failed."""
    result = await session.execute(
        select(EscalationCaseModel).where(
            EscalationCaseModel.escalation_id == escalation_id
        )
    )
    esc = result.scalar_one_or_none()
    if esc is None:
        raise HTTPException(status_code=404, detail="Escalation not found")

    if esc.state != "claimed":
        raise HTTPException(
            status_code=409,
            detail=f"Escalation in state '{esc.state}' cannot be rejected",
        )
    if esc.claimed_by != principal.actor_string:
        raise HTTPException(
            status_code=403,
            detail="Escalation is claimed by a different actor",
        )

    now = datetime.now(timezone.utc)

    # Update escalation
    esc.state = "rejected"
    esc.resolved_by = principal.actor_string
    esc.resolved_at = now
    esc.resolution_payload = {
        "reason_code": body.reason_code,
        "notes": body.notes,
    }

    # Transition workflow run to failed
    run_result = await session.execute(
        select(WorkflowRunModel).where(
            WorkflowRunModel.workflow_run_id == esc.workflow_run_id
        )
    )
    run = run_result.scalar_one_or_none()
    if run and run.state in ("running", "awaiting_human"):
        run.state = "failed"
        run.version += 1
        run.updated_at = now
        run.last_error_code = "ESCALATION_REJECTED"
        run.last_error_detail = body.notes

    await session.flush()

    # Audit
    await append_audit_event(
        session=session,
        workflow_run_id=esc.workflow_run_id,
        event_type="escalation.rejected",
        actor=principal.actor_string,
        payload={
            "escalation_id": str(escalation_id),
            "reason_code": body.reason_code,
            "notes": body.notes,
        },
        step_id=esc.step_id,
    )

    from insuranceops.observability.metrics import workflow_runs_completed_total

    if run:
        workflow_runs_completed_total.labels(
            workflow_name=run.workflow_name,
            workflow_version=run.workflow_version,
            terminal_state="failed",
        ).inc()

    return EscalationResponse(
        escalation_id=esc.escalation_id,
        workflow_run_id=esc.workflow_run_id,
        step_id=esc.step_id,
        state=esc.state,
        reason_code=esc.reason_code,
        reason_detail=esc.reason_detail,
        claimed_by=esc.claimed_by,
        claimed_at=esc.claimed_at,
        resolved_by=esc.resolved_by,
        resolved_at=esc.resolved_at,
        resolution_payload=esc.resolution_payload,
        expires_at=esc.expires_at,
        created_at=esc.created_at,
    )
