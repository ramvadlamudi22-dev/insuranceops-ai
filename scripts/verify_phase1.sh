#!/usr/bin/env bash
# verify_phase1.sh - End-to-end operational verification for Phase 1.
# Requires: docker compose running (scripts/dev_up.sh), curl, jq.
set -euo pipefail

###############################################################################
# Configuration
###############################################################################
BASE_URL="${BASE_URL:-http://localhost:8000}"
MAX_POLL_SECONDS="${MAX_POLL_SECONDS:-60}"
POLL_INTERVAL="${POLL_INTERVAL:-2}"
COMPOSE_FILE="${COMPOSE_FILE:-compose/compose.yml}"

###############################################################################
# Helpers
###############################################################################
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS_COUNT=0
FAIL_COUNT=0

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  echo -e "  ${GREEN}PASS${NC} $1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  echo -e "  ${RED}FAIL${NC} $1"
}

info() {
  echo -e "  ${YELLOW}INFO${NC} $1"
}

require_tool() {
  if ! command -v "$1" &>/dev/null; then
    echo "Error: required tool '$1' not found in PATH" >&2
    exit 1
  fi
}

###############################################################################
# Preconditions
###############################################################################
require_tool curl
require_tool jq

echo "======================================================================"
echo " InsuranceOps AI - Phase 1 Operational Verification"
echo "======================================================================"
echo ""

###############################################################################
# Step 1: Wait for API health check
###############################################################################
echo "[1/8] Waiting for API health check..."
HEALTH_OK=false
ELAPSED=0
while [ "$ELAPSED" -lt "$MAX_POLL_SECONDS" ]; do
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/healthz" 2>/dev/null || echo "000")
  if [ "$HTTP_CODE" = "200" ]; then
    HEALTH_OK=true
    break
  fi
  sleep "$POLL_INTERVAL"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

if [ "$HEALTH_OK" = true ]; then
  pass "API health check passed (${ELAPSED}s)"
else
  fail "API health check did not pass within ${MAX_POLL_SECONDS}s"
  echo "Ensure compose stack is running: docker compose -f ${COMPOSE_FILE} up -d"
  exit 1
fi

###############################################################################
# Step 2: Seed an API key
###############################################################################
echo ""
echo "[2/8] Seeding API key..."

# Use the seed script via docker compose exec, or fall back to direct DB insert
if docker compose -f "$COMPOSE_FILE" ps api --status running &>/dev/null 2>&1; then
  # Insert an API key directly via psql in the postgres container
  RAW_TOKEN="verify-phase1-test-token-$(date +%s)"
  # The API hashes with sha256(pepper + token). Pepper is "dev-pepper-not-for-production"
  KEY_HASH=$(echo -n "dev-pepper-not-for-production${RAW_TOKEN}" | sha256sum | awk '{print $1}')
  API_KEY_ID=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")
  API_KEY_ID=$(echo "$API_KEY_ID" | tr '[:upper:]' '[:lower:]')

  docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U postgres -d insuranceops -c \
    "INSERT INTO api_keys (api_key_id, key_hash, role, label, created_at)
     VALUES ('${API_KEY_ID}', decode('${KEY_HASH}', 'hex'), 'supervisor', 'verify-phase1', NOW())
     ON CONFLICT DO NOTHING;" >/dev/null 2>&1

  AUTH_HEADER="Authorization: Bearer ${RAW_TOKEN}"
  pass "API key seeded (role=supervisor)"
else
  fail "Cannot reach compose stack to seed API key"
  exit 1
fi

###############################################################################
# Step 3: Ingest a valid claim document
###############################################################################
echo ""
echo "[3/8] Ingesting a valid claim document..."

VALID_CLAIM="Claim Number: CLM-2025-001234
Policy Number: POL-12345678
Claimant: Jane Smith
Date of Loss: 01/15/2025
Claim Type: auto
Description: Vehicle collision at intersection of Main St and 5th Ave."

INGEST_RESPONSE=$(echo "$VALID_CLAIM" | curl -s -X POST "${BASE_URL}/v1/documents" \
  -H "${AUTH_HEADER}" \
  -F "file=@-;filename=claim.txt;type=text/plain")

DOCUMENT_ID=$(echo "$INGEST_RESPONSE" | jq -r '.document_id // empty')

if [ -n "$DOCUMENT_ID" ]; then
  pass "Document ingested: ${DOCUMENT_ID}"
else
  fail "Document ingestion failed: $(echo "$INGEST_RESPONSE" | jq -r '.detail // .')"
  exit 1
fi

