# RISK_ANALYSIS.md

## Purpose

This document is the authoritative risk register for InsuranceOps AI across
Phase 0 design, Phase 1 initial delivery, and the operational posture that
follows. It synthesizes the risks implied by the choices made in
[SPEC.md](./SPEC.md), [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md),
[SECURITY_REVIEW.md](./SECURITY_REVIEW.md),
[OBSERVABILITY_STRATEGY.md](./OBSERVABILITY_STRATEGY.md),
[TESTING_STRATEGY.md](./TESTING_STRATEGY.md),
[DEPLOYMENT_STRATEGY.md](./DEPLOYMENT_STRATEGY.md), and
[PHASED_ROADMAP.md](./PHASED_ROADMAP.md) and records for each one a concrete
mitigation, a named owner-role, and the signal that would reveal the risk
materializing.

This document does not introduce new architectural decisions. It only
references existing ones and names the ways they can fail or rot. A risk that
is not visible in a log, a metric, or a scheduled check is treated as not yet
mitigated, regardless of how carefully the code is written.

## Scope

In scope:

- Technical risks to correctness, availability, and data integrity of the
  platform as defined in SYSTEM_ARCHITECTURE.md.
- Operational risks that emerge from the Phase 1 single-host Compose posture
  defined in DEPLOYMENT_STRATEGY.md.
- Delivery risks to the Phase 0 and Phase 1 plan as defined in
  PHASED_ROADMAP.md.
- Compliance and legal risks implied by handling insurance-domain PII as
  discussed in SECURITY_REVIEW.md.
- The monitoring surface that makes each risk observable in production.

Out of scope:

- Business-model risk, market-fit risk, and commercial positioning. This is
  an internal platform, and product-market risk is owned by the operations
  leadership, not this document.
- Risks that are properties of the entire software industry (for example,
  the existence of zero-day CVEs in the Python runtime itself) are
  acknowledged in the dependency section but not enumerated line by line.
- Speculative risks tied to technology choices that have been explicitly
  rejected in SYSTEM_ARCHITECTURE.md section 24. This document does not
  enumerate Kubernetes or Kafka failure modes because the platform does not
  use them.

## Methodology

Risks are rated on three axes:

1. Likelihood that the risk materializes in the Phase 1 operating envelope
   (one host, moderate traffic, a small operations team). Rated low,
   medium, or high.
2. Impact on platform correctness, availability, audit integrity, or
   compliance posture if the risk materializes without mitigation. Rated
   low, medium, or high.
3. Severity derived from the Likelihood by Impact matrix below.

| Likelihood by Impact | Low impact | Medium impact | High impact |
| --- | --- | --- | --- |
| Low likelihood | Low severity | Low severity | Medium severity |
| Medium likelihood | Low severity | Medium severity | High severity |
| High likelihood | Medium severity | High severity | High severity |

A mitigation is a concrete action, a concrete configuration, or a documented
accepted-risk decision. It is not an intention. The four acceptable forms
are:

- A code-level control (for example, a retry cap in config plus a test that
  proves it holds).
- An operational control (for example, a runbook step plus a monitoring
  alert that fires when the runbook is needed).
- An architectural control (for example, a schema constraint that makes
  the failure mode representable only at boundaries the code explicitly
  handles).
- An explicit accepted-risk decision, in which case the risk is tagged
  "accepted" and is listed in the accepted-risk section of the response
  catalog with the exit criterion that would unaccept it.

Vague phrases such as "be careful", "document clearly", or "keep in mind"
are not mitigations for the purposes of this document and are rejected in
review.

Severity rules for this document:

- A high-severity risk requires a documented mitigation or an explicit
  accepted-risk decision before Phase 1 go-live. It cannot be carried
  implicitly.
- A medium-severity risk requires a mitigation or an explicit accepted-risk
  decision before the end of Phase 1 stabilization. It may be carried into
  go-live if its accepted-risk entry is recorded.
- A low-severity risk is tracked and reviewed on the cadence named in the
  risk row. It does not block go-live.

Review cadence rules:

- Every risk carries a review cadence column. The cadence is the interval
  at which the owner-role confirms the row is still accurate (likelihood
  rating, mitigation still in place, signal still visible).
