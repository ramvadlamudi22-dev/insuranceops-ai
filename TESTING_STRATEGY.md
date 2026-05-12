# TESTING_STRATEGY.md

## Purpose

This document is the authoritative testing posture for InsuranceOps AI.
It elaborates the brief testing summary in the Phase 1 slice of
[PHASED_ROADMAP.md](./PHASED_ROADMAP.md) and specifies the shape of the test suite
that protects the correctness properties declared in
[SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md): deterministic workflow execution,
bounded retries, exactly-once audit with hash-chain tamper visibility, and
reliable-queue invariants.

The audience is the engineer who will scaffold `tests/` in Phase 1 and the reviewer
who will block a PR if the suite drifts from this shape. The document names the
tiers, the directories they live in, the rules for admission to each tier, the
determinism and hermeticity rules that make the suite believable, and the CI
contract the suite must satisfy.

## Scope

In scope:

- The five-tier test structure (`tests/unit/`, `tests/integration/`, `tests/workflow/`,
  `tests/failure/`, `tests/audit/`) with per-tier purpose, entry rule, and approximate
  runtime budget.
- Determinism rules that apply to every tier.
- Hermeticity rules that keep the suite self-contained and offline.
- Test-data strategy (factories, golden files where appropriate, no shared giant JSON).
- Specific test shapes required for workflow replay, retry bounds, queue processing,
  audit consistency, and failure paths.
- Local test runtime expectations and the CI contract.
- Coverage posture and exclusions.

Out of scope:

- The concrete pytest test code. Phase 0 is documentation only. Files under
  `tests/` are authored in Phase 1 per the roadmap.
- The CI workflow YAML. That is specified in [DEPLOYMENT_STRATEGY.md](./DEPLOYMENT_STRATEGY.md)
  and created in Phase 1.
- Load testing, chaos testing, and production soak testing. The load-test harness
  is named as a Phase 2 deliverable in the roadmap; this document acknowledges it
  exists but does not design it.
- Security penetration testing. That is a Phase 2 exercise described in
  [SECURITY_REVIEW.md](./SECURITY_REVIEW.md).

## Testing principles

These principles are the yardstick against which every proposed test is measured.
A test that violates a principle is either rewritten to fit or deleted.

- **Deterministic.**
  A test produces the same result on every run. It does not depend on wall-clock time,
  on network ordering, on the order pytest happens to collect tests, or on a random
  seed it did not set itself. Workflow-level tests use an injected `Clock` and an
  injected uuid factory so that a replay run produces the same AuditEvent sequence
  byte-for-byte.
- **Hermetic.**
  A test does not reach the public internet. The only network the suite touches is
  the test Postgres and the test Redis inside the `compose.test.yml` stack. A socket
  guard fixture fails loudly if any test opens an outbound connection to any other
  host or port.
- **Fast.**
  A developer runs the default suite after every change. The default suite
  (`tests/unit/`, `tests/integration/`, `tests/workflow/`) completes under three
  minutes on a developer laptop. Tiers that cannot meet this bound live behind an
  explicit `-m slow` or run only in CI.
- **Reflective of real behavior.**
  Integration tests run against real Postgres and real Redis, not against mocks or
  in-memory substitutes. Mocks are used only at the boundary of systems the platform
  does not own (for example, a future model-backed extractor in Phase 3). Every
  in-process subsystem the platform itself owns (the orchestrator, the queue client,
  the audit writer, the reaper) is exercised with its real code path.
- **No mocks for in-process infrastructure we own.**
  If the platform owns the code, the test exercises the code. A test that mocks the
  audit writer to assert a call was made is a weaker test than one that inspects the
  `audit_events` rows the real writer produced. The second form catches driver bugs,
  query shape bugs, and serialization bugs the first form cannot.
- **No silent retries.**
  A test does not use a wait-and-retry loop with a long sleep to paper over a race.
  Either the code exposes a deterministic synchronization point (an event, an awaited
  method, a `wait_for_ready`), or the race is a bug that needs a fix. The exception
  is reaper-style polling intervals, which are tested by advancing the injected clock,
  not by sleeping.
- **Named by behavior, not by file structure.**
  Test names describe the behavior under assertion. `test_workflow_run_reaches_awaiting_human_when_validator_returns_fail_correctable`
  is preferred over `test_validator_branch_3`. A test name is a sentence a reviewer
  can read without opening the file.
- **One assertion thread per test.**
  A test asserts one behavioral property. Preconditions and sanity checks inside a
  test are acceptable; asserting two unrelated behaviors in the same function is not.
  When a test name contains "and", it is usually two tests.

## Test categories

The suite is partitioned into five tiers. Each tier has a directory, a purpose, an
entry rule (what makes a test belong in this tier), and an approximate runtime budget.
The budgets are guardrails, not contracts; a tier that exceeds its budget is a signal
to investigate before adding more work to it.

### `tests/unit/`

- **Purpose.** Exercise pure logic in isolation. Tier-1 targets include domain types
  (the `WorkflowRun` state machine transitions), pure helpers (the hash-chain computation,
  the canonical-payload serializer, the backoff calculator), Pydantic models (schema
  validation, field-level invariants), and pure utilities.
- **Entry rule.** A test belongs in `tests/unit/` if and only if it touches no network,
  no database, no Redis, no filesystem beyond `tmp_path`, no subprocess, and no
  `asyncio` event loop work beyond a single `await` on a synchronous-logic coroutine.
  If a test imports `asyncpg`, `redis.asyncio`, `httpx.AsyncClient`, or anything that
  resolves DNS, the test does not belong here.
