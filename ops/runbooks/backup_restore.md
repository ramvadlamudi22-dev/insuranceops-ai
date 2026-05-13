# Backup and Restore Runbook

Last verified: N/A (execute drill and record date here)

## Overview

PostgreSQL is the sole durable source of truth for InsuranceOps AI. Every WorkflowRun, Step, StepAttempt, EscalationCase, AuditEvent, Document metadata, and API key lives in Postgres. A complete Postgres backup is a complete platform backup.

Redis is a non-durable coordination layer (task queue, locks, rate counters). Redis is explicitly NOT backed up. A Redis loss is recovered by restarting Redis and letting the outbox relay repopulate the queue from committed `tasks_outbox` rows. No committed state is lost.

Document payload bytes live on the filesystem volume mounted at `PAYLOAD_STORAGE_PATH`. Backup of this volume is addressed separately below.

## What is backed up

| Component | Backed up | Rationale |
|-----------|-----------|-----------|
| PostgreSQL (all tables) | Yes | Source of truth for all durable state |
| Document payload volume | Yes | Raw document bytes referenced by `documents.payload_ref` |
| Redis | No | Non-durable coordination; reconstructed from Postgres on recovery |
| Application containers | No | Rebuilt from the Docker image; stateless |

## Prerequisites

- Docker Compose stack is running (`docker compose -f compose/compose.yml ps` shows healthy services)
- `pg_dump` is available (ships inside the `postgres:16` container image)
- Sufficient disk space for the dump file (estimate: 2x current database size)
- Operator has shell access to the host running the Compose stack

## RTO/RPO Assumptions (Phase 1 single-host deployment)

| Metric | Target | Rationale |
|--------|--------|-----------|
| RPO (Recovery Point Objective) | Last nightly backup (up to 24 hours of data loss) | Nightly `pg_dump` schedule; WAL archiving is a Phase 2 enhancement |
| RTO (Recovery Time Objective) | Under 30 minutes | Restore from dump + restart services on the same host |

These targets assume:
- The host is recoverable (disk not physically destroyed)
- The backup file is on a separate volume or has been copied off-host
- No WAL-based point-in-time recovery at Phase 1

## Backup Procedures

### Manual backup

Run from the repository root:

```bash
./scripts/backup_postgres.sh
```

This produces a timestamped compressed dump at `./backups/insuranceops_YYYYMMDD_HHMMSS.sql.gz`.

### Automated nightly backup

Add a cron entry on the host running the Compose stack:

```cron
0 2 * * * /path/to/repo/scripts/backup_postgres.sh >> /var/log/insuranceops-backup.log 2>&1
```

This runs at 02:00 UTC daily. Adjust the path to match your deployment.

### Document payload volume backup

The document payload volume is mounted inside the `api` and `worker` containers at `PAYLOAD_STORAGE_PATH` (default: `/data/payloads`).

For the Docker named volume (`pgdata` equivalent for payloads), back up using:

```bash
# Identify the volume mount point on the host
docker volume inspect insuranceops-ai_pgdata --format '{{ .Mountpoint }}'

# For payload storage, if using a bind mount:
tar -czf backups/payloads_$(date -u +%Y%m%d_%H%M%S).tar.gz /path/to/payload/storage/
```

If using a Docker named volume for payloads, use `docker run --rm -v <volume>:/data alpine tar czf - /data > backups/payloads_backup.tar.gz`.

## Backup Verification

Every backup must be verified before it is trusted. An unverified backup is not a backup.

### Verify dump file integrity

```bash
# Check the file is non-empty and is valid gzip
gzip -t backups/insuranceops_*.sql.gz

# List tables in the dump without restoring
gunzip -c backups/insuranceops_YYYYMMDD_HHMMSS.sql.gz | grep "^CREATE TABLE" | sort
```

Expected tables (Phase 1):
- `api_keys`
- `audit_events`
- `documents`
- `escalation_cases`
- `step_attempts`
- `steps`
- `tasks_outbox`
- `users`
- `workflow_run_documents`
- `workflow_runs`

### Verify row counts (sanity check)

```bash
./scripts/restore_postgres.sh --verify-only backups/insuranceops_YYYYMMDD_HHMMSS.sql.gz
```

This restores to a temporary database, prints row counts per table, and drops the temporary database. No production data is affected.

## Restore Procedures

### Full restore to the running stack

**WARNING: This replaces all current data in the target database.**

1. Stop the API and worker containers (prevent writes during restore):
   ```bash
   docker compose -f compose/compose.yml stop api worker
   ```

