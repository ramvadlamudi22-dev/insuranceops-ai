# OBSERVABILITY_STRATEGY.md

## Purpose

This document is the authoritative observability posture for InsuranceOps AI.
It elaborates the brief summary in [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md)
section 18 without contradicting it.
It specifies the structured logging contract, the correlation-id propagation rules,
the Prometheus metric surface with types and labels, the OpenTelemetry-ready tracing wrapper,
the operator-facing event timeline, the retry-visibility rules, the liveness and readiness
probe contract, the log retention and shipping posture, and the initial dashboard and runbook
targets that Phase 2 will realize.

Observability is a correctness concern in this platform.
A WorkflowRun that fails silently is a worse outcome than one that fails loudly,
because silent failures become escalations that no one opened.
Every state transition in the core lifecycle emits a log line, an AuditEvent, and a metric.
Every retry is a first-class event, not a hidden side effect.
Every failure is attributable to a specific Actor, Step, StepAttempt, and Task.

## Scope

In scope:

- The logging pipeline (library, renderers, processors, mandatory fields,
  contextvar bindings, redaction rules).
- Correlation-id generation, propagation, and precedence.
- The Prometheus metric surface (names, types, labels, cardinality bounds).
- The OpenTelemetry tracing wrapper (no-op-by-default contract and the activation switch).
- The event timeline query surface exposed by the API.
- The retry-visibility contract (log events, metrics, AuditEvent types).
- The `/healthz` and `/readyz` probe contracts and their inputs.
- Dashboards and runbooks as Phase 2 targets with names and panels listed so the
  Phase 2 work has a concrete shape.
- Log retention and shipping responsibilities split between the application and the
  deployment platform.

Out of scope:

- Specific Grafana dashboard JSON, alert rules YAML, and Loki or CloudWatch
  configuration. These are Phase 2 deliverables.
- A choice of OpenTelemetry collector, backend, or exporter version.
  The tracing wrapper is backend-agnostic by design; the concrete backend is a Phase 3 decision.
- Business-level SLOs and SLIs. The platform's Phase 1 SLOs are listed in
  [PRODUCT_REQUIREMENTS.md](./PRODUCT_REQUIREMENTS.md); this document provides the metrics
  those SLOs will be computed from.
- Incident response process, on-call rotations, and paging policy. These are
  operational deliverables tied to the chosen deployment platform in Phase 2.

## Principles

These principles shape every specific rule in the rest of the document.
They are listed first so a reviewer can check a proposed change against them.

- **Deterministic correlation from log to metric to trace.**
  Every log line inside a request carries a `correlation_id`. Every metric for that
  request can be joined to the log stream by the labeled route and status. Every span
  carries the same `correlation_id` as a span attribute. An operator who starts with a
  metric spike can land in the log stream and from there in the trace viewer without
  guessing.
- **Operator-first debugging.**
  The primary debugging surface is the event timeline for a WorkflowRun
  (`GET /v1/workflow-runs/{workflow_run_id}/events`). Logs and metrics exist to support it.
  When a log format or a metric label does not help the operator narrow a problem,
  it is deleted rather than kept.
- **No silent failures.**
  Every failure path emits at least one log line at WARN or ERROR, increments at least
  one metric, and (if the failure is on a Step) writes at least one AuditEvent. A
  codepath that catches an exception and does not do these three things is a bug.
- **Every retry visible.**
  A StepAttempt that is retried produces a scheduling log line, a counter increment,
  and an AuditEvent with event type `step_attempt_retry_scheduled`. There is no
  "quietly try again" path.
- **Bounded cardinality.**
  No metric carries an unbounded label. `workflow_run_id`, `step_attempt_id`, and
  user identifiers are log fields and span attributes only. They never appear as
  Prometheus label values.
- **Same shape in local and production.**
  The JSON logging pipeline runs the same processors in both environments. Local
  developers can ask the console renderer for a pretty view, but the underlying
  record is identical. A bug that hides in production but not in local development
  is not something a formatting difference should introduce.

## Structured logging

Logging uses `structlog` as the single library. The standard library `logging` module
is configured to forward to structlog, so third-party libraries (FastAPI, uvicorn,
asyncpg, redis.asyncio) emit through the same pipeline.

### Renderers

The pipeline uses two terminal renderers, selected by the `LOG_FORMAT` environment
variable:

- `LOG_FORMAT=json` in `staging` and `production`. Renders one JSON object per line
  with no pretty-printing, sorted keys, and UTF-8 encoding. This is the default when
  `ENV` is not `local`.
- `LOG_FORMAT=console` in local development. Renders a human-readable colorized view
  when a TTY is present; falls back to plain text otherwise. This is the default when
  `ENV=local`.

Tests assert that the JSON renderer produces one line per emit, no embedded newlines
in any field value, and a stable key set for each `event` string.

### Mandatory fields on every log line

Every log line carries the following fields. Missing any of these on emit is a bug
caught by a test that asserts the minimum field set on a sample of recorded log lines.

- `timestamp`: ISO 8601 UTC with microseconds, from a monotonic-backed clock source.
  The clock source is a `Clock` wrapper that can be replaced in tests.
