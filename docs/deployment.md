# Deployment Guide

This guide covers deploying InsuranceOps AI from a fresh host to a running production-like stack.

## Deployment Unit

InsuranceOps AI ships as a single Docker image (`insuranceops-ai`) with two process types:

| Process | Command | Ports | Purpose |
|---------|---------|-------|---------|
| API | `uvicorn insuranceops.api.app:app` (default) | 8000 | FastAPI control plane |
| Worker | `python -m insuranceops.workers.main` | None | Task processing, reaper, scheduler, outbox relay, audit verifier |

Both share the same image and codebase. Process selection is via the container command.

## Infrastructure Requirements

| Component | Version | Purpose |
|-----------|---------|---------|
| PostgreSQL | 16+ | Source of truth for all durable state |
| Redis | 7+ | Task queue, coordination, rate-limit counters |
| Docker + Compose | v2+ | Container orchestration |

Redis must be configured with `maxmemory-policy=noeviction`. Silent eviction of queue entries would violate platform invariants.

## Quick Deploy (Docker Compose)

```bash
# Clone the repository
git clone https://github.com/ramvadlamudi22-dev/insuranceops-ai.git
cd insuranceops-ai

# Build the image
docker build -t insuranceops-ai:latest -f docker/Dockerfile .

# Start the stack
docker compose -f compose/compose.yml up -d

# Run database migrations
docker compose -f compose/compose.yml exec api \
  alembic -c migrations/alembic.ini upgrade head

# Verify readiness
curl http://localhost:8000/readyz
```

## Configuration

All configuration is via environment variables. See [`.env.example`](../.env.example) for the complete list.

### Required Variables

| Variable | Example | Notes |
|----------|---------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host:5432/db` | Async driver required |
| `REDIS_URL` | `redis://:password@host:6379/0` | Password required in staging/production |
| `API_KEY_HASH_PEPPER` | 32+ byte random string | Generate with `secrets.token_urlsafe(32)` |
| `ENV` | `local`, `staging`, `production` | Controls log format and safety checks |

### Optional Variables (with defaults)

| Variable | Default | Notes |
|----------|---------|-------|
| `LOG_LEVEL` | `INFO` | Set to `DEBUG` for incident investigation |
| `MAX_REQUEST_BYTES` | `20971520` (20 MiB) | Document upload size cap |
| `WORKER_VISIBILITY_TIMEOUT_S` | `60` | Seconds before reaper reclaims stuck tasks |
| `RATE_LIMIT_ENABLED` | `true` | Kill switch for rate limiting |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Fixed-window duration |
| `RATE_LIMIT_OPERATOR_MAX` | `1200` | Requests per window for operator/supervisor |
| `RATE_LIMIT_VIEWER_MAX` | `600` | Requests per window for viewer |
| `AUDIT_VERIFY_INTERVAL_S` | `3600` | Seconds between audit chain verification cycles |
| `AUDIT_VERIFY_SAMPLE_SIZE` | `10` | Terminal runs verified per cycle |

## Database Migrations

Migrations run as a separate step, never on application startup:

```bash
# Run migrations (uses the migrator role with DDL privileges)
docker compose -f compose/compose.yml exec api \
  alembic -c migrations/alembic.ini upgrade head

# Check current revision
docker compose -f compose/compose.yml exec api \
  alembic -c migrations/alembic.ini current
```

**Migration safety rules:**
- Additive changes only (new nullable columns, new tables, new indexes with CONCURRENTLY)
- Destructive changes follow expand-migrate-contract (separate PRs)
- CI runs `scripts/check_migrations.py` to flag unsafe patterns

## Startup Verification Checklist

After deployment, confirm each item:

| Check | Command | Expected |
|-------|---------|----------|
| API liveness | `curl http://HOST:8000/healthz` | `{"status":"ok"}` |
| API readiness | `curl http://HOST:8000/readyz` | `{"status":"ok"}` (DB + Redis reachable) |
| Metrics endpoint | `curl http://HOST:8000/metrics` | Prometheus text output |
| Worker running | `docker compose logs worker --tail 20` | `worker_ready` log line |
| Migrations at head | `alembic current` | Shows latest revision |
| Outbox draining | Watch `outbox_drain_lag_seconds` metric | Near zero |

## Operational Verification Checklist

Run after the first deployment and after major upgrades:

```bash
# 1. Create a test API key
docker compose -f compose/compose.yml exec api python scripts/seed_dev_data.py

# 2. Ingest a test document
curl -X POST http://localhost:8000/v1/documents \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "file=@-;filename=test.txt;type=text/plain" <<< "Claim Number: CLM-TEST-001"

# 3. Start a workflow run
curl -X POST http://localhost:8000/v1/workflow-runs \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"workflow_name":"claim_intake","document_ids":["<doc_id>"],"inputs":{}}'

# 4. Poll until terminal state
# 5. Verify audit chain
./scripts/opsctl audit verify --workflow-run-id <run_id>

# Or run the full verification script:
./scripts/verify_phase1.sh
```

## Backup and Restore

See [ops/runbooks/backup_restore.md](../ops/runbooks/backup_restore.md) for:
- Nightly `pg_dump` configuration
- Restore procedures
- Restore drill process
- RTO/RPO targets

**Key points:**
- PostgreSQL is the only component that requires backup
- Redis is NOT backed up (reconstructed from outbox on recovery)
- Document payload volume requires separate backup

## Scaling

The scaling sequence (from DEPLOYMENT_STRATEGY.md):

1. **Vertical** — larger host (handles first order of magnitude)
2. **Split Postgres** — dedicated database host
3. **Split Redis** — dedicated cache host
4. **Split API/Worker** — separate hosts, same image
5. **Read replicas** — for heavy read endpoints

No Kubernetes, no sharding, no multi-region at this stage.

## Troubleshooting

### API returns 503 on all requests

**Cause:** Database or Redis unreachable.

```bash
# Check database connectivity
docker compose -f compose/compose.yml exec postgres pg_isready

# Check Redis connectivity
docker compose -f compose/compose.yml exec redis redis-cli ping

# Check readyz for specific failures
curl http://localhost:8000/readyz
```

### Worker not processing tasks

**Cause:** Worker not running, or outbox relay not draining.

```bash
# Check worker logs
docker compose -f compose/compose.yml logs worker --tail 50

# Check outbox for pending entries
docker compose -f compose/compose.yml exec postgres \
  psql -U postgres -d insuranceops -c "SELECT count(*) FROM tasks_outbox WHERE enqueued_at IS NULL;"

# Check Redis queue depth
docker compose -f compose/compose.yml exec redis redis-cli LLEN queue:tasks:ready
```

### Workflow runs stuck in "running" state

**Cause:** Worker crashed mid-task; waiting for reaper.

```bash
# Check inflight tasks
docker compose -f compose/compose.yml exec redis \
  redis-cli KEYS "queue:tasks:inflight:*"

# Force reaper cycle (restart worker)
docker compose -f compose/compose.yml restart worker
```

### Rate limiting triggered unexpectedly

**Cause:** Legitimate traffic exceeding defaults.

```bash
# Check current rate-limit state
docker compose -f compose/compose.yml exec redis \
  redis-cli KEYS "rate:api_key:*"

# Temporarily disable
# Set RATE_LIMIT_ENABLED=false and restart API

# Adjust limits
# Set RATE_LIMIT_OPERATOR_MAX to a higher value
```

### Audit chain mismatch detected

**Cause:** Data corruption or unauthorized modification.

```bash
# Verify the specific run
./scripts/opsctl audit verify --workflow-run-id <run_id>

# Run batch verification
./scripts/opsctl audit verify-batch --sample-size 100

# Check the metric
curl -s http://localhost:8000/metrics | grep audit_chain_mismatches
```

This is a high-severity event. See [ops/runbooks/backup_restore.md](../ops/runbooks/backup_restore.md) for incident response.

## Monitoring

The platform exposes Prometheus metrics on `GET /metrics`:

| Category | Key Metrics |
|----------|-------------|
| API | `api_requests_total`, `api_request_duration_seconds` |
| Auth | `auth_denials_total`, `rate_limit_exceeded_total` |
| Workflows | `workflow_runs_started_total`, `workflow_runs_completed_total` |
| Steps | `step_attempts_total`, `step_attempt_duration_seconds` |
| Queue | `queue_depth`, `queue_reaper_reclaimed_total` |
| Audit | `audit_events_appended_total`, `audit_chain_mismatches_total` |

Scrape interval: 15 seconds recommended.

## Security Notes

- API keys are stored as `sha256(pepper || token)` — plaintext visible only at creation
- The `audit_events` table is append-only (app role has INSERT + SELECT only)
- PII fields are redacted in structured logs via the `redact_pii` processor
- Rate limiting is per-API-key with role-differentiated caps
- TLS termination is the deployment platform's responsibility
