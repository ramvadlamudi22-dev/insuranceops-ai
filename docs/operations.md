# Operations Guide

This guide covers day-to-day operational tasks for InsuranceOps AI: queue management, audit verification, escalation handling, and incident response.

## opsctl CLI Reference

`opsctl` is the operator CLI tool located at `scripts/opsctl`. It requires `DATABASE_URL` and `REDIS_URL` to be set in the environment (or a `.env` file).

### Audit Commands

#### Verify a single workflow run

```bash
./scripts/opsctl audit verify --workflow-run-id <UUID>
```

Output on success:
```
PASS: All 7 events verified
```

Output on failure:
```
FAIL: Event at index 3 (seq_in_run=4): computed event_hash does not match stored value
  First mismatch at index: 3
```

Exit codes: `0` = valid, `1` = mismatch or error.

#### Batch verify terminal runs

```bash
# Verify 50 random completed runs
./scripts/opsctl audit verify-batch --sample-size 50 --state completed

# Verify all terminal runs (capped at 1000)
./scripts/opsctl audit verify-batch

# Verify only failed runs
./scripts/opsctl audit verify-batch --state failed
```

Output:
```
Summary: 50 passed, 0 failed, 50 total
```

### Queue DLQ Commands

#### Check DLQ depth

```bash
./scripts/opsctl queue dlq count
```

Output:
```
DLQ entries: 3
```

#### List DLQ entries

```bash
./scripts/opsctl queue dlq list
./scripts/opsctl queue dlq list --start 0 --count 10
```

Output:
```
DLQ entries (showing 0-2 of 3):
------------------------------------------------------------------------
  [0] workflow_run_id=abc-123... step=extract attempt=3
  [1] workflow_run_id=def-456... step=validate attempt=1
  [2] workflow_run_id=ghi-789... step=extract attempt=3
------------------------------------------------------------------------
Total: 3
```

#### Inspect a DLQ entry

```bash
./scripts/opsctl queue dlq inspect 0
```

Output (full JSON payload):
```json
{
  "workflow_run_id": "abc-123...",
  "step_id": "...",
  "step_attempt_id": "...",
  "step_name": "extract",
  "handler_name": "extract",
  "workflow_name": "claim_intake",
  "attempt_number": 3,
  "max_attempts": 3
}
```

#### Requeue a DLQ entry

```bash
./scripts/opsctl queue dlq requeue 0
```

Output:
```
Requeueing DLQ[0]: workflow_run_id=abc-123... step=extract
OK: Entry moved from DLQ to ready queue.
```

The task will be picked up by the next available worker and retried.

#### Drop a DLQ entry permanently

```bash
./scripts/opsctl queue dlq drop 0
```

Output:
```
Dropping DLQ[0]: workflow_run_id=abc-123... step=extract
OK: Entry permanently removed from DLQ.
```

Use this when the task is unrecoverable and the workflow run should remain in its current state.

## DLQ Recovery Workflow

When the `queue_depth{queue="dlq"}` metric is nonzero, follow this procedure:

### 1. Assess

```bash
./scripts/opsctl queue dlq count
./scripts/opsctl queue dlq list
```

### 2. Inspect each entry

```bash
./scripts/opsctl queue dlq inspect 0
```

Look at:
- `step_name` — which step failed
- `attempt_number` vs `max_attempts` — was it exhausted?
- `workflow_run_id` — check the workflow run state in the API

### 3. Check the workflow run state

```bash
curl -s http://localhost:8000/v1/workflow-runs/<workflow_run_id> \
  -H "Authorization: Bearer ${TOKEN}" | jq '.state'
```

### 4. Decide: requeue or drop

**Requeue** if:
- The root cause was transient (Redis blip, temporary DB load)
- The handler code has been fixed since the failure
- You want the step to retry from scratch

**Drop** if:
- The document is malformed and will never succeed
- The workflow run is already in a terminal state
- The task is a duplicate from a reaper race

### 5. Execute

```bash
# Requeue (task goes back to ready queue)
./scripts/opsctl queue dlq requeue 0

# Or drop permanently
./scripts/opsctl queue dlq drop 0
```

### 6. Verify recovery

```bash
# After requeueing, poll the workflow run
curl -s http://localhost:8000/v1/workflow-runs/<workflow_run_id> \
  -H "Authorization: Bearer ${TOKEN}" | jq '{state, current_step_id}'
```

## Audit Verification

### Scheduled verification

The worker process runs an automatic audit verifier every hour (configurable via `AUDIT_VERIFY_INTERVAL_S`). It samples 10 random terminal workflow runs and verifies their hash chains.