2. Restore the backup:
   ```bash
   ./scripts/restore_postgres.sh backups/insuranceops_YYYYMMDD_HHMMSS.sql.gz
   ```

3. Restart all services:
   ```bash
   docker compose -f compose/compose.yml up -d
   ```

4. Verify health:
   ```bash
   curl http://localhost:8000/healthz
   curl http://localhost:8000/readyz
   ```

5. Verify audit chain integrity for a sample workflow run:
   ```bash
   # Pick a workflow_run_id from the restored data
   docker compose -f compose/compose.yml exec api python scripts/opsctl audit verify --workflow-run-id <UUID>
   ```

### Restore to a separate database (drill or investigation)

```bash
./scripts/restore_postgres.sh --target-db insuranceops_drill backups/insuranceops_YYYYMMDD_HHMMSS.sql.gz
```

This creates a new database `insuranceops_drill`, restores into it, and prints row counts. The production database is untouched.

## Restore Drill Procedure

The restore drill must be executed at least once before go-live and quarterly thereafter. Record each drill execution below.

### Steps

1. Take a fresh backup:
   ```bash
   ./scripts/backup_postgres.sh
   ```

2. Restore to a drill database:
   ```bash
   ./scripts/restore_postgres.sh --target-db insuranceops_drill backups/<latest>.sql.gz
   ```

3. Verify row counts match production:
   ```bash
   docker compose -f compose/compose.yml exec postgres psql -U postgres -d insuranceops -c "SELECT 'workflow_runs' as t, count(*) FROM workflow_runs UNION ALL SELECT 'audit_events', count(*) FROM audit_events UNION ALL SELECT 'documents', count(*) FROM documents;"
   ```
   Compare with the drill database output.

4. Verify audit chain on the drill database:
   ```bash
   DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/insuranceops_drill" python scripts/opsctl audit verify --workflow-run-id <UUID>
   ```

5. Drop the drill database:
   ```bash
   docker compose -f compose/compose.yml exec postgres psql -U postgres -c "DROP DATABASE IF EXISTS insuranceops_drill;"
   ```

6. Record result below.

### Drill Log

| Date | Operator | Backup file | Restore time | Row count match | Audit chain valid | Notes |
|------|----------|-------------|--------------|-----------------|-------------------|-------|
| _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | First drill |

## Redis Recovery (no backup needed)

If Redis data is lost (restart, crash, flush):

1. Restart Redis:
   ```bash
   docker compose -f compose/compose.yml restart redis
   ```

2. Restart workers (they will reconnect):
   ```bash
   docker compose -f compose/compose.yml restart worker
   ```

3. The outbox relay will re-drain any pending `tasks_outbox` rows into Redis.

4. Any in-flight tasks that were in Redis inflight lists are lost from Redis, but the corresponding StepAttempts in Postgres remain in `queued` or `in_progress` state. The reaper will detect these as stuck (past visibility timeout) and re-enqueue them.

5. No committed state is lost. Processing resumes within one reaper cycle (15 seconds default).

## Retention Policy

| Data | Retention | Mechanism |
|------|-----------|-----------|
| Backup dump files | 30 days | Manual cleanup or cron-based rotation |
| Payload volume snapshots | 30 days | Same as above |
| Audit events in database | 7 years | No automated purge at Phase 1 |
| Document payload bytes | 2 years | Phase 2 housekeeper job |

## Failure Scenarios

### Backup fails (disk full)

- Signal: backup script exits non-zero, log shows "No space left on device"
- Response: free disk space, re-run backup immediately
- Prevention: monitor disk usage; alert at 80% capacity

### Restore fails (corrupt dump)

- Signal: `pg_restore` or `psql` reports errors during restore
- Response: try the previous day's backup; investigate corruption cause
- Prevention: always run `gzip -t` on backup files after creation

### Host lost entirely

- Signal: host unreachable, all services down
- Response: provision new host, deploy from Docker image, restore from off-host backup copy
- Prevention: copy backup files to a separate host or object store nightly
- RTO impact: depends on new host provisioning time (not controlled by this platform)

## Explicit Non-Decisions (Phase 2+)

- **WAL archiving / point-in-time recovery**: Phase 2 adds continuous WAL shipping for RPO < 1 minute.
- **Automated off-host backup shipping**: Phase 2 copies dumps to object storage.
- **Managed Postgres (RDS, Cloud SQL)**: Phase 2 deployment platform decision.
- **Backup encryption at rest**: Phase 2 when the secret management platform is chosen.
