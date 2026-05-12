# TECHNICAL_DEBT_PREVENTION.md

## Purpose

This document is the authoritative statement of how InsuranceOps AI avoids
predictable technical debt as it moves from Phase 0 design into Phase 1
delivery and beyond. It names the debt we refuse to incur, the debt we
knowingly accept with an exit criterion, and the mechanical guardrails that
keep either category from drifting.

Technical debt is not prevented by intention. It is prevented by controls
that a reviewer does not have to remember: a linter rule, a schema
constraint, a PR template field, a test that fails when the rule is broken,
a periodic review with a named owner. This document enumerates those
controls and names the role responsible for each one.

The document is descriptive where Phase 1 enforces the control today and
prescriptive where a future phase adds or hardens one. Where a control is
deferred, the phase and the reason are named. The list of knowingly
accepted debt carries an exit criterion that triggers repayment; without
such a criterion, accepted debt decays into unaccepted debt.

## Scope

In scope:

- Debt categories the platform refuses at the door rather than triaging
  later.
- Debt the platform knowingly accepts at Phase 1 and commits to repaying
  by a named phase.
- Code-level guardrails enforced by the toolchain (linters, type checkers,
  test discipline).
- Architectural guardrails enforced by import-linter rules, package
  structure, and review.
- Schema and migration guardrails enforced by Alembic review and Phase 2
  linter checks.
- Documentation, dependency, and review-discipline guardrails that keep
  the rest of the system believable.
- The anti-goals that name what this project refuses to become, so that
  future scope pressure has a document to push against.

Out of scope:

- Product-level debt (for example, the absence of a feature a user wants).
  That is owned by [PRODUCT_REQUIREMENTS.md](./PRODUCT_REQUIREMENTS.md)
  and the phased roadmap.
- Organizational debt (for example, understaffing). This document names
  the small-team reality in the review-discipline section but does not
  prescribe hiring.
- Compliance debt, which is owned by [SECURITY_REVIEW.md](./SECURITY_REVIEW.md)
  and [RISK_ANALYSIS.md](./RISK_ANALYSIS.md) under the compliance section.

## Definition of technical debt in this project

Technical debt is anything that raises the cost of future correct changes.
For InsuranceOps AI this document recognizes five concrete sources and
treats every one of them as a first-class cost:

1. Code that resists testing. A function whose correctness depends on
   wall-clock time, ambient global state, or network side effects is
   harder to test than one that takes its dependencies as arguments. The
   second is the default style in this codebase; the first is debt.
2. Undocumented tacit knowledge. A design choice that lives only in a
   single engineer's head is debt even if the code is correct. The
   Phase 0 documentation set exists because this form of debt is the
   one most commonly mistaken for clarity.
3. Abstractions that do not pull weight. A base class with one subclass,
   a plugin system with one plugin, a configuration knob with one setting
   are all speculative abstraction. They raise the cost of future changes
   because every change has to respect the abstraction boundary even
   though the abstraction does nothing.
4. Dependencies we cannot update. A pinned dependency without a tested
   upgrade path is debt; a deprecated API surface in a pinned dependency
   is debt that will collect interest; a transitive dependency we do not
   audit is debt whose size we do not know.
5. Runtime surprises operators cannot debug from logs alone. A production
   incident whose root cause is not visible in the structured log or the
   metric surface is debt in OBSERVABILITY_STRATEGY.md's shape: the next
   incident of the same type will also be unattributable.

Debt is not the same as incomplete scope. A Phase 2 feature is not Phase 1
debt. Debt is the shape of what Phase 1 ships, not what it defers.

## Debt sources we expect and reject upfront

The patterns below are known to generate debt disproportionate to the
value they provide at this stage. They are rejected at the PR boundary,
not triaged later. The preferred alternative is named for each.

### Speculative abstraction layers

Forbidden at Phase 1:

- A plugin system for workflows, extractors, or validators. Workflows are
  Python code under `workflows/`, extractors are classes behind a narrow
  interface instantiated explicitly, validators are functions composed in
  code. No dynamic loader that discovers classes by filesystem scan, no
  entry-point registration, no environment-driven plugin paths.