- `level`: one of `debug`, `info`, `warning`, `error`, `critical`.
- `logger`: dotted logger name, e.g. `app.api.routes.workflow_runs`.
- `event`: short, snake_case, stable string. The `event` is the primary index key
  for log analytics and is treated as part of the public log contract. Changing an
  `event` string is a breaking change reviewed in a PR.
- `correlation_id`: string, see `## Correlation IDs` below.
- `service`: `insuranceops-ai-api` or `insuranceops-ai-worker`.
- `service_version`: the `SERVICE_VERSION` env var, a semver string or a git sha.
- `env`: one of `local`, `ci`, `staging`, `production`, from the `ENV` env var.

### Mandatory additional fields inside an HTTP request

When a log line is emitted inside a request context (the FastAPI middleware binds the
context at request start), the following fields are also present:

- `request_id`: uuid v7 generated at the API boundary.
  Distinct from `correlation_id` because `correlation_id` may be supplied by the
  caller and is shared across the API and the worker for the same logical operation,
  while `request_id` is per-HTTP-request.
- `actor`: the resolved principal. Format is `service:<name>` for a machine client
  (e.g. `service:admin_console`) or `user:<role>:<user_id>` for a human session.
  When no credential is attached (for `/healthz`, `/readyz`, `/metrics`, and 401
  responses), `actor` is `anonymous`.
- `route`: the FastAPI route template, not the raw path. `GET /v1/workflow-runs/{id}`
  rather than `GET /v1/workflow-runs/5f9...`. This bounds cardinality for log analytics.
- `method`: the HTTP method.
- `status`: the HTTP status code, attached on response emit.

### Mandatory additional fields inside workflow execution

When a log line is emitted inside a Step handler (the worker binds the context when
it claims a Task and unbinds on ACK or DLQ), the following fields are also present:

- `workflow_run_id`: uuid v7, the identifier of the WorkflowRun.
- `workflow_name`: canonical name, e.g. `claim_intake_v1`.
- `workflow_version`: the pinned version string attached to the WorkflowRun.
- `step_id`: uuid v7 of the Step.
- `step_name`: canonical step name, e.g. `extract`, `validate`, `route`.
- `step_attempt_id`: uuid v7 of the current StepAttempt.
- `step_attempt_number`: integer, the 1-based attempt counter.

### Context binding

All of the contextual fields are injected via `contextvars`. Call sites do NOT pass
them explicitly. The `bind_request_context`, `bind_workflow_context`, and
`bind_step_attempt_context` helpers set the relevant variables; the structlog
processor `merge_contextvars` merges them into every log line emitted on that task
or thread. Unbinding happens in a `finally` block at the end of the scope.

The rule for authors: never pass these fields as keyword arguments to `log.info(...)`
when they are already bound in context. Redundant passes land in the log record twice
with different values, which is a class of bug the shape test catches.

### Example log line

The following is an example of what an info-level log line looks like in
`LOG_FORMAT=json` inside a running Step handler. Indentation and line breaks are
added here for readability; the actual output is a single JSON line.

```json
{
  "timestamp": "2025-03-14T09:42:17.813421Z",
  "level": "info",
  "logger": "app.workflow.steps.extract",
  "event": "step_attempt_started",
  "correlation_id": "01932b89-2f71-7c2e-9e8a-d1cfa1d2a401",
  "request_id": "01932b89-2f71-7d02-b6a6-7f92cc9b5d20",
  "service": "insuranceops-ai-worker",
  "service_version": "1.3.0",
  "env": "staging",
  "actor": "service:worker_extractor",
  "route": null,
  "method": null,
  "status": null,
  "workflow_run_id": "01932b89-2f71-7b00-9301-aaee03dfa11e",
  "workflow_name": "claim_intake_v1",
  "workflow_version": "1",
  "step_id": "01932b89-2f71-7b0a-9301-aaee03dfa11e",
  "step_name": "extract",
  "step_attempt_id": "01932b89-2f71-7b14-9301-aaee03dfa11e",
  "step_attempt_number": 2
}
```

### Redaction processor

A structlog processor `redact_pii` runs near the end of the pipeline, before the
renderer. It strips or SHA-256-hashes values for keys matching the PII field-name
list defined in [SECURITY_REVIEW.md](./SECURITY_REVIEW.md) section on PII handling
(`ssn`, `dob`, `policy_number`, `claimant_name`, `address`, `phone`, `email`,
`medical_code`, and close variants). The processor is the last line of defense and
is not the primary control; the primary control is not placing PII into log records
at all. Tests assert both: a direct `log.info(ssn=...)` is redacted by the processor,
and a scan of the codebase finds no direct binding of PII field names into log calls.

### Levels

- `debug`: developer-visible detail. Not emitted in `production` by default
  (`LOG_LEVEL=info` in production).
- `info`: normal operation. State transitions, request boundaries, and Step lifecycle
  events live at info.
- `warning`: degraded but self-healing. Retry scheduling, transient connection
  errors, and 4xx responses live at warning.