- **Runtime budget.** Under 200 milliseconds per test. The whole tier runs in under
  30 seconds.

### `tests/integration/`

- **Purpose.** Exercise code paths that cross the DB or Redis boundary with real
  services. Tier-2 targets include repository classes (the actual INSERTs, SELECTs,
  and upserts), the queue client (LPUSH, BRPOPLPUSH, visibility timeout reclaim), the
  outbox relay (commit-then-enqueue mechanics), and the FastAPI dependency layer with
  a real session attached to a real database.
- **Entry rule.** A test belongs in `tests/integration/` if it requires the real
  Postgres, the real Redis, or both, and does not require a full WorkflowRun to
  complete. It MUST NOT reach any host outside the `compose.test.yml` service set.
  Database state is isolated per test by opening a transaction at setup and rolling
  it back at teardown; Redis state is isolated per test by a unique key prefix bound
  to the test node id and flushed at teardown.
- **Runtime budget.** Under 2 seconds per test. The whole tier runs in under 90 seconds.

### `tests/workflow/`

- **Purpose.** Exercise end-to-end WorkflowRun execution against the deterministic
  stub extractor and the rule-based validator. Tier-3 targets include the happy path
  through `claim_intake_v1`, the escalate-on-validator-failure path, the retry path
  for a transient extractor failure, and the cancel path initiated by a supervisor.
- **Entry rule.** A test belongs in `tests/workflow/` if it drives a full WorkflowRun
  from API call to terminal state (or to an asserted intermediate state such as
  `awaiting_human`), observing the state machine through the audit timeline. It uses
  the frozen `Clock` and the injected uuid factory so that the resulting AuditEvent
  sequence is byte-stable across runs.
- **Runtime budget.** Under 5 seconds per test. The whole tier runs in under 60 seconds.

### `tests/failure/`

- **Purpose.** Assert behavior under induced failures. Tier-4 targets include DB
  down during a commit, Redis down during enqueue drain, a worker crash mid-step, a
  poison-pill Task that exhausts retries, an extractor timeout, a validator
  deterministic failure, and an EscalationCase expiring.
- **Entry rule.** A test belongs in `tests/failure/` if it deliberately breaks one of
  the platform's dependencies or components and asserts the documented response from
  [SYSTEM_ARCHITECTURE.md section 22](./SYSTEM_ARCHITECTURE.md). The breakage is done
  via test-only hooks (pause the DB container via the Compose control plane, drop all
  Redis connections via a proxy fixture, kill the worker subprocess) and never via
  sleep-based flakiness. A test in this tier MUST restore the dependency it broke
  before it exits.
- **Runtime budget.** Under 15 seconds per test. The whole tier is gated behind
  `-m slow` locally and runs on every CI build. Total runtime for this tier is under
  4 minutes.

### `tests/audit/`

- **Purpose.** Assert the invariants of the audit subsystem: every state transition
  produces exactly one AuditEvent, the per-run hash chain verifies, and tampering
  with any row is detected at the tampered event.
- **Entry rule.** A test belongs in `tests/audit/` if the product under assertion is
  the AuditEvent stream itself (its shape, ordering, chain linkage, completeness, or
  tamper detection). A workflow test that happens to read audit rows for a sanity
  check does not move here; it stays in `tests/workflow/`. A test that reconstructs
  the canonical-payload bytes and recomputes the chain for every event in a run
  belongs here.
- **Runtime budget.** Under 3 seconds per test. The whole tier runs in under 45 seconds.

The directories are flat. Subdirectories inside a tier are allowed for natural
groupings (for example, `tests/integration/db/` and `tests/integration/queue/`),
but the tier decision is always made at the top level. No test imports fixtures
across tiers; a fixture that is useful in two tiers is promoted to `tests/conftest.py`
or a shared helper module.

## Determinism rules

Determinism is the property that lets the suite catch regressions and lets the
workflow replay tier work at all. The rules below apply to every tier.

### Frozen clock

All code that reads wall-clock time goes through an injectable `Clock` abstraction.
The `Clock` has `now_utc()` returning an aware datetime and `sleep(seconds)` for
use in the few places that need to wait. The production `Clock` delegates to the
system clock; the test `Clock` is controlled from fixtures.

Test code uses one of two tools:

- A `frozen_clock` fixture that sets the clock to a fixed instant at the start of
  the test and never advances it. This is the default for workflow tests where the
  test drives the clock explicitly.
- `freezegun.freeze_time(...)` around code paths that read `datetime.utcnow()` via a
  third-party library the platform cannot easily route through `Clock`. This is the
  escape hatch and is tagged in a comment so a future refactor can remove it.

Tests that observe time-based behavior (retry backoff, delayed-queue maturation,
reaper sweeps, EscalationCase expiration) advance the test clock by known amounts
and then call the subsystem's `tick()` entry point. They do NOT sleep.

### Deterministic uuid generation

All uuid generation inside workflow code goes through an injected
`IdentifierFactory` that returns a sequence. The production factory wraps
`uuid.uuid7()`; the test factory returns a predictable sequence derived from a
per-test seed. This lets workflow tests assert on byte-stable AuditEvent chains and
byte-stable state transitions.

