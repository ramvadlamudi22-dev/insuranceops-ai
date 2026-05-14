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

rate_limit_exceeded_total = Counter(
    "rate_limit_exceeded_total",
    "Total requests rejected by rate limiting",
    ["role"],
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

# ──────────────────────────────────────────────────────────────────────────────
# AI Workflow Metrics
# ──────────────────────────────────────────────────────────────────────────────

# Extraction pipeline
ai_extraction_total = Counter(
    "ai_extraction_total",
    "Total AI-assisted extractions executed",
    ["provider", "outcome"],
)

ai_extraction_duration_seconds = Histogram(
    "ai_extraction_duration_seconds",
    "Duration of AI extraction pipeline in seconds",
    ["provider"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

ai_extraction_confidence = Histogram(
    "ai_extraction_confidence",
    "Distribution of extraction confidence scores",
    ["step_name"],
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0),
)

ai_ocr_duration_seconds = Histogram(
    "ai_ocr_duration_seconds",
    "Duration of OCR processing in seconds",
    ["provider", "content_type"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

ai_ocr_pages_total = Counter(
    "ai_ocr_pages_total",
    "Total pages processed by OCR",
    ["provider"],
)

# Summarization
ai_summarization_total = Counter(
    "ai_summarization_total",
    "Total summarization operations executed",
    ["summary_type", "outcome"],
)

ai_summarization_duration_seconds = Histogram(
    "ai_summarization_duration_seconds",
    "Duration of summarization operations in seconds",
    ["summary_type"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Human review queue
ai_review_routed_total = Counter(
    "ai_review_routed_total",
    "Total items routed to human review",
    ["reason", "suggested_action"],
)

ai_review_decisions_total = Counter(
    "ai_review_decisions_total",
    "Total review decisions made",
    ["decision"],
)

ai_review_queue_depth = Gauge(
    "ai_review_queue_depth",
    "Current number of items pending human review",
)

# Provider-level metrics
ai_provider_calls_total = Counter(
    "ai_provider_calls_total",
    "Total calls to AI providers",
    ["provider", "operation_type", "outcome"],
)

ai_provider_tokens_total = Counter(
    "ai_provider_tokens_total",
    "Total tokens consumed by AI providers",
    ["provider", "token_type"],
)

ai_provider_latency_seconds = Histogram(
    "ai_provider_latency_seconds",
    "AI provider response latency in seconds",
    ["provider", "operation_type"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
