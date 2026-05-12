# PRODUCT_REQUIREMENTS.md

## Purpose

This document enumerates the functional and non-functional requirements of InsuranceOps AI
in testable form.
Every requirement has a stable identifier, a one-sentence statement,
and a one-sentence acceptance test that can be mechanized against
a running Phase 1 deployment or a unit or integration test in the Phase 1 test suite.
Requirements here are the source of truth for what the platform must do;
design choices for how live in SYSTEM_ARCHITECTURE.md.

## Scope

This document covers the product-level requirements of InsuranceOps AI
from ingestion through escalation, audit, retries, and operator observability.
It binds the primary users defined below to the capabilities they need.
It does not specify implementation mechanics,
data schemas, or internal module boundaries;
those belong in SYSTEM_ARCHITECTURE.md.
It does not enumerate test cases;
those belong in TESTING_STRATEGY.md.
Non-goals restated briefly: no customer portal, no underwriting,
no policy pricing, no claims adjudication decisions,
no multi-tenant isolation at Phase 1.

## Primary users

Each user subsection states who the user is,
what they need to do through InsuranceOps AI,
and what they explicitly do not do through this product.

### Operations analyst

Who: the day-to-day processor of insurance back-office work.
Handles incoming Documents, monitors WorkflowRuns,
and resolves EscalationCases routed to the analyst queue.

What they need to do through this product:

- Observe their queue of `open` EscalationCases assigned to the analyst role.
- Claim an EscalationCase, inspect the associated WorkflowRun and its Documents,
  and resolve or reject the case with a structured payload.
- Read the AuditEvent timeline of a WorkflowRun to understand what has happened.
- Retry a specific Step manually if authorized by their role.

What they explicitly do not do through this product:

- They do not approve exceptions outside their authorization scope.
  Those route to a supervisor.
- They do not define Workflows, Extractors, or Validators.
  Those are code artifacts owned by the integrator role.
- They do not perform adjudication decisions.
  They perform data actions that feed adjudication elsewhere.

### Operations supervisor

Who: the manager of one or more analyst teams.
Approves exceptions above the analyst authorization scope,
reviews SLA health, and signs off on the audit trail
for a given batch of WorkflowRuns.

What they need to do through this product:

- Observe queue depth and SLA health per Workflow.
- Review EscalationCases that have been escalated beyond analyst scope,
  resolve or reject them, and have that action recorded with their Actor identity.
- Export the AuditEvent log for a given WorkflowRun or a range of WorkflowRuns
  to hand to a compliance reviewer.
- Cancel a WorkflowRun that should not proceed.

What they explicitly do not do through this product:

- They do not write code.
- They do not interact with the queue infrastructure directly.
- They do not access raw PII beyond their authorization scope;
  redacted views apply to them as well.

### Platform operator (SRE)

Who: the engineer responsible for running the platform in production.
Reads logs, traces, and metrics,
manages retries and dead-letter inspection,
triages incidents, and rolls releases forward and back.

What they need to do through this product:

- Read structured JSON logs with correlation_id, workflow_run_id,
  step_id, step_attempt_id, and actor fields.
- Read Prometheus metrics from `GET /metrics`.
- Inspect the Redis queues: main queue depth, in-flight set, and dead-letter queue.
- Re-enqueue a failed Task from the DLQ after confirming the underlying issue is fixed.
- Run Alembic migrations against the production database with a review gate.
- Run `opsctl audit verify` to detect tampering in the AuditEvent chain.

What they explicitly do not do through this product:

- They do not make product decisions about Workflow design.
- They do not resolve EscalationCases on behalf of analysts.
- They do not modify AuditEvent rows.
  The append-only property forbids it and the hash chain would detect it.

### Compliance reviewer

Who: the internal auditor or external-auditor proxy who verifies
that a processed WorkflowRun was handled per policy.

What they need to do through this product:

- Read the full AuditEvent timeline for any WorkflowRun by workflow_run_id.
- Verify the hash chain for that WorkflowRun and receive a pass or fail signal
  with the index of any broken link.
- Export the AuditEvent timeline as a structured file (JSON Lines)
  for offline review.
- See which Actor performed each action and at what time.

What they explicitly do not do through this product:

- They do not modify state.
- They do not interact with operator queues.
- They do not see raw PII.
  PII is redacted in exported views;
  raw PII disclosure is a separate legal process outside this platform.

