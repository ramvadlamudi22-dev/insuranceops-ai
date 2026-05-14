# Demo Walkthrough

This document provides a complete end-to-end demonstration of InsuranceOps AI, showing the platform's AI-assisted workflow capabilities from document ingestion through audit verification.

## Prerequisites

```bash
# Ensure the stack is running
docker compose -f compose/compose.yml up -d
docker compose -f compose/compose.yml ps  # all healthy

# Seed an API key
docker compose -f compose/compose.yml exec api python scripts/seed_dev_data.py
export TOKEN="<token-from-output>"
```

## Scenario 1: Happy Path — Auto Claim Processing

### Step 1: Ingest a well-formed claim document

```bash
curl -s -X POST http://localhost:8000/v1/documents \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "file=@-;filename=auto_claim.txt;type=text/plain" <<'EOF'
Claim Number: CLM-2025-007891
Policy Number: POL-12345678
Claimant: Sarah Johnson
Date of Loss: 03/15/2025
Claim Type: auto
Description: Rear-end collision on Highway 101 southbound near exit 42.
Estimated damage: $4,200. No injuries reported. Police report filed.
EOF
```

**Expected response:**
```json
{
  "document_id": "...",
  "content_hash": "...",
  "size_bytes": 281,
  "content_type": "text/plain",
  "ingested_at": "2025-...",
  "is_duplicate": false
}
```

### Step 2: Start a workflow run

```bash
curl -s -X POST http://localhost:8000/v1/workflow-runs \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"workflow_name\":\"claim_intake\",\"document_ids\":[\"${DOC_ID}\"],\"inputs\":{}}" | jq .
```

### Step 3: Poll until completion

```bash
while true; do
  RESP=$(curl -s http://localhost:8000/v1/workflow-runs/${RUN_ID} -H "Authorization: Bearer ${TOKEN}")
  STATE=$(echo $RESP | jq -r '.state')
  echo "$(date +%H:%M:%S) State: $STATE"
  case "$STATE" in completed|failed|cancelled|awaiting_human) break ;; esac
  sleep 2
done
```

**Expected:** Reaches `completed` after ~5-10 seconds (ingest -> extract -> validate -> route -> complete).

### Step 4: View the audit trail

```bash
curl -s http://localhost:8000/v1/workflow-runs/${RUN_ID}/events \
  -H "Authorization: Bearer ${TOKEN}" | jq '.events[] | {seq_in_run, event_type, actor}'
```

**Expected output:**
```json
{"seq_in_run": 1, "event_type": "workflow_run.started", "actor": "api_key:operator:..."}
{"seq_in_run": 2, "event_type": "step_attempt.succeeded", "actor": "worker:main:..."}
{"seq_in_run": 3, "event_type": "step.advanced", "actor": "worker:orchestrator"}
...
{"seq_in_run": N, "event_type": "workflow_run.completed", "actor": "worker:orchestrator"}
```

### Step 5: Verify audit chain integrity

```bash
./scripts/opsctl audit verify --workflow-run-id ${RUN_ID}
# PASS: All N events verified
```

---

## Scenario 2: Escalation Flow — Invalid Policy Number

### Step 1: Ingest a document with an invalid policy format

```bash
curl -s -X POST http://localhost:8000/v1/documents \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "file=@-;filename=bad_policy.txt;type=text/plain" <<'EOF'
Claim Number: CLM-2025-BAD001
Policy Number: INVALID-FORMAT-XYZ
Claimant: Test User
Date of Loss: 04/01/2025
Claim Type: property
Description: Water damage from burst pipe in basement.
EOF
```

### Step 2: Start workflow and observe escalation

```bash
# Start the run
curl -s -X POST http://localhost:8000/v1/workflow-runs \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"workflow_name\":\"claim_intake\",\"document_ids\":[\"${DOC_ID}\"],\"inputs\":{}}" | jq .

# Poll - should reach awaiting_human
```

**Expected:** Run transitions to `awaiting_human` because the validate step detects the invalid policy number format and escalates.

