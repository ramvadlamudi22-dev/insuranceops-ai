# TERMINOLOGY.md

## Purpose

This document is the canonical terminology reference for InsuranceOps AI Phase 0.
It records every term, field name, metric name, and format convention
that was normalized during the Phase 0 semantic consistency pass.
When a reader encounters a term in any design document and wonders whether it is canonical,
this document is the lookup table.

If any other document uses a term that contradicts this document,
TERMINOLOGY.md is correct and the other document must be amended.

## API-Key Hashing

| Property | Canonical value |
| --- | --- |
| Storage scheme | `sha256(pepper \|\| token)` |
| Pepper source | Deployment-level env var `API_KEY_HASH_PEPPER` |
| Pepper scope | Per-deployment, not per-key |
| Rejected alternative | Argon2id (rejected because API keys are 256-bit random; a slow KDF adds no entropy while inflating per-request cost) |
| Authoritative document | SECURITY_REVIEW.md |

## AuditEvent Fields

The `audit_events` table uses the following canonical field names for chain integrity:

| Field | Type | Description |
| --- | --- | --- |
| `seq_in_run` | bigint | Monotonically increasing sequence number within a `workflow_run_id`. Starts at 1. |
| `prev_event_hash` | bytea (nullable) | SHA-256 of the prior event's `event_hash` for the same run. NULL for the first event. |
| `event_hash` | bytea | SHA-256 of the current row's canonical serialization (all columns except `event_hash` itself). |

Retired terms (do not use):
- `chain_position` - use `seq_in_run`
- `current_event_hash` - use `event_hash`

## First-Event Hash Convention

The first AuditEvent of a WorkflowRun has `prev_event_hash = NULL`.

When computing `event_hash`, the hash input substitutes empty bytes (`b''`)
for the absent `prev_event_hash`:

```
event_hash = sha256(
    audit_event_id || workflow_run_id || actor || event_type ||
    canonical_json(event_payload) || occurred_at_iso || b''
)
```

A 32-byte-zero sentinel is NOT used. The field is nullable, not sentinel-valued.

Authoritative document: SPEC.md, SYSTEM_ARCHITECTURE.md section 16.2.

## Replay Ordering

The canonical ordering for AuditEvent replay and timeline queries is:

```sql
ORDER BY occurred_at ASC, seq_in_run ASC
```

`seq_in_run` is the tiebreaker when multiple events share the same `occurred_at` microsecond.
`audit_event_id` is NOT used as a sort key for replay ordering.

Authoritative document: SYSTEM_ARCHITECTURE.md section 6.7 (unique index), OBSERVABILITY_STRATEGY.md (timeline query).

## MAX_REQUEST_BYTES

| Property | Canonical value |
| --- | --- |
| Default value | 20 MiB (20,971,520 bytes) |
| Enforcement point | FastAPI middleware layer |
| Exceeded response | HTTP 413 Payload Too Large |
| Configurable | Yes, via `MAX_REQUEST_BYTES` env var |
| Authoritative document | SECURITY_REVIEW.md (security controls are authoritative for size limits) |

## Prometheus Metrics

The canonical metric surface is defined in OBSERVABILITY_STRATEGY.md.
All other documents reference these names exactly.

### API surface

| Metric | Type | Labels |
| --- | --- | --- |
| `api_requests_total` | counter | `route`, `method`, `status` |
| `api_request_duration_seconds` | histogram | `route`, `method` |
| `auth_denials_total` | counter | `reason` |

### Workflow lifecycle

| Metric | Type | Labels |
| --- | --- | --- |
| `workflow_runs_started_total` | counter | `workflow_name`, `workflow_version` |
| `workflow_runs_completed_total` | counter | `workflow_name`, `workflow_version`, `terminal_state` |
| `workflow_run_duration_seconds` | histogram | `workflow_name`, `workflow_version`, `terminal_state` |
| `workflow_runs_running_total` | gauge | `workflow_name` |

### Step execution

| Metric | Type | Labels |
| --- | --- | --- |
| `step_attempts_total` | counter | `workflow_name`, `step_name`, `outcome` |
| `step_attempt_duration_seconds` | histogram | `workflow_name`, `step_name` |
| `step_attempt_retries_total` | counter | `workflow_name`, `step_name`, `reason` |
| `step_attempts_terminal_total` | counter | `workflow_name`, `step_name`, `reason` |

### Queue substrate