### Developer / integrator

Who: the engineer who adds new Workflow types, Extractors, and Validators.

What they need to do through this product:

- Define a new Workflow by writing a Workflow definition module in the codebase
  with a stable `workflow_name` and a monotonic `workflow_version`.
- Implement an Extractor or Validator against the narrow interface
  with deterministic behavior and clear input and output contracts.
- Run the full test suite locally against a Compose stack.
- Exercise the new Workflow through the `/v1/workflow-runs` endpoint
  in a staging environment.

What they explicitly do not do through this product:

- They do not modify running WorkflowRuns.
  A new Workflow version is a new version;
  in-flight runs continue on their original version.
- They do not write production PII into the repository
  as fixture data.
  Fixtures are synthetic.

## Functional requirements

Requirements are grouped by concern. Each has an ID and an acceptance test.

### FR-INGEST: Document ingestion

- **FR-INGEST-001**: The platform accepts Document uploads via
  `POST /v1/documents` carrying `content_type`, `size_bytes`, and a payload body.
  Acceptance test: a well-formed upload under the configured size limit
  returns HTTP 201 with a `document_id` and produces a Document row.
- **FR-INGEST-002**: The platform rejects Document uploads
  exceeding the configured maximum size with HTTP 413.
  Acceptance test: an upload at `max_size + 1` bytes returns HTTP 413
  and does not create a Document row.
- **FR-INGEST-003**: The platform records `content_hash` as a SHA-256
  over the raw payload bytes at ingest time.
  Acceptance test: the stored `content_hash` equals the SHA-256 of the request body
  computed independently.
- **FR-INGEST-004**: Documents are immutable once ingested.
  Acceptance test: there is no API endpoint that updates or deletes a Document row;
  attempting a database UPDATE fails a test that asserts the immutability invariant.
- **FR-INGEST-005**: Every Document ingest emits an AuditEvent
  of type `document_ingested` bound to the ingesting Actor.
  Acceptance test: after a successful ingest, exactly one `document_ingested`
  AuditEvent exists referencing the `document_id`.

### FR-EXTRACT: Content extraction

- **FR-EXTRACT-001**: A Workflow's `extract` Step invokes an Extractor
  against one or more Documents and produces a structured extraction payload.
  Acceptance test: a WorkflowRun with the stub Extractor produces an extraction payload
  whose shape matches the Extractor's declared output schema.
- **FR-EXTRACT-002**: Extractors implement a narrow interface
  `Extractor.extract(documents) -> ExtractionResult`
  with deterministic output for deterministic input.
  Acceptance test: calling the stub Extractor twice on identical input
  produces byte-identical output.
- **FR-EXTRACT-003**: Extractor failures are classified as retryable or terminal
  by raising typed errors (`RetryableExtractorError`, `TerminalExtractorError`).
  Acceptance test: a retryable error produces a `failed_retryable` StepAttempt
  and schedules another; a terminal error produces `failed_terminal`
  with no further attempts.

### FR-VALIDATE: Rule-based validation

- **FR-VALIDATE-001**: A Workflow's `validate` Step runs configured Validators
  against the extraction payload and produces a pass or fail result per rule.
  Acceptance test: a WorkflowRun with a known-good payload produces pass for each rule;
  a known-bad payload produces fail for the rule that applies.
- **FR-VALIDATE-002**: Validator results are structured, include a `rule_id`,
  and become part of the AuditEvent payload for that Step.
  Acceptance test: the AuditEvent for `validate` includes `rule_id` and outcome
  for each executed rule.
- **FR-VALIDATE-003**: A failed Validator result drives the WorkflowRun
  to either escalate (if `escalate_on_failure` is set)
  or fail the run, per the Step configuration.
  Acceptance test: with `escalate_on_failure=true` and a failed rule,
  the run transitions to `awaiting_human` and an `open` EscalationCase exists.

### FR-ROUTE: Routing to downstream systems

- **FR-ROUTE-001**: A Workflow's `route` Step dispatches a structured outcome
  to a configured downstream target identified by name.
  Acceptance test: a successful `route` Step produces a routing record
  referencing the target name and a correlation_id.
- **FR-ROUTE-002**: Routing failures are retried under the Step's retry policy.
  Acceptance test: injecting a transient routing failure results in a second StepAttempt;
  injecting a persistent failure results in `failed_terminal` after `max_attempts`.
