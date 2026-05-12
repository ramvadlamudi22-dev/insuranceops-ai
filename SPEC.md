# SPEC.md

## Purpose

This document is the top-level specification for InsuranceOps AI.
It fixes the product identity, the in-scope and out-of-scope surface,
the problem being solved, the measurable success criteria,
the non-goals, and the canonical vocabulary used by every other design document.
It is the contract that keeps the ten Phase 0 design documents internally consistent.
If a later document contradicts SPEC.md, SPEC.md wins until it is amended.

## Scope

This section states what InsuranceOps AI is and is not, as a product.
It is deliberately broader than the scope of this document alone.
Every subsequent design document inherits this scope statement.

### In-scope for InsuranceOps AI as a product

- Ingesting operational Documents (PDF, image, structured file)
  submitted by internal upstream systems over the control-plane API.
- Running versioned Workflow definitions against one or more Documents
  as WorkflowRuns with a deterministic state machine.
- Executing Steps (ingest, extract, validate, route, escalate, complete)
  via a pool of worker processes that consume Tasks from a reliable queue.
- Performing content extraction through a pluggable Extractor interface.
  Phase 1 ships a deterministic stub Extractor (regex and rule-based).
  Real model-backed Extractors are a Phase 3 decision.
- Performing rule-based validation through a pluggable Validator interface.
  Validator results are structured and become part of the AuditEvent log.
- Routing successful outcomes to downstream systems via explicit Step handlers.
  Routing targets are configured per Workflow, not hardcoded in the platform.
- Escalating exceptional cases to human reviewers as EscalationCases
  that operators claim, resolve, or reject through the control-plane API.
- Writing an append-only, hash-chained AuditEvent log for every state transition
  and every human action, keyed by workflow_run_id.
- Retrying failed Steps with bounded attempts,
  exponential backoff with jitter, and explicit terminal states.
- Exposing a control-plane API (FastAPI, versioned under `/v1`)
  for ingestion, run status, audit timeline, and escalation management.
- Emitting Prometheus metrics, structured JSON logs,
  and OpenTelemetry-ready spans for operator observability.
- Supporting deterministic replay: re-running the AuditEvent log
  for a completed WorkflowRun reproduces its final state.
- Supporting horizontal scaling of the worker pool.
  Workers are stateless beyond their current in-flight Task.
- Running as a single Docker image with two process types (api, worker)
  orchestrated by Docker Compose at Phase 1.
- Shipping a pytest-based test suite that is hermetic,
  deterministic, and runnable in CI without external network access.

### Out-of-scope for InsuranceOps AI as a product

- A public-facing customer portal.
  InsuranceOps AI is an internal platform.
  Customer-facing surfaces are owned by other systems.
- Policy pricing, rating, or quoting logic.
- Underwriting models or underwriting decisions.
- Payments, billing, or premium collection.
- Claims adjudication decisions.
  InsuranceOps AI supports human adjudicators
  with extracted data, validation results, and audit trail;
  it does not replace their decision authority.
- A conversational chatbot surface.
  The product is workflow orchestration, not dialog.
- A general-purpose agent framework.
  AI components are bounded Extractors and Validators behind narrow interfaces.
- Kubernetes-native deployment, service mesh, or microservice decomposition at Phase 1.
- Multi-tenant SaaS isolation at Phase 1.
  Tenant isolation is a Phase 4+ concern.
- Any compliance certification (SOC 2, HIPAA, PCI DSS, ISO 27001).
  The platform documents a defensible design posture;
  certification is a separate program that is not claimed here.
- A customer-facing or end-user UI.
  A minimal server-rendered operator UI is a Phase 3 option,
  not a Phase 1 commitment.

## Problem statement

Insurance back-office operations depend on processing high volumes of heterogeneous documents:
claim submissions, policy endorsements, medical records, proofs of loss, and third-party correspondence.
Today this work is a mix of manual handling by operations analysts,
legacy screen-scraping RPA scripts, and ad-hoc integrations.
The result is slow cycle time, inconsistent outcomes, poor auditability,
and a constant drag on operational cost.
When something goes wrong, reconstructing what actually happened to a given document is difficult
because the trail is split across email, spreadsheets, scripts, and human memory.

Robotic Process Automation, as typically deployed, is brittle.
It couples the automation to the pixel layout of vendor UIs
and the exact structure of incoming files.
Small upstream changes break the scripts, failures are silent,
and there is no first-class concept of retry, escalation, or audit.
Teams end up babysitting RPA rather than operating it.