- A risk whose signal has been silent for longer than two review cadences
  is re-examined: the signal may be broken, the likelihood may have
  dropped to the point of re-rating, or the risk may have been resolved
  by an unrelated change.
- The full risk register is re-read end-to-end at each phase transition
  (Phase 1 go-live, Phase 2 kickoff, Phase 2 to Phase 3, and so on) and
  amendments are PRs against this document.

## Technical risks

The technical risk register below covers correctness, availability, and
integrity risks for the platform as defined in
[SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md). Each risk has a stable
identifier. Rows are sorted by identifier, not by severity; severity is a
column on each row.

| ID | Risk | Likelihood | Impact | Severity | Mitigation | Owner-role | Review-cadence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TR-001 | Postgres outage causes `/v1` writes to 503 and workers to pause mid-Step | Medium | Medium | Medium | Documented runbook for Postgres restart and restore; `/readyz` returns 503 when the DB is unreachable so the load balancer stops sending new requests; workers exit with non-zero status on a persistent connection error and Compose restarts them with backoff; alert on `workflow_runs_running_total` stagnating for longer than the expected Step duration | SRE | Weekly during Phase 1, monthly thereafter |
| TR-002 | Redis outage blocks `tasks_outbox` drain and prevents worker pickup | Medium | Medium | Medium | `tasks_outbox` is durable in Postgres; the drain loop is idempotent and resumes from the outbox on Redis recovery; `/readyz` reflects Redis reachability; alert on `outbox_drain_lag_seconds` exceeding the documented budget (see OBSERVABILITY_STRATEGY.md) | SRE | Weekly during Phase 1, monthly thereafter |
| TR-003 | Worker crashes mid-Step and leaves a `Task` inflight in the reliable-queue inflight list | High | Low | Medium | Reaper loop sweeps the inflight list on a fixed interval and returns `Tasks` whose visibility timeout has expired back to the ready queue; StepAttempt idempotency keyed on `(workflow_run_id, step_name, step_attempt_number)` makes the re-pickup safe | Platform engineer | Monthly |
| TR-004 | Poison-pill `Task` fails on every worker and loops forever | Medium | Medium | Medium | Bounded retries per Step (default 3 attempts, configurable in code, never unbounded); a `Task` that exhausts retries moves to the dead-letter list; a worker never deletes or mutates a `Task` outside the reliable-queue ACK path; DLQ depth exposed as `dlq_depth` metric | Platform engineer | Monthly |
| TR-005 | Audit chain break goes undetected because no one runs the verifier | Low | High | Medium | Phase 2 ships the hash-chain verifier as a scheduled job; until then, a manual verification step is part of the Phase 1 on-demand playbook; `audit_events.prev_event_hash` is non-nullable and the application code refuses to insert an event whose predecessor hash does not match the tail of the chain for that `workflow_run_id` | SRE | Phase 2 enables the scheduled verifier; manual check quarterly in Phase 1 |
| TR-006 | Extractor non-determinism breaks WorkflowRun replay from `AuditEvent` log | Medium | High | High | Every StepAttempt records the extractor name and version; Phase 1 extractor is a deterministic stub (regex and rules only); Phase 3 model-backed extractor stores inputs and a content-hashed result so replay returns the same output for the same input; workflow tests freeze the clock and assert byte-identical extractor output for a curated fixture corpus | Platform engineer | Per extractor release |
| TR-007 | PII leaked into application logs because a log line forgets to redact | Medium | High | High | structlog redaction processor configured at app start time and applied to every log record before emission; known PII field names are enumerated in a single module; an integration test feeds a document with seeded PII through the pipeline, collects every log line, and asserts that none of the seeded values appear; the test fails the build on any leak | Security reviewer | Every PR that touches logging or document handling |
| TR-008 | Alembic migration causes downtime because it takes a long lock on a hot table | Medium | High | High | All destructive or lock-heavy changes go through expand-migrate-contract; the migration-review checklist in CONTRIBUTING scope (documented in PHASED_ROADMAP.md engineering workflow) requires an explicit migration-safety note on every PR that adds a migration; Phase 2 adds a migration-plan dry run against a production-sized dataset in staging | Platform engineer | Every PR touching `alembic/versions/` |
| TR-009 | Clock skew between hosts corrupts the audit timeline or queue ordering | Low | Medium | Low | NTP configured on every host in the deployment unit as a baseline control; Redis server clock is authoritative for queue timestamps (`task_enqueued_at`); Postgres `NOW()` is authoritative for audit `occurred_at`; no code path compares a worker-local wall clock to a server-issued timestamp | SRE | Quarterly |
| TR-010 | A pinned dependency ships a CVE that we do not notice | Medium | Medium | Medium | `pip-audit` (or `uv audit` depending on the Phase 1 toolchain selection) runs in CI on every PR and on a nightly scheduled CI run; a finding at high or critical severity fails the build; Phase 2 adds Dependabot or Renovate with an explicit review window; dependencies are pinned via a lockfile so upgrades are explicit | Platform engineer | Nightly CI plus monthly dependency review |
| TR-011 | An attacker with DB-admin credentials tampers with `audit_events` by deleting rows | Low | High | Medium | The application DB role used by the API and worker processes has only INSERT on `audit_events`, not UPDATE or DELETE; admin DB access is separated and gated behind a break-glass process; the hash-chain verifier detects missing rows because the next row's `prev_event_hash` will not match; SECURITY_REVIEW.md documents that full physical immutability against a root-level attacker is out of scope and tamper-visibility is the property claimed instead | Security reviewer | Phase 2 and quarterly thereafter |
| TR-012 | Unbounded metric cardinality melts the Prometheus scrape target | Low | Medium | Low | OBSERVABILITY_STRATEGY.md defines a cardinality contract: labels are drawn from a closed set (workflow_name, step_name, attempt_outcome, role) and never include `workflow_run_id`, `document_id`, `user_id`, or other high-cardinality identifiers; code review rejects any metric definition that violates the contract; the metric registry is inspected in a unit test that asserts the closed-set rule | Platform engineer | Every PR that adds or modifies metrics |
| TR-013 | A change to a workflow definition silently alters what a replay produces | Medium | High | High | Every WorkflowRun records the `workflow_version` string pinned at start; the workflow loader refuses to replay a run under a `workflow_version` the codebase does not carry; new workflow logic is always a new version, never an edit to an existing one; a test locks the workflow-version registry against accidental renames | Platform engineer | Every PR that touches `workflows/` |
| TR-014 | The `tasks_outbox` to Redis drain falls behind under load and work piles up in Postgres | Medium | Medium | Medium | The drain loop batches by a configured size and emits `outbox_drain_batch_seconds` and `outbox_drain_lag_seconds` metrics; an alert fires when lag exceeds the documented budget; SYSTEM_ARCHITECTURE.md section 21 names horizontal scaling of workers and increasing drain batch size as the two levers | SRE | Weekly during Phase 1 |
| TR-015 | An operator claims an `EscalationCase` and goes offline, blocking progress on that case | Medium | Medium | Medium | Every `claimed` case has a claim TTL; a background sweeper transitions claim-TTL-expired cases back to `open` and emits an `AuditEvent` recording the automatic un-claim; OBSERVABILITY_STRATEGY.md exposes `escalations_claimed_expired_total` so supervisors can see the pattern | Supervisor | Monthly |
| TR-016 | Request body larger than available memory is accepted and crashes the API process | Low | Medium | Low | FastAPI request-size limit configured centrally; `POST /v1/documents` enforces a per-endpoint limit sized for the largest supported document type; body exceeding the limit is rejected with 413; the limit and its test live next to the endpoint | Platform engineer | Every PR that touches upload endpoints |
| TR-017 | A `Step` handler raises an unhandled exception type that bypasses the retry policy | Low | High | Medium | The worker loop wraps every Step handler call in a typed-error boundary: retryable domain errors drive a retry StepAttempt, terminal domain errors drive a failed StepAttempt, any other exception is converted to a terminal StepAttempt with full traceback in the AuditEvent and alerted on; the test suite includes a negative test per exception class | Platform engineer | Every PR that touches the worker loop or domain errors |
| TR-018 | A FastAPI endpoint returns an internal error object that leaks a database column name or stack fragment | Low | Medium | Low | A global exception handler converts unhandled exceptions to a typed error response with a stable error code and no stack trace; the trace is logged with correlation-id; a contract test asserts that no response body contains stack-trace markers (`Traceback`, `at line`, etc.) | Security reviewer | Every PR that touches error handling |