- **FR-ROUTE-003**: Routing is the last Step before `complete` in a Workflow
  that does not escalate.
  Acceptance test: for `claim_intake_v1`, the terminal path is
  `route -> complete` and the WorkflowRun ends in `completed`.

### FR-ESCALATE: Human escalation

- **FR-ESCALATE-001**: When a Step requests escalation,
  the platform creates an EscalationCase in state `open`
  and transitions the WorkflowRun to `awaiting_human`.
  Acceptance test: after a Step returns `escalate`,
  exactly one `open` EscalationCase exists for the run
  and the WorkflowRun state is `awaiting_human`.
- **FR-ESCALATE-002**: Operators list `open` EscalationCases
  via `GET /v1/escalations`.
  Acceptance test: the endpoint returns all `open` cases
  ordered by `created_at` ascending,
  and excludes cases in any other state unless a `state` filter is passed.
- **FR-ESCALATE-003**: An operator claims an EscalationCase
  via `POST /v1/escalations/{id}/claim`,
  transitioning it from `open` to `claimed`.
  Acceptance test: a successful claim returns HTTP 200,
  the case state is `claimed`, and the claiming Actor is recorded.
- **FR-ESCALATE-004**: An operator resolves a claimed EscalationCase
  via `POST /v1/escalations/{id}/resolve` with a structured payload;
  the parent WorkflowRun resumes from the escalated Step
  with the payload as the Step's synthetic success output.
  Acceptance test: after resolve, the case state is `resolved`,
  the WorkflowRun state is `running`,
  and the next StepAttempt executes using the resolution payload.
- **FR-ESCALATE-005**: An operator rejects a claimed EscalationCase
  via `POST /v1/escalations/{id}/reject`;
  the parent WorkflowRun transitions to `failed`.
  Acceptance test: after reject, the case state is `rejected`
  and the WorkflowRun state is `failed`.
- **FR-ESCALATE-006**: EscalationCases expire if unresolved
  beyond the Workflow's configured escalation SLA.
  Acceptance test: after the SLA elapses, a background job
  transitions the case to `expired` and the WorkflowRun to `failed`,
  both emitting AuditEvents.

### FR-AUDIT: Append-only audit log

- **FR-AUDIT-001**: Every state transition on WorkflowRun, Step, StepAttempt,
  or EscalationCase emits exactly one AuditEvent.
  Acceptance test: running a Workflow end-to-end and counting AuditEvents
  matches the count of state transitions the state machine performed.
- **FR-AUDIT-002**: AuditEvents are append-only;
  the schema and the application layer reject updates and deletes.
  Acceptance test: attempting a direct UPDATE on `audit_events`
  fails a database trigger; there is no API endpoint that mutates AuditEvents.
- **FR-AUDIT-003**: AuditEvents are hash-chained per workflow_run_id;
  each event stores `prev_event_hash` and `event_hash`.
  Acceptance test: a verifier walks the chain for a given workflow_run_id
  and returns a pass result; artificially modifying any event fails the verifier.
- **FR-AUDIT-004**: The audit timeline for a WorkflowRun is readable via
  `GET /v1/workflow-runs/{id}/events`.
  Acceptance test: the endpoint returns all AuditEvents for the run
  ordered by `occurred_at` ascending, paginated under a configurable page size.

### FR-RETRY: Bounded retry policy

- **FR-RETRY-001**: Each Step has a `max_attempts` value (default 3)
  enforced by the platform.
  Acceptance test: a Step configured with `max_attempts=3` and always-retryable failures
  produces exactly 3 StepAttempts, the last being `failed_terminal`.
- **FR-RETRY-002**: Retries use exponential backoff with jitter
  (base 2 seconds, cap 60 seconds, jitter 0.5x to 1.0x of computed delay).
  Acceptance test: observed delays between StepAttempts stay within the expected envelope
  across 100 simulated runs.
- **FR-RETRY-003**: After exhausting retries, the Step either fails the run
  or creates an EscalationCase if `escalate_on_failure` is set.
  Acceptance test: two Workflows differing only in `escalate_on_failure`
  produce `failed` and `awaiting_human` terminal states respectively.

### FR-OBSERVE: Operator observability

- **FR-OBSERVE-001**: The platform emits Prometheus metrics at `GET /metrics`
  in Prometheus text exposition format.
  Acceptance test: parsing `/metrics` with a Prometheus text parser succeeds
  and yields the required series names.