- `error`: human attention expected. DLQ moves, terminal Step failures, escalation
  expirations, and 5xx responses live at error.
- `critical`: data integrity concern. Audit chain mismatch detection,
  optimistic-concurrency livelock, and unrecoverable infrastructure failures live
  at critical. Critical events increment a dedicated metric and are expected to
  page.

The `LOG_LEVEL` env var controls the minimum level emitted. Lowering it to `debug`
in production is a supported temporary action for incident response; leaving it
there is not.

## Correlation IDs

A `correlation_id` is the single identifier that stitches together logs, metrics,
spans, and AuditEvents for one logical operation. The rules below define how it is
generated, propagated, and consumed.

### Format

`correlation_id` is a uuid v7 string. uuid v7 is chosen for two reasons: the
time-ordered prefix makes log-line sort order correspond to creation order, and the
standard uuid shape plays well with every downstream tool (log search, trace viewers,
databases). The application generates uuid v7 via a pinned helper to keep the
dependency surface narrow.

### Generation

On an inbound HTTP request the API middleware runs in this order:

1. If the request carries an `X-Correlation-Id` header and the value is a valid uuid
   (any version), it is used verbatim. This lets a caller thread its own id across
   systems it already operates.
2. Otherwise a fresh uuid v7 is generated.
3. The id is bound into the request context (contextvars) and echoed in the
   `X-Correlation-Id` response header on every response, including errors.

### Propagation to a WorkflowRun

When an API handler creates a WorkflowRun, the `correlation_id` is written to the
`workflow_runs.correlation_id` column. The value is immutable for the life of the
run. A subsequent status read for the same run carries its original `correlation_id`
in the response header, not the caller's new one, so operator tooling can anchor on
the originating request.

### Propagation to a Task

When the outbox relay drains a row into Redis, the Task payload carries the
`correlation_id` from the WorkflowRun. The worker reads it from the payload on claim
and binds it into the contextvar scope for the duration of the Step handler. Every
log line emitted by the handler, every AuditEvent it writes, and every span it
opens share the same `correlation_id`.

### Precedence and override

Precedence rules, highest first:

1. Explicit `X-Correlation-Id` header on the inbound request.
2. `workflow_runs.correlation_id` at the time of Task claim (used for all worker-side
   bindings).
3. A fresh uuid v7 generated at the API boundary.

An operator tool may deliberately override a captured correlation id when replaying
a request. In that case the caller supplies the header and the server uses it,
accepting that the new run is correlated to the caller-supplied value.

### Security considerations

The `correlation_id` is not security-sensitive. It is not a secret, and it is not
a stable user identifier. It MUST NOT be used as an authorization token or as a
tenant discriminator. Phase 1 is single-tenant and the correlation id is not
namespaced by tenant; a future multi-tenant deployment will add a separate
`tenant_id` field and will not overload `correlation_id` for that purpose.

## Metrics

Metrics are exposed on `GET /metrics` in Prometheus text format (content type
`text/plain; version=0.0.4`). The `api` and `worker` processes both expose a
`/metrics` endpoint on the same port as their primary surface. Scrape interval is
expected to be 15 seconds; histograms use standard buckets tuned per metric below.

The metric set below is the Phase 1 baseline. Every metric has a type, a label set,
a description, and the alert or dashboard that consumes it. New metrics added in
later phases follow the same shape. Adding a metric without naming its consumer is
reviewed skeptically.

### Cardinality contract

- No metric carries `workflow_run_id`, `step_attempt_id`, `document_id`,
  `escalation_id`, `api_key_id`, or `user_id` as a label. These are log fields and
  span attributes only.
- Route labels use the FastAPI route template, never the raw path.
- `workflow_name` and `step_name` are canonical enumerations defined in code.
  Adding a new value is a code change that passes through review.
- `status` labels for HTTP metrics use the full status code as a string.
- `outcome` and `terminal_state` labels use the canonical state names from
  [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md).

### API surface

- `api_requests_total` (counter). Labels: `route`, `method`, `status`.
  Counts every HTTP request handled by the API. Emitted on response.
  **Consumer.** Per-route error rate dashboard panel; alert on sustained
  `status=~"5.."` above threshold for any route.
- `api_request_duration_seconds` (histogram). Labels: `route`, `method`.
  Observes request handling time from middleware entry to response emit. Buckets:
  `0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10`.
  **Consumer.** Per-route p50/p95/p99 panel; SLO burn-rate alert.
- `auth_denials_total` (counter). Labels: `reason` in `missing_credential`,
  `unknown_principal`, `role`, `revoked`.
  Counts authentication and authorization denials. Populated by the FastAPI
  dependency layer.
  **Consumer.** Security dashboard; alert on sustained `reason="unknown_principal"`
  spike (credential scanning).

### Workflow lifecycle

- `workflow_runs_started_total` (counter). Labels: `workflow_name`,
  `workflow_version`.
  Counts WorkflowRun creation. Emitted when the row lands in Postgres in state
  `pending`.
  **Consumer.** Throughput dashboard; input to the per-workflow SLO.