- A generic rule engine that executes user-authored rules at runtime.
  Validation rules are Python functions named in code; if a Phase 3 need
  for authored rules emerges, that is a scoped feature, not an
  architectural layer.
- A dynamic workflow-definition loader that constructs a workflow from a
  database row or a YAML file. Workflows are code and their version is a
  string constant.
- A generic `BaseService` or `BaseRepository` that exists only because
  "services usually have a base class". Repositories are concrete modules
  under `storage/`; services are concrete modules under their feature
  package.

Reason: speculative abstraction raises the cost of every future change
because every change must respect a boundary that exists for no concrete
caller.

Preferred alternative: concrete code, one call site per feature, and a
documented rule that the second call site is when an abstraction is
introduced, not the first.

### Ambient framework magic

Forbidden at Phase 1:

- Celery task auto-discovery. The platform does not use Celery.
- SQLAlchemy automap or reflection-based model generation. Models are
  declared explicitly in `storage/models.py`.
- Flask-Admin, flask-appbuilder, or any framework that generates admin
  views by reading the database. Admin actions are explicit endpoints.
- Decorator-registered event handlers that are only discovered at import
  time. Any registration is explicit, in a `register_handlers()` function
  called at app start, and enumerable by reading one module.
- Monkey-patching of third-party modules at app start. If a dependency's
  behavior has to be changed, the change is an adapter module around it,
  not a patch into it.

Reason: ambient magic defeats `grep`. A reviewer cannot confirm a
behavior exists by searching for it; they have to know the framework's
conventions. That is tacit knowledge, which this document treats as
debt.

Preferred alternative: explicit wiring at app start time in a module
named `wiring.py` or `composition.py` for each process type (api, worker)
whose content is readable top to bottom.

### Premature async everywhere

Forbidden at Phase 1:

- CPU-bound work in an `async def` handler. CPU-bound work runs in a
  worker process with explicit synchronous code.
- Mixing sync and async database drivers in the same module. The API
  process uses the async driver; the worker process uses the sync driver;
  the shared code does not reach across.
- `asyncio.create_task` for fire-and-forget work that has no named owner.
  Every background task has a module that owns its lifecycle and its
  cancellation.

Reason: asyncio is a tool for IO concurrency, not a general-purpose
improvement. Using it for CPU work hides pathological behavior; using it
for fire-and-forget hides unhandled exceptions.

Preferred alternative: the execution model is explicit per process.
SYSTEM_ARCHITECTURE.md section 20 owns the concurrency and async
reasoning for the platform; any deviation from it is an ADR.

### Silent error handling

Forbidden at Phase 1:

- `except Exception: pass`.
- `except Exception as e: logger.error(e)` followed by continued execution
  as if nothing happened.
- Catching a specific exception and returning `None` without a typed
  sentinel or a documented reason.

Reason: silent error handling is the most common source of runtime
surprises an operator cannot debug from logs alone. The incident appears
as "it just stopped working"; the code has already swallowed the signal.

Preferred alternative: every caught exception either (a) is converted
to a typed domain error defined in the feature's `errors` module and
re-raised, or (b) is the terminal handler of a retry-aware worker loop
and produces a `StepAttempt` with the error reason recorded. The worker
loop's terminal handler is the only place where a blanket `except` is
allowed, and it is reviewed on every change.

### Copy-pasted test fixtures

Forbidden at Phase 1:

- Two tests that construct the same domain object by copying ten lines
  of setup. A factory function replaces both.
- A fixture that mutates a shared object between tests. Fixtures produce
  fresh objects per test.
- A test that depends on an environment variable set by another test.
  Environment is part of the fixture or it is not there.

Reason: copy-pasted fixtures are the most common way a test suite rots.
A schema change touches ten test files instead of one factory, and the
suite becomes expensive to maintain.

Preferred alternative: a `tests/factories/` module with one factory per
domain entity, each taking keyword arguments for the fields the caller
wants to override, all other fields filled with sensible defaults that
match the schema constraints. TESTING_STRATEGY.md names this as a
first-class rule.