- **FR-OBSERVE-002**: Structured logs are JSON with at minimum
  `correlation_id`, `workflow_run_id`, `step_id`, `step_attempt_id`, and `actor` fields
  where applicable.
  Acceptance test: every log line emitted during a test WorkflowRun parses as JSON
  and contains a non-null `correlation_id`.
- **FR-OBSERVE-003**: `GET /healthz` returns HTTP 200 when the process is alive,
  and `GET /readyz` returns HTTP 200 only when Postgres and Redis are reachable.
  Acceptance test: stopping Redis causes `/readyz` to return HTTP 503 within 5 seconds
  while `/healthz` continues to return HTTP 200.

### FR-AUTH: Authentication and authorization

- **FR-AUTH-001**: All non-public endpoints require a valid API key
  in the `Authorization` header (Phase 1).
  Acceptance test: requests with no or invalid API key receive HTTP 401.
- **FR-AUTH-002**: API keys map to a role: `operator`, `supervisor`, or `viewer`.
  Acceptance test: an `operator` key can claim an EscalationCase;
  a `viewer` key receives HTTP 403 on the same endpoint.
- **FR-AUTH-003**: Every authenticated action records the Actor derived from the API key
  into AuditEvents.
  Acceptance test: AuditEvents for actions performed by an `operator` key
  carry an Actor of the form `api_key:operator:<api_key_id>`.
- **FR-AUTH-004**: Health and readiness endpoints do not require authentication.
  Acceptance test: `GET /healthz` and `GET /readyz` without an API key
  return their respective non-401 responses.

## Non-functional requirements

### NFR-AVAIL: Availability

- **NFR-AVAIL-001**: The API is available at 99.5% over any rolling 30-day window
  on the Phase 1 single-host deployment,
  measured by external black-box probe of `GET /readyz`.
  Acceptance test: the observability dashboard computes availability
  over the last 30 days and reports a value at or above 0.995.
- **NFR-AVAIL-002**: Scheduled maintenance windows do not count against availability
  if announced at least 24 hours in advance and logged in the ops runbook.
  Acceptance test: the availability report excludes declared maintenance minutes.
- **NFR-AVAIL-003**: Workers tolerate Postgres or Redis unavailability
  by pausing, retrying their connection, and not dropping in-flight Tasks.
  Acceptance test: restarting Redis while workers are idle does not produce
  `failed_terminal` StepAttempts;
  in-flight Tasks resume after Redis recovers.

### NFR-PERF: Performance

- **NFR-PERF-001**: `POST /v1/documents` has p95 latency under 300 ms
  at 50 requests per second sustained on a single API pod.
  Acceptance test: the `api_request_duration_seconds{route="POST /v1/documents"}`
  histogram reports p95 under 300 ms for the last 10 minutes under load.
- **NFR-PERF-002**: `GET /v1/workflow-runs/{id}` has p95 latency under 150 ms
  at 100 requests per second sustained.
  Acceptance test: the same histogram for the read route reports p95 under 150 ms.
- **NFR-PERF-003**: A worker processes at least 20 Tasks per second
  for the stub `claim_intake_v1` Workflow on a 2-core worker pod.
  Acceptance test: a fixed 10-minute load run records throughput at or above 20 Tasks/s.
- **NFR-PERF-004**: Queue depth for the main Tasks queue does not exceed 10000
  under nominal load; exceeding triggers an alert.
  Acceptance test: Prometheus alert rule `queue_depth_high` fires when
  `queue_depth{queue="tasks"} > 10000` for 2 minutes.

### NFR-DETERMINISM: Determinism

- **NFR-DETERMINISM-001**: The same (workflow_name, workflow_version) applied
  to the same set of Documents produces the same Step sequence.
  Acceptance test: running `claim_intake_v1` twice on the same input
  yields identical ordered Step sequences in the AuditEvent log.
- **NFR-DETERMINISM-002**: Replaying the AuditEvent log reproduces the final WorkflowRun state.
  Acceptance test: `test_replay_is_deterministic` passes;
  reconstructed state matches recorded final state.
- **NFR-DETERMINISM-003**: Test runs are time-deterministic via a frozen clock fixture.
  Acceptance test: the test suite uses a `freezer` fixture;
  removing the fixture causes a dedicated time-dependent test to fail loudly.

### NFR-AUDITABILITY: Auditability