Large-language-model-only solutions solve a different problem and introduce new ones.
They are non-deterministic by construction, hard to audit at the decision boundary,
expensive to run at volume, and do not compose cleanly
with the transactional constraints of an insurance back office.
A claim either advances to a defined next step or it does not;
a free-form generated answer is not an acceptable substitute
for a state transition recorded in a durable ledger.

What operations teams actually need is a workflow platform.
The platform must treat each processing stage as an explicit, versioned Step inside a Workflow,
record every transition in an append-only AuditEvent log,
bound retries so failures cannot loop indefinitely,
surface human escalation as a first-class concept rather than a flag,
and allow AI and ML components to be plugged in as bounded Extractors and Validators
behind narrow interfaces.
InsuranceOps AI is that platform.
It is engineered so that determinism, auditability, and operator control come first,
and AI components earn their way into the pipeline one measurable step at a time.

## Success criteria

All criteria below are measurable and testable.
They apply to a deployed Phase 1 stack unless otherwise stated.
Each criterion names the artifact (test, metric, runbook) that confirms it.

### Correctness and termination

- Every WorkflowRun reaches a terminal state (`completed`, `failed`, or `cancelled`)
  or the intermediate human-gated state `awaiting_human` within a bounded time
  configured per Workflow.
  No WorkflowRun remains in `pending` or `running` indefinitely.
  A reaper loop enforces timeouts and transitions stuck runs to `failed`
  with an explanatory AuditEvent.
  Confirmed by the test `test_workflow_run_respects_deadline`
  and by the Prometheus counter `workflow_runs_terminated_by_reaper_total`.
- Every state transition on a WorkflowRun, Step, StepAttempt, or EscalationCase
  produces exactly one AuditEvent.
  No transition is silent.
  No AuditEvent exists without a corresponding transition.
  Confirmed by the test `test_every_transition_emits_one_audit_event`
  and by the invariant `count(AuditEvent) == count(state_transitions)`
  verified nightly by a maintenance job.
- Replaying the AuditEvent log for any `completed` WorkflowRun
  from its first event to its last reproduces its final state
  byte-for-byte in a test fixture.
  This is enforced by `test_replay_is_deterministic` in the Phase 1 suite.

### Retry and escalation bounds

- Retries are bounded per Step.
  The default is three StepAttempts per Step
  with exponential backoff (base 2 seconds, cap 60 seconds) and jitter.
  After the final retryable failure the Step either
  transitions the WorkflowRun to `failed` or,
  if the Step is configured `escalate_on_failure`,
  creates an EscalationCase and transitions the WorkflowRun to `awaiting_human`.
  Confirmed by `test_retry_bounds_are_enforced`
  and by `test_escalate_on_failure_creates_case`.
- When an EscalationCase is created,
  it appears in the operator queue within one second of enqueue,
  measured as the p95 of `escalation_created_at` to `escalation_visible_in_list_at`
  under nominal load.
  Confirmed by the load-test harness `bench_escalation_visibility.py`
  and by the Prometheus histogram `escalation_visibility_seconds`.

### API performance

- The control-plane API has p95 latency under 200 ms for read endpoints
  and under 300 ms for write endpoints,
  at 50 requests per second sustained on a single API pod
  backed by a single Postgres instance and a single Redis instance.
  Confirmed by the `http_request_duration_seconds{route}` histogram
  evaluated over a 10 minute window in the load test.

### Test hermeticity and determinism

- The test suite is hermetic.
  It runs with no external network calls.
  Postgres and Redis are provided by CI service containers.
  Any test that tries to open an outbound socket fails the suite.
- The suite is deterministic:
  running it ten times in a row produces ten identical results on the same commit.
  Confirmed by the CI workflow `test-determinism.yml`
  which runs the suite three times per job and compares result hashes.

### Audit integrity

- The AuditEvent log is tamper-visible.
  Each event stores `prev_event_hash`.
  A verifier job walks the chain for a given workflow_run_id
  and fails loudly if any link is broken or any event has been modified.
  Confirmed by `test_audit_chain_detects_tampering`
  and by the operator command `opsctl audit verify --workflow-run-id <id>`.

### Deployment and scaling

- The platform runs as a single Docker image.
  The same image with different `CMD` starts an API process or a worker process.
  Worker processes can be scaled horizontally without coordination
  beyond the shared Postgres and Redis.
  Confirmed by the Compose definition and the scaling test `test_two_workers_share_load`.

### Operator observability