| Metric | Type | Labels |
| --- | --- | --- |
| `queue_depth` | gauge | `queue` (values: `ready`, `inflight`, `delayed`, `dlq`) |
| `queue_tasks_enqueued_total` | counter | `workflow_name`, `step_name` |
| `queue_tasks_acked_total` | counter | `workflow_name`, `step_name`, `outcome` |
| `queue_tasks_dlq_total` | counter | `workflow_name`, `step_name`, `reason` |
| `queue_reaper_reclaimed_total` | counter | (none) |

### Outbox

| Metric | Type | Labels |
| --- | --- | --- |
| `outbox_drain_lag_seconds` | histogram | (none) |
| `outbox_drain_batch_seconds` | histogram | (none) |

### Escalation

| Metric | Type | Labels |
| --- | --- | --- |
| `escalations_opened_total` | counter | `workflow_name`, `step_name` |
| `escalations_resolved_total` | counter | `workflow_name`, `resolution` |
| `escalation_open_age_seconds` | histogram | `workflow_name` |
| `escalations_claimed_expired_total` | counter | `workflow_name` |

### Audit

| Metric | Type | Labels |
| --- | --- | --- |
| `audit_events_appended_total` | counter | `event_type` |
| `audit_chain_mismatches_total` | counter | (none) |

### Resource and dependency health

| Metric | Type | Labels |
| --- | --- | --- |
| `db_pool_in_use` | gauge | `role` |
| `db_query_duration_seconds` | histogram | `operation` |
| `redis_pool_in_use` | gauge | (none) |
| `process_startup_ready_seconds` | histogram | `service` |

Retired metric names (do not use):
- `http_requests_total` - use `api_requests_total`
- `http_request_duration_seconds` - use `api_request_duration_seconds`
- `workflow_runs_total` - use `workflow_runs_started_total` / `workflow_runs_completed_total`
- `workflow_runs_failed_total` - use `workflow_runs_completed_total{terminal_state="failed"}`
- `escalations_open` - use `escalations_opened_total`
- `escalation_cases_total` - use `escalations_opened_total` / `escalations_resolved_total`
- `escalation_case_age_seconds` - use `escalation_open_age_seconds`
- `dlq_depth` - use `queue_depth{queue="dlq"}`
- `queue_reaper_recovered_total` - use `queue_reaper_reclaimed_total`

## UUID Versions

| Entity | UUID version | Rationale |
| --- | --- | --- |
| `document_id` | v4 | Random, no time-ordering requirement |
| `workflow_run_id` | v4 | Random, no time-ordering requirement |
| `step_id` | v4 | Random, no time-ordering requirement |
| `step_attempt_id` | v4 | Random, no time-ordering requirement |
| `escalation_id` | v4 | Random, no time-ordering requirement |
| `api_key_id` | v4 | Random, no time-ordering requirement |
| `user_id` | v4 | Random, no time-ordering requirement |
| `audit_event_id` | v7 | Time-sortable; enables efficient range queries on the append-only audit table |
| `request_id` | v7 | Time-sortable; log-line sort order matches creation order |
| `correlation_id` | v7 | Time-sortable; shared across API and worker for a logical operation |

Authoritative documents: SYSTEM_ARCHITECTURE.md section 5 (entity IDs), OBSERVABILITY_STRATEGY.md (operational IDs).

## reference_data_snapshot_id

| Property | Canonical value |
| --- | --- |
| Column location | `workflow_runs.reference_data_snapshot_id` |
| Type | uuid, nullable |
| Set at | WorkflowRun creation |
| Mutability | Immutable for the life of the run |
| Purpose | Pins the reference-data snapshot used by extractors and validators for this run, enabling deterministic replay |
| Authoritative document | SYSTEM_ARCHITECTURE.md sections 6.2 and 11.5 |

## Actor-String Format

The canonical Actor-string format is `<kind>:<subkind>:<id>`.

### Canonical actor kinds

| Kind | Pattern | Examples | Usage |
| --- | --- | --- | --- |
| `worker` | `worker:<subprocess>` | `worker:main`, `worker:reaper`, `worker:scheduler`, `worker:outbox_relay`, `worker:extractor` | Internal worker process identities |
| `api` | `api:<component>` | `api:control_plane` | Internal API process identity |
| `user` | `user:<role>:<user_id>` | `user:operator:42`, `user:supervisor:7` | Human users authenticated via session |
| `api_key` | `api_key:<role>:<api_key_id>` | `api_key:operator:a1b2c3d4`, `api_key:supervisor:e5f6g7h8` | Machine clients authenticated via API key |
| (literal) | `anonymous` | `anonymous` | Unauthenticated requests (`/healthz`, `/readyz`, `/metrics`, 401 responses) |

