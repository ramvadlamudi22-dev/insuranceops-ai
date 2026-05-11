# DEPLOYMENT_STRATEGY.md

## Purpose

This document describes how InsuranceOps AI is packaged, configured, and deployed
through Phase 1 and Phase 2.
It is the authoritative source for the deployment unit, the orchestration tool,
the CI/CD pipeline, the environment-variable contract, the secrets delivery model,
the database migration discipline, the rollout and rollback procedure,
the backup posture, and the explicit decisions to NOT adopt certain platforms yet.
It references [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md) for the internal
process topology and [SECURITY_REVIEW.md](./SECURITY_REVIEW.md) for secret-handling policy.

## Scope

In scope:

- Deployment unit (Docker image) and process model (`api`, `worker`).
- Orchestration mechanism (Docker Compose) for local, CI, staging, and production.
- CI/CD pipeline (GitHub Actions) at Phase 1 and Phase 2.
- Environment-variable contract and how the application consumes configuration.
- Secrets delivery contract (platform-agnostic, concrete platform deferred to Phase 2).
- Alembic migration posture as a deploy-pipeline step.
- Backups, restore drills, and data retention at the deployment layer.
- Scaling playbook and the triggers to escalate past a single host.
- The explicit non-deploy targets and the reasoning.

Out of scope:

- The internal software architecture of the platform, which is owned by
  [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md).
- Threat enumeration at the network layer (see [SECURITY_REVIEW.md](./SECURITY_REVIEW.md)).
- Observability dashboards and runbooks (see [OBSERVABILITY_STRATEGY.md](./OBSERVABILITY_STRATEGY.md)).
- Test tier definitions (see [TESTING_STRATEGY.md](./TESTING_STRATEGY.md)).
- Phase 3 operator UI deploy topology. Revisited when the UI lands.
- Phase 4+ multi-region topology. Deferred.

## Target environments

The platform defines four named environments.
Each is a deployment posture, not a software release.
The same Docker image flows through all four; only configuration differs.

| Environment | Orchestrator             | DB size                          | Worker count | Secret source                              | Log destination                                    | `/metrics` exposure                     | Persistence |
|-------------|--------------------------|----------------------------------|--------------|--------------------------------------------|----------------------------------------------------|-----------------------------------------|-------------|
| local       | Docker Compose           | Single container, 2 GB shared_buffers | 1 or 2   | `.env` file (git-ignored) sourced at startup | stdout to terminal, pretty-printed via structlog | Exposed on the host port, no auth       | Bind mount on developer laptop |
| ci          | Docker Compose (compose.test.yml) | Single service container, small | 1 or 2 | Static test fixtures via env vars            | stdout captured by GitHub Actions                  | Exposed inside the CI job, not published | Ephemeral volume, discarded after job |
| staging     | Docker Compose on a dedicated staging host | Dedicated instance, production-like tuning | 2 to 4 | Runtime env vars from deployment platform's secret store | JSON lines to stdout, scraped by platform log agent | Exposed on cluster-internal network only | Managed persistent volume with daily snapshot |
| production  | Docker Compose on the production host(s), or managed container platform (Phase 2 decision) | Dedicated instance, full tuning | 4 to 16 | Runtime env vars from platform secret store | JSON lines to stdout, scraped by platform log agent | Exposed on cluster-internal network only | Managed persistent volume with continuous WAL archiving |

The table above is intentionally compact.
Each column is a single axis of difference.
The key invariant is that the image, the schema, and the workflow code are identical across environments;
only the config differs.
This is what makes "deploy" a mechanical operation rather than a negotiation.

## Deployment unit

The platform ships as a single Docker image named `insuranceops-ai`.
The image is built from `docker/Dockerfile` (file created at Phase 1, not in Phase 0).

Key properties of the image:

- **Base image.** `python:3.12-slim-bookworm` pinned by digest, not by floating tag.
  The digest is recorded in `docker/Dockerfile` and is updated by an explicit commit,
  not silently on rebuild.
- **Multi-stage build.** Stage 1 installs build dependencies and compiles wheels.
  Stage 2 copies only the runtime wheels and application code.
  The final image contains no compilers, no build tools, no dev headers.