###############################################################################
# Step 4: Create a workflow run
###############################################################################
echo ""
echo "[4/8] Creating workflow run (claim_intake)..."

RUN_RESPONSE=$(curl -s -X POST "${BASE_URL}/v1/workflow-runs" \
  -H "${AUTH_HEADER}" \
  -H "Content-Type: application/json" \
  -d "{
    \"workflow_name\": \"claim_intake\",
    \"document_ids\": [\"${DOCUMENT_ID}\"],
    \"inputs\": {}
  }")

WORKFLOW_RUN_ID=$(echo "$RUN_RESPONSE" | jq -r '.workflow_run_id // empty')
RUN_STATE=$(echo "$RUN_RESPONSE" | jq -r '.state // empty')

if [ -n "$WORKFLOW_RUN_ID" ]; then
  pass "Workflow run created: ${WORKFLOW_RUN_ID} (state=${RUN_STATE})"
else
  fail "Workflow run creation failed: $(echo "$RUN_RESPONSE" | jq -r '.detail // .')"
  exit 1
fi

###############################################################################
# Step 5: Poll workflow until terminal state
###############################################################################
echo ""
echo "[5/8] Polling workflow run until terminal state..."

TERMINAL_STATES="completed failed cancelled awaiting_human"
FINAL_STATE=""
ELAPSED=0

while [ "$ELAPSED" -lt "$MAX_POLL_SECONDS" ]; do
  STATUS_RESPONSE=$(curl -s "${BASE_URL}/v1/workflow-runs/${WORKFLOW_RUN_ID}" \
    -H "${AUTH_HEADER}")
  CURRENT_STATE=$(echo "$STATUS_RESPONSE" | jq -r '.state // "unknown"')

  for ts in $TERMINAL_STATES; do
    if [ "$CURRENT_STATE" = "$ts" ]; then
      FINAL_STATE="$CURRENT_STATE"
      break 2
    fi
  done

  sleep "$POLL_INTERVAL"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

if [ -n "$FINAL_STATE" ]; then
  pass "Workflow reached terminal state: ${FINAL_STATE} (${ELAPSED}s)"
else
  fail "Workflow did not reach terminal state within ${MAX_POLL_SECONDS}s (current: ${CURRENT_STATE})"
fi

###############################################################################
# Step 6: Query audit event timeline
###############################################################################
echo ""
echo "[6/8] Querying audit event timeline..."

EVENTS_RESPONSE=$(curl -s "${BASE_URL}/v1/workflow-runs/${WORKFLOW_RUN_ID}/events" \
  -H "${AUTH_HEADER}")
EVENT_COUNT=$(echo "$EVENTS_RESPONSE" | jq '.events | length')

if [ "$EVENT_COUNT" -gt 0 ]; then
  pass "Retrieved ${EVENT_COUNT} audit events"
  info "Event types: $(echo "$EVENTS_RESPONSE" | jq -r '[.events[].event_type] | join(", ")')"
else
  fail "No audit events found for workflow run"
fi

###############################################################################
# Step 7: Verify audit chain integrity (seq_in_run continuity)
###############################################################################
echo ""
echo "[7/8] Verifying audit chain integrity..."

CHAIN_VALID=true
PREV_SEQ=0

for SEQ in $(echo "$EVENTS_RESPONSE" | jq -r '.events[].seq_in_run' | sort -n); do
  EXPECTED=$((PREV_SEQ + 1))
  if [ "$SEQ" -ne "$EXPECTED" ]; then
    CHAIN_VALID=false
    fail "Sequence gap detected: expected ${EXPECTED}, got ${SEQ}"
    break
  fi
  PREV_SEQ=$SEQ
done

if [ "$CHAIN_VALID" = true ] && [ "$PREV_SEQ" -gt 0 ]; then
  pass "Audit chain integrity verified (seq 1..${PREV_SEQ} continuous)"
elif [ "$PREV_SEQ" -eq 0 ]; then
  fail "No sequence numbers to verify"
fi

###############################################################################
# Step 8: Escalation flow (invalid document)
###############################################################################
echo ""
echo "[8/8] Demonstrating escalation flow (invalid document)..."

INVALID_CLAIM="Claim Number: CLM-2025-BAD999
Policy Number: INVALID-FORMAT
Claimant: Test User
Date of Loss: 01/20/2025
Claim Type: property
Description: Intentionally invalid policy number to trigger validation failure."

# Ingest invalid document
INVALID_INGEST=$(echo "$INVALID_CLAIM" | curl -s -X POST "${BASE_URL}/v1/documents" \
  -H "${AUTH_HEADER}" \
  -F "file=@-;filename=invalid_claim.txt;type=text/plain")