- `workflow_runs_completed_total` (counter). Labels: `workflow_name`,
  `workflow_version`, `terminal_state` in `completed`, `failed`, `cancelled`.
  Counts WorkflowRun termination. Emitted on the state transition to a terminal
  state.
  **Consumer.** Success-rate panel; alert on
  `rate(workflow_runs_completed_total{terminal_state="failed"}[5m])` breach.
- `workflow_run_duration_seconds` (histogram). Labels: `workflow_name`,
  `workflow_version`, `terminal_state`.
  Observes the wall-clock time from state `pending` to terminal state. Buckets:
  `1, 5, 15, 30, 60, 300, 900, 1800, 3600, 10800, 86400`.
  **Consumer.** Latency SLO panel per workflow.

### Step execution

- `step_attempts_total` (counter). Labels: `workflow_name`, `step_name`,
  `outcome` in `succeeded`, `failed_retryable`, `failed_terminal`, `skipped`.
  Counts StepAttempt resolutions.
  **Consumer.** Per-step reliability panel; alert on
  `outcome="failed_terminal"` rate breach per `step_name`.
- `step_attempt_duration_seconds` (histogram). Labels: `workflow_name`,
  `step_name`.
  Observes Step handler wall-clock time. Buckets:
  `0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 300`.
  **Consumer.** Per-step latency panel; triage surface for slow extractors.
- `step_attempt_retries_total` (counter). Labels: `workflow_name`, `step_name`,
  `reason` from the canonical retry-reason enum (`extractor_timeout`,
  `validator_transient`, `db_conflict`, `unexpected_exception`, others).
  Counts every retry scheduling. This is the retry-visibility surface described in
  `## Retry visibility`.
  **Consumer.** Retry storm detection; alert on sudden per-reason increase.

### Queue substrate

- `queue_depth` (gauge). Labels: `queue` in `ready`, `inflight`, `delayed`, `dlq`.
  Observes the length of each Redis structure backing the reliable queue. Sampled
  by a background task inside the worker supervisor at a bounded interval.
  **Consumer.** Queue backlog panel; alert on `queue="ready"` sustained above
  threshold (back pressure) or `queue="dlq"` nonzero (poison pill).
- `queue_tasks_enqueued_total` (counter). Labels: `workflow_name`, `step_name`.
  Counts Tasks inserted into `queue:tasks:ready` by the outbox relay.
  **Consumer.** Matches `workflow_runs_started_total` inflow for sanity checks.
- `queue_tasks_acked_total` (counter). Labels: `workflow_name`, `step_name`,
  `outcome` in `succeeded`, `failed_retryable`, `failed_terminal`.
  Counts Task ACKs by workers. An ACK corresponds to the `inflight` removal, not to
  Step outcome; the two are related but distinct (a `failed_retryable` Task is
  ACKed and re-enqueued).
  **Consumer.** Throughput vs. outcome correlation panel.
- `queue_tasks_dlq_total` (counter). Labels: `workflow_name`, `step_name`,
  `reason` in `max_attempts_exceeded`, `poison_pill`, `operator_requeue`.
  Counts moves into `queue:tasks:dlq`.
  **Consumer.** Primary SLI for operational health; alert on any nonzero rate.
- `queue_reaper_reclaimed_total` (counter). No labels beyond the default.
  Counts Tasks reclaimed from a stale `inflight` list by the reaper loop.
  **Consumer.** Worker-health panel; sustained nonzero suggests a crashing worker.

### Escalation

- `escalations_opened_total` (counter). Labels: `workflow_name`, `step_name`.
  Counts EscalationCase creation.
  **Consumer.** Operator workload panel; capacity planning input.
- `escalations_resolved_total` (counter). Labels: `workflow_name`,
  `resolution` in `resolved`, `rejected`, `expired`.
  Counts EscalationCase termination.
  **Consumer.** SLA burn panel; alert on `resolution="expired"` rate breach.
- `escalation_open_age_seconds` (histogram). Labels: `workflow_name`.
  Observed on the transition out of `open` or `claimed`. Buckets span the SLA
  classes: `60, 300, 900, 1800, 3600, 10800, 21600, 43200, 86400, 172800`.
  **Consumer.** SLA p95 panel per workflow.

### Audit

- `audit_events_appended_total` (counter). Labels: `event_type` from the canonical
  AuditEvent type enumeration.
  Counts AuditEvent inserts. `event_type` is a bounded set defined in code.
  **Consumer.** Completeness check (every state transition is expected to produce
  at least one audit event of a specific type).
- `audit_chain_mismatches_total` (counter). No labels.
  Counts audit chain mismatches detected by the verifier. In healthy operation this
  is always zero.
  **Consumer.** Tamper detection alert; any nonzero value pages.

### Resource and dependency health

- `db_pool_in_use` (gauge). Labels: `role` in `app_rw`, `app_ro`, `app_audit_writer`.
  Observes Postgres connection pool utilization per DB role. Sampled at a bounded
  interval.
  **Consumer.** Pool saturation panel; alert on sustained high utilization.
