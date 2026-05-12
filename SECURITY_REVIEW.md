# SECURITY_REVIEW.md

## Purpose

This document is the authoritative security posture for InsuranceOps AI at Phase 1
and the planned hardening for Phase 2 and beyond.
It elaborates the brief summary in [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md) section 19
without contradicting it.
It enumerates the threat model, role boundaries, authentication and authorization mechanics,
secret handling, PII handling, audit retention, access logging, rate-limiting posture,
supply-chain controls, least-privilege rules, and the list of things this platform explicitly does NOT claim.

The document is descriptive where Phase 1 ships a concrete control,
and prescriptive where a future phase will add or harden one.
Where a control is deferred, the phase and the reason are named.

## Scope

In scope:

- Security controls implemented by the platform itself (the `api` and `worker` processes,
  the Postgres schema, the Redis key surface, and the container image).
- Role model for the three Phase 1 principals: `operator`, `supervisor`, `viewer`.
- Threat model for the Phase 1 attack surface (public API, background workers,
  queue substrate, state store, document ingestion pipeline, audit chain).
- Data handling for PII carried inside Documents and surfaced in API responses.
- Audit trail mechanics and retention.
- Supply-chain controls at build time (CI pipeline is described in
  [DEPLOYMENT_STRATEGY.md](./DEPLOYMENT_STRATEGY.md); this document states the requirements
  the CI pipeline must meet).

Out of scope:

- Physical and platform security of the host running the Docker image. That is
  the responsibility of the deployment platform chosen in Phase 2 and is described
  abstractly in DEPLOYMENT_STRATEGY.md.
- Network perimeter configuration (firewall, WAF, DDoS mitigation). Phase 1 treats
  these as the deployment platform's job.
- Endpoint security of the operator's workstation.
- Regulatory compliance certification. This document explicitly does NOT claim
  SOC 2, HIPAA, PCI-DSS, ISO 27001, GDPR DPA, or CCPA readiness.
  See `## Explicitly NOT claimed` below.

This document describes the Phase 1 security posture plus the Phase 2 and Phase 3
hardening plan. Any language suggesting certification, accreditation, attestation,
or audit readiness is forbidden and would be removed on review.

## Threat model

The Phase 1 attack surface has five principal entry points:
the public `/v1` API, the `/metrics` endpoint, the `/healthz` and `/readyz` probes,
the document ingestion path (which accepts arbitrary binary uploads),
and the database and Redis connections (reachable only inside the deployment network).

The table below is a STRIDE-flavored enumeration. It is deliberately short and specific.
Each row names a Threat, the Asset at risk, the Vector by which the threat is realized,
and the Mitigation shipped in Phase 1 or named for a later phase with the phase number attached.

