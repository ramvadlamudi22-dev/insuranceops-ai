"""Escalation schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
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
    reason_detail: Optional[str] = None
    claimed_by: Optional[str] = None
    claimed_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_payload: Optional[dict[str, Any]] = None
    expires_at: datetime
    created_at: datetime


class EscalationListResponse(BaseModel):
    """Response model for escalation list (paginated)."""

    escalations: list[EscalationResponse]
    next_cursor: Optional[str] = None


class EscalationClaimResponse(BaseModel):
    """Response model for a successful claim."""

    escalation_id: UUID
    state: str
    claimed_by: str
    claimed_at: datetime


class ResolveRequest(BaseModel):
    """Request model for resolving an escalation."""

    approve: Optional[bool] = None
    override: Optional[dict[str, Any]] = None
    notes: str


class RejectRequest(BaseModel):
    """Request model for rejecting an escalation."""

    reason_code: str
    notes: str
