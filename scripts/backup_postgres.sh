#!/usr/bin/env bash
# backup_postgres.sh - Create a compressed Postgres dump of the insuranceops database.
#
# Usage:
#   ./scripts/backup_postgres.sh [--compose-file path/to/compose.yml]
#
# Output:
#   Creates backups/insuranceops_YYYYMMDD_HHMMSS.sql.gz in the repository root.
#   Exits 0 on success, 1 on failure.
#
# Environment:
#   COMPOSE_FILE  - Override compose file path (default: compose/compose.yml)
#   BACKUP_DIR    - Override backup output directory (default: ./backups)
#   PG_SERVICE    - Override postgres service name (default: postgres)
#   PG_USER       - Override postgres user (default: postgres)
#   PG_DB         - Override database name (default: insuranceops)

set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-compose/compose.yml}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
PG_SERVICE="${PG_SERVICE:-postgres}"
PG_USER="${PG_USER:-postgres}"
PG_DB="${PG_DB:-insuranceops}"

TIMESTAMP="$(date -u +%Y%m%d_%H%M%S)"
FILENAME="insuranceops_${TIMESTAMP}.sql.gz"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --compose-file)
            COMPOSE_FILE="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# Validate compose file exists
if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "ERROR: Compose file not found: $COMPOSE_FILE" >&2
    exit 1
fi

# Create backup directory
mkdir -p "$BACKUP_DIR"

BACKUP_PATH="${BACKUP_DIR}/${FILENAME}"

echo "Starting backup..."
echo "  Compose file: $COMPOSE_FILE"
echo "  Database:     $PG_DB"
echo "  Output:       $BACKUP_PATH"
echo "  Timestamp:    $TIMESTAMP (UTC)"

# Run pg_dump inside the postgres container, pipe through gzip
docker compose -f "$COMPOSE_FILE" exec -T "$PG_SERVICE" \
    pg_dump -U "$PG_USER" -d "$PG_DB" --no-owner --no-acl \
    | gzip > "$BACKUP_PATH"

# Verify the output file
if [[ ! -s "$BACKUP_PATH" ]]; then
    echo "ERROR: Backup file is empty or was not created: $BACKUP_PATH" >&2
    rm -f "$BACKUP_PATH"
    exit 1
fi

# Verify gzip integrity
if ! gzip -t "$BACKUP_PATH" 2>/dev/null; then
    echo "ERROR: Backup file failed gzip integrity check: $BACKUP_PATH" >&2
    exit 1
fi

FILE_SIZE="$(du -h "$BACKUP_PATH" | cut -f1)"
echo "Backup complete: $BACKUP_PATH ($FILE_SIZE)"
exit 0