| Threat | Asset | Vector | Mitigation |
| --- | --- | --- | --- |
| Spoofed API client using a stolen API key | Document bytes, WorkflowRun state, EscalationCase queue | Token leak through a developer laptop, a committed secret, or a compromised HTTP client | API keys are 256-bit random tokens, stored as `sha256(pepper \|\| token)` in `api_keys.hashed_token`; plaintext visible only at creation; manual rotation by operator in Phase 1 via SQL update on `api_keys.enabled`; Phase 2 admin endpoint for rotation and Phase 2 Redis-backed short-TTL allowlist to let revocation propagate within seconds |
| Tampered AuditEvent to hide an operator action | AuditEvent chain, compliance evidence | Direct SQL modification, backup restore mismatch, operator with DB credentials | Per-workflow hash chain (see [SYSTEM_ARCHITECTURE.md section 16](./SYSTEM_ARCHITECTURE.md)); verifier script (Phase 2) walks `audit_events WHERE workflow_run_id = ?` by `occurred_at` and reports the first `event_hash != sha256(prev_event_hash \|\| canonical_payload)` row; `audit_events` table has REVOKE UPDATE, REVOKE DELETE for the app DB role (Phase 1); database role separation (`app_rw`, `app_audit_writer`, `migrator`) so the app-runtime role cannot mutate existing audit rows |
| Repudiation by an operator of an escalation action | EscalationCase resolution trail | Operator claims "I never resolved that case" | Every resolve, reject, claim, and cancel emits an AuditEvent with `actor = user:<role>:<user_id>`, `correlation_id`, and the resolution payload hash; AuditEvent is signed by its position in the hash chain and is non-updatable; session cookie or API key that produced the call is recorded alongside the actor |
| Information disclosure of PII through logs or responses | SSN, DOB, policy_number, claimant_name, address, phone, email, medical codes carried in Documents | Accidental log of a field name, stack trace that includes a payload, error response that echoes input | structlog processor `redact_pii` strips or SHA-256-hashes fields by exact name before emit; response serializers for PII-bearing models have a role-gated field filter; raw document bytes are NEVER logged; error handlers return an opaque `error_id` and log the detail server-side |
| Information disclosure of Document bytes through the object layer | Raw PDF and image bytes | Path traversal on the Phase 1 local filesystem backend, world-readable bind mount, backup exfiltration | Phase 1 stores Document bytes under a single configured directory with a content-hash filename (`<sha256>.<ext>`); no user-supplied path component; directory permissions 0700, owned by the app user; Phase 2 encrypts-at-rest via application-layer Fernet with a KMS-wrapped key and document bytes move to an object store with signed short-TTL read URLs |
| Denial of service by request flood | API process, DB connection pool, Redis, worker pool | Large unauthenticated POST volume, one authenticated caller saturating workers | Phase 1 ships `MAX_REQUEST_BYTES` hard cap on upload size (configurable, default 20 MiB) and a coarse per-key QPS cap implemented with a Redis counter under `rate:api_key:<key_hash>:<bucket_window>` (see [SYSTEM_ARCHITECTURE.md section 7.6](./SYSTEM_ARCHITECTURE.md)); per-route differentiated rate limits and token-bucket smoothing are Phase 2; `WORKER_CONCURRENCY` and `uvicorn` worker counts are bounded in the deployment config; the deployment platform is expected to terminate TLS and provide L7 rate limiting at the edge |
| Elevation of privilege across roles | viewer acting as operator, operator acting as supervisor | Missing role check on a new route, inherited permissions from a permissive base class | Role enforcement is a FastAPI dependency that denies by default; every route declares `Depends(requires_role("operator"))` or equivalent explicitly in code; there is no role inheritance and no "admin" superrole; a route with no role decorator fails the test that asserts `all routes have explicit role`; supervisors do not automatically inherit operator actions, they are granted each capability explicitly in the permissions matrix |
| Poisoned Document exploiting a parser | Extraction worker process | Malicious PDF with embedded scripts, a zip bomb, an image crafted to crash a parser | Mimetype sniffed server-side against a small allowlist (`application/pdf`, `image/png`, `image/jpeg`, `image/tiff`); hard size cap before the parser ever sees the bytes; extractor runs inside a per-attempt timeout and memory bound; Phase 2 isolates heavy parsers in a sidecar subprocess so a parser crash cannot corrupt the worker state; extractor never executes document-embedded code paths and never renders HTML |
| Replay of a captured API request | Duplicate Document ingestion, duplicate WorkflowRun start | An attacker replays a captured authenticated request against the same server | Write endpoints require an idempotency key (`Idempotency-Key` header for POST on `/v1/documents` and `/v1/workflow-runs`); the key is stored under `idempotency:<scope>:<key>` in Redis with TTL, mapping to the original response (see [SYSTEM_ARCHITECTURE.md section 7.7](./SYSTEM_ARCHITECTURE.md)); replay returns the original result rather than creating a duplicate |
| Server-side request forgery from an extractor or validator | Internal network services | An extractor that accepts a URL and fetches it (none ship in Phase 1) | Phase 1 ships no URL-fetching extractor; the deterministic extractor only reads the provided Document bytes; if Phase 3 adds a URL-fetching extractor, it MUST use a resolver with a deny-by-default allowlist of egress hosts and block all RFC1918 ranges, link-local, and metadata IPs |

The threat model is complete for the Phase 1 surface. It is intended to be extended
row-by-row as endpoints and integrations are added. A row is added BEFORE the endpoint
ships, not after; a PR that introduces a new authenticated path without a threat-model
row is an incomplete PR.

## Role boundaries

Three roles exist in Phase 1: `operator`, `supervisor`, and `viewer`.
Role is a property of either an API key (for machine clients) or a session cookie (for the Phase 3 operator UI).
Role is evaluated on every request at the FastAPI dependency layer.
There is no role inheritance. A supervisor does not automatically have operator capabilities;
each capability is granted to each role explicitly in the table below.

### operator

Day-to-day operations principal. Claims, resolves, and rejects EscalationCases.
Reads WorkflowRun status and audit timeline for runs they are working on.
May start a WorkflowRun on a Document that has been ingested.
Cannot cancel a WorkflowRun mid-flight (that is a supervisor action).
Cannot manage api_keys or users.

### supervisor

All operator capabilities, explicitly re-granted in the table.
Cancels WorkflowRuns in `running` or `awaiting_human` states.
Requeues entries from the DLQ surface (Phase 2).
Manages `api_keys` and `users` via the admin surface (Phase 2 endpoints;
at Phase 1 these are SQL statements run by the on-call operator,
not an exposed HTTP endpoint).