Random numbers used for jitter go through an injected `Random` with a per-test
seed. The production `Random` is seeded from the system entropy source; the test
`Random` is seeded from the test node id so that a specific failing test reproduces
the same sequence on rerun.

### No sleeps longer than 10 milliseconds on the test path

The test suite does not call `asyncio.sleep(seconds)` or `time.sleep(seconds)` with
a value greater than 10 milliseconds on the path from test entry to assertion.
A test that needs a time-dependent side effect uses the injected clock to simulate
the passage of time. A test that needs to wait on an event uses an `asyncio.Event`
or a `wait_for_ready` helper with a tight timeout (200 milliseconds maximum) that
fails loudly rather than sleeping hopefully.

Sleeps longer than 10 milliseconds inside production code are reviewed against the
retry-bound and reaper-interval contracts; they are not prohibited in production,
only on the test path.

### Stable ordering

Tests that read rows from the database use an explicit `ORDER BY` on a stable
column. Tests that iterate over a dictionary use `sorted()` where order matters.
Tests never rely on the order pytest happens to collect tests; fixtures that
depend on ordering are rewritten to depend on explicit setup instead. The suite
is run with `pytest-randomly` enabled so order-dependent bugs fail fast.

### Byte-stable serialization

The canonical-payload serializer that feeds the AuditEvent hash chain is
deterministic: sorted keys, UTC-aware timestamps formatted with a single format
string, no floating-point timestamps, and no "one of many valid orderings" list
fields. The audit tier asserts byte equality, not just logical equality.

## Hermeticity rules

Hermeticity is the property that lets the suite run in CI without network access
and without leaking state between tests.

### No outbound network

A session-scoped `socket_guard` fixture patches `socket.socket` to raise on any
`connect()` to a host or port outside an allowlist. The allowlist contains exactly
the Postgres host, the Redis host, and any loopback loopbacks needed by the test
framework. A test that triggers an outbound connect fails immediately with a
descriptive error naming the test, the destination, and the call stack.

The socket guard is not optional. A test that needs to bypass it (for example, a
future contract test against a local fake of an external service) must add the
fake's host to the allowlist in the fixture, which is a visible change on review.

### No wall-clock-order dependencies

Tests do not assume that a row written at time T1 appears before a row written at
time T2 just because the test code wrote them in that order. The platform's ordering
invariants are expressed as explicit columns (`occurred_at`, `created_at`,
`seq_in_run`), and tests assert on those columns rather than on insertion order.

### No filesystem outside `tmp_path`

Tests that read or write the filesystem use pytest's `tmp_path` fixture. Writing
to the current directory, to `/tmp` directly, to the user home, or to any path
the runtime also uses is forbidden. The Phase 1 filesystem object-storage backend
is pointed at a subdirectory of `tmp_path` for every test.

### Per-test database and Redis isolation

Postgres isolation uses a transaction-per-test pattern: the fixture opens a
connection, starts a transaction, yields a session bound to that transaction, and
rolls back at teardown. Tests that need to observe committed state across
connections use a dedicated fixture that commits and a dedicated cleanup that
truncates the affected tables in dependency order.

Redis isolation uses a per-test key prefix. The fixture generates a prefix from the
pytest node id, wraps the Redis client to prepend the prefix to every key, and
calls `DEL` on every matching key at teardown. No test touches the default keyspace.

### One source of truth per tier

An integration test does not start its own Postgres server; it uses the one in
`compose.test.yml`. A workflow test does not spin up its own worker process; it
uses the worker thread or subprocess the test harness manages. This keeps the
suite from accumulating half-copies of the platform that drift out of sync.

## Test data strategy

Test data is produced by factory functions, not by a shared corpus of JSON files
that every test imports. A factory is a small Python function that returns a valid
domain object with sensible defaults and keyword overrides for the fields the test
cares about.

### Factory functions, not fixtures with implicit coupling

The shape is:

```
def make_workflow_run(
    *,
    workflow_name: str = "claim_intake_v1",
    workflow_version: str = "2024.01.01",
    state: WorkflowRunState = WorkflowRunState.pending,
    created_at: datetime | None = None,
    correlation_id: str | None = None,
    **overrides,
) -> WorkflowRun:
    ...
```

A test that needs a running workflow writes
`wr = make_workflow_run(state=WorkflowRunState.running)` and gets a valid object
with every required field filled. Fields that vary in the test are passed as
overrides; fields that do not vary use the defaults.

Factories are defined in `tests/factories/` as plain Python modules. They are not
pytest fixtures. A fixture that wraps a factory is added only when the test needs
the factory's output bound to a persistence layer (for example, a
`persisted_workflow_run` fixture that calls `make_workflow_run` and writes it to
Postgres).

### Golden files only for audit chain assertions

Golden files (committed test artifacts the test compares against) are allowed in
exactly one place: audit-chain assertions where the product under test is the
serialized byte sequence of a run's AuditEvent stream. Everywhere else, equality
is asserted field-by-field on typed objects, not by serializing to JSON and
comparing text.

Golden files live under `tests/audit/golden/` with file names that name the
WorkflowRun shape they describe (`claim_intake_v1_happy_path.ndjson`,
`claim_intake_v1_escalate_on_validator_fail.ndjson`). Each file is a
newline-delimited JSON sequence of canonical AuditEvent payloads in chain order.
A test that regenerates a golden file must justify the regeneration in the commit
message; a silent golden-file update is reviewed as a bug.

### No shared giant JSON corpus

