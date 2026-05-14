# Demo Scenarios

Pre-built scenarios for demonstrating InsuranceOps AI capabilities. Each scenario exercises a specific platform feature.

## Scenario Index

| # | Name | Features Exercised | Expected Duration |
|---|------|-------------------|-------------------|
| 1 | Happy path claim | Ingestion, extraction, validation, routing, completion, audit | 30 seconds |
| 2 | Escalation flow | Invalid data, escalation, claim, resolve, resume | 60 seconds |
| 3 | AI extraction with OCR | PDF processing, OCR, confidence scoring | 30 seconds |
| 4 | Review routing | Low confidence, review queue, approve/reject | 45 seconds |
| 5 | DLQ recovery | Poison pill, DLQ inspection, requeue | 30 seconds |
| 6 | Batch audit verification | Chain integrity, scheduled verification | 15 seconds |
| 7 | Supervisor cancellation | Running workflow, cancel, audit trail | 20 seconds |
| 8 | Rate limiting | Rapid requests, 429 response, Retry-After | 15 seconds |

## Sample Documents

### Well-formed auto claim (`docs/demo-assets/sample_auto_claim.txt`)

```
Claim Number: CLM-2025-007891
Policy Number: POL-12345678
Claimant: Sarah Johnson
Date of Loss: 03/15/2025
Claim Type: auto
Description: Rear-end collision on Highway 101 southbound near exit 42.
Estimated damage: $4,200. No injuries reported. Police report filed.
```

### Well-formed property claim (`docs/demo-assets/sample_property_claim.txt`)

```
Claim Number: CLM-2025-008234
Policy Number: POL-98765432
Claimant: Michael Chen
Date of Loss: 02/28/2025
Claim Type: property
Description: Kitchen fire caused by electrical fault. Fire department responded.
Structural damage to kitchen and adjacent dining room. Family displaced.
```

### Invalid policy format (triggers escalation) (`docs/demo-assets/sample_invalid_policy.txt`)

```
Claim Number: CLM-2025-BAD001
Policy Number: INVALID-FORMAT-XYZ
Claimant: Test User
Date of Loss: 04/01/2025
Claim Type: property
Description: Water damage from burst pipe in basement.
```

### Minimal document (triggers review routing) (`docs/demo-assets/sample_minimal.txt`)

```
Subject: Insurance Inquiry
Date: unknown
Notes: Customer called about their policy.
```

## Expected Outcomes

### Scenario 1: Happy Path

```
ingest(succeeded) -> extract(succeeded, 5 fields, confidence 0.95)
  -> validate(succeeded, pass) -> route(succeeded) -> complete(succeeded + summary)
WorkflowRun: completed
Audit events: ~10 events, chain verified
```

### Scenario 2: Escalation

```
ingest(succeeded) -> extract(succeeded, 4 fields, policy_number missing)
  -> validate(escalate, VALIDATION_FAIL_CORRECTABLE)
WorkflowRun: awaiting_human
EscalationCase: open -> claimed -> resolved
WorkflowRun: running -> completed
```

### Scenario 3: AI Review Routing

```
ingest(succeeded) -> extract(succeeded, 2 fields, min confidence 0.3)
  -> validate(escalate, REVIEW_REQUIRED, reasons: [missing_fields, low_confidence])
WorkflowRun: awaiting_human (routed by AI confidence evaluation)
```

### Scenario 4: DLQ Recovery

```
Task fails max_attempts -> moves to queue:tasks:dlq
Operator: opsctl queue dlq list -> inspect -> requeue
Task retries successfully after root cause fix
```

## Metrics to Monitor During Demo

```bash
# Watch key metrics in real-time
watch -n 5 'curl -s http://localhost:8000/metrics | grep -E "^(workflow_runs_started|workflow_runs_completed|step_attempts_total|queue_depth|audit_chain)" | sort'
```

## Demo Reset

To reset the platform for a fresh demo:

```bash
# Stop the stack
docker compose -f compose/compose.yml down -v

# Restart clean
docker compose -f compose/compose.yml up -d

# Run migrations
docker compose -f compose/compose.yml exec api alembic -c migrations/alembic.ini upgrade head

# Seed API key
docker compose -f compose/compose.yml exec api python scripts/seed_dev_data.py
```