- Operator-visible metrics are emitted as Prometheus text at `GET /metrics`.
  At minimum:
  `workflow_runs_started_total`,
  `workflow_runs_completed_total{terminal_state}`,
  `step_attempts_total{workflow_name,step_name,outcome}`,
  `queue_depth{queue}`,
  `escalations_opened_total`,
  and histogram `api_request_duration_seconds{route,method}`.
  Confirmed by `test_metrics_endpoint_exposes_required_series`.

## Non-goals

The following are explicit non-goals for Phase 1 and are restated here
so no later document can quietly widen the scope.

- InsuranceOps AI is not a chatbot.
  There is no conversational surface, no dialog state,
  no end-user LLM interaction, no persistent chat thread model.
- InsuranceOps AI is not a general-purpose agent framework.
  AI components are bounded Extractors and Validators
  with explicit input and output contracts;
  they do not call tools autonomously or plan their own sequences.
- InsuranceOps AI is not a Kubernetes platform.
  Phase 1 ships as a Docker image plus Compose.
  Kubernetes and service mesh are explicitly deferred
  with reasoning in DEPLOYMENT_STRATEGY.md.
- InsuranceOps AI is not a multi-tenant SaaS at Phase 1.
  Tenant isolation, per-tenant configuration,
  and SaaS-shape concerns are Phase 4+ decisions.
- InsuranceOps AI does not claim any compliance certification.
  SOC 2, HIPAA, PCI DSS, ISO 27001 are not claimed and are not implied.
  SECURITY_REVIEW.md documents the design posture only.
- InsuranceOps AI does not ship a customer-facing UI.
  Operator UI, if built, is a minimal server-rendered surface
  for internal users and is a Phase 3 decision.
- InsuranceOps AI does not replace claims adjudicators.
  It extracts, validates, routes, and escalates; humans decide.
- InsuranceOps AI does not perform underwriting, pricing, or payments.
- InsuranceOps AI does not provide document storage as a primary product surface.
  Documents are stored as an implementation detail of the Workflow pipeline,
  not as a content-management system.

## Glossary

The following canonical entity names are locked for Phase 0 and all implementation phases.
Every design document and every code artifact must use these exact spellings.
Alternate synonyms are forbidden.
Where a field name is given (for example `document_id`),
that exact name is the canonical schema name.

### Document

A single uploaded artifact (PDF, image, structured file) identified by `document_id`.
Documents are immutable once ingested.
A Document carries:

- `document_id` (UUID primary key)
- `content_hash` (SHA-256 over raw payload bytes)
- `content_type` (IANA media type, for example `application/pdf`)
- `size_bytes` (integer)
- `payload_ref` (opaque reference to the stored payload)
- `ingested_at` (UTC timestamp)
- `ingested_by` (Actor identifier)

Documents are the input material that WorkflowRuns process.
A Document may be referenced by zero or more WorkflowRuns.
Deleting a Document is never a direct operation;
the payload may be retired by retention policy,
but the Document row remains to preserve referential integrity with the AuditEvent log.

### Workflow

A named, versioned definition of a processing pipeline, expressed in Python code.
Example: `claim_intake_v3`.
A Workflow is identified by the pair (`workflow_name`, `workflow_version`).
The same (name, version) always produces the same Step sequence for the same input.
Workflows are defined in code, not in the database,
to keep the version graph reviewable in git.
A Workflow declares:

- its `workflow_name` (stable string, snake_case)
- its `workflow_version` (monotonically increasing string, for example `v3`)
- its ordered list of Steps, including retry policy and escalation policy per Step
- its deadline (maximum wall-clock time from start to terminal state)

Bumping a Workflow's version is a code change reviewed like any other.
In-flight WorkflowRuns continue to execute under the version they started with.

### WorkflowRun

A single execution of a Workflow against one or more Documents.
Identified by `workflow_run_id`.
A WorkflowRun has a deterministic state machine with states:

- `pending` (created, not yet picked up)
- `running` (at least one Step has started, not all have completed)
- `awaiting_human` (an EscalationCase is open, execution is paused)
- `completed` (terminal, all Steps succeeded or were skipped)
- `failed` (terminal, a Step exhausted retries without escalation)
- `cancelled` (terminal, operator cancelled the run before completion)

The WorkflowRun row in Postgres is the source of truth for run status
and for the current Step cursor.
It also stores the `workflow_name` and `workflow_version` that started it,
the set of `document_id` values it is processing,
its creation and last-updated timestamps,
and the Actor that initiated it.

Valid transitions:

```
pending -> running
running -> awaiting_human
running -> completed
running -> failed
running -> cancelled
awaiting_human -> running
awaiting_human -> cancelled
```