A file named `tests/fixtures/big_sample_data.json` is a smell. If a test needs a
large Document payload, the factory builds it in memory. If a test needs many
related objects, the factory loops. A corpus file that is read by dozens of tests
couples them together and makes changes painful; a factory keeps each test's
data visible at its call site.

### Deterministic test-only extractors and validators

The Phase 1 deterministic stub extractor and the rule-based validator are the same
code production uses. Tests do not redefine them. Tests that need a controlled
extractor outcome (timeout, exception, specific extracted payload) use an
`ExtractorFactory` test seam that returns an extractor configured to produce the
desired outcome. The factory is in `tests/factories/` and is used only by the
test suite.

## Workflow replay tests

Workflow replay is the strongest correctness property the platform makes. Given
the AuditEvent log of a finished WorkflowRun, re-running the same workflow from
scratch against the same deterministic extractor, validator, clock, and identifier
factory MUST produce the same AuditEvent sequence byte-for-byte.

The shape of a replay test is as follows. It is described here in narrative; the
actual Python file is authored in Phase 1.

- **Setup.** The test selects a scenario (happy path, escalate-on-validator-fail,
  retry-then-succeed, retry-then-fail-terminal). It instantiates the test clock at
  a known instant and the test identifier factory with a known seed. It uses the
  deterministic extractor and validator with a scripted input.
- **First run.** The test starts a WorkflowRun, drives it to a terminal state by
  ticking the worker through every pending Task, and records the ordered list of
  AuditEvent rows from the `audit_events` table.
- **Capture.** The test serializes the AuditEvent stream into the canonical payload
  bytes using the same serializer the chain uses. The result is a list of bytes.
- **Second run.** The test truncates the `workflow_runs`, `steps`, `step_attempts`,
  `escalation_cases`, and `audit_events` tables (in dependency order) to clear
  state. It re-instantiates the clock and identifier factory with the same seed.
  It starts a new WorkflowRun with the same input and drives it to terminal state.
- **Compare.** The test re-serializes the new AuditEvent stream and asserts the
  two byte lists are equal. Any mismatch fails the test with a diff showing the
  first divergent event.
- **Assertion on state sequence.** The test also asserts the ordered list of
  `(step_name, step_attempt_number, state)` tuples the run traversed is equal
  across the two runs. This is a stronger invariant than terminal state equality
  and catches bugs where a run reaches the same end but through a different path.

One replay test exists per scenario. The happy-path test runs in the default
suite; scenarios that depend on timer advances (retry-then-succeed-after-backoff)
run in the default suite because the test clock makes them cheap. Scenarios that
depend on real service failures (DB down during the middle event) live in the
failure tier instead.

The golden file approach is used in addition to the two-run compare: one file
per scenario is committed under `tests/audit/golden/` and acts as a tripwire if
anyone changes the canonical-payload serializer by accident. The golden file is
regenerated by running the test with an explicit `--update-golden` pytest flag,
which is gated on a human reviewer in CI.

## Retry bound tests

Retries are bounded per step by `max_attempts` and by an exponential-backoff
schedule with jitter (base 2 seconds, cap 60 seconds). The retry tier asserts the
bounds.

### Exactly max_attempts StepAttempts on a retryable failure

- **Setup.** Configure the Step to `max_attempts = 3` with an extractor that
  always returns `failed_retryable`.
- **Action.** Drive the WorkflowRun with the test clock, advancing past each
  backoff interval to mature delayed tasks, until the run terminates.
- **Assertion.** The `step_attempts` table contains exactly three rows for this
  Step, with `attempt_number` equal to 1, 2, 3 and `state` equal to
  `failed_retryable`, `failed_retryable`, `failed_terminal` respectively. The
  final StepAttempt transitions to `failed_terminal` because the retry budget is
  exhausted.
- **Further assertion on terminal policy.** If the Step is configured with
  `escalate_on_failure=False`, the WorkflowRun is in state `failed`. If it is
  configured `escalate_on_failure=True`, the WorkflowRun is in state
  `awaiting_human` with a single open EscalationCase referencing this Step.

### Backoff delays are non-decreasing

- **Setup.** Configure the Step to `max_attempts = 5` with a forced failure.
- **Action.** Drive the run and record each Task's `scheduled_for` timestamp.
- **Assertion.** For attempts 2 through 5, the delay between the previous attempt's
  failure and the next attempt's scheduled time is greater than or equal to the
  delay of the preceding retry. Jitter is asserted as a range, not as an exact
  value: the delay for attempt N falls within `[base * 2^(N-1) * (1 - jitter_ratio),
  base * 2^(N-1) * (1 + jitter_ratio)]` and is bounded above by the cap.

### No retries past max_attempts

- **Setup.** Configure the Step to `max_attempts = 3`.
- **Action.** Drive the run past terminal failure and continue ticking the clock
  for a full visibility-timeout period.
- **Assertion.** No fourth StepAttempt row is created. The Task is either ACKed
  (if the handler treated the terminal failure as a clean outcome) or moved to the
  DLQ (if the Task exhausted its retry budget from the queue side). Either way,
  the retry budget is not exceeded.

### Jitter produces distinct schedules under the same seed

- **Setup.** Run the previous test twice with different random seeds and observe
  the delay for attempt 2.
- **Assertion.** The delay values are not identical across seeds (proving jitter
  is applied) and both fall within the declared range.

## Queue processing tests