### viewer

Read-only principal. Reads WorkflowRun status, audit timeline, and the list of EscalationCases.
Cannot claim, resolve, reject, ingest, start, or cancel. Cannot manage anything.
Intended for compliance reviewers and for dashboards that need a service-to-service read credential.

### Permissions matrix

Capability on rows, role on columns. Values are `allow` or `deny`. There is no "inherit".

| Capability | operator | supervisor | viewer |
| --- | --- | --- | --- |
| Ingest Document (`POST /v1/documents`) | allow | allow | deny |
| Start WorkflowRun (`POST /v1/workflow-runs`) | allow | allow | deny |
| View WorkflowRun (`GET /v1/workflow-runs/{id}`) | allow | allow | allow |
| View audit timeline (`GET /v1/workflow-runs/{id}/events`) | allow | allow | allow |
| List EscalationCases (`GET /v1/escalations`) | allow | allow | allow |
| Claim EscalationCase (`POST /v1/escalations/{id}/claim`) | allow | allow | deny |
| Resolve EscalationCase (`POST /v1/escalations/{id}/resolve`) | allow | allow | deny |
| Reject EscalationCase (`POST /v1/escalations/{id}/reject`) | allow | allow | deny |
| Cancel WorkflowRun (Phase 2 endpoint) | deny | allow | deny |
| Requeue DLQ entry (Phase 2 endpoint) | deny | allow | deny |
| Manage api_keys (Phase 2 endpoint) | deny | allow | deny |
| Manage users (Phase 2 endpoint) | deny | allow | deny |
| Read `/metrics` | allow | allow | allow |
| Read `/healthz`, `/readyz` | allow | allow | allow |

A viewer hitting a claim route receives HTTP 403 with a log line
`event=authz_denied actor=... required_role=operator actual_role=viewer route=...`
and increments `auth_denials_total{reason="role"}`.

A request with no credential at all on a credential-required route receives HTTP 401
and increments `auth_denials_total{reason="missing_credential"}`.

A request with a credential that does not resolve to a known principal receives HTTP 401
and increments `auth_denials_total{reason="unknown_principal"}`.

The distinction between 401 and 403 is intentional: 401 signals the caller to attach or refresh
a credential, 403 signals the caller that the credential is valid but the principal is not authorized.

## Authentication

Phase 1 supports API-key authentication for machine clients. Session-cookie authentication
for the Phase 3 operator UI is described but not yet implemented; OIDC/SSO is a Phase 3 deliverable.

### API keys

An API key is a 256-bit random value generated by a CSPRNG (`secrets.token_bytes(32)`),
base64url-encoded at the boundary, and prefixed with a short tag (`ioa_live_`, `ioa_test_`)
to make key class obvious in logs and screenshots.
The plaintext is returned exactly once at creation time.
What persists in the database is `sha256(pepper || plaintext)` in `api_keys.hashed_token`.
The pepper is a deployment-level env var (`API_KEY_HASH_PEPPER`), not per-key.
Using SHA-256 (not argon2) for storage is deliberate for API keys:
the search space is the full 256 bits of the token, so a slow KDF adds no meaningful entropy
while inflating the per-request verification cost. The pepper prevents offline rainbow attacks
against a dumped table.

Note on consistency: [SYSTEM_ARCHITECTURE.md section 19.2](./SYSTEM_ARCHITECTURE.md) mentions
argon2id as a candidate storage scheme during early drafting.
This document (SECURITY_REVIEW.md) is the authoritative source for the storage scheme,
and the choice is `sha256(pepper || plaintext)` with the reasoning above.
SYSTEM_ARCHITECTURE.md will be reconciled in a Phase 1 follow-up if the discrepancy materializes in code review;
it is noted here to prevent drift.

Each `api_keys` row carries:

- `hashed_token`: the stored hash.
- `key_prefix`: the first eight characters of the plaintext, for display and lookup.
- `role`: one of `operator`, `supervisor`, `viewer`.
- `scopes`: a JSONB array for forward compatibility (Phase 2 introduces narrower scopes within a role).
- `enabled`: boolean. Setting to `false` is the disable mechanism at Phase 1.
- `created_at`, `created_by`, `last_used_at`, `expires_at` (nullable).

### Rotation

Phase 1 rotation is a manual operator action: create a new key, update the caller to use it,
set the old key's `enabled` to `false`. This is intentionally primitive. Phase 2 adds
`POST /v1/admin/api-keys` and `POST /v1/admin/api-keys/{id}/revoke`
with AuditEvent emission, and a Redis-backed revocation allowlist so that revocation
propagates within seconds even if a replica caches the previous state.