No other transitions are valid.
Attempting an invalid transition raises an error
and emits no AuditEvent (the invariant is preserved).

### Step

A unit of work inside a WorkflowRun.
Identified by `step_id` and by a stable `step_name`
(for example `ingest`, `extract`, `validate`, `route`, `escalate`, `complete`).
Steps are defined by the Workflow definition;
retries do not create new Steps, they create new StepAttempts against the same Step.
A Step carries:

- `step_id` (UUID)
- `workflow_run_id` (FK)
- `step_name` (string)
- `step_index` (integer, position in the Workflow)
- `max_attempts` (integer)
- `escalate_on_failure` (boolean)
- `created_at`, `started_at`, `ended_at`

### StepAttempt

One try of a Step.
Identified by `step_attempt_id` and carries a `step_attempt_number` starting at 1.
Retries create additional StepAttempts bound to the same Step.
StepAttempt state is one of:

- `queued` (Task enqueued, not yet picked up)
- `in_progress` (worker has claimed the Task)
- `succeeded` (handler returned success)
- `failed_retryable` (handler raised a retryable error, more attempts available)
- `failed_terminal` (handler raised a terminal error or exhausted attempts)
- `skipped` (handler declined to run, for example due to an idempotency guard)

The final StepAttempt of a Step determines whether the Step advances the WorkflowRun
or terminates it.

### Task

A queue message pointing at a (WorkflowRun, Step) pair.
Consumed by a worker process.
Tasks live in Redis Lists using the reliable-queue pattern
(in-flight list, visibility timeout, explicit acknowledgement by removing from in-flight).
Tasks are transient;
the durable state they represent lives in Postgres.
A Task payload carries:

- `workflow_run_id`
- `step_id`
- `step_attempt_id`
- `enqueued_at`
- `correlation_id`

If a Task is lost (worker crash), the reaper detects the stale in-flight entry
after the visibility timeout expires and re-enqueues the Task
with the same `step_attempt_id`, or, if the attempt has already been finalized,
creates a new StepAttempt per the retry policy.

### EscalationCase

A human-in-the-loop work item created when a Step requests human judgment,
either by design (a Step whose handler returns `escalate`)
or by policy (a Step configured `escalate_on_failure` exhausting its retries).
Identified by `escalation_id`.
Has states:

- `open` (created, not yet claimed)
- `claimed` (an operator has claimed it, work in progress)
- `resolved` (operator resolved with a success payload; run resumes)
- `rejected` (operator rejected; run transitions to `failed`)
- `expired` (no operator acted within the configured SLA; run transitions to `failed`)

Resolving or rejecting an EscalationCase emits an AuditEvent
and resumes the parent WorkflowRun from the escalated Step
with a synthetic success or override payload.

### AuditEvent

An append-only, immutable record of a state transition or human action.
Identified by `audit_event_id` and linked to `workflow_run_id`.
AuditEvents are hash-chained per workflow_run_id:
each event stores `prev_event_hash` so the log is tamper-visible.
AuditEvents are write-only at the database level;
rows are never updated or deleted.
Each AuditEvent carries:

- `audit_event_id`
- `workflow_run_id`
- `step_id` (nullable)
- `step_attempt_id` (nullable)
- `event_type` (enum, for example `workflow_run_started`, `step_attempt_succeeded`, `escalation_resolved`)
- `payload` (structured, redacted where necessary)
- `actor` (Actor identifier)
- `occurred_at` (UTC timestamp)
- `prev_event_hash` (bytes, nullable only for the first event of a run)
- `event_hash` (bytes, derived from the fields above)

### Actor

The principal that caused an event.
Either a service identity (for example `worker:extractor`, `api:control_plane`)
or a human user (for example `user:analyst:42`).
Every AuditEvent carries an Actor.
Every write endpoint records the Actor that caused the write.
Actor strings follow the pattern `<kind>:<subkind>:<id>` where `<id>` may be omitted
for service identities that are singleton per process type.

## Assumptions

- Upstream systems that submit Documents are internal and trusted at the network layer.
  Authentication is machine-to-machine via static API keys for Phase 1;
  OIDC and SSO for operator users is a Phase 3 concern.
- The initial deployment target is a single Linux host running Docker Compose.
  The Postgres and Redis instances are operated by the same team that operates the platform.
  Managed services are allowed but not required.
- Document volume at Phase 1 is on the order of tens of thousands of Documents per day,
  peaking into hundreds of requests per second for short windows.
  The architecture scales out by adding worker replicas;
  it does not require re-architecture for that volume.
