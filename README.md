# InsuranceOps AI

An internal, production-grade AI-assisted workflow orchestration platform for insurance back-office operations (document ingestion, extraction, validation, routing, and human escalation) with deterministic execution and full audit trails.

## Status

Phase 0 (architecture and design) is complete. The ten design documents listed below describe the platform end to end: product surface, system architecture, phased delivery, security posture, observability, testing, deployment, risk register, and technical-debt guardrails.

Implementation has not started. No application code, Dockerfile, CI workflow, or database migration exists in this repository yet. Those are Phase 1 and later artifacts described in the documents. The Phase 0 deliverables land on the `phase-0-architecture` branch and will be merged into `main` through a pull request after review.

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

## Repository layout at Phase 0

At the end of Phase 0 the repository contains only the design documents and the minimum files required to make it a usable git repository. There is no `src/`, no `tests/`, no `docker/`, and no `.github/workflows/` yet. Those arrive in Phase 1.

```
.
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
└── TERMINOLOGY.md
```

The proposed Phase 1 repository tree (packages, modules, and folders the code will be organized into) lives in [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md) section 4. That tree is a specification for Phase 1 scaffolding, not a current state of this branch.

The absence of implementation artifacts at Phase 0 is deliberate. The Phase 0 deliverable is a design that a second engineer could implement without asking questions the documents do not already answer; anything that would prejudge the Phase 1 scaffolding beyond the documented architecture is out of scope for this branch.

### What is not in the repository at Phase 0

Readers arriving from a typical project template may expect files that are intentionally absent here. The following are Phase 1 or later artifacts and are not part of the Phase 0 diff:

- No `pyproject.toml`, `requirements.txt`, or lockfile. The dependency pinning discipline is described in [DEPLOYMENT_STRATEGY.md](./DEPLOYMENT_STRATEGY.md) and [TECHNICAL_DEBT_PREVENTION.md](./TECHNICAL_DEBT_PREVENTION.md), but no package manifest is committed yet.
- No `Dockerfile` or `docker-compose.yml`. The deployment unit and Compose topology are specified in [DEPLOYMENT_STRATEGY.md](./DEPLOYMENT_STRATEGY.md); the Phase 1 implementation commit authors them against that specification.
- No `alembic.ini` or `alembic/` tree. The migration discipline and the expand-migrate-contract rule live in [SYSTEM_ARCHITECTURE.md](./SYSTEM_ARCHITECTURE.md) and [TECHNICAL_DEBT_PREVENTION.md](./TECHNICAL_DEBT_PREVENTION.md); the first migration arrives with the Phase 1 schema.
- No `.github/workflows/`. The CI pipeline shape (ruff, mypy, pytest with service containers, docker build without push) is specified in [DEPLOYMENT_STRATEGY.md](./DEPLOYMENT_STRATEGY.md) and is wired as part of the Phase 1 scaffolding feature.

## How Phase 0 was produced

The repository is a fresh git history with the following shape:

- `main` carries a single seed commit that creates the repository: a minimum README placeholder and a forward-looking `.gitignore`. This is a one-time direct-to-`main` action to establish a merge base for subsequent pull requests; no further direct-to-`main` commits are permitted.
- The `phase-0-architecture` branch is cut from the seed commit. Every Phase 0 design document lands on this branch as its own commit with a Conventional Commits message in the `docs:` type. The final commit on this branch rewrites this README into the index you are reading.
- Commits are small and reviewable. There is no squash of the planned per-document commits; the commit history of the branch is the audit trail of how the design was assembled.
- No emoji, no em dashes, no placeholder markers of any kind appear in any document. Every deferred decision is named with the phase it belongs to and the reason it is deferred.
- Every document carries a `## Purpose` section and a `## Assumptions` section. Documents whose domain admits meaningful rejected alternatives also carry a `## Rejected alternatives` or `## Tradeoffs` section. These are structural properties of the set, not stylistic conventions, and are verified before the Phase 0 branch is opened for review.

The contribution rules the project commits to (feature branches, small reviewable commits, no direct-to-`main` after the seed, deterministic CI, clean commit history) are documented in the engineering-workflow section of [PHASED_ROADMAP.md](./PHASED_ROADMAP.md).

The cross-document consistency contract is enforced by review. A PR that changes a canonical name, a lifecycle state, or a domain-entity field updates every document that references it in the same PR, or the PR is rejected. This is described in more detail in the Review discipline section of [TECHNICAL_DEBT_PREVENTION.md](./TECHNICAL_DEBT_PREVENTION.md).

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

Phase 0 closes with a pull request from `phase-0-architecture` into `main`. The sequence is:

1. Open the pull request from `phase-0-architecture` to `main`. The PR description links each of the ten design documents and summarizes the decisions locked by Phase 0.
2. Review. Every reviewer confirms that the documents are internally consistent with the canonical vocabulary, that no forbidden implementation file has been introduced, and that every document carries a Purpose and an Assumptions section.
3. Approval gate. Phase 1 implementation is blocked until the pull request is approved and merged. Opening Phase 1 work before the gate is a process failure, not a shortcut.
4. Merge. The branch merges into `main` without a squash so the per-document commit history is preserved. The Phase 0 tag marks the merge commit.

Phase 1 work then begins on its own feature branches as described in [PHASED_ROADMAP.md](./PHASED_ROADMAP.md). The first Phase 1 feature scaffolds the repository tree specified in SYSTEM_ARCHITECTURE.md section 4 and wires the CI pipeline specified in DEPLOYMENT_STRATEGY.md; subsequent features implement the lifecycles in the order the roadmap commits to.

Until the approval gate clears, this repository's `main` branch contains only the seed commit. The design is complete; the platform is not yet built.