### Undocumented magic constants in workflow code

Forbidden at Phase 1:

- A literal `3` for retry count, `60` for timeout seconds, or `"v1"` for
  workflow version appearing inline in a Step handler.
- A config value read from an environment variable without a named
  configuration object.
- A policy such as "retry at 2 seconds, then 4, then 8" encoded in a
  loop body.

Reason: every one of these is a policy, and policies live in named
configuration. A reviewer changing a retry policy should change one
line in `config/retries.py`, not hunt for literals.

Preferred alternative: retry policies, timeouts, and workflow versions
live in a `config/` package and are imported by name. The configuration
object is a Pydantic model so the types and defaults are readable in one
place.

## Debt we knowingly accept at Phase 1 (with exit criteria)

Accepted debt is not a failure of discipline; it is the honest shape of
a phased delivery. Every row below has an exit criterion that triggers
repayment. The interim posture is what holds until the exit criterion
fires.

| Accepted debt | Why accepted at Phase 1 | Exit criterion | Target phase for repayment |
| --- | --- | --- | --- |
| Single-host Compose deployment | The Phase 1 traffic envelope fits one host, and cross-host coordination is itself a risk until operated | Sustained CPU above the documented host budget, sustained memory above 80 percent, or a named business requirement for cross-host redundancy | Phase 2 |
| API-key-only authentication for machine clients | OIDC and SSO integration require a directory service decision that is out of scope for Phase 1 | When operator identity federation becomes a requirement or when the operator UI is built at Phase 3 | Phase 3 |
| Session-cookie auth stub for any Phase 1 admin endpoint | The Phase 1 operator UI does not exist yet; any admin endpoint uses the same API-key mechanism | When the Phase 3 operator UI ships | Phase 3 |
| Stubbed deterministic extractor | A real model-backed extractor at Phase 1 would delay the platform in order to validate model integration first; the stub is substitutable | When the Phase 1 pipeline is demonstrably solid end to end and a production use case needs model output | Phase 3 |
| Single-tenant assumptions in data model | Multi-tenant isolation is a Phase 4 concern and adding it to Phase 1 schemas is premature | When a second tenant is a named business requirement | Phase 4 |
| Unpartitioned `audit_events` table | At Phase 1 volumes a single table is adequate and partitioning adds migration complexity before it is needed | When `audit_events` row count passes the documented threshold in SYSTEM_ARCHITECTURE.md section 21 | Phase 2 |
| Manual secret rotation | The number of secrets is small and rotation cadence is annual absent an incident | When the admin rotation endpoint is specified and built | Phase 2 |
| No dashboards-as-code | The Phase 1 Prometheus metric surface is small enough to read from a default Grafana install or command-line query | When a Phase 2 dashboard set is agreed and versioned | Phase 2 |
| No scheduled audit-chain verifier | Phase 1 verifies the chain on demand as part of quarterly security review | When a Phase 2 scheduled job is specified | Phase 2 |
| No load-test harness | Phase 1 traffic envelope does not require one; performance budgets are derived from single-host capacity | Phase 2 adds a load-test harness as part of operational hardening | Phase 2 |
| No backup-restore drill cadence | A one-off pre-go-live drill is the Phase 1 baseline | Phase 2 establishes a quarterly drill | Phase 2 |

Repayment of an accepted-debt row means: the exit criterion fires, a PR
implements the repayment, the row is removed from this table, and the
repayment is recorded in the commit history of this document.

## Code-level guardrails

These controls are enforced by the toolchain. A PR that violates them is
rejected by CI, not by a reviewer reading the diff. Phase 1 sets up each
control; Phase 2 tightens the thresholds where documented below.

- ruff is the single Python linter. The enabled rule categories are
  E (pycodestyle errors), W (pycodestyle warnings), F (pyflakes), I
  (isort), B (bugbear), C4 (comprehensions), SIM (simplifications), UP
  (pyupgrade), RUF (ruff-specific), S (bandit-lite security), ASYNC
  (async antipatterns). Specific rules disabled at Phase 1 carry a
  one-line comment in `pyproject.toml` explaining why. Disabling a
  category wholesale requires an ADR.