The queue substrate is a Redis reliable-queue with LPUSH, BRPOPLPUSH into a
per-worker inflight list, an ACK via LREM, and a reaper loop that returns stuck
items from inflight to ready after the visibility timeout.

The queue tier asserts the invariants.

### Every Task is eventually ACKed or moved to DLQ

- **Setup.** Enqueue a batch of mixed-outcome Tasks (some succeed, some fail
  retryably, some fail terminally).
- **Action.** Drive the worker until the ready list and every inflight list are
  empty.
- **Assertion.** For every enqueued Task there is either a matching ACK (the task
  does not appear in ready, inflight, or dlq) or a matching DLQ entry. No Task is
  in limbo.

### Simulated worker crash does not lose a Task

- **Setup.** Enqueue a Task. Start a worker in a subprocess. Claim the Task (it
  moves to `queue:tasks:inflight:<worker_id>`). Kill the worker subprocess with
  SIGKILL.
- **Action.** Advance the test clock past the visibility timeout. Start the
  reaper. Start a replacement worker. Tick.
- **Assertion.** The Task is reclaimed to `queue:tasks:ready`, with
  `attempt_number` incremented. The replacement worker claims it, processes it,
  and ACKs. No `audit_events` row is lost; the pre-crash StepAttempt is either
  `in_progress` (left that way until the reaper runs) or `failed_retryable` (if
  the reaper writes a terminal StepAttempt row as part of reclaim, per
  architecture section 22.2).

### The reaper reclaims inflight items after visibility timeout

- **Setup.** Enqueue a Task. Claim it but do not ACK. Hold the inflight entry.
- **Action.** Advance the test clock by less than the visibility timeout. Run the
  reaper.
- **Assertion.** The inflight entry is still there (not prematurely reclaimed).
- **Action.** Advance the test clock past the visibility timeout. Run the reaper.
- **Assertion.** The inflight entry is now in `queue:tasks:ready` with
  `attempt_number` incremented.

### The delayed-queue matures items at the correct score

- **Setup.** Schedule a Task with `scheduled_for = now + 5 minutes` via the
  delayed queue (`queue:tasks:delayed`, a Redis sorted set with score equal to
  the unix timestamp of `scheduled_for`).
- **Action.** Advance the test clock by 4 minutes, run the scheduler tick.
- **Assertion.** The Task is still in the delayed set, not in ready.
- **Action.** Advance the test clock by another 2 minutes (total 6 minutes), run
  the scheduler tick.
- **Assertion.** The Task is now in `queue:tasks:ready` and no longer in the
  delayed set. The ZPOPMIN + LPUSH transaction is atomic (asserted by a test that
  inspects Redis state between the two operations using a script hook).

### Enqueue is strictly post-commit (outbox)

- **Setup.** Stage a WorkflowRun creation that is expected to enqueue a Task.
- **Action.** Intercept the DB commit with a fixture that raises an exception
  after the outbox INSERT but before commit completes.
- **Assertion.** The `workflow_runs` row is absent (transaction rolled back). The
  `tasks_outbox` row is absent. The Redis ready list is unchanged. No Task was
  enqueued because the outbox never drained.

### ACK is idempotent

- **Setup.** Claim a Task. ACK it. ACK it again.
- **Assertion.** The second ACK is a no-op (LREM returns zero). No exception is
  raised. No state is corrupted.

## Audit consistency tests

The audit tier is the final correctness tier. Every assertion here is about the
shape, ordering, or integrity of the AuditEvent stream.

### Every state transition produces exactly one AuditEvent

For each of the state machines enumerated in the canonical vocabulary
(`WorkflowRun` with states `pending`, `running`, `awaiting_human`, `completed`,
`failed`, `cancelled`; `StepAttempt` with states `queued`, `in_progress`,
`succeeded`, `failed_retryable`, `failed_terminal`, `skipped`; `EscalationCase`
with states `open`, `claimed`, `resolved`, `rejected`, `expired`), a test drives
a transition and asserts exactly one new `audit_events` row is present with the
expected `event_type`, `actor`, `workflow_run_id`, and relevant foreign keys.

A transition that writes zero AuditEvents is a bug (silent state change). A
transition that writes two AuditEvents is a bug (duplicate audit). Both are
caught by a generic parameterized test that iterates over the catalog of
transitions and their expected audit row shape.

### Per-run hash chain is verifiable

- **Setup.** Drive a complete happy-path WorkflowRun with several Steps and
  multiple retries.
- **Action.** Read every `audit_events` row for this `workflow_run_id` ordered by
  `occurred_at`, `seq_in_run`.
- **Assertion.** For each event after the first, `event_hash` equals
  `sha256(prev_event_hash || canonical_payload_bytes)`. The first event has a
  sentinel `prev_event_hash` (32 zero bytes) and a `event_hash` equal to
  `sha256(sentinel || canonical_payload_bytes)`. The last event's
  `event_hash` is stored as the run's terminal chain-head in
  `workflow_runs.last_audit_hash` (if the schema exports that) or is
  recomputable from the stream.

### Tampering with any row causes the verifier to report a mismatch at the tampered event

- **Setup.** Drive a WorkflowRun to a terminal state. Identify the middle
  AuditEvent in its chain.
- **Action.** Using a direct SQL update (bypassing the app's DB role, which has
  UPDATE revoked on `audit_events`), modify the middle event's `payload` field by
  a single byte. Run the verifier over the run's event stream.