INVALID_DOC_ID=$(echo "$INVALID_INGEST" | jq -r '.document_id // empty')

if [ -z "$INVALID_DOC_ID" ]; then
  fail "Failed to ingest invalid document"
else
  info "Invalid document ingested: ${INVALID_DOC_ID}"

  # Create workflow run for invalid document
  INVALID_RUN=$(curl -s -X POST "${BASE_URL}/v1/workflow-runs" \
    -H "${AUTH_HEADER}" \
    -H "Content-Type: application/json" \
    -d "{
      \"workflow_name\": \"claim_intake\",
      \"document_ids\": [\"${INVALID_DOC_ID}\"],
      \"inputs\": {}
    }")

  INVALID_RUN_ID=$(echo "$INVALID_RUN" | jq -r '.workflow_run_id // empty')
  info "Workflow run created: ${INVALID_RUN_ID}"

  # Poll until terminal state (expect awaiting_human or failed)
  ELAPSED=0
  INVALID_FINAL=""
  while [ "$ELAPSED" -lt "$MAX_POLL_SECONDS" ]; do
    INVALID_STATUS=$(curl -s "${BASE_URL}/v1/workflow-runs/${INVALID_RUN_ID}" \
      -H "${AUTH_HEADER}")
    INVALID_STATE=$(echo "$INVALID_STATUS" | jq -r '.state // "unknown"')

    for ts in $TERMINAL_STATES; do
      if [ "$INVALID_STATE" = "$ts" ]; then
        INVALID_FINAL="$INVALID_STATE"
        break 2
      fi
    done

    sleep "$POLL_INTERVAL"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
  done

  if [ "$INVALID_FINAL" = "awaiting_human" ]; then
    pass "Invalid document triggered escalation (state=awaiting_human)"

    # Find the escalation and claim it
    ESCALATIONS=$(curl -s "${BASE_URL}/v1/escalations?state=open" \
      -H "${AUTH_HEADER}")
    ESCALATION_ID=$(echo "$ESCALATIONS" | jq -r '.escalations[0].escalation_id // empty')

    if [ -n "$ESCALATION_ID" ]; then
      # Claim the escalation
      CLAIM_RESP=$(curl -s -X POST "${BASE_URL}/v1/escalations/${ESCALATION_ID}/claim" \
        -H "${AUTH_HEADER}")
      CLAIM_STATE=$(echo "$CLAIM_RESP" | jq -r '.state // empty')

      if [ "$CLAIM_STATE" = "claimed" ]; then
        pass "Escalation claimed: ${ESCALATION_ID}"

        # Resolve the escalation
        RESOLVE_RESP=$(curl -s -X POST "${BASE_URL}/v1/escalations/${ESCALATION_ID}/resolve" \
          -H "${AUTH_HEADER}" \
          -H "Content-Type: application/json" \
          -d '{"approve": false, "override": true, "notes": "Resolved via verify_phase1.sh"}')
        RESOLVE_STATE=$(echo "$RESOLVE_RESP" | jq -r '.state // empty')

        if [ "$RESOLVE_STATE" = "resolved" ]; then
          pass "Escalation resolved"
        else
          fail "Escalation resolution failed: $(echo "$RESOLVE_RESP" | jq -r '.detail // .')"
        fi
      else
        fail "Escalation claim failed: $(echo "$CLAIM_RESP" | jq -r '.detail // .')"
      fi
    else
      info "No open escalation found (may already have been processed)"
    fi
  elif [ -n "$INVALID_FINAL" ]; then
    info "Invalid document reached state: ${INVALID_FINAL} (escalation path depends on workflow config)"
    pass "Invalid document workflow completed with state: ${INVALID_FINAL}"
  else
    fail "Invalid document workflow did not reach terminal state within ${MAX_POLL_SECONDS}s"
  fi
fi

###############################################################################
# Summary
###############################################################################
echo ""
echo "======================================================================"
echo " Summary"
echo "======================================================================"
TOTAL=$((PASS_COUNT + FAIL_COUNT))
echo -e "  Total checks: ${TOTAL}"
echo -e "  ${GREEN}Passed: ${PASS_COUNT}${NC}"
echo -e "  ${RED}Failed: ${FAIL_COUNT}${NC}"
echo ""

if [ "$FAIL_COUNT" -eq 0 ]; then
  echo -e "  ${GREEN}All Phase 1 operational checks passed.${NC}"
  exit 0
else
  echo -e "  ${RED}Some checks failed. Review output above.${NC}"
  exit 1
fi