### Step 3: List and claim the escalation

```bash
# List open escalations
curl -s http://localhost:8000/v1/escalations?state=open \
  -H "Authorization: Bearer ${TOKEN}" | jq '.cases[0]'

# Claim it
curl -s -X POST http://localhost:8000/v1/escalations/${ESC_ID}/claim \
  -H "Authorization: Bearer ${TOKEN}" | jq .
```

### Step 4: Resolve the escalation

```bash
curl -s -X POST http://localhost:8000/v1/escalations/${ESC_ID}/resolve \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"approve": true, "notes": "Manually verified policy number with carrier system"}' | jq .
```

### Step 5: Observe workflow resumption

```bash
# Poll the workflow run - should transition from awaiting_human -> running -> completed
curl -s http://localhost:8000/v1/workflow-runs/${RUN_ID} \
  -H "Authorization: Bearer ${TOKEN}" | jq '{state, version}'
```

---

## Scenario 3: DLQ Recovery

### Observe DLQ state

```bash
# Check DLQ depth
./scripts/opsctl queue dlq count

# If non-empty, list entries
./scripts/opsctl queue dlq list

# Inspect a specific entry
./scripts/opsctl queue dlq inspect 0

# Requeue for retry
./scripts/opsctl queue dlq requeue 0
# OK: Entry moved from DLQ to ready queue.
```

---

## Scenario 4: Batch Audit Verification

```bash
# Verify all completed runs (up to 1000)
./scripts/opsctl audit verify-batch --state completed --sample-size 100

# Expected output:
# Summary: 100 passed, 0 failed, 100 total
```

---

## Scenario 5: Rate Limiting Observation

```bash
# Fire rapid requests to observe rate limiting
for i in $(seq 1 20); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/v1/workflow-runs/00000000-0000-0000-0000-000000000000 \
    -H "Authorization: Bearer ${TOKEN}")
  echo "Request $i: HTTP $STATUS"
done
```

At default settings (1200/60s for operator), this won't trigger rate limiting. To test:
```bash
# Temporarily set RATE_LIMIT_OPERATOR_MAX=5 and restart API, then repeat
```

---

## Scenario 6: Metrics Observation

```bash
# View key platform metrics
curl -s http://localhost:8000/metrics | grep -E "^(workflow_runs|step_attempts|queue_depth|audit_events|ai_)" | head -30
```

**Expected metrics include:**
```
workflow_runs_started_total{workflow_name="claim_intake",workflow_version="v1"} 3.0
workflow_runs_completed_total{workflow_name="claim_intake",workflow_version="v1",terminal_state="completed"} 2.0
step_attempts_total{workflow_name="claim_intake",step_name="extract",outcome="success"} 2.0
queue_depth{queue="ready"} 0.0
queue_depth{queue="dlq"} 0.0
audit_events_appended_total{event_type="workflow_run.started"} 3.0
audit_chain_mismatches_total 0.0
```

---

## Scenario 7: Supervisor Cancellation

```bash
# Start a workflow run
# ... (same as scenario 1)

# Cancel it (requires supervisor role)
curl -s -X POST http://localhost:8000/v1/workflow-runs/${RUN_ID}/cancel \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Duplicate submission", "notes": "Original processed under CLM-2025-007891"}' | jq .
```

**Expected:** Run transitions to `cancelled`, AuditEvent emitted with cancellation reason.

---

## Key Observations for Demo

| What to show | Where to look |
|-------------|---------------|
| Deterministic extraction | Same document always produces same fields |
| Hash-chain integrity | `opsctl audit verify` returns PASS |
| Fail-safe AI | Extract step succeeds even if AI enhancement fails |
| Human-in-the-loop | Escalation claim/resolve flow |
| Operational tooling | `opsctl queue dlq` and `opsctl audit verify-batch` |
| Observability | `/metrics` endpoint with Prometheus counters |
| Rate limiting | 429 responses with Retry-After header |
| Replay safety | Audit events form a verifiable hash chain |