### Notes on the top technical risks

TR-006 (extractor non-determinism breaking replay) is the sharpest risk in
this register for a reason: the audit-replay property is the feature that
distinguishes this platform from a generic task runner. The mitigation has
three layers: (a) Phase 1 ships only a deterministic stub so the property
is demonstrably true at Phase 1 go-live, (b) every StepAttempt records the
extractor name and version so a replay can refuse to proceed under an
unknown version, and (c) Phase 3 model-backed extractors are wrapped in an
adapter that content-hashes the input and caches the result so the same
input returns the same output. A Phase 3 extractor that cannot be wrapped
in this adapter cannot ship; the alternative is a documented degradation
of the replay property, which requires a SPEC.md amendment.

TR-007 (PII leaked into logs) is rated high-severity because a single
leaked log line is an incident that cannot be undone. The control is not
"remember to redact"; it is a processor installed at app start time that
redacts by field name and a test that feeds seeded PII through the
pipeline and asserts none of the seeded values appear in captured logs.
The test is in the unit tier so it runs on every PR, not just nightly.

TR-008 (Alembic migration causes downtime) is the risk most often
under-rated by development teams. A new column with a default on a large
hot table is a long lock in Postgres unless the column is added without a
default and backfilled in a later step. The review discipline requires
every migration PR to state which phase of expand-migrate-contract the
migration is in and why it is safe for the size of the target table.