### Transport

Transport is HTTPS only, and TLS termination is the deployment layer's job, not the app's.
The app refuses to bind a plaintext socket to anything other than `127.0.0.1` in any non-local
environment; `ENV=staging` and `ENV=production` assert that the process is fronted by a TLS
terminator before serving traffic. The assertion is a startup check against an env var
(`ASSUME_TLS_TERMINATOR=true`). The app does not attempt to terminate TLS itself.

### Sessions (Phase 3)

For the Phase 3 operator UI, the plan is a signed session cookie with:

- `sid`: a random session id (not the user id).
- Server-side session store in Postgres (`sessions` table) with a last-activity timestamp.
- Cookie attributes: `HttpOnly`, `Secure`, `SameSite=Lax`.
- Sliding inactivity window of 30 minutes, absolute cap of 8 hours.
- OIDC as the upstream identity provider. The app never stores passwords.

No JWT. The rationale is in `## Rejected alternatives` below.

## Authorization

Authorization is a single FastAPI dependency chain:

1. `resolve_principal`: reads `Authorization: Bearer <token>` or the session cookie,
   looks up the principal, fails closed on missing or unknown credentials.
2. `requires_role("operator")` or equivalent: compares the principal's role against the
   required role for the route. Denies by default.
3. Route handler: runs only if both dependencies returned a principal.

Every route in `/v1` declares its required role explicitly. A test in the Phase 1 suite
asserts that every registered route either:

- Requires a role (and the test records which role), or
- Is explicitly allowlisted as public (`/healthz`, `/readyz`, `/metrics`).

A route that fails this assertion is a CI failure. This is how we prevent the
"forgot the decorator" class of vulnerability.

There is no permission inheritance. If a supervisor should be able to do an operator action,
that capability is granted to supervisor in the permissions matrix. This is more verbose
than an inheritance model and it is deliberate: a role model that is visible in a table
is easier to review than one reconstructed from a class hierarchy.

Authorization failures are logged at WARN with actor, route, required role, actual role,
and correlation id, and counted in `auth_denials_total{reason="role"}`.

## Secret handling

Secrets are environment variables at runtime, delivered by the deployment platform's secret store.
The Docker image contains no secrets. A secret that appears in any image layer is a build-time
bug that must be remediated by rebuilding the image from the clean layer and rotating the secret.

The `.env.example` file at the repo root lists variable NAMES only, never values.
A CI check greps `.env.example` for obviously-real-looking values (entropy heuristic on strings
longer than 16 characters that do not end in `_EXAMPLE` or `CHANGE_ME`) and fails the build
on any hit.

### Runtime contract

The app refuses to start if any required secret is missing or empty.
A required secret's absence is a startup error with a precise message naming the missing variable
(the variable name, not the value) and the process exits with a non-zero code.
The secret loader logs at INFO that each required secret is present (value length only,
never the value itself) so operators can verify the expected set of secrets is wired.

### Memory handling

Phase 1 does not attempt to zero secret memory after use; Python string immutability makes this
theater in almost every case. Phase 2 considers the narrow case of raw key material
used for Fernet encryption, which can be kept in a `bytearray` and zeroed deterministically
after the cipher is torn down.

### Secrets in logs, errors, crash reports

The structlog processor `redact_secrets` strips values for any field whose name matches
`SECRET`, `TOKEN`, `PASSWORD`, `API_KEY`, `HASH_PEPPER`, `SALT`, or `PRIVATE_KEY`
(case-insensitive). The same processor refuses to emit a string value that contains the exact
current value of any registered secret env var; registered secrets are loaded into a guard set
at startup and consulted by the redactor on every emit. Error responses never echo request bodies.

### Secrets in git history

A detection is more valuable than a policy here. CI runs a `gitleaks`-equivalent scan on every PR
(Phase 2 deliverable; Phase 1 ships the config for it). If a secret is detected in git history,
the response is the Phase 2 "rotate-and-purge" runbook:

1. Rotate the leaked secret at its issuing authority (so the leak is moot).
2. Purge the history using `git filter-repo` against the target branch.
3. Force-push with explicit review, with all collaborators warned.
4. Revoke any cloned copies of the repo inside the organization.

The rotate step runs first because purging history is best-effort; rotation is definitive.

## PII handling

Documents ingested into InsuranceOps AI may contain PII. The platform recognizes nine canonical
PII field classes and handles them per the policy below.

### Recognized PII field classes