- **Assertion.** The verifier reports a mismatch at the tampered event's
  `seq_in_run` and does not report mismatches at earlier positions. The
  verifier's output includes `workflow_run_id`, `tampered_seq_in_run`, the
  expected hash, and the observed hash.
- **Further assertion.** The verifier detects tampering whether the change is in
  `payload`, `actor`, `event_type`, `occurred_at`, or `prev_event_hash`. A test
  per field flavor confirms the canonical-payload serializer includes each field.

### No AuditEvent is updatable by the runtime DB role

- **Setup.** Using the app's runtime DB role, attempt an UPDATE on an
  `audit_events` row.
- **Assertion.** The UPDATE raises a `permission denied` error. DELETE likewise
  fails. Only the `audit_writer` role (used only by the code path that appends
  events) has INSERT.

### Completeness: no gap in seq_in_run

- **Setup.** Drive a WorkflowRun with N state transitions.
- **Assertion.** `audit_events.seq_in_run` for this `workflow_run_id` is a
  contiguous sequence from 1 to N with no gaps. A gap indicates a lost event and
  is a chain integrity bug.

## Failure-path tests

The failure tier induces the dependency failures enumerated in
[SYSTEM_ARCHITECTURE.md section 22](./SYSTEM_ARCHITECTURE.md) and asserts the
documented response.

### DB down during a commit

- **Setup.** Start a WorkflowRun creation. Allow the app to open a transaction.
- **Action.** Pause the Postgres container (or close the connection underneath
  the driver) before the commit completes.
- **Assertion.** The API returns 503. The `workflow_runs`, `steps`,
  `tasks_outbox`, and `audit_events` tables are unchanged (transaction rolled
  back). No Task was enqueued (outbox was never drained because commit failed).
  Unpausing Postgres and retrying the same request with the same
  `Idempotency-Key` succeeds and produces exactly one WorkflowRun.

### Redis down during enqueue drain

- **Setup.** Complete a successful commit that writes a `tasks_outbox` row.
- **Action.** Drop the Redis connection at the moment the outbox relay tries to
  LPUSH.
- **Assertion.** The `tasks_outbox` row remains (not marked drained). The API
  response has already returned 201 because the commit succeeded; the client is
  not told about the enqueue delay. Restoring Redis and running the relay again
  drains the row on the next cycle. The relay's drain is idempotent against
  duplicate LPUSH (the queue client checks or the handler's idempotency key
  covers duplicate delivery).

### Worker crash mid-Step

- **Setup.** Start a WorkflowRun. Claim the first Task. Begin the Step handler.
  The handler opens a transaction, writes the StepAttempt row as `in_progress`,
  and is about to write the extraction result.
- **Action.** Kill the worker subprocess with SIGKILL before the transaction
  commits.
- **Assertion.** The transaction was never committed, so no StepAttempt row
  exists. The Task remains in the worker's inflight list. Advancing the clock
  past the visibility timeout and running the reaper returns the Task to ready
  with `attempt_number` incremented. A replacement worker claims, processes, and
  ACKs. The final `step_attempts` row count equals the number of attempts up to
  and including the successful one; no partial state lingers. Idempotency keyed
  on `(workflow_run_id, step_name, attempt_number)` ensures that if the crashed
  handler had somehow committed partially (via a different mechanism, which the
  design excludes) the retry would not create duplicate side effects.

### Extractor timeout

- **Setup.** Configure the Step with `extractor_timeout_seconds = 5`. Point the
  Step at an extractor that sleeps for 30 seconds.
- **Action.** Drive the Task. The clock advances past 5 seconds via the test
  clock and the extractor supervisor fires.
- **Assertion.** The StepAttempt transitions to `failed_retryable` with
  `error_code = "extractor_timeout"`. A new StepAttempt is scheduled per the
  backoff rules. An AuditEvent with `event_type = "step_attempt_failed"` and the
  timeout error code is written.

### Validator deterministic failure

- **Setup.** Configure a validator to return `fail_correctable` with a list of
  typed reasons.
- **Action.** Drive the Task.
- **Assertion.** The StepAttempt transitions to `succeeded` (the validator ran to
  completion) but the Step transitions to a terminal outcome that opens an
  EscalationCase. The WorkflowRun state becomes `awaiting_human`. An AuditEvent
  with `event_type = "escalation_opened"` and the validator's reasons in the
  payload is written.
- **Further case.** A validator that returns `fail_terminal` transitions the
  WorkflowRun to `failed`. An AuditEvent with `event_type = "workflow_run_failed"`
  is written and no EscalationCase is created.

### Expired EscalationCase

- **Setup.** Open an EscalationCase with `ttl_seconds = 300`. Do not claim or
  resolve.
- **Action.** Advance the test clock past the TTL. Run the EscalationCase
  reaper.
- **Assertion.** The case transitions to `expired`. An AuditEvent with
  `event_type = "escalation_expired"` is written. The WorkflowRun transitions to
  `failed` (or, if `retry_on_expiration` is set, a new StepAttempt is scheduled
  for the escalated Step).

### Poison-pill Task

- **Setup.** Configure a Step with `max_attempts = 3`. Point the Task at a
  handler that always raises.
- **Action.** Drive the Task through all three attempts, advancing the clock past
  each backoff.
- **Assertion.** After the third failure, the Task moves to `queue:tasks:dlq`.
  An AuditEvent with `event_type = "task_dlq_moved"` is written. The Step
  transitions to `failed_terminal`. The WorkflowRun transitions per policy
  (`failed` or `awaiting_human`).

