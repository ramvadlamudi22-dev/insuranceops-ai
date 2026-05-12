"""Initial schema - all platform tables.

Revision ID: 0001
Revises: None
Create Date: 2025-01-15 12:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- api_keys (created before documents due to FK) ---
    op.create_table(
        "api_keys",
        sa.Column("api_key_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("key_hash", sa.LargeBinary(32), nullable=False, unique=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("octet_length(key_hash) = 32", name="ck_api_keys_hash_len"),
        sa.CheckConstraint(
            "role IN ('operator','supervisor','viewer')", name="ck_api_keys_role"
        ),
    )
    op.create_index(
        "idx_api_keys_role_active",
        "api_keys",
        ["role"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    # --- users ---
    op.create_table(
        "users",
        sa.Column("user_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False, unique=True),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('operator','supervisor','viewer')", name="ck_users_role"
        ),
    )
    op.create_index(
        "idx_users_role_active",
        "users",
        ["role"],
        postgresql_where=sa.text("disabled_at IS NULL"),
    )

    # --- documents ---
    op.create_table(
        "documents",
        sa.Column("document_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("content_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("payload_ref", sa.Text(), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ingested_by", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column(
            "api_key_id",
            UUID(as_uuid=True),
            sa.ForeignKey("api_keys.api_key_id"),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.CheckConstraint(
            "octet_length(content_hash) = 32", name="ck_documents_content_hash_len"
        ),
        sa.CheckConstraint(
            "content_type ~ '^[a-z0-9.+-]+/[a-z0-9.+-]+$'",
            name="ck_documents_content_type_format",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_documents_size_bytes_nonneg"),
    )
    op.create_index("idx_documents_content_hash", "documents", ["content_hash"])
    op.create_index("idx_documents_ingested_at", "documents", ["ingested_at"])

    # --- workflow_runs (forward-declared without current_step_id FK, added later) ---
    op.create_table(
        "workflow_runs",
        sa.Column("workflow_run_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_name", sa.Text(), nullable=False),
        sa.Column("workflow_version", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column(
            "version", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("current_step_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reference_data_snapshot_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("last_error_detail", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending','running','awaiting_human','completed','failed','cancelled')",
            name="ck_workflow_runs_state",
        ),
    )
    op.create_index(
        "idx_workflow_runs_state_updated", "workflow_runs", ["state", "updated_at"]
    )
    op.create_index(
        "idx_workflow_runs_deadline",
        "workflow_runs",
        ["deadline_at"],
        postgresql_where=sa.text(
            "state IN ('pending','running','awaiting_human')"
        ),
    )
    op.create_index(
        "idx_workflow_runs_created_by", "workflow_runs", ["created_by", "created_at"]
    )

    # --- workflow_run_documents ---
    op.create_table(
        "workflow_run_documents",
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.workflow_run_id"),
            primary_key=True,
        ),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.document_id"),
            primary_key=True,
        ),
        sa.Column(
            "attached_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --- steps ---
    op.create_table(
        "steps",
        sa.Column("step_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.workflow_run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("step_name", sa.Text(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), nullable=False),
        sa.Column(
            "escalate_on_failure",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "retry_policy",
            JSONB,
            nullable=False,
            server_default=sa.text(
                """'{"base_delay_s":2,"cap_s":60,"jitter":"full"}'"""
            ),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("step_index >= 0", name="ck_steps_step_index_nonneg"),
        sa.CheckConstraint(
            "state IN ('queued','in_progress','succeeded','failed_retryable','failed_terminal','skipped')",
            name="ck_steps_state",
        ),
        sa.CheckConstraint(
            "max_attempts >= 1 AND max_attempts <= 10",
            name="ck_steps_max_attempts_range",
        ),
        sa.UniqueConstraint("workflow_run_id", "step_index", name="uq_steps_run_index"),
        sa.UniqueConstraint("workflow_run_id", "step_name", name="uq_steps_run_name"),
    )
    op.create_index("idx_steps_run", "steps", ["workflow_run_id", "step_index"])

    # Add the FK from workflow_runs.current_step_id -> steps.step_id
    op.create_foreign_key(
        "fk_workflow_runs_current_step_id",
        "workflow_runs",
        "steps",
        ["current_step_id"],
        ["step_id"],
    )

    # --- step_attempts ---
    op.create_table(
        "step_attempts",
        sa.Column("step_attempt_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "step_id",
            UUID(as_uuid=True),
            sa.ForeignKey("steps.step_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("step_attempt_number", sa.SmallInteger(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column(
            "origin",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'system'"),
        ),
        sa.Column("extractor_name", sa.Text(), nullable=True),
        sa.Column("extractor_version", sa.Text(), nullable=True),
        sa.Column("validator_name", sa.Text(), nullable=True),
        sa.Column("validator_version", sa.Text(), nullable=True),
        sa.Column("input_ref", sa.Text(), nullable=True),
        sa.Column("output_ref", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "step_attempt_number >= 1", name="ck_step_attempts_number_positive"
        ),
        sa.CheckConstraint(
            "state IN ('queued','in_progress','succeeded','failed_retryable','failed_terminal','skipped')",
            name="ck_step_attempts_state",
        ),
        sa.CheckConstraint(
            "origin IN ('system','human','reaper','replay')",
            name="ck_step_attempts_origin",
        ),
        sa.UniqueConstraint(
            "step_id", "step_attempt_number", name="uq_step_attempts_step_number"
        ),
    )
    op.create_index(
        "idx_step_attempts_run_step", "step_attempts", ["step_id", "step_attempt_number"]
    )
    op.create_index(
        "idx_step_attempts_state_scheduled",
        "step_attempts",
        ["state", "scheduled_for"],
        postgresql_where=sa.text("state = 'queued'"),
    )

    # --- tasks_outbox ---
    op.create_table(
        "tasks_outbox",
        sa.Column(
            "outbox_id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.workflow_run_id"),
            nullable=False,
        ),
        sa.Column(
            "step_id",
            UUID(as_uuid=True),
            sa.ForeignKey("steps.step_id"),
            nullable=False,
        ),
        sa.Column(
            "step_attempt_id",
            UUID(as_uuid=True),
            sa.ForeignKey("step_attempts.step_attempt_id"),
            nullable=False,
        ),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column(
            "scheduled_for",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempts",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= 10", name="ck_tasks_outbox_attempts_range"
        ),
    )
    op.create_index(
        "idx_tasks_outbox_undelivered",
        "tasks_outbox",
        ["enqueued_at", "scheduled_for"],
    )

    # --- escalation_cases ---
    op.create_table(
        "escalation_cases",
        sa.Column("escalation_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.workflow_run_id"),
            nullable=False,
        ),
        sa.Column(
            "step_id",
            UUID(as_uuid=True),
            sa.ForeignKey("steps.step_id"),
            nullable=False,
        ),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("reason_detail", sa.Text(), nullable=True),
        sa.Column("claimed_by", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_payload", JSONB, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "state IN ('open','claimed','resolved','rejected','expired')",
            name="ck_escalation_cases_state",
        ),
        sa.UniqueConstraint(
            "workflow_run_id", "step_id", name="uq_escalation_cases_run_step"
        ),
    )
    op.create_index(
        "idx_escalation_cases_state_expires",
        "escalation_cases",
        ["state", "expires_at"],
        postgresql_where=sa.text("state IN ('open','claimed')"),
    )
    op.create_index(
        "idx_escalation_cases_queue",
        "escalation_cases",
        ["state", "created_at"],
        postgresql_where=sa.text("state = 'open'"),
    )

    # --- audit_events ---
    op.create_table(
        "audit_events",
        sa.Column("audit_event_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.workflow_run_id"),
            nullable=False,
        ),
        sa.Column(
            "step_id",
            UUID(as_uuid=True),
            sa.ForeignKey("steps.step_id"),
            nullable=True,
        ),
        sa.Column(
            "step_attempt_id",
            UUID(as_uuid=True),
            sa.ForeignKey("step_attempts.step_attempt_id"),
            nullable=True,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("seq_in_run", sa.BigInteger(), nullable=False),
        sa.Column("prev_event_hash", sa.LargeBinary(32), nullable=True),
        sa.Column("event_hash", sa.LargeBinary(32), nullable=False),
        sa.CheckConstraint(
            "prev_event_hash IS NULL OR octet_length(prev_event_hash) = 32",
            name="ck_audit_events_prev_hash_len",
        ),
        sa.CheckConstraint(
            "octet_length(event_hash) = 32", name="ck_audit_events_hash_len"
        ),
        sa.UniqueConstraint(
            "workflow_run_id", "seq_in_run", name="uq_audit_events_run_seq"
        ),
    )
    op.create_index(
        "idx_audit_events_run_seq", "audit_events", ["workflow_run_id", "seq_in_run"]
    )
    op.create_index(
        "idx_audit_events_type_occurred",
        "audit_events",
        ["event_type", "occurred_at"],
    )
    op.create_index(
        "idx_audit_events_actor", "audit_events", ["actor", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("escalation_cases")
    op.drop_table("tasks_outbox")
    op.drop_table("step_attempts")
    op.drop_constraint("fk_workflow_runs_current_step_id", "workflow_runs", type_="foreignkey")
    op.drop_table("steps")
    op.drop_table("workflow_run_documents")
    op.drop_table("workflow_runs")
    op.drop_table("documents")
    op.drop_table("users")
    op.drop_table("api_keys")