| Field class | Examples | Sensitivity |
| --- | --- | --- |
| government_id | SSN, ITIN, TIN, driver's license number, passport number | high |
| dob | date of birth | high |
| policy_number | insurance policy numbers, claim numbers | medium |
| claimant_name | first name, middle name, last name, full name | medium |
| address | street, city, postal code, full address | medium |
| phone | any phone number | medium |
| email | any email address | medium |
| medical_code | ICD-10 code, CPT code, diagnosis description | high |
| financial_account | bank account number, routing number, card PAN | high |

These field classes are encoded in a single module (`ioa.pii.fields`) and referenced by name
throughout the codebase. Adding a new class requires adding it to the module, updating the
redaction list, and updating the encryption-at-rest column definitions if the field is stored.

### Redaction in logs

The structlog processor `redact_pii` runs on every log record. It:

1. Strips the value of any field whose exact name appears in a PII-name allowlist
   (`ssn`, `dob`, `date_of_birth`, `policy_number`, `claimant_name`, `first_name`,
   `last_name`, `address`, `phone`, `email`, `icd_code`, `cpt_code`, `account_number`,
   `routing_number`, `card_pan`).
2. Replaces the value with a SHA-256 hash if the caller explicitly passed
   `_redact_strategy="hash"` on the bound logger. Hashing allows correlation across lines
   without exposing the underlying value. The hash is unsalted inside a single run and
   salted with `LOG_PII_HASH_SALT` for cross-run correlation resistance.
3. Walks nested dicts one level deep. The policy is not recursive beyond that:
   deeply nested structures are a log-hygiene problem in their own right and are flagged.

The redactor never attempts regex-based PII detection on arbitrary strings. Pattern-based
detection produces false positives and false negatives that are worse than no detection at all.
Fields are redacted by name only; the guarantee is "we never log a value under a known PII
field name", not "we guarantee no PII ever appears in any log".

### Redaction in API responses

PII fields in response models are role-gated. A viewer sees a masked representation
(last four digits for government_id, policy_number, and financial_account; a hash stub
for email and phone; city-and-state only for address; initials for claimant_name).
An operator and supervisor see the full value when the endpoint is designed to surface it.
Masking is the default, unmasking is explicit per endpoint per role.

### Encryption at rest

Phase 1 stores PII fields in Postgres using `pgcrypto` column-level symmetric encryption
with a deployment-level key (`PII_ENCRYPTION_KEY`, 32 bytes base64url-encoded, delivered as an env var).
The plaintext is never written to disk; `pgcrypto`'s `pgp_sym_encrypt` runs on the app side of
the connection in Phase 2 (Phase 1 is permitted to use server-side encryption with the caveat
that the key ends up in Postgres memory; this is acceptable given the Phase 1 threat model).

Application-layer Fernet with a KMS-wrapped data key is the Phase 2 target. The KMS backend
(AWS KMS, GCP KMS, HashiCorp Vault Transit, or a standalone boundary service) is a Phase 2
decision; the interface is a `KeyProvider` class with two methods (`encrypt_dek`, `decrypt_dek`)
that does not change when the backend is chosen.

### Document bytes

Raw document bytes are stored only in the configured object layer.
Phase 1 uses a local filesystem backend rooted at `DOCUMENT_STORE_PATH`.
Phase 2 moves to an object store (S3, GCS, or MinIO) with server-side encryption and
short-TTL signed read URLs. Document bytes are NEVER logged, NEVER included in AuditEvent
payloads, and NEVER echoed in API responses (the API serves metadata and content hashes;
the raw bytes are fetched via a separate endpoint with explicit role gating).

### Retention

Retention is per-class and configurable per deployment. Defaults:

| Entity | Default retention | Rationale |
| --- | --- | --- |
| `audit_events` | 7 years | Matches common insurance retention obligations without claiming compliance |
| `documents` (bytes) | 2 years | Operational need for re-extraction during dispute windows |
| `workflow_runs`, `steps`, `step_attempts` | 7 years | Parallel to audit_events |
| `escalation_cases` | 7 years | Decision record; parallel to audit_events |
| `api_keys` (disabled rows) | 2 years | Forensic record of which key performed which action |
| `sessions` (Phase 3) | 90 days after last activity | Short enough to limit replay, long enough to investigate |

Retention is enforced by a Phase 2 housekeeper job that moves expired rows to a cold
archive partition (or deletes them, per deployment policy). Phase 1 runs no purge; data
accumulates and is acknowledged in the capacity plan.

### No secondary copies

The architecture rejects "helpful" caches that would create a second copy of PII:

- Redis is NOT used to cache document bytes, Document rows, or EscalationCase detail.
- The metrics surface does not use high-cardinality labels that would embed PII
  (see [OBSERVABILITY_STRATEGY.md](./OBSERVABILITY_STRATEGY.md)).
- The `/metrics` endpoint does not expose per-user or per-run counters.