- **Process type selection.** The image's `ENTRYPOINT` is a small shell shim
  (`/app/entrypoint.sh`) that switches on the `PROCESS_TYPE` environment variable.
  Valid values:
  - `api` starts the FastAPI app via `uvicorn src.insuranceops.api.app:app`.
  - `worker` starts the worker main loop via `python -m insuranceops.workers.main`.
  - `migrate` runs `alembic upgrade head` and exits.
  - `verify-audit` runs the audit-chain verifier and exits.
  Any other value causes the container to exit with status 1 and a single log line
  naming the invalid value.
- **Port surface.** The `api` process listens on `0.0.0.0:8000`.
  The `worker` process listens on no ports (makes no inbound connections).
  Neither exposes anything else.
- **User.** The image runs as an unprivileged user `app` with UID 10001.
  `WORKDIR /app` is owned by `app`.
  No capabilities are added.
- **Labels.** The image carries labels `org.opencontainers.image.source`,
  `org.opencontainers.image.revision` (git SHA), and `org.opencontainers.image.created`
  (build timestamp).
  These power provenance queries against the image registry.
- **Size budget.** The final image targets under 250 MB.
  Exceeding this is not a failure, but any PR that grows the image by more than 20 MB
  explains the addition in the PR description.
- **No secrets.** The image contains no credentials, no keys, no tokens.
  Secrets arrive via the environment at process start
  (see the Secrets delivery section below).

A single image with a process-type switch is deliberate.
It eliminates a class of drift bugs where the `api` and `worker` images diverge.
It keeps the build matrix small.
It keeps the security review narrow: one image, one SBOM, one CVE surface.

## Orchestration

Phase 1 and Phase 2 target Docker Compose.
Compose files live under `compose/`:

- `compose/compose.yml`.
  Base file declaring the four services `api`, `worker`, `postgres`, `redis`.
  Uses the image built locally or pulled from the registry.
  Exposes `api:8000` to the host for local access.
  Declares named volumes for Postgres data and for the local payload store.
- `compose/compose.dev.yml`.
  Overlay with developer ergonomics: source bind mounts for hot reload,
  exposed Postgres and Redis ports for local inspection, `PROCESS_TYPE=api` on `api`,
  `PROCESS_TYPE=worker` on `worker`, a small `WORKER_CONCURRENCY=1`.
- `compose/compose.test.yml`.
  Overlay with ephemeral tmpfs volumes for Postgres and Redis so the test
  suite starts from a clean slate every run.
  Used by CI and by `make test-up`.

`docker compose -f compose/compose.yml -f compose/compose.dev.yml up` starts the
local development stack.
`docker compose -f compose/compose.yml -f compose/compose.test.yml up -d && pytest`
is the pattern CI uses under the hood.

The Phase 2 staging and production deployments also run Docker Compose.
The host is either a dedicated VM that the team owns
or a managed container platform that accepts Compose files
(for example, AWS Copilot, Google Cloud Run with Compose support, or a bare-metal
host using `systemd` unit files that invoke `docker compose up`).
The exact target is a Phase 2 decision; the Compose file is the source of truth
for process topology regardless.

### Explicit non-use of Kubernetes, Nomad, ECS, Fargate

Phase 1 and Phase 2 deliberately avoid:

- **Kubernetes.**
  Full reasoning in the Rejected alternatives section and in
  [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md) §24.
  Reconsidered when either condition holds for a sustained period (one quarter):
  the platform requires more than one production host to meet load,
  AND the team needs zero-downtime rolling deploys across those hosts
  that Compose-with-sequenced-restarts cannot deliver acceptably.
- **Nomad.**
  Similar to Kubernetes at a smaller operational cost, but still more machinery
  than Compose for this problem shape.
  Reconsidered only alongside Kubernetes reconsideration.
- **ECS or Fargate.**
  AWS-native options that simplify operating containers on AWS.
  Reasonable if the organization standardizes on AWS;
  revisited as part of the Phase 2 deployment-platform decision.
  Not chosen as a default at Phase 1 because it locks the architecture to AWS
  before the architecture has earned that coupling.

## CI/CD

Continuous integration lives at `.github/workflows/ci.yml` (Phase 1 artifact,
not created in Phase 0).
The workflow runs on every pull request and on every push to `main`.

Jobs:

- **lint.**
  Runs `ruff check` and `ruff format --check` against the repository.
  Fails on any finding.
- **type.**
  Runs `mypy src/` against the checked-out code with the pinned `mypy` version.
  Fails on any error.
- **test.**
  Brings up the compose.test.yml stack with pinned service versions
  (`postgres:16-alpine@sha256:...` and `redis:7-alpine@sha256:...`).
  Runs `pytest` with the full test suite as defined in
  [TESTING_STRATEGY.md](./TESTING_STRATEGY.md).
  Tests are hermetic: no outbound network beyond the service containers.
  Fails on any failing test.
