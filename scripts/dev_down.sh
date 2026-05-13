#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
docker compose -f "$PROJECT_ROOT/compose/compose.yml" down -v
echo "All services stopped and volumes removed."