## Audit retention and tamper visibility

The AuditEvent hash chain is the platform's evidence mechanism. Its mechanics are documented
in [SYSTEM_ARCHITECTURE.md section 16](./SYSTEM_ARCHITECTURE.md). This section documents
the retention policy and the tamper-visibility posture; it does not restate chain construction.

### Retention

`audit_events` rows retain for 7 years by default. This is configurable per deployment
via `AUDIT_RETENTION_DAYS`. Lowering the retention below 2 years requires an explicit
override flag (`AUDIT_RETENTION_ALLOW_SHORT=true`) because a short retention defeats
the evidentiary purpose.

### Immutability

The `audit_events` table carries row-level REVOKE UPDATE and REVOKE DELETE for the
app-runtime DB role. A dedicated `app_audit_writer` role has INSERT only; it does not
have UPDATE or DELETE either. The `migrator` role has full DDL power but is not the
role the app runs as. This three-role model is enforced by Alembic migrations and
verified by a CI test that asserts the expected grants.

### Verifier

A verifier script (Phase 2 deliverable) walks the chain for a given `workflow_run_id`:

1. Select all rows WHERE workflow_run_id = ? ORDER BY occurred_at, seq_in_run.
2. For each row, recompute `expected_current_hash = sha256(prev_event_hash || canonical_payload)`.
3. Assert `row.event_hash == expected_current_hash` and
   `row.prev_event_hash == previous_row.event_hash`.
4. On mismatch, report the first broken link: the `audit_event_id`, the expected hash,
   the actual hash, and the occurred_at.

The verifier runs in two modes: on-demand for a specific run (operator tool), and
periodically across a sample of runs (Phase 2 housekeeper). Periodic verification emits
a Prometheus metric `audit_chain_mismatches_total` that MUST be zero in healthy operation;
any non-zero value is a paging alert.

### Export

Compliance reviewers export evidence for a specific case via
`GET /v1/workflow-runs/{id}/events` with the viewer role (Phase 2 adds an `Accept: application/x-ndjson`
content negotiation for bulk export). Export emits an AuditEvent of type `audit.exported`
with `actor`, the run id, and the timestamp. Exports are themselves audited.

## Access logging

Every authenticated API call emits a structured log line at INFO level with:

- `actor` (e.g., `api_key:operator:a1b2c3d4`, `user:operator:42`).
- `route` (the matched FastAPI route path, not the raw URL, to avoid cardinality on path params).
- `method`, `status`, `duration_ms`.
- `correlation_id`.
- `client_ip` (left-most non-trusted-proxy entry from `X-Forwarded-For`).

Failed authentication attempts (HTTP 401) are logged at WARN with `reason` = `missing_credential`,
`malformed_credential`, or `unknown_principal`. Failed authorization attempts (HTTP 403) are
logged at WARN with `reason=role`, `required_role`, and `actual_role`. Both are counted in
`auth_denials_total{reason=...}` (see [OBSERVABILITY_STRATEGY.md](./OBSERVABILITY_STRATEGY.md)).

This log stream is the input to any future SIEM integration. The log shape is intentionally
stable: a Phase 3 SIEM pipe does not require app changes, only a log router at the platform layer.

## Rate limiting and abuse controls

Phase 1 ships three controls:

1. **Request size limit.** `MAX_REQUEST_BYTES` (default 20 MiB) is enforced at the FastAPI
   layer. Exceeding it returns HTTP 413. This prevents trivial memory-exhaustion attacks
   through oversized uploads.
2. **Coarse per-key QPS cap.** A Redis counter at `rate:api_key:<key_hash>:<bucket_window>`
   with a fixed window (default 60 seconds) and a cap (default 1200 requests per key per
   60-second window for `operator` and `supervisor`, 600 for `viewer`). On exceed, the API
   returns HTTP 429 with `Retry-After`. This is a blunt instrument; per-route shaping is
   Phase 2.
3. **WORKER_CONCURRENCY cap.** The worker pool size is bounded by configuration. A single
   noisy caller cannot monopolize workers beyond their queue share because the queue is
   FIFO per priority and the workers drain it uniformly.

Phase 1 does NOT ship:

- Per-route rate limits with differentiated caps.
- Token-bucket smoothing with burst allowances.
- Concurrent-request caps per principal.
- Adaptive rate limits that respond to load.

These are Phase 2 deliverables. Phase 1's honest position is "we have a floor, not a ceiling".

## Dependency supply chain

Python dependencies are locked. The lockfile (`uv.lock` or `requirements.lock` produced
by `pip-compile`) is checked in. CI fails on any unlocked dependency or on a lockfile drift
against `pyproject.toml`. A lock-drift check runs on every PR.