- **build.**
  Runs `docker build -f docker/Dockerfile -t insuranceops-ai:ci .`
  to validate the Dockerfile still builds.
  Does NOT push.
  Image push lives in a separate workflow triggered on tags (Phase 2).

Phase 2 adds `.github/workflows/release.yml`:

- Triggered on tag push matching `v*`.
- Rebuilds the image with build args for git SHA and version tag.
- Pushes to the image registry.
- Does NOT deploy.
  Deployment is a separate operator action against the tagged image.

Determinism rules for CI:

- **Pinned runner image.**
  `runs-on: ubuntu-22.04` rather than `ubuntu-latest`.
  A runner upgrade is an explicit commit, not a surprise.
- **Pinned action SHAs.**
  `uses: actions/checkout@<sha>` rather than `@v4`.
  Dependabot or Renovate opens PRs to bump the SHA.
- **Cached dependency install.**
  The lockfile hash is the cache key.
  A lockfile change invalidates the cache;
  a code change does not.
- **No outbound network in tests.**
  The test suite's hermeticity fixture asserts no outbound sockets except to the
  compose.test.yml service containers.
  A regression trips the assertion.
- **Wall-clock independent tests.**
  Tests use a frozen clock via a `Clock` injection pattern described in
  [TESTING_STRATEGY.md](./TESTING_STRATEGY.md).
  A test that depends on real wall-clock time is a flaky test and is fixed or deleted.

Required checks on merge:

- `lint`, `type`, `test`, `build` all pass.
- At least one reviewer has approved the PR.
- Branch is up to date with `main`.

The workflow is intentionally short.
Adding a new required check is a decision reviewed against the acceptance criteria for the change,
not a reflex.

## Environment configuration

The application reads configuration exclusively from environment variables.
`src/insuranceops/config.py` declares a Pydantic v2 `Settings` model that
enumerates every variable, its type, and its default.
The application refuses to start if a required variable is missing.

The table below is the Phase 1 contract.
Columns:

- **Name.** The environment variable.
- **Required.** Whether the application fails fast if absent.
- **Default.** The default when not required, or a sample when required.
- **Description.** One line on what the variable controls.
- **Owner.** Who supplies it at runtime.
  `app reads` means the variable is consumed by the application process.
  `platform provides` means the deployment platform's secret store injects it.
  `both` means the variable is read by the app and supplied by the platform.

