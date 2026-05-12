"""SQLAlchemy ORM models for all platform tables."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class DocumentModel(Base):
    """ORM model for the documents table."""

    __tablename__ = "documents"

    document_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload_ref: Mapped[str] = mapped_column(Text, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    ingested_by: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("api_keys.api_key_id"), nullable=True
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="'{}'::jsonb"
    )

    __table_args__ = (
        CheckConstraint("octet_length(content_hash) = 32", name="ck_documents_content_hash_len"),
        CheckConstraint(
            "content_type ~ '^[a-z0-9.+-]+/[a-z0-9.+-]+$'",
            name="ck_documents_content_type_format",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_documents_size_bytes_nonneg"),
        Index("idx_documents_content_hash", "content_hash"),
        Index("idx_documents_ingested_at", "ingested_at"),
    )


class WorkflowRunModel(Base):
    """ORM model for the workflow_runs table."""

    __tablename__ = "workflow_runs"

    workflow_run_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    workflow_name: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_version: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    current_step_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("steps.step_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference_data_snapshot_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','running','awaiting_human','completed','failed','cancelled')",
            name="ck_workflow_runs_state",
        ),
        Index("idx_workflow_runs_state_updated", "state", "updated_at"),
        Index("idx_workflow_runs_created_by", "created_by", "created_at"),
    )


class WorkflowRunDocumentModel(Base):
    """ORM model for the workflow_run_documents association table."""

    __tablename__ = "workflow_run_documents"

    workflow_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.workflow_run_id"),
        primary_key=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.document_id"),
        primary_key=True,
    )
    attached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class StepModel(Base):
    """ORM model for the steps table."""

    __tablename__ = "steps"

    step_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    workflow_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.workflow_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    step_name: Mapped[str] = mapped_column(Text, nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    escalate_on_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    retry_policy: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='\'{"base_delay_s":2,"cap_s":60,"jitter":"full"}\'::jsonb',
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("step_index >= 0", name="ck_steps_step_index_nonneg"),
        CheckConstraint(
            "state IN ('queued','in_progress','succeeded','failed_retryable','failed_terminal','skipped')",
            name="ck_steps_state",
        ),
        CheckConstraint(
            "max_attempts >= 1 AND max_attempts <= 10", name="ck_steps_max_attempts_range"
        ),
        UniqueConstraint("workflow_run_id", "step_index", name="uq_steps_run_index"),
        UniqueConstraint("workflow_run_id", "step_name", name="uq_steps_run_name"),
        Index("idx_steps_run", "workflow_run_id", "step_index"),
    )


class StepAttemptModel(Base):
    """ORM model for the step_attempts table."""

    __tablename__ = "step_attempts"

    step_attempt_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    step_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("steps.step_id", ondelete="RESTRICT"),
        nullable=False,
    )
    step_attempt_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="'system'")
    extractor_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    validator_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    validator_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        CheckConstraint("step_attempt_number >= 1", name="ck_step_attempts_number_positive"),
        CheckConstraint(
            "state IN ('queued','in_progress','succeeded','failed_retryable','failed_terminal','skipped')",
            name="ck_step_attempts_state",
        ),
        CheckConstraint(
            "origin IN ('system','human','reaper','replay')",
            name="ck_step_attempts_origin",
        ),
        UniqueConstraint("step_id", "step_attempt_number", name="uq_step_attempts_step_number"),
        Index("idx_step_attempts_run_step", "step_id", "step_attempt_number"),
    )


class TasksOutboxModel(Base):
    """ORM model for the tasks_outbox table."""

    __tablename__ = "tasks_outbox"

    outbox_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.workflow_run_id"),
        nullable=False,
    )
    step_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("steps.step_id"),
        nullable=False,
    )
    step_attempt_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("step_attempts.step_attempt_id"),
        nullable=False,
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        CheckConstraint("attempts >= 0 AND attempts <= 10", name="ck_tasks_outbox_attempts_range"),
        Index("idx_tasks_outbox_undelivered", "enqueued_at", "scheduled_for"),
    )


class EscalationCaseModel(Base):
    """ORM model for the escalation_cases table."""

    __tablename__ = "escalation_cases"

    escalation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    workflow_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.workflow_run_id"),
        nullable=False,
    )
    step_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("steps.step_id"),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    reason_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('open','claimed','resolved','rejected','expired')",
            name="ck_escalation_cases_state",
        ),
        UniqueConstraint("workflow_run_id", "step_id", name="uq_escalation_cases_run_step"),
        Index("idx_escalation_cases_state_expires", "state", "expires_at"),
        Index("idx_escalation_cases_queue", "state", "created_at"),
    )


class AuditEventModel(Base):
    """ORM model for the audit_events table."""

    __tablename__ = "audit_events"

    audit_event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    workflow_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflow_runs.workflow_run_id"),
        nullable=False,
    )
    step_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("steps.step_id"),
        nullable=True,
    )
    step_attempt_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("step_attempts.step_attempt_id"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="'{}'::jsonb")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    seq_in_run: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prev_event_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    event_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "prev_event_hash IS NULL OR octet_length(prev_event_hash) = 32",
            name="ck_audit_events_prev_hash_len",
        ),
        CheckConstraint("octet_length(event_hash) = 32", name="ck_audit_events_hash_len"),
        UniqueConstraint("workflow_run_id", "seq_in_run", name="uq_audit_events_run_seq"),
        Index("idx_audit_events_run_seq", "workflow_run_id", "seq_in_run"),
        Index("idx_audit_events_type_occurred", "event_type", "occurred_at"),
        Index("idx_audit_events_actor", "actor", "occurred_at"),
    )


class ApiKeyModel(Base):
    """ORM model for the api_keys table."""

    __tablename__ = "api_keys"

    api_key_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("octet_length(key_hash) = 32", name="ck_api_keys_hash_len"),
        CheckConstraint(
            "role IN ('operator','supervisor','viewer')", name="ck_api_keys_role"
        ),
        Index("idx_api_keys_role_active", "role", postgresql_where="revoked_at IS NULL"),
    )


class UserModel(Base):
    """ORM model for the users table."""

    __tablename__ = "users"

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "role IN ('operator','supervisor','viewer')", name="ck_users_role"
        ),
        Index("idx_users_role_active", "role", postgresql_where="disabled_at IS NULL"),
    )