TR-013 (workflow-definition change silently alters replay) and TR-006
together guard the same property from two different directions: TR-006
guards it from non-determinism inside a Step, TR-013 guards it from a
change to the sequence of Steps. Both must hold for replay to be
believable. A workflow change that modifies the step sequence without
creating a new `workflow_version` would defeat the TR-013 mitigation; the
control is that the workflow loader refuses to run an unknown version and
the version registry is locked against accidental rename in a test.

TR-017 (unhandled exception bypasses retry policy) is rated high-impact
because an unbounded traceback-only failure can take down a worker loop.
The typed-error boundary is the guard: retryable domain errors, terminal
domain errors, and everything else are three distinct handling paths.
Adding a new exception class without assigning it to one of these paths
is a review rejection.

## Operational risks

Operational risks describe ways that the running system and the team that
operates it can fail, independent of code correctness. The Phase 1 posture
documented in DEPLOYMENT_STRATEGY.md is intentionally small; many of the
rows below are explicit accepted risks with a named Phase 2 exit.

| ID | Risk | Likelihood | Impact | Severity | Mitigation | Owner-role | Review-cadence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OR-001 | Single-host Compose deployment is a single point of failure; host loss loses the running state | High | High | High (accepted at Phase 1) | Accepted risk for Phase 1 with exit criterion: when traffic or resilience requirements exceed a single host, the deployment moves to the Phase 2 posture documented in DEPLOYMENT_STRATEGY.md. Mitigations that hold at Phase 1: nightly Postgres backup to a distinct volume, restore-from-backup runbook that has been executed at least once before go-live, and monitoring that detects host-level failure within minutes | SRE | Quarterly review of the exit criterion |
| OR-002 | No on-call rotation at Phase 1, so a nighttime incident is detected only on the next business morning | High | Medium | High (accepted at Phase 1) | Accepted risk for Phase 1 with exit criterion: Phase 2 defines SLOs and establishes an on-call rotation. Mitigation that holds at Phase 1: the platform is not load-bearing for synchronous customer traffic and its work is queued, so an overnight outage delays work but does not drop it; the queue is durable and resumes cleanly on recovery | Operations supervisor | Phase 2 entry criterion |
| OR-003 | Manual secret rotation at Phase 1 is easy to forget, and a rotated secret may linger in an env file longer than intended | Medium | Medium | Medium (accepted at Phase 1) | Accepted risk for Phase 1 with exit criterion: Phase 2 ships an admin endpoint for API-key rotation and documents a secret-rotation cadence in DEPLOYMENT_STRATEGY.md. Mitigation that holds at Phase 1: secrets live only in the deployment platform's secret store and the `.env.example` carries only variable names; rotation is a documented runbook step after any suspected leak | SRE | Quarterly |
| OR-004 | Backup restore is not drilled at Phase 1, so the first real restore is the production incident | Medium | High | High | Phase 2 establishes a quarterly restore drill against a throwaway database built from the latest backup; the drill produces a dated, signed runbook entry; Phase 1 mitigation is a one-time pre-go-live restore exercise that is recorded as done or the go-live is blocked | SRE | Quarterly starting Phase 2; one-off before Phase 1 go-live |
| OR-005 | Log volume grows faster than disk and fills the host, crashing all processes | Low | High | Medium | Log rotation configured in the deployment unit; log shipping to a persistent backend is a Phase 2 decision (see OBSERVABILITY_STRATEGY.md); disk-usage alert fires at a documented threshold; the container log driver has a max-size cap configured | SRE | Monthly |
| OR-006 | Operators execute manual SQL against production under time pressure and corrupt state | Low | High | Medium | DB access is gated behind a break-glass role documented in SECURITY_REVIEW.md; the application role used by API and worker cannot perform destructive operations on audit tables; a runbook lists the approved queries and the approval required for anything else | Security reviewer | Quarterly |
| OR-007 | Operations team turnover loses tacit knowledge about the queue and escalation model | Medium | Medium | Medium | The documentation set produced in Phase 0 is the canonical handoff; every runbook carries a last-reviewed date; a new-hire onboarding checklist walks through the Phase 0 docs in the reading order defined in the README | Operations supervisor | Quarterly |