## Local test runtime

The default local command is `pytest -q`. It runs `tests/unit/`,
`tests/integration/`, and `tests/workflow/` in that order. Total runtime is under
three minutes on a developer laptop with the `compose.test.yml` stack warm
(Postgres container already running, Redis container already running). The first
run after a cold boot is slower by the container-start cost (typically 5 to 10
seconds) and the pytest collection cost.

The failure tier and the audit tier are gated behind pytest markers (`-m slow`
and `-m audit`). A developer who touches the audit writer runs
`pytest -q -m "audit or unit or integration or workflow"` to include the audit
tier. A developer who touches the queue reaper or the retry scheduler runs
`pytest -q -m "slow or unit or integration or workflow"` to include the failure
tier. CI runs the full matrix on every build.

The `compose.test.yml` stack is brought up by a Makefile-level target
(`make test-stack-up`) that the pytest session hook invokes if the stack is not
already running. The same hook tears the stack down on `make test-stack-down`;
local developers typically leave the stack up across runs for speed. Ephemeral
volumes in `compose.test.yml` ensure no state persists across stack restarts.

## CI integration

CI runs in a single GitHub Actions workflow, `.github/workflows/ci.yml`, authored
in Phase 1 and described in [DEPLOYMENT_STRATEGY.md](./DEPLOYMENT_STRATEGY.md).
The contract the test suite imposes on CI is:

- **Single job for the full test run.** Lint, type check, test tiers, and
  container build are steps in one job. Split jobs are reconsidered only if the
  single-job runtime exceeds 15 minutes.
- **Service containers via `compose.test.yml`.** CI brings up the same stack
  local developers use. Pinned image digests for Postgres and Redis ensure
  version drift does not silently reshape test behavior.
- **Pinned runner image.** The GitHub Actions runner is pinned to a specific
  Ubuntu version, not `ubuntu-latest`. This keeps CI reproducible across months.
- **Pinned action SHAs.** Every action reference uses a git SHA, not a floating
  tag. The `actions/checkout@v4` shorthand is not accepted; only
  `actions/checkout@<sha>` is.
- **Cached dependency install.** `pip` or `uv` cache is keyed on the lockfile
  SHA. The cache is not keyed on the date or on the runner id. A lockfile change
  invalidates the cache exactly once.
- **No network inside tests.** The same socket guard fixture that fires locally
  fires in CI. CI's network is not relied on beyond the initial dependency
  install step (itself against the project's allowlist per the deployment
  document).
- **Wall-clock-independent tests.** Tests that are correct on a developer laptop
  at noon UTC are correct on a CI runner at midnight UTC. The injected clock
  guarantees this; CI is not a different environment for test logic.
- **No `@pytest.mark.flaky` decorator in the tree.** A flaky test is either fixed
  or deleted. Marking a test as flaky and accepting the noise is not a supported
  workflow. A grep for `@pytest.mark.flaky` in CI fails the build.
- **Test output is machine-readable.** `pytest --junit-xml=...` emits the run
  log for aggregation. `pytest-json-report` is added in Phase 2 if a dashboard
  wants structured output.
- **No skipped tests without explicit justification.** A `@pytest.mark.skip` or
  `pytest.skip(...)` call requires a comment with an issue link; a grep in CI
  surfaces any skip without a matching pattern.

CI runs on every PR and on every push to `main`. The release pipeline (described
in the deployment document) inherits from this job; it does not re-run tests but
trusts the upstream job's result.

## Coverage

Coverage is a signal, not gospel. The suite's strongest correctness evidence
comes from the workflow replay and audit consistency tiers, not from line
coverage percentages. A line marked covered because a test imported the module
is not meaningfully tested.

That said, coverage is measured and enforced.

- **Line coverage floor.** 85 percent on the production code under `src/` in
  Phase 1. Modules explicitly excluded (see below) are removed from the
  denominator. Coverage is computed by `coverage.py` via `pytest-cov`.
- **Branch coverage for the orchestrator core.** Modules that own state
  transitions (`src/app/orchestrator/`, `src/app/queue/`, `src/app/audit/`) are
  measured with branch coverage. The floor for branch coverage on these modules
  is 90 percent.
- **Explicit exclusions.** Test-only code (`tests/`), generated code (none at
  Phase 1), vendored code (none at Phase 1), and `if TYPE_CHECKING` blocks are
  excluded. The exclusion list is in `pyproject.toml` and is reviewed in PR
  when it changes.
- **Coverage drop gate.** A PR that drops line coverage by more than 2 percent
  on the baseline, or drops any module's branch coverage below the floor,
  requires a reviewer sign-off citing a specific reason. The gate is a soft
  block, not a hard failure, because mechanical coverage gates produce gaming
  behaviors (tests that touch lines without asserting behavior). The hard
  failures are the correctness tiers.

Coverage is reported in the PR summary by CI. It is not reported in a dashboard
that nobody reads. An aggregated dashboard is a Phase 3 deliverable.

## Assumptions

- The Phase 1 test runner is `pytest` with the plugins enumerated in
  [SYSTEM_ARCHITECTURE.md section 23.1](./SYSTEM_ARCHITECTURE.md)
  (`pytest-asyncio`, `pytest-postgresql`, `pytest-randomly`, `pytest-xdist`,
  `pytest-cov`). No other test framework is mixed in.
