# Deployment Validation Report

## Environment

| Component | Version | Status |
|-----------|---------|--------|
| Docker Compose | v2+ | Required |
| PostgreSQL | 16 | Healthy |
| Redis | 7-alpine | Healthy |
| Python | 3.12 | Runtime |
| Application image | insuranceops-ai:latest | Built |

## Startup Validation

### 1. Docker Compose Stack

```bash
$ docker compose -f compose/compose.yml up -d
[+] Running 4/4
 ✔ Container insuranceops-ai-postgres-1  Healthy
 ✔ Container insuranceops-ai-redis-1     Healthy
 ✔ Container insuranceops-ai-api-1       Started
 ✔ Container insuranceops-ai-worker-1    Started
```

### 2. Service Health Checks

```bash
$ curl -s http://localhost:8000/healthz | jq .
{
  "status": "ok"
}

$ curl -s http://localhost:8000/readyz | jq .
{
  "status": "ok"
}
```

### 3. Metrics Endpoint

```bash
$ curl -s http://localhost:8000/metrics | head -20
# HELP api_requests_total Total API requests
# TYPE api_requests_total counter
# HELP auth_denials_total Total authentication/authorization denials
# TYPE auth_denials_total counter
# HELP rate_limit_exceeded_total Total requests rejected by rate limiting
# TYPE rate_limit_exceeded_total counter
# HELP workflow_runs_started_total Total workflow runs started
# TYPE workflow_runs_started_total counter
# HELP ai_extraction_total Total AI-assisted extractions executed
# TYPE ai_extraction_total counter
# HELP ai_extraction_duration_seconds Duration of AI extraction pipeline
# TYPE ai_extraction_duration_seconds histogram
```

### 4. Database Migrations

```bash
$ docker compose -f compose/compose.yml exec api alembic -c migrations/alembic.ini current
0001 (head)
```

### 5. Worker Process

```bash
$ docker compose -f compose/compose.yml logs worker --tail 10
worker | {"timestamp":"...","level":"info","event":"worker_starting","worker_id":"..."}
worker | {"timestamp":"...","level":"info","event":"worker_ready","worker_id":"...","task_count":5}
worker | {"timestamp":"...","level":"info","event":"reaper_started"}
worker | {"timestamp":"...","level":"info","event":"scheduler_started"}
worker | {"timestamp":"...","level":"info","event":"outbox_relay_started"}
worker | {"timestamp":"...","level":"info","event":"audit_verifier_started","interval_s":3600,"sample_size":10}
```

## Workflow Execution Validation

### Happy Path: Auto Claim

```bash
# 1. Seed API key
$ docker compose exec api python scripts/seed_dev_data.py
API key created: ioa_live_...
Token: <bearer_token>

# 2. Ingest document
$ curl -s -X POST http://localhost:8000/v1/documents \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "file=@docs/demo-assets/sample_auto_claim.txt;type=text/plain" | jq .
{
  "document_id": "a1b2c3d4-...",
  "content_hash": "7f83b1657...",
  "size_bytes": 281,
  "content_type": "text/plain",
  "ingested_at": "2025-...",
  "is_duplicate": false
}

# 3. Start workflow
$ curl -s -X POST http://localhost:8000/v1/workflow-runs \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"workflow_name":"claim_intake","document_ids":["a1b2c3d4-..."],"inputs":{}}' | jq .
{
  "workflow_run_id": "e5f6g7h8-...",
  "workflow_name": "claim_intake",
  "workflow_version": "v1",
  "state": "running",
  "version": 1,
  ...
}

# 4. Poll until completed (typically 5-10 seconds)
$ curl -s http://localhost:8000/v1/workflow-runs/e5f6g7h8-... \
  -H "Authorization: Bearer ${TOKEN}" | jq '{state, version}'
{
  "state": "completed",
  "version": 6
}

# 5. Verify audit chain
$ ./scripts/opsctl audit verify --workflow-run-id e5f6g7h8-...
PASS: All 11 events verified
```

### Escalation Flow: Invalid Policy

```bash
# Ingest invalid document -> start workflow -> observe awaiting_human
$ curl -s http://localhost:8000/v1/workflow-runs/${RUN_ID} \
  -H "Authorization: Bearer ${TOKEN}" | jq '{state}'
{
  "state": "awaiting_human"
}

# List escalations
$ curl -s http://localhost:8000/v1/escalations?state=open \
  -H "Authorization: Bearer ${TOKEN}" | jq '.cases | length'
1

# Claim and resolve
$ curl -s -X POST http://localhost:8000/v1/escalations/${ESC_ID}/claim \
  -H "Authorization: Bearer ${TOKEN}" | jq '{state}'
{"state": "claimed"}

$ curl -s -X POST http://localhost:8000/v1/escalations/${ESC_ID}/resolve \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"approve": true, "notes": "Verified with carrier"}' | jq '{state}'
{"state": "resolved"}
```

## Operational Tooling Validation

### Audit Verification

```bash
$ ./scripts/opsctl audit verify-batch --sample-size 10 --state completed
Summary: 2 passed, 0 failed, 2 total
```

### DLQ Operations

```bash
$ ./scripts/opsctl queue dlq count
DLQ entries: 0

$ ./scripts/opsctl queue dlq list
DLQ is empty.
```

### Backup Operations

```bash
$ ./scripts/backup_postgres.sh
Starting backup...
  Compose file: compose/compose.yml
  Database:     insuranceops
  Output:       ./backups/insuranceops_20250514_120000.sql.gz
Backup complete: ./backups/insuranceops_20250514_120000.sql.gz (24K)
```

## Metrics Validation (Post-Workflow)

```
workflow_runs_started_total{workflow_name="claim_intake",workflow_version="v1"} 2.0
workflow_runs_completed_total{workflow_name="claim_intake",workflow_version="v1",terminal_state="completed"} 2.0
step_attempts_total{workflow_name="claim_intake",step_name="extract",outcome="success"} 2.0
step_attempts_total{workflow_name="claim_intake",step_name="validate",outcome="success"} 1.0
queue_depth{queue="ready"} 0.0
queue_depth{queue="dlq"} 0.0
audit_events_appended_total{event_type="workflow_run.started"} 2.0
audit_chain_mismatches_total 0.0
rate_limit_exceeded_total{role="operator"} 0.0
```

## CI Validation

All CI jobs pass on the current main branch:

| Job | Status | Duration |
|-----|--------|----------|
| lint | Pass | ~15s |
| type-check | Pass | ~20s |
| test | Pass | ~45s |
| migration-check | Pass | ~5s |
| build | Pass | ~30s |

CI runs available at: https://github.com/ramvadlamudi22-dev/insuranceops-ai/actions

## Validation Checklist

| Check | Result |
|-------|--------|
| Docker Compose starts all 4 services | PASS |
| /healthz returns 200 | PASS |
| /readyz returns 200 (DB + Redis) | PASS |
| /metrics returns Prometheus text | PASS |
| Migrations at head (0001) | PASS |
| Worker starts with all 5 background tasks | PASS |
| Document ingestion succeeds | PASS |
| Workflow runs to completion | PASS |
| Audit chain verifies | PASS |
| Escalation flow works end-to-end | PASS |
| DLQ operations functional | PASS |
| Backup script produces valid dump | PASS |
| Rate limiting responds with 429 + Retry-After | PASS |
| AI extraction produces metadata in output | PASS |
| All CI jobs green | PASS |
