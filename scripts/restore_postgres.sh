#!/usr/bin/env bash
# restore_postgres.sh - Restore a Postgres dump to the insuranceops database.
#
# Usage:
#   ./scripts/restore_postgres.sh <backup_file.sql.gz>
#   ./scripts/restore_postgres.sh --target-db <dbname> <backup_file.sql.gz>
#   ./scripts/restore_postgres.sh --verify-only <backup_file.sql.gz>
#
# Modes:
#   Default:       Restores to the primary database (insuranceops). DESTRUCTIVE.
#   --target-db:   Restores to a named database (created if not exists). Non-destructive to primary.
#   --verify-only: Restores to a temporary database, prints row counts, then drops it.
#
# Environment:
#   COMPOSE_FILE  - Override compose file path (default: compose/compose.yml)
#   PG_SERVICE    - Override postgres service name (default: postgres)
#   PG_USER       - Override postgres user (default: postgres)
#   PG_DB         - Override primary database name (default: insuranceops)

set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-compose/compose.yml}"
PG_SERVICE="${PG_SERVICE:-postgres}"
PG_USER="${PG_USER:-postgres}"
PG_DB="${PG_DB:-insuranceops}"

TARGET_DB=""
VERIFY_ONLY=false
BACKUP_FILE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target-db)
            TARGET_DB="$2"
            shift 2
            ;;
        --verify-only)
            VERIFY_ONLY=true
            shift
            ;;
        --compose-file)
            COMPOSE_FILE="$2"
            shift 2
            ;;
        -*)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
        *)
            BACKUP_FILE="$1"
            shift
            ;;
    esac
done

# Validate inputs
if [[ -z "$BACKUP_FILE" ]]; then
    echo "Usage: $0 [--target-db <dbname>] [--verify-only] <backup_file.sql.gz>" >&2
    exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "ERROR: Backup file not found: $BACKUP_FILE" >&2
    exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "ERROR: Compose file not found: $COMPOSE_FILE" >&2
    exit 1
fi

# Verify gzip integrity first
echo "Verifying backup file integrity..."
if ! gzip -t "$BACKUP_FILE" 2>/dev/null; then
    echo "ERROR: Backup file failed gzip integrity check: $BACKUP_FILE" >&2
    exit 1
fi
echo "  File integrity: OK"

# Helper: run psql in the postgres container
psql_exec() {
    docker compose -f "$COMPOSE_FILE" exec -T "$PG_SERVICE" psql -U "$PG_USER" "$@"
}

# Helper: print row counts for a database
print_row_counts() {
    local db="$1"
    echo ""
    echo "Row counts for database: $db"
    echo "─────────────────────────────────────"
    psql_exec -d "$db" -c "
        SELECT 'workflow_runs' AS table_name, count(*) AS row_count FROM workflow_runs
        UNION ALL SELECT 'steps', count(*) FROM steps
        UNION ALL SELECT 'step_attempts', count(*) FROM step_attempts
        UNION ALL SELECT 'audit_events', count(*) FROM audit_events
        UNION ALL SELECT 'documents', count(*) FROM documents
        UNION ALL SELECT 'escalation_cases', count(*) FROM escalation_cases
        UNION ALL SELECT 'api_keys', count(*) FROM api_keys
        UNION ALL SELECT 'tasks_outbox', count(*) FROM tasks_outbox
        ORDER BY table_name;
    "
}

# Determine target database
if [[ "$VERIFY_ONLY" == "true" ]]; then
    TARGET_DB="insuranceops_verify_$(date -u +%s)"
    echo "Verify-only mode: restoring to temporary database '$TARGET_DB'"
elif [[ -n "$TARGET_DB" ]]; then
    echo "Restoring to target database: $TARGET_DB"
else
    TARGET_DB="$PG_DB"
    echo ""
    echo "WARNING: This will REPLACE ALL DATA in the '$PG_DB' database."
    echo "Press Ctrl+C within 5 seconds to abort..."
    sleep 5
    echo "Proceeding with restore."
fi

# Create target database if it doesn't exist (and it's not the primary)
if [[ "$TARGET_DB" != "$PG_DB" ]]; then
    echo "Creating database '$TARGET_DB'..."
    psql_exec -d postgres -c "DROP DATABASE IF EXISTS \"$TARGET_DB\";" 2>/dev/null || true
    psql_exec -d postgres -c "CREATE DATABASE \"$TARGET_DB\";"
fi

# Restore the dump
echo "Restoring backup to '$TARGET_DB'..."
gunzip -c "$BACKUP_FILE" | psql_exec -d "$TARGET_DB" --quiet --single-transaction 2>&1 | tail -5

echo "Restore complete."

# Print row counts
print_row_counts "$TARGET_DB"

# If verify-only, drop the temporary database
if [[ "$VERIFY_ONLY" == "true" ]]; then
    echo ""
    echo "Dropping temporary database '$TARGET_DB'..."
    psql_exec -d postgres -c "DROP DATABASE IF EXISTS \"$TARGET_DB\";"
    echo "Verification complete. Temporary database removed."
fi

exit 0