| Name                           | Required | Default                                  | Description                                                                  | Owner              |
|--------------------------------|----------|------------------------------------------|------------------------------------------------------------------------------|--------------------|
| `PROCESS_TYPE`                 | yes      | none (example: `api`, `worker`, `migrate`) | Selects the process the entrypoint launches.                                | platform provides  |
| `ENV`                          | yes      | none (example: `local`, `staging`, `production`) | Environment label used for logs, metrics, and feature gates.         | platform provides  |
| `SERVICE_VERSION`              | yes      | none (example: `v0.3.2` or git SHA)       | Service version string included in log lines, metrics, and traces.          | platform provides  |
| `DATABASE_URL`                 | yes      | none (example: `postgresql+asyncpg://...`) | Postgres connection string.                                                  | platform provides  |
| `DATABASE_POOL_MIN`            | no       | `2`                                       | Minimum connections kept warm per process.                                  | app reads          |
| `DATABASE_POOL_MAX`            | no       | `20`                                      | Cap on connections per process.                                             | app reads          |
| `REDIS_URL`                    | yes      | none (example: `redis://redis:6379/0`)    | Redis connection string.                                                     | platform provides  |
| `LOG_LEVEL`                    | no       | `INFO`                                    | structlog minimum level.                                                     | both               |
| `LOG_FORMAT`                   | no       | `json` in non-local, `console` in local   | structlog output format.                                                     | app reads          |
| `SECRET_KEY`                   | yes      | none (32+ bytes high-entropy)             | Signs session cookies; used when operator UI is enabled.                    | platform provides  |
| `API_KEY_HASH_PEPPER`          | yes      | none (32+ bytes high-entropy)             | Application-layer pepper mixed into API key hashes alongside argon2id.      | platform provides  |
| `MAX_REQUEST_BYTES`            | no       | `26214400` (25 MiB)                       | Hard request body cap; exceeded requests return `413`.                       | app reads          |
| `WORKER_CONCURRENCY`           | no       | `1`                                       | Number of inflight Tasks a single worker process handles in parallel.        | app reads          |
| `RETRY_MAX_ATTEMPTS_DEFAULT`   | no       | `3`                                       | Default `max_attempts` per Step when the Workflow does not override.         | app reads          |
| `RETRY_BACKOFF_BASE_S`         | no       | `2`                                       | Base delay for retry backoff.                                                | app reads          |
| `RETRY_BACKOFF_CAP_S`          | no       | `60`                                      | Cap for retry backoff.                                                       | app reads          |
| `VISIBILITY_TIMEOUT_SECONDS`   | no       | `60`                                      | Per-Task visibility timeout; reaper reclaims stuck Tasks older than this.    | app reads          |
| `REAPER_INTERVAL_SECONDS`      | no       | `15`                                      | Reaper loop cadence.                                                         | app reads          |
| `SCHEDULER_INTERVAL_SECONDS`   | no       | `1`                                       | Delayed-queue scheduler cadence.                                             | app reads          |
| `OUTBOX_RELAY_BATCH_SIZE`      | no       | `100`                                     | Outbox-relay drain batch size.                                               | app reads          |
| `OTEL_EXPORTER_OTLP_ENDPOINT`  | no       | unset                                     | When set, the OpenTelemetry bridge becomes a real span exporter.             | platform provides  |
| `OTEL_SERVICE_NAME`            | no       | `insuranceops-ai`                         | Service name attribute on spans.                                             | platform provides  |
| `HEALTH_CHECK_TIMEOUT_SECONDS` | no       | `2`                                       | Timeout for the database and Redis probes that back `/readyz`.               | app reads          |
| `PAYLOAD_STORAGE_BACKEND`      | no       | `local`                                   | Which `BlobStore` implementation to use (`local` at Phase 1, `s3` at Phase 2). | both             |
| `PAYLOAD_LOCAL_ROOT`           | no       | `/var/lib/insuranceops/payloads`          | Root directory for local payload store.                                      | app reads          |
| `ESCALATION_DEFAULT_TTL_SECONDS` | no     | `86400`                                   | Default EscalationCase TTL used when a Workflow does not override.           | app reads          |

A variable added to the table requires a PR that also adds the default
in `src/insuranceops/config.py` and a test asserting the default.
Deleting a variable requires first deprecating it (a warning log line)
for at least one release before removal.

## Secrets delivery

The platform's secret-delivery contract is deliberately abstract.
The concrete secret backend (AWS Secrets Manager, GCP Secret Manager,
HashiCorp Vault, SOPS-encrypted files on disk, Kubernetes Secrets mapped to env vars)
is a Phase 2 decision documented when chosen.
The application is agnostic to that choice:

- Secrets arrive as environment variables at process start.
- The application never reads secrets from a file inside the image.
- The application never reads secrets from a network endpoint at request time.
- The application never writes secrets into logs.
  A structlog processor described in [OBSERVABILITY_STRATEGY.md](./OBSERVABILITY_STRATEGY.md)
  strips fields that match the secret-name patterns declared in `src/insuranceops/security/redaction.py`.

Rotation:

- A secret rotation is a platform operation: the platform updates its secret store
  and restarts the affected processes.
  The application does nothing during rotation;
  the old process dies with the old secret, the new process starts with the new secret.
- There is no "hot reload" of secrets at Phase 1.
  Hot reload is an operational complexity that is not earned at this scale.
- Rotation is exercised in a drill no less often than quarterly at Phase 2.
  The Phase 2 runbook records the drill.

No exception: secrets never appear in a git commit, a built image, or a log line.
If a secret is found anywhere it should not be,
the procedure is rotate-then-purge-history, documented in
[SECURITY_REVIEW.md](./SECURITY_REVIEW.md).

## Database migrations

Database migrations are managed by Alembic.
The discipline below is mandatory, not advisory.

### Migrations run as a separate deploy step, not on app start

Migrations run as their own container invocation:

```
docker run --rm --env-file /etc/insuranceops/env insuranceops-ai:${VERSION} \
  /app/entrypoint.sh migrate
```

This is invoked by the deploy pipeline before the new `api` and `worker` image
replaces the old one.
The invocation runs `alembic upgrade head` and exits zero on success.

Migrations are explicitly NOT run on application start.
An `api` or `worker` process that starts does not touch Alembic.
The reasoning:

- **Concurrent starts race.**
  Two or more replicas starting in parallel would both attempt the migration.
  Alembic's version table is advisory, not a coordination primitive;
  relying on it to serialize concurrent upgrade attempts is a race the platform refuses to run.
- **Rollback ambiguity.**
  App-startup migrations make rollback unsafe:
  rolling back the image does not roll back the schema.
  A separate migration step lets the deploy pipeline sequence the rollback
  (stop new replicas, schema contract step if applicable, start old replicas).
- **Observability.**
  A dedicated migration step logs a single action at a single time.
  App-startup migrations interleave migration logs with normal startup logs
  and make incident post-mortems harder.
- **Database role separation.**
  The `migrate` invocation uses a database role with DDL privileges.
  The `api` and `worker` invocations use a database role with only DML privileges
  on the tables the application touches.
  Running migrations on app start would force every `api` and `worker`
  to carry DDL privileges, a gratuitous privilege expansion.

### Forward-only in production

Production migrations are forward-only.
`alembic downgrade` is used in local development for ergonomics and is present in the codebase
so that authors can iterate, but no production rollback plan relies on it.
A production rollback is a code rollback plus a targeted forward fix, not a schema downgrade.

### Expand-migrate-contract for destructive changes

Additive migrations (add nullable column, add new table, add index CONCURRENTLY)
are simple, reviewed once, and applied.

Destructive migrations (drop column, change type, rename table, tighten NOT NULL)
follow expand-migrate-contract:

1. **Expand.**
   Add the new shape alongside the old.
   For a column rename: add the new column, default to a value derived from the old.
   For a type change: add a new column of the new type, dual-write.
   This migration is forward-deployable with the old image.
2. **Migrate.**
   Backfill and start reading from the new shape.
   This deploy upgrades the application code to dual-read preferring new, dual-write.
3. **Contract.**
   Drop the old shape in a later migration, after at least one release cycle
   has confirmed the new shape is complete and correct.

Each phase is a separately-reviewed deploy.
Skipping a phase is not permitted.
The cost is pace; the benefit is that no deploy in the sequence is a cliff.

### Review discipline

Every migration is hand-reviewed.
Alembic's autogenerate is a starting point, never a committed artifact.
The reviewer checks that indexes use `CONCURRENTLY` where the table is non-trivial,
that check constraints match the declared domain (for example, state enum constraints),
that foreign keys reference the right columns with the right ON DELETE semantics,
and that the down migration, if present, is honest about reversibility.

A migration that is not reversible in practice is labeled in a comment
so that a reader is not misled by a formally defined `downgrade` function.

## Deployment procedure

The Phase 1 and Phase 2 deployment procedure is a written sequence rather than an implicit one.
The steps below are for a staging deploy;
production follows the same shape with an additional change-window and approval step.

1. **CI builds the image.**
   A green CI run on the target commit produces `insuranceops-ai:${VERSION}` in the registry.
   `${VERSION}` is the git SHA or a semver tag.
2. **Deploy pipeline pulls the image.**
   The deploy host pulls `insuranceops-ai:${VERSION}` from the registry.
   If the registry is unreachable, the deploy aborts.
3. **Migration step.**
   The pipeline runs `docker run --rm ... insuranceops-ai:${VERSION} /app/entrypoint.sh migrate`.
   On success, the version table advances to the new head.
   On failure, the deploy aborts and leaves the old image running.
4. **Compose apply.**
   The pipeline updates the `compose/compose.yml` (or a generated per-env overlay)
   with the new image tag and runs `docker compose -f ... up -d`.
   Compose replaces the `api` and `worker` containers one at a time.
5. **Readiness wait.**
   The pipeline polls `GET /readyz` on the `api` service until it returns `200`
   for a sustained window (for example, 10 consecutive successes over 30 seconds)
   or until a timeout (for example, 2 minutes).
   Timeout is a deploy failure.
6. **Worker restart.**
   Compose restarts the `worker` service.
   Workers drain their inflight Tasks gracefully if possible
   (SIGTERM, finish current Task, then exit) within a bounded grace period.
   Tasks still inflight when the grace expires are reaped after the visibility timeout.
7. **Post-deploy check.**
   The pipeline runs a short synthetic check:
   submit a trivial `claim_intake_v1` WorkflowRun via the API, assert it reaches `completed`
   within the expected budget.
   Failure of the synthetic check triggers the rollback below.

### Rollback