- mypy runs in strict mode against the core orchestrator package
  (`domain/`, `application/`, `storage/`, `queue/`, `workers/`). The API
  layer uses strict with one documented concession for request-model
  boundaries where Pydantic produces types mypy cannot narrow.
- An import-linter configuration enforces the layering described in the
  architectural-guardrails section. A layer violation fails CI.
- Cyclomatic complexity is capped per function. The Phase 1 threshold is
  the ruff default; Phase 2 can tighten it if incidents point at
  complexity as a contributing factor.
- Files over 500 lines trigger an advisory check and a reviewer note; a
  PR that adds such a file includes a one-sentence justification in the
  PR body. This is a soft control, not a CI failure.
- Public module boundaries (anything importable from another package)
  require a module-level docstring summarizing the contract. A script
  in CI enforces that every public module has a docstring.
- pytest is configured with `--strict-markers` and `--strict-config`.
  An unknown marker fails the suite; an unknown config option fails the
  suite.
- Deprecation warnings in tests are errors. A new deprecation warning
  from a pinned dependency fails the build and forces a decision:
  upgrade the dependency, suppress the warning with a dated reason, or
  refactor the call site.
- Coverage reports are produced for the unit and integration tiers but
  coverage percentage is advisory at Phase 1. A reviewer blocks a PR on
  missed coverage of a retry path, a failure path, or an audit path;
  they do not block on a line-coverage number.
- Typing and lint jobs run in parallel in CI so the feedback loop stays
  short. The order is deterministic so the failing job is the same on
  every run.

## Architectural guardrails

The Phase 1 architecture has four layers: `api`, `application`, `domain`,
`infrastructure`. The layering rule is: `api` depends on `application`,
`application` depends on `domain`, and `infrastructure` depends on
`domain` from the outside. `domain` has no dependencies on any other
layer.

- The `domain` package cannot import from `api`, `workers`, `storage`,
  or `queue`. Enforced by import-linter.
- The `application` package cannot import from `api` or `workers`.
  Enforced by import-linter.
- No database access outside the `storage/` package. SQLAlchemy sessions,
  models, and queries live only under `storage/`. Enforced by an
  import-linter rule against importing `sqlalchemy` from outside
  `storage/` and a ruff check against `from storage.models import` at
  the `api` or `domain` boundary. The `application` layer receives
  repository-shaped dependencies.
- No Redis access outside `queue/` and an explicit `cache/` module if
  one is added at Phase 2. The worker imports the queue module; the
  domain does not.
- HTTP framework types (`fastapi.Request`, `fastapi.Response`,
  `starlette.*`) do not appear in `application/` or `domain/`. The
  `api/` layer adapts them at the boundary.
- The `workers/` package is the only caller of the queue's blocking
  pop; no other package is allowed to pop from the queue, so a rogue
  script cannot drain work out of band.
- Cross-layer dependency injection is explicit. A module that needs a
  repository receives it as a parameter; no service-locator pattern, no
  global registry of constructed services.
- Public contracts between layers are named dataclasses or Pydantic
  models in a `contracts/` submodule of the consuming layer, not types
  reused from the producing layer. This keeps a storage-model change
  from rippling into the domain without an explicit boundary touch.

## Schema and migration guardrails

Migrations change production data. They are reviewed like code and carry
additional discipline.

- Every migration is a reviewed PR. `alembic revision --autogenerate` is
  a starting point; a reviewer inspects the generated migration for
  correctness before it is committed.
- Destructive changes (drop column, drop table, rename column, change
  column type in a way that is not implicit) go through
  expand-migrate-contract: a migration that adds the new shape alongside
  the old, an application deploy that reads both and writes the new, a
  backfill migration, a deploy that reads only the new, and finally a
  migration that removes the old shape. Each step is a separate PR.
- Every column addition carries an explicit `nullable=True` with
  rationale, or a server-side default. A `nullable=False` addition
  without a default is rejected because it locks the table on backfill.
- Migration naming follows `YYYYMMDD_HHMM_slug.py` so ordering is
  explicit and the review reads the filename before the diff.