### Notes on the accepted operational risks

OR-001 (single-host SPOF) is the largest single risk in the register and
it is explicitly accepted for Phase 1. The alternative, a Phase 2
deployment posture at Phase 1 time, is premature on two grounds:
complexity that is not justified by the Phase 1 traffic envelope, and
cross-host coordination concerns (shared Postgres, shared Redis, shared
object storage) that are themselves risks until they are operated for
long enough to be understood. The exit criterion is concrete: measured
resource pressure or a named business requirement moves the deployment
to the Phase 2 posture. Until then, the mitigation that keeps the
acceptance honest is the backup and restore discipline, which is
verified once before go-live.

OR-002 (no on-call at Phase 1) is accepted on the grounds that the work
is asynchronous and durable: the queue does not drop work on outage, and
customer-facing latency is not part of the Phase 1 contract. If the work
becomes synchronous or latency-sensitive before Phase 2, the acceptance
is revoked.

OR-003 (manual secret rotation) is accepted on the grounds that the
number of secrets at Phase 1 is small (database URL, Redis URL, API key
signing secret, encryption key) and the cadence is annual unless an
incident forces it. The exit criterion is the Phase 2 admin endpoint.
The interim control is a runbook that names each secret, the rotation
procedure, and the last rotation date.

## Delivery risks

Delivery risks are risks to completing the Phase 0 and Phase 1 plan as
described in PHASED_ROADMAP.md. They are about the process of building the
thing, not the thing itself.

| ID | Risk | Likelihood | Impact | Severity | Mitigation | Owner-role | Review-cadence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| DR-001 | Scope creep pulls Phase 2 or Phase 3 work into the Phase 1 slice | Medium | Medium | Medium | PRD discipline: every requirement in PRODUCT_REQUIREMENTS.md carries a phase tag, and work outside the Phase 1 tag is a deliberate exception recorded in the PR body with named approver; PHASED_ROADMAP.md engineering workflow names the exception path | Tech lead | Every PR |
| DR-002 | Premature optimization wastes phase budget on abstractions that do not pull weight | Medium | Medium | Medium | PHASED_ROADMAP.md explicitly rejects speculative work; TECHNICAL_DEBT_PREVENTION.md enumerates the anti-patterns refused at the door (no plugin system, no generic rule engine, no abstract workflow DSL at Phase 1); review rejects abstractions that are not justified by at least two concrete call sites | Tech lead | Every PR |
| DR-003 | Vendor lock-in emerges by choosing a specific secret store, queue, or deploy platform too early | Medium | Medium | Medium | DEPLOYMENT_STRATEGY.md defines an abstract contract for secrets, deployment target, and CI; concrete platform choices at Phase 2 or later are implementations of that contract; no cross-cutting code path imports a vendor-specific SDK outside a dedicated adapter module | Platform engineer | On every new adapter introduction |
| DR-004 | Sandbox network constraint blocks CI-like verification during Phase 0 development | High | Low (Phase 0), Medium (Phase 1) | Medium | Phase 0 deliverable is markdown only and has no CI; Phase 1 work is staged in an environment with package-registry access so CI (ruff, mypy, pytest, docker build) can actually run; this risk is recorded explicitly so the Phase 1 kickoff does not discover it | Platform engineer | Phase 1 kickoff |
| DR-005 | Reviewer availability is the bottleneck for merging Phase 1 PRs | Medium | Medium | Medium | Review discipline in TECHNICAL_DEBT_PREVENTION.md acknowledges a small-team reality: one reviewer plus the author is acceptable if the discipline is explicit; PR template requires reviewer sign-off; at-risk weeks are flagged in the phase kickoff | Tech lead | Weekly during Phase 1 |
| DR-006 | A Phase 0 document drifts from another Phase 0 document during editing and the inconsistency is merged | Medium | Medium | Medium | Cross-document-consistency rules in context.json are enforced by the review: every PR that touches a canonical name, lifecycle state, or domain entity must update every document that references it, or the PR is rejected; SPEC.md is the tie-breaker if two documents disagree | Tech lead | Every Phase 0 PR |