Rollback is re-tagging to the previous image and repeating the deploy procedure.
Because destructive migrations always follow expand-migrate-contract,
a rollback to the previous code version is always compatible with the current schema
if the previous version was in an expand or migrate phase.
A rollback from a contract phase requires a forward fix, not a schema downgrade.

A written rollback entry in the deploy log accompanies every rollback,
naming the original version, the reason, and the outcome.

## Blue-green vs in-place

Docker Compose on a single host does not support true blue-green.
The honest Phase 1 posture is an in-place rolling restart:
the `api` service has a short window (typically under 10 seconds)
during which the old container is stopping and the new container is warming up.
A client that hits the socket during that window receives a connection error
or a 502 from whatever the upstream load balancer is.

Two mitigations reduce the impact:

- **Readiness.**
  Compose waits for `/readyz` before replacing the next replica.
  With two or more replicas on the host, at least one stays up during the restart.
- **Graceful shutdown.**
  The `api` process handles SIGTERM by stopping new request acceptance,
  draining in-flight requests up to a bounded timeout, then exiting.

This is not zero-downtime.
It is short-downtime, accepted and documented.
Production deploys are performed during a declared short maintenance window
until either the scale demands more or the operational team invests in
a platform that supports zero-downtime rolling across hosts.
That investment triggers the Kubernetes reconsideration and is explicit.

## Backups

Backups are the platform's responsibility, not the application's.
Phase 1 defaults:

- **Postgres.**
  A nightly `pg_dump` of the application database with a 30-day retention window,
  run from the deploy host or a dedicated backup sidecar.
  Continuous WAL archiving is enabled when the deployment platform supports it
  (for example, managed Postgres services provide this natively);
  self-hosted Postgres configures `archive_mode = on` with an `archive_command`
  that writes WAL segments to an object store.
- **Restore drill.**
  A Phase 2 runbook documents the restore procedure and the recovery-time objective (RTO)
  and recovery-point objective (RPO).
  The drill runs no less often than quarterly.
  A drill that fails is an incident, not a routine observation.
- **Document payloads.**
  The local filesystem payload store is backed up via the platform's volume snapshot
  (Phase 1 single host)
  or via the object-storage backend's native replication (Phase 2 S3-compatible).
  Payload retention is separate from row retention; the Document row outlives the payload bytes
  when the retention policy retires the bytes.
- **Redis.**
  Redis is NOT backed up.
  Redis is cache plus queue, never source of truth.
  A Redis loss is recovered by restarting Redis and letting the `tasks_outbox` drain
  re-populate the queue; no committed state is lost.
  This is an explicit decision, stated here so operators do not configure Redis backups
  out of habit.

### Rough capacity planning

Under the Phase 1 assumption of thousands of WorkflowRuns per day, each with
tens of AuditEvents, a month of backups is on the order of low single-digit gigabytes.
WAL archival at that rate is on the order of tens of megabytes per hour.
These numbers are rough and depend on Document attachment volume;
the actual sizing is confirmed by the first week of staging operation.

## Sandbox and network constraints (current)

The sandbox in which Phase 0 documents are authored operates in an `INTEGRATIONS_ONLY`
network posture.
Concrete consequences:

- No external package registries are reachable.
  `pip install` against PyPI fails.
  `docker pull` against Docker Hub or any external registry fails.
- No external HTTP is reachable.
  A test that calls an external API fails with a connection error.
- Only the connected source-control remote (GitHub) is reachable,
  and only for git operations.

Effect on Phase 0:

- **None.**
  Phase 0 is markdown authoring.
  No network is required to produce the design documents.

Effect on Phase 1 and beyond:

- Implementation work (dependency installation, image builds, test-time service containers)
  must run in an environment with package-registry access
  (`COMMON_DEPENDENCIES` mode or `OPEN_INTERNET` mode).
- CI runs in GitHub Actions, which has general network access;
  the deterministic-CI rules in the CI/CD section bound what CI is allowed to reach.
- Local developer environments are expected to have package registry access
  for the initial `pip install`.
  Once the image is built, local runs use the image.
- Any Phase 1 attempt to run `docker build` from inside the current sandbox
  will fail at the base-image pull.
  The documented remediation is to stage implementation in a non-restricted environment.

The constraint is recorded here so no future reader is surprised
by a build failing at package install time and concluding the project is broken.

## Scaling playbook

Phase 1 deployments run on a single host.
This is deliberate.
The scaling posture is vertical first, horizontal only when measured load demands it,
and never decomposition-for-its-own-sake.