`pip-audit` runs in CI on every PR and nightly on main. A new high-severity advisory on a
production dependency fails the nightly build and pages the maintainer. The nightly job is
the mechanism for catching advisories published after a release.

The container base image is pinned by digest, not by tag. `FROM python:3.12-slim@sha256:...`
with the digest refreshed deliberately (Phase 2 adds a Renovate-equivalent bot for base-image
digest updates, gated by a build-and-test pipeline). A floating tag base image is a CI failure.

### Minimum dependency policy

A dependency is added only if it carries non-trivial behavior. The rejected alternatives
in [SYSTEM_ARCHITECTURE.md section 24](./SYSTEM_ARCHITECTURE.md) and
[TECHNICAL_DEBT_PREVENTION.md](./TECHNICAL_DEBT_PREVENTION.md) elaborate the policy.
For security, the implication is that the supply-chain surface is intentionally small.

### Image layer scanning

A Phase 2 CI step scans the final image with `trivy` or equivalent for known CVEs in
system packages and language dependencies. The scan runs against the built image, not
against a manifest.

## Least privilege

Three database roles exist:

1. `app_rw`: the role the `api` and `worker` processes run as.
   - SELECT, INSERT, UPDATE on mutable tables (`workflow_runs`, `steps`, `step_attempts`,
     `escalation_cases`, `documents`, `tasks_outbox`, `api_keys.last_used_at`, `sessions`).
   - SELECT on reference tables.
   - INSERT only on `audit_events` (no UPDATE, no DELETE).
   - No DDL. No `CREATE`, `ALTER`, or `DROP`.
2. `migrator`: the role the Alembic migration step runs as.
   - Full DDL on the app schema.
   - No runtime access; the app refuses to connect as migrator.
3. `app_audit_reader`: optional Phase 2 role for a compliance reviewer running ad-hoc
   verifier queries.
   - SELECT on `audit_events`, `workflow_runs`, `step_attempts`, `escalation_cases`.
   - No access to raw document bytes or api_keys.

Redis auth is required. The deployment sets `REDIS_URL` to include the password
(`redis://:password@host:port/0`). A Redis without a password fails the Phase 1
startup check in `ENV=staging` and `ENV=production`.

No shared credentials across environments. `staging` and `production` carry distinct
API keys, distinct DB credentials, distinct Redis credentials, distinct PII encryption keys,
and distinct API-key hash peppers. Reusing a credential across environments is a CI-detectable
check against a deployment manifest (Phase 2 infrastructure task).

## Explicitly NOT claimed

InsuranceOps AI does not claim any of the following certifications, attestations, accreditations,
or regulatory readiness states:

- **SOC 2 (Type I or Type II).** We do not claim a Service Organization Control 2 report.
  No independent auditor has evaluated the platform. The controls described here are a
  design posture, not an audited control framework.
- **HIPAA.** We do not claim Health Insurance Portability and Accountability Act compliance
  or readiness. We do not operate as a HIPAA Business Associate. If a deployment handles
  PHI, the operator is responsible for determining their own compliance obligations and
  configuring the platform accordingly; Phase 1 does not ship the controls required for
  HIPAA (BAA workflow, breach notification workflow, audit event classification aligned
  to the HIPAA rubric).
- **PCI-DSS.** We do not claim Payment Card Industry Data Security Standard compliance.
  The platform is not designed to process or store cardholder data. Storing PAN in
  InsuranceOps AI is out of scope; `financial_account` as a PII field class is intended
  for bank account numbers carried on claim documents for disbursement routing, not for
  card transactions.
- **ISO 27001 / ISO 27017 / ISO 27018.** We do not claim Information Security Management
  System certification under any ISO 27000-family standard.
- **GDPR DPA.** We do not claim General Data Protection Regulation readiness. We do not
  offer a standard Data Processing Addendum. Deployments that process EU personal data
  are the operator's responsibility to configure and contractually paper.
- **CCPA.** We do not claim California Consumer Privacy Act readiness.
- **FedRAMP, StateRAMP, IRAP, C5, ENS.** We do not claim any government-cloud readiness
  framework.
- **NIST SP 800-53 / 800-171 control baselines.** We do not claim adherence to any specific
  control baseline.

The design does not preclude any of these. The audit chain, role model, PII handling,
and supply-chain posture are compatible with compliance work. What Phase 1 specifically
does NOT do is claim the compliance itself.