## Compliance and legal risks

InsuranceOps AI handles PII in the insurance domain. Phase 1 does not claim
any compliance certification. This section records the compliance posture
honestly and names the path forward if the operating context requires more.

- Non-claims at Phase 1. The platform does not claim SOC 2, HIPAA, GDPR
  certification, PCI-DSS posture, or ISO 27001 alignment. This is stated
  explicitly in SECURITY_REVIEW.md and is not something to discover during
  a customer or auditor conversation.
- PII handling. Documents may contain PII (names, addresses, SSNs, DOBs,
  policy numbers). Phase 1 stores known-PII fields encrypted at rest using
  a key sourced from the deployment platform's secret store. Logs redact
  known PII via a structlog processor. Backups inherit the at-rest
  encryption model of the underlying storage volume and do not decrypt
  PII columns. SECURITY_REVIEW.md owns the full policy.
- HIPAA alignment, not certification. If the operating context becomes one
  where the platform processes protected health information, the path is
  Phase 2 or later: (a) a Business Associate Agreement is put in place with
  the deployment platform vendor, (b) the minimum-necessary principle is
  encoded in the role model and audit retention, (c) a dedicated access
  review cadence is established. This is alignment with HIPAA
  administrative and technical safeguards; certification is a separate
  legal process that is out of scope for this document.
- GDPR posture. The data-minimization posture is established at Phase 1
  (only the fields needed for the workflow are ingested). Right-to-erasure
  and data-subject-access responses are a Phase 2 or later operational
  capability and are named as such. The risk is that a request arrives
  before the capability exists; mitigation is a contractual boundary in
  the operating context that defers such requests to a Phase 2 date, or
  a manual process gated by the security reviewer role.
- Data residency. Phase 1 assumes a single deployment region. Cross-region
  residency requirements are a Phase 4 or later concern aligned with the
  PHASED_ROADMAP.md tenant-isolation slice and are not promised before
  then.
- Audit retention. The audit model in SYSTEM_ARCHITECTURE.md section 16
  is append-only, and the retention horizon is documented in
  SECURITY_REVIEW.md. The risk is that retention shrinks under storage
  pressure; mitigation is a monitored free-space budget and a documented
  archival procedure in Phase 2.
- Legal hold. A per-WorkflowRun legal-hold flag is not a Phase 1
  capability. If one becomes necessary before the capability exists, the
  mitigation is a manual freeze of the relevant rows through the
  break-glass admin role, recorded in the audit trail of admin access.

## Risk response catalog

Every risk recorded above falls into one of three response categories.
Rows are grouped by response so a reader can see at a glance which risks
are mitigated by action, which are accepted with an exit criterion, and
which are transferred.

### Accepted risks

An accepted risk is one where the Phase 1 response is deliberately to live
with it under named conditions. Each accepted risk has an exit criterion
that triggers re-evaluation. Unaccepting a risk is a roadmap event, not a
spontaneous decision.