- `db_query_duration_seconds` (histogram). Labels: `operation` from a bounded set
  (`select_workflow_run`, `insert_audit_event`, `update_escalation`, others).
  Observes query wall-clock time. Buckets:
  `0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5`.
  **Consumer.** Query-latency panel; input to the `db_slow_query_ratio` SLO.
- `redis_pool_in_use` (gauge). No labels.
  Observes Redis connection pool utilization.
  **Consumer.** Queue throughput triage panel.
- `process_startup_ready_seconds` (histogram). Labels: `service`.
  Observes the wall-clock time from process start to first `/readyz` 200.
  Buckets: `0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120`.
  **Consumer.** Deploy health panel.

The baseline above enumerates more than the 12-metric floor required by the
architecture review. Phase 1 ships exactly this set, and any addition passes through
a PR that names the consumer and declares the label set.

## Tracing (OpenTelemetry-ready)

Tracing is implemented behind a thin wrapper, not by sprinkling the codebase with
OpenTelemetry calls. The wrapper has two modes.

### Modes

- **No-op mode (default).** When `OTEL_EXPORTER_OTLP_ENDPOINT` is unset or empty,
  the wrapper's `start_span(name, attrs)` returns a cheap no-op context manager that
  does nothing. Span attribute arguments are accepted and discarded. The overhead
  is a single dict allocation per call, measured and bounded.
- **Exporting mode.** When `OTEL_EXPORTER_OTLP_ENDPOINT` is set, the wrapper
  initializes an OpenTelemetry tracer provider with an OTLP exporter at startup and
  `start_span(name, attrs)` creates real spans. The exporter batches spans and is
  resilient to collector unavailability (degrades to dropping spans, never blocks
  the caller).

The toggle happens once at process start. There is no runtime flip between modes.
The test suite exercises both modes (a CI step sets the endpoint to a local
in-memory exporter fixture to assert spans shape; the default suite runs in no-op
mode).

### Span naming

Span names are hierarchical and bounded to keep the per-service cardinality sane
in a future backend.

- `api.{route}` for HTTP handlers. Example: `api.POST /v1/workflow-runs`.
- `workflow.{workflow_name}.step.{step_name}` for Step handlers. Example:
  `workflow.claim_intake_v1.step.extract`.
- `db.{operation}` for database queries. Example: `db.insert_audit_event`.
- `redis.{operation}` for Redis commands where they carry meaningful semantics
  (`redis.enqueue_task`, `redis.claim_task`, `redis.ack_task`, `redis.reap_inflight`).
  Raw Redis commands (`GET`, `SET`) are not traced; they are summarized by the queue
  operation spans.

### Span attributes

Required attributes on every span:

- `service`: `insuranceops-ai-api` or `insuranceops-ai-worker`.
- `service.version`: mirrors the `SERVICE_VERSION` env var.
- `env`: `local`, `ci`, `staging`, `production`.
- `correlation_id`: the current `correlation_id`.

Required attributes on workflow spans:

- `workflow_run_id`, `workflow_name`, `workflow_version`, `step_id`, `step_name`,
  `step_attempt_id`, `step_attempt_number`.

Forbidden attributes:

- No PII. The PII field list from [SECURITY_REVIEW.md](./SECURITY_REVIEW.md) is the
  canonical list. Span attribute setting goes through a helper that rejects any key
  in the PII list and that is tested.
- No raw request bodies, no Document bytes, no error messages that include PII.
  Error status is recorded via `span.set_status(StatusCode.ERROR)` and an
  `error.type` attribute, not by stuffing the exception message into an attribute.

### Propagation

Trace context uses the W3C Trace Context headers (`traceparent`, `tracestate`).

- Inbound HTTP requests extract trace context from headers if present.
- Outbound enqueue writes the trace context into the Task payload's `trace`
  subfield (`traceparent`, `tracestate`). The worker reads it on claim and makes
  the Step span a child of the enqueuing request span.
- Outbound HTTP calls (Phase 3 extractors may reach external services) inject
  trace context into the outgoing headers.

### Collector and backend

The OTel collector and the storage backend (Tempo, Jaeger, a vendor product) are a
Phase 3 decision. Phase 1 ships the instrumented code and the OTLP export capability;
it does NOT ship a running collector, a running backend, or any configuration assuming
either exists. The platform is fully functional without tracing; tracing is a
debugging luxury, not a correctness requirement.

## Event timeline

The event timeline is the operator's primary debugging surface for a WorkflowRun.
It is a chronologically ordered view of the AuditEvents for a single run.

### Query shape

The backing query, expressed in pseudo-SQL:

```
SELECT audit_event_id,
       occurred_at,
       actor,
       event_type,
       step_id,
       step_attempt_id,
       payload_summary,
       correlation_id,
       prev_event_hash,
       event_hash
  FROM audit_events
 WHERE workflow_run_id = :workflow_run_id
 ORDER BY occurred_at ASC, audit_event_id ASC
 LIMIT :page_size
OFFSET :page_offset
```

The secondary ordering by `audit_event_id` breaks ties when multiple events land in
the same `occurred_at` microsecond, giving a fully stable order.

### API endpoint