- Phase 2 adds a migration-linter check that asserts naming, ordering,
  and the absence of patterns known to cause long locks (index creation
  without `CONCURRENTLY`, data migration inside the same file as DDL,
  etc.).
- The application DB role used by API and worker does not have DDL
  privileges. Migrations run under a separate migration role; this role
  is used only by the migration job and is enumerated in
  SECURITY_REVIEW.md.
- A migration that would take a long lock on a table is flagged by the
  author in the PR body with the row count and the expected lock
  duration; the reviewer approves the window and the rollout plan.

## Documentation guardrails

A change that crosses a boundary is not complete until the boundary is
documented.

- A PR that adds or changes a public API endpoint updates
  SYSTEM_ARCHITECTURE.md section 17 in the same PR. The reviewer
  enforces this.
- A PR that changes a domain-entity field updates the relevant section
  of SYSTEM_ARCHITECTURE.md section 5 in the same PR.
- A PR that changes a configuration knob updates DEPLOYMENT_STRATEGY.md
  and, if the knob has operational impact, OBSERVABILITY_STRATEGY.md.
- From Phase 2 onward, architectural decisions live in a `decisions/`
  folder as Architecture Decision Records (ADRs). An ADR is required
  for any deviation from a guardrail in this document. The ADR names
  the exception, the reason, the review date, and the owner-role that
  will revisit it. ADR filenames are `NNNN-short-slug.md`.
- A Phase 0 document is amended by PR. Every amendment PR updates the
  Assumptions section and records the reason for the change. The
  document history is believable: no silent rewrites, no squash of
  amendment history.
- Every code module that has a non-obvious contract carries a module
  docstring. The contract describes inputs, outputs, error types, and
  whether the module is safe to call from a worker, an API handler, or
  both.

## Dependency guardrails

Pinned dependencies without a tested upgrade path are a known form of
debt. These controls prevent the upgrade path from drifting.

- Dependencies are pinned via a lockfile. The Phase 1 toolchain choice
  (pip-tools or uv) is recorded in DEPLOYMENT_STRATEGY.md. The lockfile
  is committed.
- A new top-level dependency requires a dependency-justification entry
  in SYSTEM_ARCHITECTURE.md section 23. The entry names: what the
  dependency provides, what the alternative would be, why we accept the
  cost of the dependency, and the reviewer who approved.
- Transitive dependencies are audited once per release cadence. Any
  transitive with a known CVE at high or critical severity forces a
  decision.
- Deprecation warnings from dependencies are errors in the test suite.
  A deprecated API in a pinned dependency surfaces in CI, not in
  production.
- From Phase 2, Dependabot or Renovate raises PRs on a documented
  cadence. A dependency-upgrade PR runs the full test matrix and is
  reviewed on the same day it is raised or the PR is explicitly
  deferred with a reason.
- The base image for the Docker build is pinned to a specific digest,
  not a floating tag. Base-image upgrades are PRs.
- An import of a deprecated module from the standard library (one
  marked deprecated in the current Python version the project targets)
  fails the build through the deprecation-warnings-as-errors rule.

## Review discipline

A review that is mechanical is a review that scales. These controls
make the review mechanical without making it shallow.

- PR template fields (required):
  - What changed: one paragraph.
  - Why: one paragraph referencing a PRD line, an ADR, or a phase
    commitment.
  - Which doc section was updated: a filename and section number.
  - Which test covers it: a file path and a test name.
  - Migration note: expand-migrate-contract phase if a migration is
    included.
  - Rollout note: anything non-obvious about deploy order.
- At least one reviewer approves before merge. CI required checks must
  pass. A reviewer not approving their own PR is the default; the
  exception is a small-team reality in which the author is also the
  only available reviewer, in which case the PR body names the absent
  reviewer and the author merges after a 24-hour cooling-off window,
  during which another team member may still object. This exception is
  named explicitly so it does not become silent custom.
- A reviewer is empowered to block on any guardrail in this document.
  "It passes CI" is necessary but not sufficient.