| ID | Why accepted now | Exit criterion |
| --- | --- | --- |
| OR-001 | Single host is the right operational scope for the Phase 1 traffic envelope | Move to Phase 2 deployment posture when any of: sustained CPU above the documented host capacity, sustained memory above 80 percent, or a business requirement for cross-host redundancy |
| OR-002 | No on-call at Phase 1 because the work is asynchronous and durable | Establish rotation when SLOs are adopted in Phase 2, or when overnight incident count crosses the documented threshold, whichever comes first |
| OR-003 | Manual secret rotation is acceptable while the number of secrets and the rotation cadence are both small | Build the admin rotation endpoint in Phase 2 |
| DR-004 | Phase 0 is markdown only, so the sandbox network constraint does not block delivery | Stage Phase 1 work where package registries and container registries are reachable |

### Mitigated risks

A mitigated risk has a concrete control that reduces likelihood or impact.
The control is named in the Mitigation column of the technical,
operational, or delivery tables above. The monitoring section below states
how we would see the control fail.

Mitigated risks: TR-001, TR-002, TR-003, TR-004, TR-005, TR-006, TR-007,
TR-008, TR-009, TR-010, TR-011, TR-012, TR-013, TR-014, TR-015, TR-016,
TR-017, TR-018, OR-004, OR-005, OR-006, OR-007, DR-001, DR-002, DR-003,
DR-005, DR-006.

### Transferred risks

A transferred risk is one whose impact is borne by a platform or contract
outside this project. The transfer is only valid if the contract is real.
At Phase 1, transfer candidates are few because the deployment target is
small; the list grows as the platform moves to a managed environment.

- Underlying hypervisor or cloud-host failure is transferred to the
  hosting platform's availability contract once a managed platform is
  adopted at Phase 2. Until then the risk is accepted under OR-001.
- Certificate-authority compromise for TLS endpoints is transferred to the
  CA chain and rotated through the hosting platform's certificate manager
  when one is adopted; until then the operator rotates certs manually and
  the risk is recorded under OR-003.
- Third-party extractor availability (Phase 3 real model integration) is
  transferred to the model vendor's SLA; the mitigation at the platform
  boundary is a bounded timeout, a deterministic fallback, and a
  retry-with-cap discipline.

## Monitoring of risks

Every mitigated risk above is paired below with the specific signal that
reveals the mitigation failing. A risk with no signal is not considered
mitigated even if the code is written; it is added to the accepted list
with an exit criterion that creates the signal.