Retired actor formats (do not use):
- `service:<name>` - use `api_key:<role>:<id>` for machine clients, `worker:<name>` for internal processes
- `system:<name>` - use `worker:<name>` for system processes

Authoritative document: SYSTEM_ARCHITECTURE.md section 5.9, SPEC.md glossary.

## Phase 1 API Surface

The complete Phase 1 endpoint surface:

| Method | Path | Auth | Role | Purpose |
| --- | --- | --- | --- | --- |
| POST | `/v1/documents` | API key | operator, supervisor | Ingest a Document |
| GET | `/v1/documents/{document_id}/content` | API key | operator, supervisor | Fetch raw Document bytes |
| POST | `/v1/workflow-runs` | API key | operator, supervisor | Start a new WorkflowRun |
| POST | `/v1/workflow-runs/{workflow_run_id}/cancel` | API key | supervisor | Cancel a running or awaiting_human WorkflowRun |
| GET | `/v1/workflow-runs/{workflow_run_id}` | API key | operator, supervisor, viewer | Read WorkflowRun status |
| GET | `/v1/workflow-runs/{workflow_run_id}/events` | API key | operator, supervisor, viewer | Read AuditEvent timeline |
| GET | `/v1/escalations` | API key | operator, supervisor, viewer | List EscalationCases |
| POST | `/v1/escalations/{escalation_id}/claim` | API key | operator, supervisor | Claim an EscalationCase |
| POST | `/v1/escalations/{escalation_id}/resolve` | API key | operator, supervisor | Resolve a claimed case |
| POST | `/v1/escalations/{escalation_id}/reject` | API key | operator, supervisor | Reject a claimed case |
| GET | `/healthz` | none | public | Liveness probe |
| GET | `/readyz` | none | public | Readiness probe |
| GET | `/metrics` | none | public | Prometheus metrics |

Authoritative document: SYSTEM_ARCHITECTURE.md section 17.1.

## Normalization Summary

The following 11 cross-document drifts were resolved in this normalization pass:

| # | Drift | Resolution | Authority |
| --- | --- | --- | --- |
| 1 | API-key hashing: Argon2id vs sha256 | Normalized to `sha256(pepper \|\| token)` | SECURITY_REVIEW.md |
| 2 | AuditEvent field names: chain_position/current_event_hash vs seq_in_run/event_hash | Normalized to `seq_in_run` + `event_hash` | SYSTEM_ARCHITECTURE.md |
| 3 | First-event hash: 32-byte-zero sentinel vs NULL | Normalized to `prev_event_hash = NULL` | SPEC.md, SYSTEM_ARCHITECTURE.md |
| 4 | Replay ordering: by audit_event_id vs (occurred_at, seq_in_run) | Normalized to `(occurred_at, seq_in_run)` | SYSTEM_ARCHITECTURE.md |
| 5 | MAX_REQUEST_BYTES: 20 MiB vs 25 MiB | Normalized to 20 MiB (20,971,520 bytes) | SECURITY_REVIEW.md |
| 6 | Prometheus metric names: multiple naming conventions | Normalized to OBSERVABILITY_STRATEGY baseline | OBSERVABILITY_STRATEGY.md |
| 7 | RISK_ANALYSIS metrics not in OBSERVABILITY baseline | Added missing metrics to OBSERVABILITY_STRATEGY | OBSERVABILITY_STRATEGY.md |
| 8 | UUID version: v4 vs v7 for entity IDs | v4 for entities, v7 for time-sortable operational IDs | SYSTEM_ARCHITECTURE.md |
| 9 | reference_data_snapshot_id missing from schema | Added to `workflow_runs` table | SYSTEM_ARCHITECTURE.md |
| 10 | Actor-string format: 4 different shapes | Normalized to `<kind>:<subkind>:<id>` | SYSTEM_ARCHITECTURE.md |
| 11 | Missing API endpoints: cancel and document-bytes-fetch | Added to Phase 1 surface | SYSTEM_ARCHITECTURE.md |

## Assumptions

- This document is produced once during Phase 0 normalization and maintained alongside the design documents.
- Adding a new term to this document requires updating every design document that references the old term.
- SPEC.md remains the ultimate tie-breaker if TERMINOLOGY.md and SPEC.md ever disagree on a glossary definition.
  TERMINOLOGY.md extends SPEC.md for the specific areas of terminology drift; it does not replace it.
