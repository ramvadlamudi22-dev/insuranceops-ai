"""Escalation schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EscalationResponse(BaseModel):
    """Response model for an escalation case."""

    model_config = ConfigDict(from_attributes=True)

    escalation_id: UUID
    workflow_run_id: UUID
    step_id: UUID
    state: str
    reason_code: str
    reason_detail: str | None = None
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_payload: dict[str, Any] | None = None
    expires_at: datetime
    created_at: datetime


class EscalationListResponse(BaseModel):
    """Response model for escalation list (paginated)."""

    escalations: list[EscalationResponse]
    next_cursor: str | None = None


class EscalationClaimResponse(BaseModel):
    """Response model for a successful claim."""

    escalation_id: UUID
    state: str
    claimed_by: str
    claimed_at: datetime


class ResolveRequest(BaseModel):
    """Request model for resolving an escalation."""

    approve: bool | None = None
    override: dict[str, Any] | None = None
    notes: str


class RejectRequest(BaseModel):
    """Request model for rejecting an escalation."""

    reason_code: str
    notes: str
