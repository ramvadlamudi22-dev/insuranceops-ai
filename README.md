# InsuranceOps AI

An internal, production-grade AI-assisted workflow orchestration platform for insurance back-office operations (document ingestion, extraction, validation, routing, and human escalation) with deterministic execution and full audit trails.

## Status

Phase 0 (architecture and design) and Phase 1 (initial implementation) are complete. The repository contains the full Phase 0 design document set plus the working Phase 1 implementation: application code, test suite, Docker packaging, Compose topology, database migrations, CI pipeline, and operational verification tooling.

The canonical vocabulary (`Document`, `Workflow`, `WorkflowRun`, `Step`, `StepAttempt`, `Task`, `EscalationCase`, `AuditEvent`, `Actor`) and the canonical lifecycle states are fixed in [SPEC.md](./SPEC.md) and used consistently across every document in the set. A cross-document disagreement is a bug in the document, not in the reader; SPEC.md is the tie-breaker.

## Design documents

The table lists the ten Phase 0 design documents in the canonical order. The one-line description for each is derived from that document's own Purpose section so this index remains a faithful summary.

| Document | What it establishes |
| --- | --- |
| [SPEC.md](./SPEC.md) | The top-level specification for InsuranceOps AI: product identity, in-scope and out-of-scope surface, problem, measurable success criteria, non-goals, and the canonical vocabulary used by every other design document. |
| [PRODUCT_REQUIREMENTS.md](./PRODUCT_REQUIREMENTS.md) | The functional and non-functional requirements of the platform in testable form, each with a stable identifier, a one-sentence statement, and a mechanizable acceptance test. |
| [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md) | The architectural center of Phase 0: every lifecycle, every domain model, every boundary, and every storage and queue contract the platform will implement in Phase 1 and beyond. |
| [PHASED_ROADMAP.md](./PHASED_ROADMAP.md) | How the platform is delivered phase by phase: goals, exit criteria, and effort shape of each phase, plus the engineering workflow every phase follows. |
| [SECURITY_REVIEW.md](./SECURITY_REVIEW.md) | The authoritative security posture for Phase 1 and the planned hardening for Phase 2 and beyond: threat model, role boundaries, auth, secrets, PII, audit retention, and the things this platform explicitly does not claim. |
| [OBSERVABILITY_STRATEGY.md](./OBSERVABILITY_STRATEGY.md) | The authoritative observability posture: structured logging contract, correlation-id propagation, the Prometheus metric surface with cardinality rules, OpenTelemetry-ready tracing hooks, operator-facing event timeline, and probe contract. |
| [TESTING_STRATEGY.md](./TESTING_STRATEGY.md) | The shape of the Phase 1 test suite that protects the platform's correctness properties: deterministic workflow execution, bounded retries, exactly-once audit with hash-chain tamper visibility, and reliable-queue invariants. |
| [DEPLOYMENT_STRATEGY.md](./DEPLOYMENT_STRATEGY.md) | How the platform is packaged, configured, and deployed through Phase 1 and Phase 2: deployment unit, orchestration tool, CI/CD pipeline, environment-variable contract, secrets delivery, migration discipline, rollout and rollback, backup posture, and explicit decisions not to adopt certain platforms yet. |
| [RISK_ANALYSIS.md](./RISK_ANALYSIS.md) | The authoritative risk register across Phase 0 design, Phase 1 initial delivery, and operations: technical, operational, delivery, and compliance risks, each with a mitigation, an owner-role, and the signal that would reveal it materializing. |
| [TECHNICAL_DEBT_PREVENTION.md](./TECHNICAL_DEBT_PREVENTION.md) | How the platform avoids predictable technical debt: the debt refused at the door, the debt knowingly accepted with exit criteria, and the code-level, architectural, schema, documentation, dependency, and review-discipline guardrails that keep either category from drifting. |
| [TERMINOLOGY.md](./TERMINOLOGY.md) | Canonical terminology reference documenting all normalized terms, field names, metric names, and formatting conventions. |

### Reading order

Different readers have different entry points. The sequences below are suggestions, not prerequisites; every document stands alone.

- New readers start with [SPEC.md](./SPEC.md) for the product identity and vocabulary, then read [PRODUCT_REQUIREMENTS.md](./PRODUCT_REQUIREMENTS.md) to see what the platform must do.
- Architects read [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md) next. It is the longest document in the set and is deliberately cohesive; reading it end to end is the fastest path to understanding the system.
- Operators and SREs read [SECURITY_REVIEW.md](./SECURITY_REVIEW.md), [OBSERVABILITY_STRATEGY.md](./OBSERVABILITY_STRATEGY.md), and [DEPLOYMENT_STRATEGY.md](./DEPLOYMENT_STRATEGY.md) as a group. Together they describe the runtime posture a Phase 1 deployment ships with and the Phase 2 hardening that follows.
- Delivery planners read [PHASED_ROADMAP.md](./PHASED_ROADMAP.md) alongside [RISK_ANALYSIS.md](./RISK_ANALYSIS.md). The roadmap commits to a sequence; the risk register names what can go wrong at each step.
- Maintainers and reviewers read [TECHNICAL_DEBT_PREVENTION.md](./TECHNICAL_DEBT_PREVENTION.md) last. It is the set of guardrails every PR is measured against and is the document most often referenced in code review.
- Testers read [TESTING_STRATEGY.md](./TESTING_STRATEGY.md) before writing any Phase 1 test. The test-suite shape is prescribed, not discovered.