`GET /v1/workflow-runs/{workflow_run_id}/events` serves this view.

- Pagination uses `?page_size` (default 100, max 500) and `?page_token` (opaque
  string encoding `occurred_at` and `audit_event_id` of the last row). Offset-based
  pagination is NOT used because the table grows append-only and offsets drift
  under concurrent writes.
- Response includes a `next_page_token` field when more rows exist.
- `Cache-Control: no-store` because the timeline is live.
- Role requirement: any of `operator`, `supervisor`, `viewer`.
- The endpoint emits an `audit_events_read_total` metric increment (not in the
  baseline set above; added if read-audit is itself auditable, which is a Phase 2
  decision).

### Timeline completeness

The platform guarantees that every state transition emits an AuditEvent and that
every AuditEvent appears in the timeline. The test suite in the `tests/audit`
tier asserts this for every canonical transition (see
[TESTING_STRATEGY.md](./TESTING_STRATEGY.md)). A transition without an AuditEvent
is a bug; so is an AuditEvent without a corresponding state transition (except the
ones that are pure audit by design, such as `access_granted` or `access_denied`).

### Operator workflow

A canonical operator investigation flow:

1. Operator observes a spike in `workflow_runs_completed_total{terminal_state="failed"}`.
2. Operator queries the log stream for `event=~"workflow_run_failed"` over the same
   time window and retrieves a handful of `workflow_run_id` values from log fields.
3. Operator hits `GET /v1/workflow-runs/{id}/events` for each run.
4. The timeline shows the exact sequence of StepAttempts, the retry schedule, the
   AuditEvent for the terminal failure, and the `error_code` payload.
5. If deeper inspection is needed, the operator pivots from `correlation_id` into
   the log stream for per-log-line detail, and (if tracing is enabled) into the
   trace viewer.

The timeline is designed so that most investigations terminate at step 4 without
needing steps 5 or 6.

## Retry visibility

Every retry is a first-class event. The three outputs below MUST all appear for a
retry to be considered observable. Missing any one is a bug.

### Log

A structured log line at level `info` (if the retry is expected under the step's
contract) or `warning` (if the retry is triggered by an unexpected exception):

- `event=step_attempt_retry_scheduled`.
- `step_attempt_id`, `step_attempt_number` (the one that failed), `next_attempt_number`
  (the one that will be scheduled), `retry_reason` from the canonical enum,
  `delay_seconds` (the scheduled backoff delay, post-jitter), `retry_exhausted=false`.
- If the retry exhausts `max_attempts`, the same log line is emitted with
  `retry_exhausted=true` and is upgraded to `error` level.

### Metric

`step_attempt_retries_total{workflow_name,step_name,reason}` increments. Emitted on
the scheduling, not on the re-execution, so the metric reflects the intent to retry.
Successful retries do not decrement; the counter is monotonic.

### AuditEvent

One AuditEvent of type `step_attempt_retry_scheduled` with payload fields matching
the log line. The AuditEvent is written inside the same Postgres transaction that
updates the StepAttempt row to `failed_retryable`, so the two states are never
out of sync.

### DLQ visibility

When a Task is moved to the DLQ, the three outputs are analogous:

- Log at `warning` with `event=task_moved_to_dlq`, including `workflow_run_id`,
  `step_id`, `step_attempt_number`, `reason`.
- Metric `queue_tasks_dlq_total{workflow_name,step_name,reason}` increments.
- AuditEvent of type `task_dlq_moved` with the payload.

Operators are expected to watch `queue_tasks_dlq_total` at a sustained-nonzero
alert threshold of zero for the first 30 days in production, then tune the alert
to a small absolute per-window threshold once the baseline is understood.

### SLIs the operator watches

Primary SLIs visible on the Phase 2 operator dashboard:

- `queue_tasks_dlq_total` rate. Any sustained increase is an immediate page.
- `step_attempts_total{outcome="failed_terminal"}` rate per `step_name`. A spike is
  a page.
- `escalations_resolved_total{resolution="expired"}` rate. A spike is a page.
- `audit_chain_mismatches_total`. Any nonzero value is an immediate page.
- `workflow_run_duration_seconds` p95 per `workflow_name`. Breach of the SLO budget
  is a burn-rate alert.

## Healthz and readyz

`/healthz` and `/readyz` are two distinct probes with two distinct jobs. Both return
`text/plain` with a short human-readable body and the `Content-Length` set so load
balancers with pedantic parsers are happy.

### /healthz

Returns HTTP 200 with body `ok` if the process is alive and the event loop is
responsive. The implementation is a trivial handler that returns immediately. It
does NOT consult the database, Redis, or any dependency. A failing `/healthz`
indicates the process is stuck or dead, which is a signal to the deployment platform
to restart it.

- Role requirement: none. The endpoint is open.
- Does not log on success (noise suppression); logs at warning on any exception.
- Does not increment any per-request metric (the counter is noisy and low-value
  for a probe).

### /readyz

Returns HTTP 200 with body `ready` only if all of the following are true within a
short timeout (default 2 seconds total, 500 ms per check):