On mismatch:
- Logs at CRITICAL level: `audit_chain_mismatch`
- Increments `audit_chain_mismatches_total` metric

### On-demand verification

For incident response or periodic manual checks:

```bash
# Verify a specific run you're investigating
./scripts/opsctl audit verify --workflow-run-id <UUID>

# Sweep a larger sample
./scripts/opsctl audit verify-batch --sample-size 200

# Focus on recently completed runs
./scripts/opsctl audit verify-batch --sample-size 100 --state completed
```

### What a mismatch means

A chain mismatch indicates one of:
1. **Data corruption** — hardware or software fault modified a row
2. **Unauthorized modification** — someone bypassed the app and edited `audit_events` directly
3. **Application bug** — a code change altered the hash computation

**Response:**
1. Do NOT modify any data
2. Record the workflow_run_id and the mismatch index
3. Take a database backup immediately
4. Investigate the specific event at the reported index
5. Compare the stored `event_hash` with a recomputation from the row fields

## Escalation Management

### List open escalations

```bash
curl -s http://localhost:8000/v1/escalations?state=open \
  -H "Authorization: Bearer ${TOKEN}" | jq '.cases[] | {escalation_id, step_name: .reason_code, workflow_run_id}'
```

### Claim an escalation

```bash
curl -X POST http://localhost:8000/v1/escalations/<escalation_id>/claim \
  -H "Authorization: Bearer ${TOKEN}"
```

### Resolve an escalation (approve)

```bash
curl -X POST http://localhost:8000/v1/escalations/<escalation_id>/resolve \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"approve": true, "notes": "Reviewed and approved"}'
```

### Resolve an escalation (override)

```bash
curl -X POST http://localhost:8000/v1/escalations/<escalation_id>/resolve \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"override": {"policy_number": "POL-CORRECTED-123"}, "notes": "Corrected policy number"}'
```

### Reject an escalation

```bash
curl -X POST http://localhost:8000/v1/escalations/<escalation_id>/reject \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"reason_code": "INVALID_DOCUMENT", "notes": "Document is not a valid claim"}'
```

Rejection transitions the workflow run to `failed`.

## Workflow Cancellation

Supervisors can cancel running or awaiting_human workflows:

```bash
curl -X POST http://localhost:8000/v1/workflow-runs/<run_id>/cancel \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Duplicate submission", "notes": "Original processed under RUN-xyz"}'
```

## Backup Operations

```bash
# Take a backup
./scripts/backup_postgres.sh

# Verify a backup without restoring to production
./scripts/restore_postgres.sh --verify-only backups/insuranceops_YYYYMMDD_HHMMSS.sql.gz

# Restore drill (to a separate database)
./scripts/restore_postgres.sh --target-db insuranceops_drill backups/latest.sql.gz
```

See [ops/runbooks/backup_restore.md](../ops/runbooks/backup_restore.md) for the full procedure.

## Monitoring Quick Reference

### Key alerts to configure

| Condition | Metric | Threshold |
|-----------|--------|-----------|
| DLQ non-empty | `queue_depth{queue="dlq"} > 0` | Any sustained nonzero |
| Audit chain broken | `audit_chain_mismatches_total > 0` | Any nonzero (page immediately) |
| API error rate | `rate(api_requests_total{status=~"5.."}[5m])` | Sustained above baseline |
| Workflow failure spike | `rate(workflow_runs_completed_total{terminal_state="failed"}[5m])` | Spike above normal |
| Rate limiting active | `rate(rate_limit_exceeded_total[5m]) > 0` | Sustained (may indicate abuse) |
| Reaper reclaiming | `rate(queue_reaper_reclaimed_total[5m]) > 0` | Sustained (worker health issue) |

### Health check endpoints

```bash
# Liveness (is the process alive?)
curl http://localhost:8000/healthz

# Readiness (can it serve traffic?)
curl http://localhost:8000/readyz

# Metrics (Prometheus scrape target)
curl http://localhost:8000/metrics
```

## Local Development

### Run CI checks locally

```bash
# Lint
ruff check src/ tests/

# Format check
ruff format --check src/ tests/

# Type check
mypy src/ --ignore-missing-imports

# Tests (requires running Postgres + Redis via compose)
pytest tests/ -v --tb=short
```

### Start/stop the development stack

```bash
# Start
docker compose -f compose/compose.yml up -d

# Stop
docker compose -f compose/compose.yml down

# Stop and remove volumes (clean slate)
docker compose -f compose/compose.yml down -v
```