When a single host is no longer enough, the sequence is:

1. **Vertical scaling.**
   Larger host.
   More CPU, more RAM.
   This handles the first order of magnitude of growth at trivial operational cost.
2. **Split Postgres.**
   Postgres moves to a dedicated host (or a managed Postgres service).
   `DATABASE_URL` is updated in the deploy config.
   No application change.
3. **Split Redis.**
   Redis moves to a dedicated host or a managed Redis service.
   `REDIS_URL` is updated.
   No application change.
4. **Split `api` and `worker` across hosts.**
   Run the `api` process on one host (or two behind a load balancer)
   and the `worker` processes on separate hosts.
   Same image, different `PROCESS_TYPE`.
   Compose remains the orchestrator on each host.
5. **Postgres read replicas.**
   Introduce read replicas for the endpoints that dominate read load,
   primarily `GET /v1/workflow-runs/{id}` and `GET /v1/workflow-runs/{id}/events`.
   The application gets a read-preferring connection pool for these endpoints
   via a second `DATABASE_URL_READONLY`.
   Writes remain on the primary.
6. **Redis stays single-writer.**
   Redis Cluster is not introduced at this scale.
   The queue throughput a single Redis supports comfortably exceeds what the platform
   generates in its Phase 1 and Phase 2 envelopes.

At no step in this sequence is the application rearchitected.
The scaling steps are configuration changes, not code changes.
That is the invariant the Phase 1 design buys.

## Explicit NOT-deploying to

Stated directly so intent is unambiguous.

### Kubernetes

Not adopted at Phase 1 or Phase 2.
Reasoning in the Rejected alternatives section below and in
[SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md) §24.1.
Reconsideration conditions:

- Sustained need for more than one production host.
- Sustained need for zero-downtime rolling deploys across replicas beyond what Compose delivers.
- An operations team explicitly resourced to own a Kubernetes control plane
  (cluster upgrades, networking, storage, RBAC, admission, observability of the cluster itself).

All three conditions must hold for a sustained period (no less than one quarter)
before Kubernetes is reconsidered.

### Serverless (AWS Lambda, GCP Cloud Run functions, Fly Machines-as-serverless)

Not adopted at Phase 1, Phase 2, or Phase 3.
Reasoning:

- The `worker` process is a long-running loop that benefits from in-memory caches
  (reference data, connection pools).
  Serverless execution per Task discards those caches.
- The `api` process is long-lived by design and cooperates with Postgres pool lifecycle.
  Serverless cold starts on each request add latency for no gain.
- Cost under the platform's sustained throughput favors always-on containers over
  pay-per-invocation.

Potential reconsideration at Phase 4+ for a narrow burst-only surface,
not for the core `api` or `worker`.

### PaaS that obscures the runtime (Heroku-style)

Not adopted.
Reasoning:

- The platform needs control over process supervision, filesystem paths, and sidecar shapes
  (for example, a Phase 3 ML extractor sidecar).
  A PaaS that hides the runtime removes that control.
- Observability surface is narrower than the platform's requirements
  (no direct scrape of Prometheus metrics, no direct filesystem access to payload store).

A PaaS may be reconsidered for a future non-core component (a status page, an analytics sidecar),
never for `api` or `worker`.

### Helm

Not adopted.
Helm is a Kubernetes package manager; it is only relevant if Kubernetes is adopted.
See Kubernetes above.

## Assumptions

- The deployment platform at Phase 1 provides:
  a Docker engine, a network, a persistent volume for Postgres data,
  a persistent volume or bind mount for the local payload store,
  a way to inject environment variables at process start,
  and a way to ship stdout logs to a log aggregator.
- The team operating the platform at Phase 1 is small and owns both the application and its deployment.
  There is no separate operations org.
- Package registries (PyPI, Docker Hub or a private registry) are reachable from the build
  environment.
  The current sandbox's `INTEGRATIONS_ONLY` posture is a Phase 0 constraint only;
  Phase 1 builds run in a less restricted environment.
- The image registry supports immutable tags and content-addressable digests.
  The deploy procedure depends on digest-level reproducibility.
- Postgres is version 15 or later with standard defaults and tuned shared buffers.
  Redis is version 7 or later with `maxmemory-policy=noeviction`.
- Wall-clock synchronization across deployment hosts is within one second via NTP.
- Secrets are supplied by the platform's secret store.
  No secret appears in git, in a Docker image layer, or in a log line.
