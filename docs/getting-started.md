# Getting Started

This guide walks you from a fresh clone to a running InsuranceOps AI stack with a completed workflow run in under 10 minutes.

## Prerequisites

- Docker and Docker Compose (v2+)
- `curl` and `jq` for API interaction
- Python 3.12+ (for running `opsctl` and tests locally)

## 1. Clone and Boot

```bash
git clone https://github.com/ramvadlamudi22-dev/insuranceops-ai.git
cd insuranceops-ai

# Start the full stack (postgres, redis, api, worker)
docker compose -f compose/compose.yml up -d
```

Wait for all services to become healthy:

```bash
docker compose -f compose/compose.yml ps
```

Verify the API is reachable:

```bash
curl http://localhost:8000/healthz
# {"status":"ok"}

curl http://localhost:8000/readyz
# {"status":"ok"}
```

## 2. Create an API Key

Seed a development API key:

```bash
docker compose -f compose/compose.yml exec api python scripts/seed_dev_data.py
```

The script prints a Bearer token. Export it:

```bash
export TOKEN="<token-from-output>"
```

## 3. Ingest a Document

Upload a sample claim document:

```bash
curl -X POST http://localhost:8000/v1/documents \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "file=@-;filename=claim.txt;type=text/plain" <<'EOF'
Claim Number: CLM-2025-001234
Policy Number: POL-12345678
Claimant: Jane Smith
Date of Loss: 01/15/2025
Claim Type: auto
Description: Vehicle collision at intersection of Main St and 5th Ave.
EOF
```

Save the `document_id` from the response:

```bash
export DOC_ID="<document_id from response>"
```

## 4. Start a Workflow Run

```bash
curl -X POST http://localhost:8000/v1/workflow-runs \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"workflow_name\": \"claim_intake\",
    \"document_ids\": [\"${DOC_ID}\"],
    \"inputs\": {}
  }"
```

Save the `workflow_run_id`:

```bash
export RUN_ID="<workflow_run_id from response>"
```

## 5. Poll Until Complete

```bash
while true; do
  STATE=$(curl -s http://localhost:8000/v1/workflow-runs/${RUN_ID} \
    -H "Authorization: Bearer ${TOKEN}" | jq -r '.state')
  echo "State: $STATE"
  case "$STATE" in completed|failed|cancelled|awaiting_human) break ;; esac
  sleep 2
done
```

A successful run reaches `completed` after all five steps (ingest, extract, validate, route, complete) execute.

## 6. View the Audit Trail

```bash
curl -s http://localhost:8000/v1/workflow-runs/${RUN_ID}/events \
  -H "Authorization: Bearer ${TOKEN}" | jq '.events[] | {seq_in_run, event_type, actor}'
```

## 7. Verify Chain Integrity

```bash
docker compose -f compose/compose.yml exec api python scripts/opsctl audit verify \
  --workflow-run-id ${RUN_ID}
# PASS: All N events verified
```

## What Just Happened

1. The API accepted your document and stored it with a SHA-256 content hash
2. A WorkflowRun was created with five ordered Steps
3. The outbox relay drained the first task into Redis
4. The worker claimed the task and executed each step handler in sequence
5. Every state transition produced a hash-chained AuditEvent
6. The run reached terminal state `completed`

## Next Steps

- [Deployment Guide](./deployment.md) — production configuration and hardening
- [Operations Guide](./operations.md) — DLQ management, audit verification, troubleshooting
- [Architecture Diagrams](./architecture/) — visual system topology