- Document payloads are opaque to the platform at the storage layer.
  Extractors interpret them.
  The platform stores payloads by reference with an encrypted-at-rest backing store.
  The exact backing store (filesystem, S3-compatible object storage, database large objects)
  is a Phase 2 decision and does not change the platform API.
- PII fields that are known in advance (SSN, DOB, policy numbers)
  are encrypted at the column level in Postgres.
  Logs redact PII through a structlog processor.
  The exact key management backend is a Phase 2 decision;
  the application reads a key reference from configuration, not the key material.
- The sandbox in which Phase 0 documents are produced is network-restricted
  (INTEGRATIONS_ONLY).
  This affects Phase 1+ operations (no external package pulls at runtime);
  it does not affect Phase 0 markdown authoring.
  Operational constraints are documented in
  DEPLOYMENT_STRATEGY.md and RISK_ANALYSIS.md.
- AI model-backed Extractors, if adopted,
  are invoked through the same narrow interface as the Phase 1 stub Extractor.
  The platform does not assume or require a specific model vendor.
  No model vendor is committed in Phase 0.
- The team operating InsuranceOps AI at Phase 1 is small (single-digit engineers).
  Decisions that would be correct at hundred-engineer scale
  (service mesh, dedicated orchestration platform, heavy framework adoption)
  are explicitly rejected at this scale.
  The phased roadmap revisits those choices as scale changes.
- Workflow definitions are the unit of change that requires the most review.
  Changing a Workflow definition bumps `workflow_version`
  and is a code change reviewed like any other code change.
  In-flight WorkflowRuns continue to execute under the version they started with.
- Wall-clock time on all platform hosts is NTP-synchronized within one second.
  The AuditEvent log records times from the process that emitted the event;
  monotonic clock skew across hosts is not a correctness concern for the hash chain,
  which is ordered by database insertion, not by wall-clock time.

## Rejected alternatives

The following choices are explicitly rejected for the Phase 1 platform.
Each is stated in one line here;
the full reasoning, including the scenarios under which we would revisit each rejection,
lives in SYSTEM_ARCHITECTURE.md and RISK_ANALYSIS.md.

- **Kubernetes (K8s) at Phase 1**:
  rejected because Compose on a single host is sufficient for the target scale
  and Kubernetes adds operational surface disproportionate to the team size.
- **Microservices decomposition**:
  rejected because one service is the correct boundary
  for the workflow orchestration problem at Phase 1;
  splitting multiplies operational cost without reducing cognitive load.
- **Event bus such as Kafka or NATS**:
  rejected because a Redis reliable-queue satisfies the queue requirements,
  is directly inspectable, and does not introduce a separate durable log to reason about.
- **Celery**:
  rejected because Celery's ambient behavior, implicit retry semantics,
  and scheduler coupling are not what the platform needs;
  we want explicit, inspectable Task handling.
- **RQ**:
  rejected for the same family of reasons as Celery, at a smaller scale.
- **Amazon SQS**:
  rejected because it binds the platform to a cloud provider at Phase 1
  and is unnecessary for the target load.
- **In-process asyncio queue**:
  rejected because it loses work on process restart
  and is not a durable substrate for Tasks.
- **Temporal or Cadence**:
  rejected because they own orchestration but carry operational and conceptual weight
  we do not need at the current team and scale;
  revisited if Workflow complexity grows beyond what code-defined Workflows support.
- **Airflow, Prefect, or Dagster**:
  rejected because they are batch-oriented orchestrators
  and do not fit low-latency operational workflows with human escalation.
- **GraphQL for the control plane**:
  rejected because REST under `/v1` with a small endpoint surface is sufficient
  and avoids schema and caching complexity.
- **Dedicated frontend framework at Phase 1**:
  rejected because operator actions happen via API at Phase 1
  and a minimal server-rendered operator UI (HTMX plus Jinja)
  is the correct Phase 3 shape.
- **Document-oriented database (MongoDB, DynamoDB)**:
  rejected because WorkflowRun, Step, StepAttempt, EscalationCase, and AuditEvent
  are natively relational and benefit from transactional guarantees.
- **Fake compliance certification claims**:
  rejected on principle.
  SECURITY_REVIEW.md states design posture only
  and names no certification that has not been earned.
- **Agent frameworks (LangChain, LlamaIndex, and similar)**:
  rejected because the platform is workflow orchestration,
  not open-ended tool-using dialog;
  AI components are bounded Extractors and Validators behind explicit interfaces.

Each rejection above is a current decision, not a permanent one.
The phased roadmap defines the conditions under which any of these can be revisited.