- **NFR-AUDITABILITY-001**: An AuditEvent exists for every state transition
  and every human action.
  Acceptance test: `test_every_transition_emits_one_audit_event` passes;
  the nightly invariant job reports zero gaps.
- **NFR-AUDITABILITY-002**: The AuditEvent hash chain is tamper-visible.
  Acceptance test: `opsctl audit verify --workflow-run-id <id>` returns zero
  for a clean run and a non-zero exit with the first broken index
  for an artificially modified run.
- **NFR-AUDITABILITY-003**: Audit retention is at least 7 years
  for WorkflowRuns that touched PII.
  Acceptance test: the retention policy configuration sets the PII tier to
  2555 days and the retention job refuses to prune within that window.

### NFR-SECURITY: Security

- **NFR-SECURITY-001**: All API traffic is served over TLS in any non-local environment.
  Acceptance test: the staging deploy rejects HTTP connections with a redirect
  or refusal, verified by an automated probe.
- **NFR-SECURITY-002**: API keys are hashed at rest using sha256(pepper || token)
  and compared in constant time.
  Acceptance test: inspecting the `api_keys` table shows only hash values;
  a timing-attack unit test on the comparison function passes.
- **NFR-SECURITY-003**: PII fields (SSN, DOB, policy numbers) are encrypted at column level.
  Acceptance test: inspecting the Postgres table shows ciphertext for those columns;
  a unit test decrypts them through the application-layer helper.
- **NFR-SECURITY-004**: Logs redact PII through a structlog processor.
  Acceptance test: running a WorkflowRun with a known SSN payload
  produces no log line containing the SSN in clear text.
- **NFR-SECURITY-005**: No secrets are baked into the Docker image.
  Acceptance test: `docker run --rm <image> env` does not expose secret values;
  secrets are loaded at process start from the runtime environment.

### NFR-OBSERVABILITY: Observability

- **NFR-OBSERVABILITY-001**: Every request and every Task carries a `correlation_id`
  propagated through logs, metrics exemplars, and outbound calls.
  Acceptance test: a request's `correlation_id` appears in every log line
  that was emitted in the context of that request.
- **NFR-OBSERVABILITY-002**: The OpenTelemetry bridge is a no-op when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is unset and becomes a real exporter when set.
  Acceptance test: with the variable unset, no OTel spans are exported;
  with it set to a test collector, spans arrive at the collector.
- **NFR-OBSERVABILITY-003**: Alerts exist for: high queue depth,
  p95 latency breach, AuditEvent invariant violation, and escalation SLA breach.
  Acceptance test: the Prometheus rules file contains at least one rule per alert name;
  a synthetic breach triggers the rule in a CI rule-test.

### NFR-OPERABILITY: Operability

- **NFR-OPERABILITY-001**: The platform provides `opsctl` commands for
  audit verification, queue inspection, and DLQ re-enqueue.
  Acceptance test: `opsctl --help` lists these commands
  and each command has its own integration test.
- **NFR-OPERABILITY-002**: Database migrations are managed by Alembic;
  migrations are idempotent and reversible where practical.
  Acceptance test: running `alembic upgrade head` twice is a no-op on the second run;
  `alembic downgrade -1` reverses the most recent migration in CI.
- **NFR-OPERABILITY-003**: The platform is runnable locally with `docker compose up`
  and reaches `readyz` green within 60 seconds on a developer laptop.
  Acceptance test: `make dev-up` (Phase 1 Makefile target)
  returns success within the 60 second budget in CI.
- **NFR-OPERABILITY-004**: Runbooks exist for each alert defined in NFR-OBSERVABILITY-003.
  Acceptance test: a link check in CI confirms each alert name
  resolves to a runbook section in the repo.

## User stories

Stories are short and in the `As a <role>, I need to <capability>, so that <outcome>` form.

### Operations analyst

- As an operations analyst, I need to see the list of `open` EscalationCases
  assigned to the analyst role, so that I can claim the next item of work.
- As an operations analyst, I need to claim a specific EscalationCase,
  so that no one else works the same item.
- As an operations analyst, I need to see the AuditEvent timeline of the WorkflowRun
  behind a case, so that I understand what happened before the escalation.
- As an operations analyst, I need to resolve a case with a structured payload,
  so that the WorkflowRun can resume with the data I provided.
- As an operations analyst, I need to reject a case when the work should not proceed,
  so that the WorkflowRun fails cleanly with a reason.

