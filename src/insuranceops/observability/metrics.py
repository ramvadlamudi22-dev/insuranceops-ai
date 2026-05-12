"""Prometheus metrics definitions.

All metric names follow the canonical names from TERMINOLOGY.md.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ──────────────────────────────────────────────────────────────────────────────
# Counters
# ──────────────────────────────────────────────────────────────────────────────

api_requests_total = Counter(
    "api_requests_total",
    "Total API requests",
    ["route", "method", "status"],
)

auth_denials_total = Counter(
    "auth_denials_total",
    "Total authentication/authorization denials",
    ["reason"],
)

workflow_runs_started_total = Counter(
    "workflow_runs_started_total",
    "Total workflow runs started",
    ["workflow_name", "workflow_version"],
)

workflow_runs_completed_total = Counter(
    "workflow_runs_completed_total",
    "Total workflow runs reaching terminal state",
    ["workflow_name", "workflow_version", "terminal_state"],
)

step_attempts_total = Counter(
    "step_attempts_total",
    "Total step attempts started",
    ["workflow_name", "step_name", "outcome"],
)

step_attempt_retries_total = Counter(
    "step_attempt_retries_total",
    "Total step attempt retries",
    ["workflow_name", "step_name", "reason"],
)

step_attempts_terminal_total = Counter(
    "step_attempts_terminal_total",
    "Total step attempts reaching terminal failure",
    ["workflow_name", "step_name", "reason"],
)

queue_tasks_enqueued_total = Counter(
    "queue_tasks_enqueued_total",
    "Total tasks enqueued to Redis",
    ["workflow_name", "step_name"],
)

queue_tasks_acked_total = Counter(
    "queue_tasks_acked_total",
    "Total tasks acknowledged from Redis",
    ["workflow_name", "step_name", "outcome"],
)

queue_tasks_dlq_total = Counter(
    "queue_tasks_dlq_total",
    "Total tasks moved to dead letter queue",
    ["workflow_name", "step_name", "reason"],
)

queue_reaper_reclaimed_total = Counter(
    "queue_reaper_reclaimed_total",
    "Total tasks reclaimed by the reaper",
)

escalations_opened_total = Counter(
    "escalations_opened_total",
    "Total escalation cases opened",
    ["workflow_name", "step_name"],
)

escalations_resolved_total = Counter(
    "escalations_resolved_total",
    "Total escalation cases resolved",
    ["workflow_name", "resolution"],
)

escalations_claimed_expired_total = Counter(
    "escalations_claimed_expired_total",
    "Total escalation claims that expired",
    ["workflow_name"],
)

audit_events_appended_total = Counter(
    "audit_events_appended_total",
    "Total audit events appended",
    ["event_type"],
)

audit_chain_mismatches_total = Counter(
    "audit_chain_mismatches_total",
    "Total audit chain hash mismatches detected",
)

# ──────────────────────────────────────────────────────────────────────────────
# Histograms
# ──────────────────────────────────────────────────────────────────────────────

api_request_duration_seconds = Histogram(
    "api_request_duration_seconds",
    "Duration of API requests in seconds",
    ["route", "method"],
)

workflow_run_duration_seconds = Histogram(
    "workflow_run_duration_seconds",
    "Duration of workflow runs in seconds",
    ["workflow_name", "workflow_version", "terminal_state"],
)

step_attempt_duration_seconds = Histogram(
    "step_attempt_duration_seconds",
    "Duration of step attempts in seconds",
    ["workflow_name", "step_name"],
)

outbox_drain_lag_seconds = Histogram(
    "outbox_drain_lag_seconds",
    "Lag between outbox entry creation and relay in seconds",
)

outbox_drain_batch_seconds = Histogram(
    "outbox_drain_batch_seconds",
    "Duration of outbox drain batch in seconds",
)

db_query_duration_seconds = Histogram(
    "db_query_duration_seconds",
    "Duration of database queries in seconds",
    ["operation"],
)

process_startup_ready_seconds = Histogram(
    "process_startup_ready_seconds",
    "Time from process start to ready state in seconds",
    ["service"],
)

escalation_open_age_seconds = Histogram(
    "escalation_open_age_seconds",
    "Age of open escalation cases in seconds",
    ["workflow_name"],
)

# ──────────────────────────────────────────────────────────────────────────────
# Gauges
# ──────────────────────────────────────────────────────────────────────────────

workflow_runs_running_total = Gauge(
    "workflow_runs_running_total",
    "Number of workflow runs currently in running state",
    ["workflow_name"],
)

queue_depth = Gauge(
    "queue_depth",
    "Current queue depth",
    ["queue"],
)

db_pool_in_use = Gauge(
    "db_pool_in_use",
    "Number of database connections currently in use",
    ["role"],
)

redis_pool_in_use = Gauge(
    "redis_pool_in_use",
    "Number of Redis connections currently in use",
)