- The `compose.test.yml` stack is available both locally and in CI with the same
  pinned service versions. A difference between local and CI versions is a bug,
  not a feature.
- The developer laptop has Docker (or a Docker-compatible runtime) available.
  Running the suite without a container runtime is not supported; the platform
  is built around real Postgres and real Redis in integration tests, not around
  Python-level fakes.
- Network access to package registries is available at CI install time (per the
  deployment document's allowlist). The test execution itself is offline; the
  install step is not.
- Clock skew on the developer laptop and the CI runner is bounded by typical
  NTP accuracy. The test suite does not depend on absolute wall-clock values,
  only on elapsed intervals read through the injected `Clock`.
- Hash collisions in sha256 do not occur in the test fixtures. The audit chain
  assertions are byte-equality assertions, so a collision would produce a false
  positive; the probability is negligible at this scale and is not mitigated.
- The deterministic stub extractor and the rule-based validator stay
  deterministic across Phase 1 and Phase 2. Phase 3 introduces a model-backed
  extractor; at that point the workflow replay tests gain a test-only variant
  that holds the stub extractor and the production variant that exercises the
  real extractor behind an explicit marker. The replay invariant still holds
  for the stub path.

## Tradeoffs

The testing posture is a set of tradeoffs, made deliberately. The options
considered and the reasons for the chosen path follow.

### Real Postgres and Redis in the integration tier, not mocks or in-memory fakes

The platform's correctness depends on SQL behavior (transaction isolation,
foreign key constraints, unique indexes on idempotency keys, UPDATE grants on
`audit_events`) and on Redis behavior (BRPOPLPUSH atomicity, sorted-set score
semantics, LREM counting). A mock of these subsystems returns what the mock
author assumed they return, not what they actually return. The cost of running
a real service in tests is:

- An image pull at CI setup (amortized over every test in the run).
- A container start at stack-up (amortized over every test in the run; typically
  5 to 10 seconds).
- Per-test setup for transaction or key-prefix isolation (single-digit
  milliseconds).

The benefit is that bugs in the driver, the SQL, the Redis command choice, and
the concurrency semantics are caught by tests instead of by production. For a
platform whose correctness story is "deterministic execution with tamper-visible
audit", running the actual database and the actual queue is the cheapest way to
make that story believable. In-memory fakes would either be incomplete (missing
some SQL or Redis behavior) or as complex as the real thing (and still not the
real thing).

This tradeoff was the easy call.

### Deterministic stub extractor and rule-based validator, not recorded real-model responses

A recorded-response approach (where a real model is called once, the response is
frozen to a file, and tests replay against the file) is appealing because it
exercises the real interface shape. It is rejected at Phase 1 because the
determinism properties are the platform's main correctness claim: if the stub
extractor itself is non-deterministic, the whole workflow replay story falls
apart. Recorded responses also couple the suite to a specific model version; a
model change requires regenerating every recording. At Phase 3, when a real
model-backed extractor ships, contract tests (a small number, not the full
workflow suite) exercise the real model at a known revision, and the workflow
replay tier continues to use the stub.

### Transaction-per-test isolation, not per-test database creation

Creating a fresh database per test (via `pytest-postgresql` in "createdb" mode)
gives full isolation at the cost of a few hundred milliseconds per test. For a
suite of several hundred integration tests, that is a minute or two of setup
cost that the transaction-per-test pattern avoids. The transaction-per-test
pattern loses a small amount of realism (tests cannot observe cross-transaction
effects the same way production does) and compensates with the explicit
"commit fixture" for the few tests that need cross-connection visibility.

### Golden files for audit chain only, not for every test

Golden-file testing ("run the code, diff the output against a committed file")
is easy to write and hard to maintain. Every unrelated change that touches
serialization produces a golden-file diff, and reviewers get tempted to regenerate
files without reading them. The platform scopes golden files to the one place
they are worth the cost: the audit chain, where the serialized bytes are the
product. Everywhere else, typed equality on domain objects is more precise and
more informative.

### Five tiers, not three or seven

Three tiers (unit, integration, end-to-end) undercover the retry, queue, and
audit concerns that define the platform. Seven tiers (adding separate queue,
retry, and DLQ tiers) fragment the suite and make the navigation harder than
the insight is worth. Five tiers is the point where every concern has a home
and nothing is duplicated.

### pytest plugins pinned in the lockfile, not installed from HEAD

Every pytest plugin (pytest-asyncio, pytest-postgresql, pytest-randomly,
pytest-xdist, pytest-cov) is pinned. Plugin updates have caused test-suite
behavior changes in the past (pytest-asyncio's loop-scope shifts, for example).
Pinning avoids silent cross-version breakage; plugin upgrades are explicit PRs
reviewed for behavior changes.

### One CI job, not a matrix across Python versions

Phase 1 targets Python 3.12 exclusively. A matrix across 3.11 and 3.12 doubles
CI runtime and does not catch a bug this platform will ever ship, because the
deployed image is 3.12. The matrix is added only if a supported runtime version
range ever emerges (not in Phase 1, not in Phase 2).

### No `@pytest.mark.flaky`, no retry-on-failure

Accepting flakiness is accepting a reliability debt that compounds. The suite
is either deterministic or broken. A failing test is fixed or deleted; the
ceremony of marking it flaky and moving on is explicitly rejected. The cost is
the occasional hour spent hunting a real race condition; the benefit is a suite
whose green signal means something.