Any marketing copy, README text, sales collateral, or external document that uses the
phrase "SOC 2 compliant", "HIPAA compliant", "HIPAA ready", "PCI-DSS compliant",
"ISO 27001 certified", "GDPR compliant", or equivalent is a bug that must be corrected.
This policy applies to phrasing that implies compliance through adjacency as well:
"built for regulated industries", "enterprise-grade compliance controls",
"audit-ready by design" are all forbidden unless they are specifically quoting this
section and the quote includes the explicit non-claim.

## Assumptions

This document assumes:

- TLS termination happens at the deployment-platform layer. The app relies on HTTPS
  but does not terminate it.
- The deployment platform provides a secret store with delivery as environment variables.
  The app reads env vars and does not read secrets from files or from a secret-store SDK
  at runtime.
- The Phase 1 deployment is single-tenant. The concept of tenant isolation is deferred
  to Phase 4+. Until then, every deployment serves one insurance operations organization.
- The PostgreSQL and Redis instances are inside the deployment's private network and
  are not directly reachable from the public internet.
- The physical host and the container runtime are operated by a party that has already
  satisfied their own security obligations for those layers.
- The operator class is a small, internal, authenticated user population (tens, not
  millions). Rate-limiting and abuse controls are designed for this shape and would
  need to be hardened for a public-facing deployment.
- Document upload volumes at Phase 1 are bounded by human operator action
  (tens per minute, not tens of thousands per minute). This bound is what permits the
  coarse per-key QPS cap to be a sufficient Phase 1 control.
- The deployment platform chosen in Phase 2 provides backup, restore, and WAL
  archiving for PostgreSQL.
- CI runs in an environment with network access to public package registries
  (COMMON_DEPENDENCIES or OPEN_INTERNET). The Phase 0 documentation workspace runs
  in INTEGRATIONS_ONLY and therefore does not run dependency installs or image builds;
  see [DEPLOYMENT_STRATEGY.md](./DEPLOYMENT_STRATEGY.md).

## Rejected alternatives

### JWT for API authentication

JWT was considered and rejected. The reasons:

- Verifying a JWT on every request requires either a shared secret or a public-key lookup,
  both of which are more operational surface than looking up an opaque token in a local
  database index. The index lookup is fast in Postgres for the Phase 1 traffic shape.
- JWT rotation requires a signing-key rotation workflow (the `kid` header and a key set),
  which is a separate operational surface to design, document, and test. An opaque token
  rotates by flipping `enabled` to `false`; that is the whole workflow.
- JWT revocation before expiry requires an additional allowlist or blocklist, which is
  equivalent to the opaque-token model we already have, minus the token signing.
- The common JWT pitfalls (`alg: none`, algorithm confusion, RS vs HS conflation,
  unrestricted audience, overly-long expiry, missing `exp` validation) are a library
  and review burden we do not need to take on for a system with a small, trusted client
  population.
- The common JWT claim to fame is decentralized verification, which is irrelevant when
  all API requests hit a single service talking to a single Postgres instance.

Opaque API keys stored as `sha256(pepper || token)` are simpler, easier to revoke, easier
to audit, and easier to reason about. We adopt them.

### Argon2id for API-key storage

Argon2id (and bcrypt, scrypt) are the right primitive for user passwords, which have
low entropy and need a KDF to raise the attacker's cost. An API key is a 256-bit random
value; the entropy is already at the storage ceiling. A slow KDF on every request is a
DoS-adjacent design choice with no gain. We use `sha256(pepper || token)`.

### Session tokens with server-side random IDs instead of opaque API keys

These are the same mechanism with different marketing. We are using opaque random values
stored as hashes. The naming (API key vs session token) tracks whether the client is a
machine (API key, long-lived, scoped) or a human (session token, short-lived, refreshable).
Both use the same storage discipline.

### A single "admin" superuser role

Rejected as inconsistent with the least-privilege posture. A superuser role in a workflow
orchestration platform is a blast radius larger than any single business action justifies.
Capabilities are granted explicitly per role.

### Storing PII unencrypted on the grounds that the DB is inside the VPC

Rejected. VPC boundaries are not a substitute for column-level encryption when the
threat model includes backup exfiltration and compromised DB credentials. The VPC is
a defense-in-depth layer, not the innermost layer.

### Regex-based PII redaction in logs

Rejected. Pattern-based PII detection is noisy at both ends: it catches numeric strings
that are not PII (ticket numbers, timestamps, IDs) and it misses PII that is not numeric
or is formatted unusually. A field-name-based redactor paired with a discipline of
binding structured fields (not string-formatting values into `event`) is more reliable.
The cost is discipline; the benefit is determinism.

### Shipping a built-in SIEM

Rejected. The platform emits structured logs and metrics in open formats
(JSON lines, Prometheus text). A SIEM is the deployment platform's concern,
and embedding one would bind the platform to a specific vendor choice.