### Operations supervisor

- As an operations supervisor, I need to export AuditEvents for a range of WorkflowRuns,
  so that I can hand clean evidence to compliance.
- As an operations supervisor, I need to cancel a WorkflowRun in flight,
  so that I can stop work that should not continue.
- As an operations supervisor, I need to see SLA health per Workflow,
  so that I can act before breaches occur.

### Platform operator (SRE)

- As a platform operator, I need structured JSON logs with correlation_id,
  so that I can trace a single request across processes.
- As a platform operator, I need to inspect the DLQ and re-enqueue a fixed Task,
  so that I can recover from a transient upstream failure without losing work.
- As a platform operator, I need to run `opsctl audit verify` on any WorkflowRun,
  so that I can detect tampering before compliance asks.

### Compliance reviewer

- As a compliance reviewer, I need to read the full AuditEvent timeline for a WorkflowRun,
  so that I can reconstruct what happened without asking engineering.
- As a compliance reviewer, I need to verify the AuditEvent hash chain,
  so that I can sign off that the record has not been tampered with.

### Developer / integrator

- As a developer, I need to define a new Workflow by writing code and tests,
  so that I can ship new processing pipelines without touching the platform core.
- As a developer, I need to implement an Extractor or Validator against a narrow interface,
  so that I can plug in new capabilities without coupling to unrelated code.

## Out of scope

Restated here so subsequent documents cannot quietly widen scope:

- No customer-facing portal or customer UI.
- No underwriting models or underwriting decisions.
- No policy pricing, rating, quoting, billing, or payments.
- No claims adjudication decisions.
  The platform supports human adjudicators; it does not replace them.
- No multi-tenant isolation at Phase 1.
- No Kubernetes, service mesh, or microservice decomposition at Phase 1.
- No compliance certification claims (SOC 2, HIPAA, PCI DSS, ISO 27001).
- No conversational chatbot surface.
- No agent framework.

## Assumptions

- Upstream submitters authenticate with static API keys at Phase 1;
  operator users authenticate via signed session cookies if an operator UI ships at Phase 3.
- The target environment is a single Linux host running Docker Compose at Phase 1,
  with Postgres and Redis colocated or operated by the same team.
- Document volume at Phase 1 peaks in the low hundreds of requests per second.
- PII fields that are known in advance are enumerated in SECURITY_REVIEW.md
  and are encrypted at the column level.
- Operator staffing is sufficient to keep EscalationCase SLAs meetable;
  if it is not, the business accepts `expired` cases and the resulting `failed` runs.
- The Phase 1 stub Extractor is sufficient for end-to-end testing and staging demos.
  Real model-backed Extractors arrive at Phase 3 under the same interface.
- Requirements stated in latency or throughput terms
  are measured on the documented reference hardware in OBSERVABILITY_STRATEGY.md.
  Hardware changes permit renegotiation of the numbers with a recorded decision.

## Dependencies on future decisions

This document intentionally defers the following decisions.
Each is tracked as a phase concern, not an open placeholder.

- **Secret management backend**:
  The application loads secrets from the runtime environment.
  The concrete platform (Vault, AWS Secrets Manager, GCP Secret Manager, other)
  is a Phase 2 decision captured in DEPLOYMENT_STRATEGY.md.
- **PII key-management provider**:
  PII column-level encryption uses a key reference loaded from configuration.
  The concrete KMS (cloud KMS, HashiCorp Vault Transit, `pgcrypto`-backed local key)
  is a Phase 2 decision captured in SECURITY_REVIEW.md.
- **Deployment target platform**:
  Phase 1 targets Docker Compose on a single host.
  The Phase 2 deploy target (managed VM, managed container service)
  is recorded in DEPLOYMENT_STRATEGY.md when chosen.
- **Model-backed Extractor vendor**:
  Phase 1 ships the stub Extractor.
  Vendor selection for a real model-backed Extractor is a Phase 3 decision
  recorded in SYSTEM_ARCHITECTURE.md under the Extractor interface section.
- **Operator UI technology**:
  If an operator UI ships, HTMX plus Jinja is the current default
  and is a Phase 3 decision.
  No SPA framework is in scope at Phase 1.
- **Multi-tenant isolation model**:
  Phase 4+ decision.
  Row-level security, schema-per-tenant, and database-per-tenant are all candidates;
  selection depends on actual tenant scale at the time.
