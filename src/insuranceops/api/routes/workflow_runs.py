"""Workflow run routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.api.deps import get_db_session
from insuranceops.api.schemas.workflow_runs import (
    AuditEventResponse,
    CancelRequest,
    WorkflowRunCreate,
    WorkflowRunEventsResponse,
    WorkflowRunResponse,
)
from insuranceops.audit.chain import append_audit_event
from insuranceops.security.auth import ApiKeyPrincipal
from insuranceops.security.rbac import requires_role
from insuranceops.storage.models import (
    StepAttemptModel,
    StepModel,
    TasksOutboxModel,
    WorkflowRunDocumentModel,
    WorkflowRunModel,
)
from insuranceops.storage.repositories.audit import AuditRepository
from insuranceops.storage.repositories.workflow_runs import WorkflowRunRepository

router = APIRouter(prefix="/v1/workflow-runs", tags=["workflow-runs"])

# Simple workflow registry for Phase 1 - maps workflow_name to step definitions
WORKFLOW_REGISTRY: dict[str, dict] = {
    "document_processing": {
        "version": "1.0.0",
        "steps": [
            {"name": "extract", "max_attempts": 3, "escalate_on_failure": True},
            {"name": "validate", "max_attempts": 2, "escalate_on_failure": True},
            {"name": "enrich", "max_attempts": 3, "escalate_on_failure": False},
        ],
        "deadline_hours": 24,
    },
}


@router.post(
    "",
    response_model=WorkflowRunResponse,
    status_code=201,
)
async def create_workflow_run(
    body: WorkflowRunCreate,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    principal: ApiKeyPrincipal = Depends(requires_role("operator", "supervisor")),
) -> WorkflowRunResponse:
    """Create a new workflow run with steps, first step attempt, and outbox entry."""
    # Validate workflow exists
    workflow_def = WORKFLOW_REGISTRY.get(body.workflow_name)
    if workflow_def is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown workflow: {body.workflow_name}",
        )

    workflow_version = body.workflow_version or workflow_def["version"]
    now = datetime.now(timezone.utc)
    workflow_run_id = uuid.uuid4()
    deadline = now + timedelta(hours=workflow_def["deadline_hours"])

    # Create WorkflowRun
    run_model = WorkflowRunModel(
        workflow_run_id=workflow_run_id,
        workflow_name=body.workflow_name,
        workflow_version=workflow_version,
        state="pending",
        version=0,
        created_at=now,
        updated_at=now,
        deadline_at=deadline,
        created_by=principal.actor_string,
    )
    session.add(run_model)

    # Attach documents
    for doc_id in body.document_ids:
        session.add(WorkflowRunDocumentModel(
            workflow_run_id=workflow_run_id,
            document_id=doc_id,
            attached_at=now,
        ))

    # Create Steps
    step_models: list[StepModel] = []
    for idx, step_def in enumerate(workflow_def["steps"]):
        step_id = uuid.uuid4()
        step_model = StepModel(
            step_id=step_id,
            workflow_run_id=workflow_run_id,
            step_name=step_def["name"],
            step_index=idx,
            state="queued",
            max_attempts=step_def["max_attempts"],
            escalate_on_failure=step_def["escalate_on_failure"],
            created_at=now,
        )
        session.add(step_model)
        step_models.append(step_model)

    # Create first StepAttempt
    first_step = step_models[0]
    step_attempt_id = uuid.uuid4()
    step_attempt = StepAttemptModel(
        step_attempt_id=step_attempt_id,
        step_id=first_step.step_id,
        step_attempt_number=1,
        state="queued",
        origin="system",
        scheduled_for=now,
        created_at=now,
    )
    session.add(step_attempt)

    # Update run to point to first step and set to running
    run_model.current_step_id = first_step.step_id
    run_model.state = "running"
    run_model.version = 1

    # Create outbox entry for first step attempt
    outbox_payload = {
        "workflow_run_id": str(workflow_run_id),
        "step_id": str(first_step.step_id),
        "step_attempt_id": str(step_attempt_id),
        "step_name": first_step.step_name,
        "workflow_name": body.workflow_name,
        "workflow_version": workflow_version,
        "attempt_number": 1,
    }
    outbox_entry = TasksOutboxModel(
        workflow_run_id=workflow_run_id,
        step_id=first_step.step_id,
        step_attempt_id=step_attempt_id,
        payload=outbox_payload,
        scheduled_for=now,
        created_at=now,
    )
    session.add(outbox_entry)

    # Flush to ensure IDs are available
    await session.flush()

    # Append audit event for workflow start
    await append_audit_event(
        session=session,
        workflow_run_id=workflow_run_id,
        event_type="workflow_run.started",
        actor=principal.actor_string,
        payload={
            "workflow_name": body.workflow_name,
            "workflow_version": workflow_version,
            "document_ids": [str(d) for d in body.document_ids],
            "inputs": body.inputs,
        },
    )

    # Increment metrics
    from insuranceops.observability.metrics import workflow_runs_started_total

    workflow_runs_started_total.labels(
        workflow_name=body.workflow_name,
        workflow_version=workflow_version,
    ).inc()

    return WorkflowRunResponse(
        workflow_run_id=workflow_run_id,
        workflow_name=body.workflow_name,
        workflow_version=workflow_version,
        state="running",
        version=1,
        current_step_id=first_step.step_id,
        created_at=now,
        updated_at=now,
        deadline_at=deadline,
        created_by=principal.actor_string,
    )


@router.get(
    "/{workflow_run_id}",
    response_model=WorkflowRunResponse,
)
async def get_workflow_run(
    workflow_run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    principal: ApiKeyPrincipal = Depends(requires_role("operator", "supervisor", "viewer")),
) -> WorkflowRunResponse:
    """Return current state of a workflow run."""
    repo = WorkflowRunRepository(session)
    run = await repo.get_by_id(workflow_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    return WorkflowRunResponse(
        workflow_run_id=run.workflow_run_id,
        workflow_name=run.workflow_name,
        workflow_version=run.workflow_version,
        state=run.state,
        version=run.version,
        current_step_id=run.current_step_id,
        created_at=run.created_at,
        updated_at=run.updated_at,
        deadline_at=run.deadline_at,
        created_by=run.created_by,
        last_error_code=run.last_error_code,
        last_error_detail=run.last_error_detail,
    )


@router.get(
    "/{workflow_run_id}/events",
    response_model=WorkflowRunEventsResponse,
)
async def get_workflow_run_events(
    workflow_run_id: uuid.UUID,
    event_type: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    principal: ApiKeyPrincipal = Depends(requires_role("operator", "supervisor", "viewer")),
) -> WorkflowRunEventsResponse:
    """Return cursor-paginated audit events for a workflow run."""
    from sqlalchemy import select

    from insuranceops.storage.models import AuditEventModel

    # Check run exists
    repo = WorkflowRunRepository(session)
    run = await repo.get_by_id(workflow_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    # Build query
    query = (
        select(AuditEventModel)
        .where(AuditEventModel.workflow_run_id == workflow_run_id)
        .order_by(AuditEventModel.seq_in_run)
    )

    if event_type:
        query = query.where(AuditEventModel.event_type == event_type)

    if cursor:
        # Cursor is the seq_in_run to start after
        try:
            cursor_seq = int(cursor)
            query = query.where(AuditEventModel.seq_in_run > cursor_seq)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cursor")

    query = query.limit(limit + 1)  # fetch one extra to detect next page

    result = await session.execute(query)
    events = list(result.scalars().all())

    has_next = len(events) > limit
    if has_next:
        events = events[:limit]

    next_cursor = str(events[-1].seq_in_run) if has_next and events else None

    return WorkflowRunEventsResponse(
        events=[
            AuditEventResponse(
                audit_event_id=e.audit_event_id,
                workflow_run_id=e.workflow_run_id,
                event_type=e.event_type,
                actor=e.actor,
                payload=e.payload,
                occurred_at=e.occurred_at,
                seq_in_run=e.seq_in_run,
                step_id=e.step_id,
                step_attempt_id=e.step_attempt_id,
            )
            for e in events
        ],
        next_cursor=next_cursor,
    )


@router.post(
    "/{workflow_run_id}/cancel",
    response_model=WorkflowRunResponse,
)
async def cancel_workflow_run(
    workflow_run_id: uuid.UUID,
    body: CancelRequest,
    session: AsyncSession = Depends(get_db_session),
    principal: ApiKeyPrincipal = Depends(requires_role("supervisor")),
) -> WorkflowRunResponse:
    """Cancel a workflow run (supervisor only)."""
    repo = WorkflowRunRepository(session)
    run = await repo.get_by_id(workflow_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    # Validate that the run is in a cancellable state
    cancellable_states = {"pending", "running", "awaiting_human"}
    if run.state not in cancellable_states:
        raise HTTPException(
            status_code=409,
            detail=f"Workflow run in state '{run.state}' cannot be cancelled",
        )

    now = datetime.now(timezone.utc)
    updated = await repo.update_state_optimistic(
        workflow_run_id=workflow_run_id,
        expected_version=run.version,
        new_state="cancelled",
        new_version=run.version + 1,
        updated_at=now,
    )
    if not updated:
        raise HTTPException(
            status_code=409,
            detail="Concurrent modification detected, please retry",
        )

    # Write audit event
    await append_audit_event(
        session=session,
        workflow_run_id=workflow_run_id,
        event_type="workflow_run.cancelled",
        actor=principal.actor_string,
        payload={
            "reason": body.reason or "",
            "notes": body.notes or "",
        },
    )

    from insuranceops.observability.metrics import workflow_runs_completed_total

    workflow_runs_completed_total.labels(
        workflow_name=run.workflow_name,
        workflow_version=run.workflow_version,
        terminal_state="cancelled",
    ).inc()

    return WorkflowRunResponse(
        workflow_run_id=run.workflow_run_id,
        workflow_name=run.workflow_name,
        workflow_version=run.workflow_version,
        state="cancelled",
        version=run.version + 1,
        current_step_id=run.current_step_id,
        created_at=run.created_at,
        updated_at=now,
        deadline_at=run.deadline_at,
        created_by=run.created_by,
        last_error_code=run.last_error_code,
        last_error_detail=run.last_error_detail,
    )