- The team reviews Alembic migrations by hand and will not auto-commit autogenerate output.

## Rejected alternatives

The rejections below name alternatives considered and explain the reasoning
and the conditions under which each would be revisited.
Some entries cross-reference [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md) §24
where the broader architectural reasoning lives.

### Kubernetes

Kubernetes is a powerful, widely-adopted container orchestrator.
It is not adopted at Phase 1 or Phase 2 for three reasons.
First, the target scale is a single host or a small set of hosts;
Compose delivers that topology with a fraction of the operational surface.
Second, the organization operating the platform at Phase 1 is small;
owning a Kubernetes control plane (cluster upgrades, networking, storage classes,
admission controllers, RBAC, the cluster's own observability)
is disproportionate to the application's requirements.
Third, Kubernetes does not solve a problem the platform has:
the bottlenecks we measure are Postgres write throughput and queue depth,
neither of which is mitigated by a more elaborate scheduler.
Reconsidered when the three conditions stated in the Explicit NOT-deploying to section all hold.

### Nomad

Nomad is a simpler container and workload orchestrator than Kubernetes.
It is not adopted because Compose already delivers the process supervision
the platform requires, and because adopting Nomad would be an investment
in a platform whose sole payoff is "not Kubernetes."
If the platform outgrows Compose and the team wants a lighter alternative than Kubernetes,
Nomad is a reasonable reconsideration, evaluated against managed container services
available on the target cloud.

### Managed PaaS (Heroku, Railway, Render)

Managed PaaS platforms make deployment mechanics very cheap for simple web applications.
They are not adopted because the platform's `worker` process topology,
the need for direct filesystem access to a payload store, and the requirement for
Prometheus scrape endpoints inside the cluster-internal network
do not fit the PaaS shape cleanly.
A PaaS becomes attractive only if the platform shrinks to a single API process
with no worker pool, which is a fundamental architectural regression the team will not make.

### AWS Fargate or Google Cloud Run for the core services

Fargate and Cloud Run remove the host-ops burden by running containers on managed infrastructure.
They are not adopted as defaults at Phase 1 because choosing either before the
deployment-platform decision would lock the architecture to a specific cloud vendor
before any Cloud-vendor dependency has earned that coupling.
Either is a reasonable Phase 2 target for the core services
once the deployment platform decision is made and recorded.

### Helm

Helm is a Kubernetes package manager.
Not adopted because Kubernetes is not adopted.
If Kubernetes is adopted later, Helm (or Kustomize, or a simple raw-manifest approach)
is a separate decision evaluated then.

### App-startup migrations

Running `alembic upgrade head` inside the `api` or `worker` entrypoint is a common pattern.
It is rejected for the reasons in the Database migrations section:
race between concurrent starts, ambiguous rollback, observability noise,
and gratuitous privilege expansion on the application's database role.
A dedicated `migrate` invocation is the discipline.

### Terraform for the Phase 1 deploy

Terraform is infrastructure-as-code for cloud provisioning.
It is not adopted at Phase 1 because the Phase 1 infrastructure is one host,
one Postgres, and one Redis.
The Phase 1 infrastructure fits in a short README with a few `docker compose` commands.
Terraform becomes appropriate when the infrastructure grows to multiple hosts,
multiple networks, and per-environment configuration that benefits from declarative state.
Reconsidered at the Phase 2 deployment-platform decision.

### Ansible, Chef, Puppet, SaltStack

Configuration management tools are useful for managing many hosts.
Phase 1 manages one host.
The `compose/compose.yml` file plus a short deploy script is sufficient.
Reconsidered when the host count grows and host state drift becomes a real problem.

### CI on a self-hosted runner from day one

Self-hosted GitHub Actions runners provide more control and sometimes cheaper CI.
They are not adopted at Phase 1 because GitHub-hosted runners are sufficient,
they remove a class of "it works on my machine" surprises between CI and local,
and the operational burden of maintaining a runner fleet is not justified at the
current rate of CI minutes.
Reconsidered when CI minutes or egress costs make self-hosting meaningfully cheaper.

### Pushing the image on every PR

Some teams push the built image to the registry on every PR, tagged by commit SHA.
The Phase 1 CI builds the image but does not push, because the push-on-every-PR
pattern accumulates registry objects that are rarely used and costs storage and cleanup effort.
Releases on tag push are the only path to a pushed image.
Reconsidered if integration tests against the pushed image become part of the review loop.