- Postgres is reachable: a simple `SELECT 1` over a connection from the
  `app_rw` pool returns within timeout.
- Redis is reachable: a `PING` returns `PONG` within timeout.
- Migrations are at head: the most recent row in `alembic_version` matches the
  expected head embedded at image build time.
- On the worker process specifically, the queue consumer loop has claimed the
  shared advisory lock and is in its normal run state. If the worker is in a
  cooldown after repeated failures, `/readyz` returns 503 with the reason.

Returns HTTP 503 with a body that names the failing check on any failure. The
response body for an unready state is a short string, not a JSON object (load
balancers choke on JSON parsing in readiness checks).

- Role requirement: none. The endpoint is open.
- Logs at info on transition from ready to not-ready and back.
- Increments `readyz_checks_total{outcome}` (not part of the baseline above; a
  small addendum that the Phase 1 CI suite can add without negotiation).

Load balancers should use `/readyz` for pool membership and `/healthz` for
liveness restarts.

### Migration state check

The migration-head check in `/readyz` is deliberate. A pod that starts against a
database that has not yet been migrated would serve traffic against the wrong
schema. The check reads `alembic_version.version_num` and compares to a constant
baked in at build time (image label `com.insuranceops.alembic_head`). A mismatch
returns 503 with body `migrations_not_at_head`. The deploy pipeline migrates
first, then rolls the image; this makes the check redundant in the happy path and
a safety net otherwise.

## Dashboards and runbooks

Dashboards and runbooks are Phase 2 deliverables, not Phase 1. The Phase 0
commitment is to name the initial panel set so that the Phase 2 work has a target
and so that reviewers of Phase 1 metrics can check "is there a panel for this?"
against a list.

### Initial dashboard panels

Panels live in three dashboards, stored as Grafana JSON under `ops/dashboards/`
in Phase 2:

- **Platform overview**:
  API request rate and 5xx rate by route; API request p95 latency; WorkflowRun
  start and completion rate; queue depth per queue; DLQ counter; audit chain
  mismatch counter; DB pool utilization; Redis pool utilization.
- **Workflow health**:
  WorkflowRun success rate by `workflow_name`; run duration p50/p95 by
  `workflow_name`; per-`step_name` attempt rate and failure rate; retry rate by
  `step_name` and `reason`; escalation open age p95 by `workflow_name`.
- **Operator workload**:
  Open EscalationCases count per `workflow_name`; EscalationCase resolution
  throughput; expiration rate; per-operator resolution count (from AuditEvents,
  not from metrics, because the per-operator label is high-cardinality and lives
  in the log analytics surface).

No dashboard JSON lands in the Phase 0 commit. The panel names above exist so the
Phase 2 deliverable has a concrete shape.

### Initial runbooks

Runbooks live as markdown under `ops/runbooks/` in Phase 2:

- `dlq_entry.md`: how to inspect a DLQ Task, interpret the AuditEvent chain, and
  decide between requeue and fail.
- `audit_chain_mismatch.md`: how to confirm the mismatch with the verifier script,
  identify the tampered row, freeze further writes, and proceed with the incident
  response process.
- `postgres_unreachable.md`: how the platform degrades, what the operator can do,
  what to confirm before restarting anything.
- `redis_unreachable.md`: the analog for Redis.
- `escalation_backlog.md`: how to triage a sudden increase in open EscalationCases.

Phase 0 does not write these runbooks. It commits to their names so Phase 2 has a
list.

### Explicit non-claim

The Phase 1 deliverable does NOT include dashboards or runbooks. A fake dashboard at
Phase 1 (a JSON file checked in with no real data behind it) is explicitly rejected.
Phase 1 ships the metric surface with documented consumers; Phase 2 ships the
dashboards and runbooks that consume them.

## Log retention and shipping

The application writes JSON lines to `stdout` and nothing else. Log shipping is the
deployment platform's job, handled by a sidecar, a node agent, or a managed agent
that tails the container's stdout stream and ships to the log aggregator.

### Rationale

- The application is not a log-shipping client. Adding a shipper to the image
  couples the application to a specific aggregator and complicates the Dockerfile.
- Stdout is the universal contract every container platform supports.
- Rotating files, buffering on disk, and retrying to the aggregator are solved
  problems at the platform layer; we are not solving them again inside the app.

### Shipping targets (Phase 2 decision)

The platform will choose one of: a hosted provider (Datadog, New Relic, vendor X),
a self-hosted Loki stack, or a cloud-native destination (CloudWatch Logs on AWS,
Cloud Logging on GCP). The choice is made at the same time as the deployment
platform decision; nothing about the log format changes when the destination does.

### Retention

Retention is a property of the log aggregator, not of the application. The Phase 2
policy is:

- 30 days hot retention for all structured logs.
- 1 year cold retention for logs that carry a `workflow_run_id`, for audit trail
  support.
- Deletion after 1 year except for logs explicitly carrying a legal-hold tag
  (Phase 3 mechanism).

### Log volume control

The application's primary lever for log volume is `LOG_LEVEL`. Secondary levers:

- A sampler in the middleware for the `/metrics`, `/healthz`, `/readyz` endpoints
  at info level (they emit at debug by default; the sampler reduces even that).
- A dedup processor for high-frequency warnings emitted by a retry loop (ten
  identical warnings in a minute collapse to one with a `occurrences` field).

No sampler is applied to error or critical logs. Every error is emitted.

### Secrets in logs

Secrets do not appear in logs. The same `redact_pii` processor described earlier
removes known PII field names; a parallel `redact_secret` processor removes keys
matching a secret-field allowlist (`api_key`, `token`, `password`, `secret_key`,
`pepper`). Any apparent secret detected on emit is replaced with the fixed string
`[REDACTED]` and the processor increments a `log_redaction_total{kind}` counter.
This is the last line of defense; the primary control is not binding secrets into
log calls in the first place.

## Assumptions

- The deployment platform can scrape `GET /metrics` on both `api` and `worker`
  processes at a 15-second cadence without adversely affecting request handling.
- The deployment platform terminates TLS in front of the `api` process; the
  platform itself serves HTTP with `/metrics` and `/healthz` on the same port.
  A Phase 2 decision splits `/metrics` onto a second port when this assumption
  becomes inconvenient (e.g. public egress rules for a hosted scraper).
- The log aggregator the deployment platform uses accepts JSON lines on stdout.
  Any format translation (Loki label extraction, Datadog attribute indexing)
  happens at the aggregator's ingest stage, not in the application.
- The uuid v7 helper the platform uses produces monotonic ids within a single
  process. Across processes, ordering is time-based with millisecond resolution,
  which is sufficient for the timeline's stable-sort fallback to
  `audit_event_id`.
- The OpenTelemetry exporter, when enabled, can tolerate the configured
  collector being unreachable without slowing down the application. The chosen
  exporter is the OTLP batch exporter, which drops spans on overflow rather
  than blocking.
- `contextvars` propagate correctly across the asyncio event loop and across
  the FastAPI middleware stack. The test suite asserts this on a representative
  handler; a regression on any Python 3.12 point release would be caught there.

## Tradeoffs

### Prometheus text over OTel metrics

Phase 1 uses Prometheus text on `/metrics` rather than the OpenTelemetry metrics
SDK with an OTLP exporter. The reasoning:

- Fewer moving parts. A working Prometheus scrape is a six-line config; an
  OTel metrics collector is a collector process plus a pipeline plus exporters.
- The Prometheus data model is the one the on-call team knows. Training on
  OTel metrics is a cost that buys no additional signal at Phase 1 scale.
- The metric surface is a fixed enumeration. OTel's strength is dynamic
  instrumentation and cross-signal correlation; we benefit from that for traces
  and not for metrics at Phase 1.
- A future migration to OTel metrics is straightforward. The same metric names
  and labels map cleanly to OTel instruments; a shim exporter could emit both
  during a transition.

The tradeoff is accepted: lose some future-proofing in exchange for lower
operational surface today.

### Statsd rejected

Statsd is an alternative push-based metrics protocol. It is rejected because
cardinality contracts are harder to enforce on a push-based wire format, and
because Prometheus-style pull scraping gives the scraper explicit control over
when and how often to measure. Statsd also tends to encourage metric names with
dots that would require renaming for Prometheus naming conventions.

### Tracing off by default

The tracing wrapper is a no-op unless explicitly enabled. An alternative is to always
emit spans to a local ring buffer. That alternative is rejected because a ring
buffer only helps if the operator knows to look at it, it adds a background flush
pathway and disk usage with no clear consumer, and partial traces to nothing add
noise. The accepted tradeoff is that Phase 1 debugging leans on logs and the event
timeline, not on traces. When the deployment platform adds a tracing backend, the
wrapper lights up with no code change in the application.

### No log shipping inside the image

The application does not ship a log shipper inside the Docker image. The
alternative would be to bake Fluent Bit or a similar agent into the image and
have it tail the app. That alternative is rejected because:

- It couples the image to the aggregator choice, which is explicitly a Phase 2
  decision.
- It widens the attack surface of the container image.
- Container platforms provide this as a first-class capability at the node level.

The accepted tradeoff is that a deployment platform without built-in log
shipping (a bare VM running `docker run`) requires the operator to add a shipper
at the platform layer. That is understood and documented in
[DEPLOYMENT_STRATEGY.md](./DEPLOYMENT_STRATEGY.md).

### AuditEvent as the authority, logs as signal

The platform treats AuditEvents as the authoritative record of what happened to a
WorkflowRun and treats logs as a debugging signal. This means AuditEvent coverage
is exhaustive (every state transition) and log coverage is pragmatic (high-value
events and errors). The tradeoff: logs are lossy by design (sampling, level
filtering, retention trimming), AuditEvents are not. An investigation that needs
a definitive answer goes to the timeline; an investigation that needs context and
detail goes to the logs.

### Uniform field set across services

`api` and `worker` share the same contextvar-based logging setup and the same
mandatory field set. A log query for a single `correlation_id` returns the full
chain of API emit plus worker emit plus any downstream call, which is worth the
shared setup cost.