- A reviewer records blocking comments as change-requests, not as
  suggestions. A reviewer who approves but leaves a change-request
  comment has approved by mistake.
- Self-merge without review is not allowed except in the documented
  small-team case above. A self-merge PR in the commit log without a
  named reviewer in the body is an incident for the tech lead to
  investigate.

## Debt visibility

Accepted debt and known exceptions to guardrails are visible in two
places: the accepted-debt table above, and a Phase 2 artifact
`docs/debt-ledger.md` that is referenced here but not created at
Phase 0.

- The debt ledger records every accepted-debt row from this document
  with: the date accepted, the exit criterion, the owner-role, and the
  last review date.
- The debt ledger is reviewed quarterly. A row whose last review date
  is older than one quarter is escalated to the tech lead.
- A row whose exit criterion has fired but which has not been repaid
  within two quarters is escalated to the operations supervisor and
  tagged in [RISK_ANALYSIS.md](./RISK_ANALYSIS.md) as a delivery risk
  to the next phase.
- Exceptions to guardrails (a mypy ignore with a date, a ruff disable
  with a reason) are enumerated by a CI job at Phase 2 so the count is
  visible. A growing exception count is itself a signal.
- Exception entries in code carry the same shape: `# noqa: <rule>`
  without an owner and date is a review rejection; `# noqa: <rule>  #
  reason; review YYYY-MM-DD; owner ROLE` is the accepted form.

## Anti-goals

The project refuses to become certain things. Each anti-goal below has
a one-line reason so that a future scope pressure has something to push
against.

- A framework-producer. This project does not ship a framework for
  other teams. It ships an internal platform with a stable API and the
  discipline to keep that API small.
- A generic rule engine. Rules are Python functions composed in code.
  Authored rules at runtime would require a rule-authoring interface,
  a rule-validation story, and a replay story, none of which are on
  any phase.
- A chatbot. The product is workflow orchestration. A conversational
  surface would be a different product built on top of this one.
- A low-code workflow editor. Workflows are code and their correctness
  is established by code review and tests. A graphical editor would
  make workflow changes look cheap while raising their review cost.
- A plugin marketplace. Extensibility at Phase 3 means a new extractor
  class wired at build time by a named engineer, not a marketplace of
  anonymous contributors.
- A one-size-fits-all orchestration platform. The design is tight to
  insurance back-office operations (document intake, extraction,
  validation, routing, escalation). Expanding the shape to fit
  arbitrary domains would force generalizations this document refuses.

## Assumptions

- Every guardrail above has either a CI job, a schema constraint, a PR
  template field, or a review cadence associated with it. Guardrails
  that exist only as intent in this document are not considered
  enforced until the control is in place.
- The Phase 1 toolchain choice (ruff, mypy, import-linter, pytest,
  alembic) is locked in DEPLOYMENT_STRATEGY.md and referenced here by
  name. If a Phase 2 tool replaces one of these, this document is
  amended in the same PR as the tool change.
- The accepted-debt table is read as the definitive statement of what
  this project owes itself. A piece of debt not in that table is not
  accepted; if a reviewer sees debt in a PR that is not represented
  here and not reasoned in an ADR, the reviewer rejects the PR.
- The review-discipline section acknowledges a small-team reality
  honestly. At Phase 1 the reviewer may be the tech lead for most PRs.
  This does not relax any other guardrail; the tech lead is not the
  exception to ruff, mypy, or the PR template.
- The Phase 2 artifacts referenced by this document (debt ledger,
  Dependabot or Renovate config, migration-linter check, scheduled
  audit-chain verifier) are part of the Phase 2 scope in
  [PHASED_ROADMAP.md](./PHASED_ROADMAP.md) and are not created at
  Phase 0.
- Debt visibility depends on the debt being recorded. A piece of debt
  a reviewer accepts informally is invisible to the ledger and defeats
  the control. Informal acceptance is a review failure, not a minor
  lapse.
- This document is a living artifact. It is amended when a new debt
  source is observed in a PR, when an accepted-debt row graduates, or
  when a guardrail is tightened or relaxed. The commit history of this
  file is the record.
