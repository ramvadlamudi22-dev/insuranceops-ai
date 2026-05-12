"""Workflow run schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkflowRunCreate(BaseModel):
    """Request model for creating a workflow run."""

    workflow_name: str
    workflow_version: str | None = None
    document_ids: list[UUID]
    inputs: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class WorkflowRunResponse(BaseModel):
    """Response model for a workflow run."""

    model_config = ConfigDict(from_attributes=True)

    workflow_run_id: UUID
    workflow_name: str
    workflow_version: str
    state: str
    version: int
    current_step_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    deadline_at: datetime
    created_by: str
    last_error_code: str | None = None
    last_error_detail: str | None = None


class AuditEventResponse(BaseModel):
    """Response model for an audit event in the events list."""

    model_config = ConfigDict(from_attributes=True)

    audit_event_id: UUID
    workflow_run_id: UUID
    event_type: str
    actor: str
    payload: dict[str, Any]
    occurred_at: datetime
    seq_in_run: int
    step_id: UUID | None = None
    step_attempt_id: UUID | None = None


class WorkflowRunEventsResponse(BaseModel):
    """Response model for workflow run events (paginated)."""

    events: list[AuditEventResponse]
    next_cursor: str | None = None


class CancelRequest(BaseModel):
    """Request model for cancelling a workflow run."""

    reason: str | None = None
    notes: str | None = None
