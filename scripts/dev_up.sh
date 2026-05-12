#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
docker compose -f "$PROJECT_ROOT/compose/compose.yml" up -d
echo "Waiting for services to be healthy..."
docker compose -f "$PROJECT_ROOT/compose/compose.yml" ps
echo "Services are up. API available at http://localhost:8000"