A complete reader path from empty to full is: SPEC, PRODUCT_REQUIREMENTS, SYSTEM_ARCHITECTURE, PHASED_ROADMAP, SECURITY_REVIEW, OBSERVABILITY_STRATEGY, TESTING_STRATEGY, DEPLOYMENT_STRATEGY, RISK_ANALYSIS, TECHNICAL_DEBT_PREVENTION. That sequence respects the dependency of each document on the one before it: the product surface is defined before the architecture, the architecture is defined before the operational posture, and the operational posture is defined before the risks and the debt guardrails that watch it.

## Repository layout

The repository contains the Phase 0 design documents plus the full Phase 1 implementation.

```
.
├── .env.example                # Environment variable template
├── .github/workflows/ci.yml   # GitHub Actions CI pipeline
├── .gitignore
├── README.md
├── SPEC.md
├── PRODUCT_REQUIREMENTS.md
├── SYSTEM_ARCHITECTURE.md
├── PHASED_ROADMAP.md
├── SECURITY_REVIEW.md
├── OBSERVABILITY_STRATEGY.md
├── TESTING_STRATEGY.md
├── DEPLOYMENT_STRATEGY.md
├── RISK_ANALYSIS.md
├── TECHNICAL_DEBT_PREVENTION.md
├── TERMINOLOGY.md
├── pyproject.toml              # Package manifest and tool configuration
├── compose/
│   ├── compose.yml            # Production-like Compose topology
│   └── compose.test.yml       # CI test Compose overlay
├── docker/
│   └── Dockerfile             # Multi-stage application image
├── migrations/
│   ├── alembic.ini
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial.py    # Phase 1 schema migration
├── scripts/
│   ├── dev_up.sh              # Start local development stack
│   ├── dev_down.sh            # Stop local development stack
│   ├── opsctl                 # Operational control CLI
│   ├── seed_dev_data.py       # Seed development API keys
│   └── verify_phase1.sh       # End-to-end verification script
├── src/insuranceops/
│   ├── api/                   # FastAPI application, routes, schemas
│   ├── audit/                 # Audit chain and hash-chain verifier
│   ├── config.py              # Centralized configuration
│   ├── domain/                # Domain models and value objects
│   ├── observability/         # Logging, metrics, tracing
│   ├── queue/                 # Redis reliable queue, DLQ, delayed queue
│   ├── security/              # Auth, RBAC, redaction
│   ├── storage/               # SQLAlchemy models, repositories, payloads
│   ├── workers/               # Task worker, reaper, outbox relay
│   └── workflows/             # Workflow definitions and registry
└── tests/
    ├── audit/                 # Audit chain unit tests
    ├── integration/           # Integration tests (DB, Redis)
    ├── unit/                  # Pure unit tests
    └── workflow/              # Workflow lifecycle tests
```

## Phase history

### Phase 0 (architecture)

Phase 0 produced the ten design documents that define the platform end to end. The design was assembled as individually reviewable commits on the `phase-0-architecture` branch, then merged into `main`. The Phase 0 deliverables established the canonical vocabulary, lifecycle state machines, domain models, storage contracts, queue contracts, security posture, observability surface, testing shape, deployment topology, risk register, and technical-debt guardrails.

### Phase 1 (initial implementation)

Phase 1 implemented the architecture specified in the Phase 0 documents. The deliverables include:

- Application package (`src/insuranceops/`) with API, domain, storage, queue, worker, audit, security, observability, and workflow modules.
- Test suite (`tests/`) covering unit, integration, audit, and workflow lifecycle scenarios.
- Docker packaging (`docker/Dockerfile`) as a multi-stage build.
- Compose topology (`compose/`) for local development and CI.
- Database migration (`migrations/versions/0001_initial.py`) for the Phase 1 schema.
- GitHub Actions CI pipeline (`.github/workflows/ci.yml`) running lint, type-check, and tests with service containers.
- Operational scripts (`scripts/`) for development workflow and end-to-end verification.

## Operational Verification

This section describes how to boot the platform, exercise the full Phase 1 workflow, and verify correctness locally. All examples assume you are in the repository root.

### Boot the compose stack

```bash
docker compose -f compose/compose.yml up -d
```

Wait for services to become healthy:

```bash
docker compose -f compose/compose.yml ps
```

The API is available at `http://localhost:8000`. Verify with:

```bash
curl http://localhost:8000/healthz
# {"status":"ok"}
```

### Create an API key

Run the seed script inside the running stack:

```bash
docker compose -f compose/compose.yml exec api python scripts/seed_dev_data.py
```

The script prints a Bearer token. Export it for use in subsequent commands:

```bash
export TOKEN="<token-from-seed-output>"
```

Alternatively, insert a key directly via psql:

```bash
RAW_TOKEN="my-dev-token"
KEY_HASH=$(echo -n "dev-pepper-not-for-production${RAW_TOKEN}" | sha256sum | awk '{print $1}')
docker compose -f compose/compose.yml exec -T postgres psql -U postgres -d insuranceops -c \
  "INSERT INTO api_keys (api_key_id, key_hash, role, label, created_at)
   VALUES (gen_random_uuid(), decode('${KEY_HASH}', 'hex'), 'supervisor', 'manual-key', NOW());"
export TOKEN="${RAW_TOKEN}"
```

### Ingest a document

Upload a plain-text claim document:

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

Response includes `document_id`:

```json
{
  "document_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  "content_hash": "...",
  "size_bytes": 187,
  "content_type": "text/plain",
  "ingested_at": "2025-01-15T12:00:00Z",
  "is_duplicate": false
}
```

### Create a workflow run

```bash
curl -X POST http://localhost:8000/v1/workflow-runs \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_name": "claim_intake",
    "document_ids": ["<document_id>"],
    "inputs": {}
  }'
```

### Poll workflow status

```bash
curl http://localhost:8000/v1/workflow-runs/<workflow_run_id> \
  -H "Authorization: Bearer ${TOKEN}"
```

Terminal states: `completed`, `failed`, `cancelled`, `awaiting_human`.

Poll in a loop:

```bash
while true; do
  STATE=$(curl -s http://localhost:8000/v1/workflow-runs/<workflow_run_id> \
    -H "Authorization: Bearer ${TOKEN}" | jq -r '.state')
  echo "State: $STATE"
  case "$STATE" in completed|failed|cancelled|awaiting_human) break ;; esac
  sleep 2
done
```

### Query audit events

```bash
curl http://localhost:8000/v1/workflow-runs/<workflow_run_id>/events \
  -H "Authorization: Bearer ${TOKEN}" | jq '.events[] | {seq_in_run, event_type, actor}'
```

### Verify audit chain integrity

Audit events carry a monotonically increasing `seq_in_run` starting at 1. Verify continuity:

```bash
curl -s http://localhost:8000/v1/workflow-runs/<workflow_run_id>/events \
  -H "Authorization: Bearer ${TOKEN}" \
  | jq -e '[.events[].seq_in_run] | sort | . as $s |
    if length == 0 then false
    elif .[0] != 1 then false
    elif length == 1 then true
    else [range(1; length)] | all(. as $i | $s[$i] == $s[$i-1] + 1) end'
```

A truthy result confirms no gaps in the sequence.

### Observe retry/escalation behavior

Ingest a document with an invalid policy number format to trigger a validation failure and escalation:

```bash
curl -X POST http://localhost:8000/v1/documents \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "file=@-;filename=bad_claim.txt;type=text/plain" <<'EOF'
Claim Number: CLM-2025-BAD999
Policy Number: INVALID-FORMAT
Claimant: Test User
Date of Loss: 01/20/2025
Claim Type: property
Description: Invalid policy number to trigger validation failure.
EOF
```

Create a workflow run for this document and poll. The run should transition to `awaiting_human` after the validate step exhausts retries.

List and claim the resulting escalation:

```bash
# List open escalations
curl http://localhost:8000/v1/escalations?state=open \
  -H "Authorization: Bearer ${TOKEN}"

# Claim an escalation
curl -X POST http://localhost:8000/v1/escalations/<escalation_id>/claim \
  -H "Authorization: Bearer ${TOKEN}"

# Resolve the escalation
curl -X POST http://localhost:8000/v1/escalations/<escalation_id>/resolve \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"approve": false, "override": true, "notes": "Manual override after review"}'
```

### Run CI checks locally

```bash
# Lint
ruff check src/ tests/

# Format check
ruff format --check src/ tests/

# Type check
mypy src/ --ignore-missing-imports

# Tests (requires running Postgres and Redis)
pytest tests/ -v --tb=short
```

Or run the full verification script (requires compose stack to be up):

```bash
./scripts/verify_phase1.sh
```

## Next steps

Phase 1 is complete. Subsequent phases will deliver the capabilities described in [PHASED_ROADMAP.md](./PHASED_ROADMAP.md), including AI/ML handler integration, production hardening, and operational maturity improvements. Phase 2 work begins on its own feature branches as described in the roadmap.