| Risk | Signal type | Signal name or description | Where it lives |
| --- | --- | --- | --- |
| TR-001 | Health probe plus metric | `/readyz` returns 503 when Postgres is unreachable; `workflow_runs_running_total` stagnating for longer than the expected Step duration | API process; Prometheus scrape |
| TR-002 | Health probe plus metric | `/readyz` reflects Redis reachability; `outbox_drain_lag_seconds` histogram | API and worker processes; Prometheus scrape |
| TR-003 | Metric | `queue_reaper_recovered_total` counter increments when the reaper returns timed-out inflight tasks | Worker process |
| TR-004 | Metric | `dlq_depth` gauge exposes dead-letter queue size; alert at documented threshold | Worker process |
| TR-005 | Scheduled check | Phase 2 scheduled `audit_chain_verify` job; Phase 1 manual quarterly verification recorded in runbook | CI schedule (Phase 2); runbook (Phase 1) |
| TR-006 | Test plus metric | `extractor_version` label on StepAttempt metrics; replay test in CI asserts byte-identical extractor output across versions in the fixture corpus | Test suite; Prometheus scrape |
| TR-007 | Integration test plus log-pattern check | End-to-end test feeds seeded PII and asserts no seeded value appears in captured logs; runtime pattern check in the log shipper at Phase 2 | Test suite; log shipper (Phase 2) |
| TR-008 | PR gate | Migration-safety note required on every PR that adds a migration; migration-plan dry run in staging at Phase 2 | Review process; staging CI job |
| TR-009 | System metric | NTP offset exposed as host-level telemetry (standard node exporter or equivalent at Phase 2) | Host metrics |
| TR-010 | CI job | `pip-audit` (or `uv audit`) nightly run and per-PR run fails the build on high or critical severity | CI |
| TR-011 | Schema constraint plus scheduled verifier | DB role lacks UPDATE/DELETE on `audit_events`; hash-chain verifier catches missing rows | Postgres grants; scheduled job |
| TR-012 | Unit test | Metric-registry inspection test asserts closed-set labels | Test suite |
| TR-013 | Schema invariant plus loader check | `workflow_runs.workflow_version` non-nullable; workflow loader refuses to replay an unknown version | Postgres schema; application code |
| TR-014 | Metric | `outbox_drain_lag_seconds` and `outbox_drain_batch_seconds` | Worker process |
| TR-015 | Metric | `escalations_claimed_expired_total` counter | API process |
| TR-016 | Contract test | Upload size limit test asserts 413 on oversize bodies | Test suite |
| TR-017 | Unit test plus metric | Per-exception-class negative tests; `step_attempts_terminal_total{reason}` labelled by terminal reason | Test suite; Prometheus scrape |
| TR-018 | Contract test | Response bodies are scanned for stack-trace markers; global exception handler is covered by tests | Test suite |
| OR-001 | Host metric plus backup log | Host availability probe; backup job produces a success log each night, absence triggers an alert | Host metrics; backup runbook |
| OR-002 | Review cadence | Phase 2 kickoff checks whether on-call rotation is in place | Roadmap review |
| OR-003 | Calendar control | Secret rotation cadence recorded in runbook with last-rotated date | Runbook |
| OR-004 | Runbook artifact | Dated restore-drill record, produced quarterly from Phase 2 | Runbook |
| OR-005 | Host metric | Disk-free percentage alert at documented threshold | Host metrics |
| OR-006 | Access log | Admin-role access log reviewed monthly | Security review cadence |
| OR-007 | Onboarding checklist | New-hire walkthrough signed off before first on-call shift | HR and onboarding process |
| DR-001 | Review gate | Phase tag on every PRD line; PR body declares any out-of-phase work | Review process |
| DR-002 | Review gate | Reviewer rejects unjustified abstractions; TECHNICAL_DEBT_PREVENTION.md is the checklist | Review process |
| DR-003 | Review gate | New vendor-specific adapter requires an entry in SYSTEM_ARCHITECTURE.md section 23 | Review process |
| DR-005 | Weekly check | Reviewer load reviewed at weekly Phase 1 sync | Weekly sync |
| DR-006 | Review gate | PR that touches a canonical term updates every document that references it | Review process |

## Assumptions

- The Phase 1 operating envelope matches what DEPLOYMENT_STRATEGY.md
  describes: one host, one Compose stack, asynchronous work, a small
  operations team. Risks whose likelihood rating depends on this envelope
  (OR-001 through OR-005) should be re-rated at Phase 2 entry when the
  envelope grows.
- Every control named in the Mitigation column is implementable within the
  Phase 1 budget. Where a control is Phase 2, the row says so, and the
  accepted-risk section carries the interim posture.
- Observability is real by Phase 1 in the shape defined by
  OBSERVABILITY_STRATEGY.md. If a metric named in the monitoring table
  does not exist at Phase 1 go-live, the corresponding risk is re-rated
  higher until the metric exists.
- Audit integrity is implemented as tamper-visibility, not
  tamper-proofness. A sufficiently privileged attacker with root access
  to the database host can remove rows; the verifier will detect the
  removal. This is the property SECURITY_REVIEW.md claims and this
  document preserves.
- The structlog redaction processor is applied at app start time and
  cannot be bypassed by a caller; any change to logging configuration
  must be reviewed with TR-007 in mind.
- The hash-chain verifier is a Phase 2 scheduled job. Phase 1 runs it
  manually as part of the quarterly security review. If a real tamper
  event is suspected before the scheduled job exists, the manual run is
  an immediate incident-response step.
- Vendor-specific failure modes (managed Postgres outage, managed Redis
  outage, hosting-platform incident) are inherited from the chosen
  managed platform at Phase 2 and are not individually enumerated here
  until that choice is made; they will be added to this register when
  the platform is chosen.
- Risks not in this register are not necessarily absent; they are
  understood to exist at a level of detail below what this document
  tracks (for example, a bug in a specific line of Python). The test
  suite and the review discipline in TECHNICAL_DEBT_PREVENTION.md are
  the controls for that layer, not this document.
