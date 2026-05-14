# Audit Chain

## Hash-Chain Construction

Every state transition in a WorkflowRun produces exactly one AuditEvent. Events are linked into a per-run hash chain that makes tampering detectable.

```mermaid
flowchart LR
    subgraph "WorkflowRun: abc-123"
        E1[Event 1<br/>seq=1<br/>workflow_run.started]
        E2[Event 2<br/>seq=2<br/>step_attempt.succeeded]
        E3[Event 3<br/>seq=3<br/>step.advanced]
        E4[Event 4<br/>seq=4<br/>workflow_run.completed]
    end

    E1 -->|event_hash| E2
    E2 -->|event_hash| E3
    E3 -->|event_hash| E4

    style E1 fill:#e1f5fe
    style E4 fill:#e8f5e9
```

Each event stores:
- `prev_event_hash`: SHA-256 of the previous event's `event_hash` (NULL for first)
- `event_hash`: SHA-256 of the current event's canonical content

## Hash Computation Formula

```
event_hash = SHA-256(
    audit_event_id.bytes ||
    workflow_run_id.bytes ||
    actor.encode("utf-8") ||
    event_type.encode("utf-8") ||
    canonical_json(payload).encode("utf-8") ||
    occurred_at.isoformat().encode("utf-8") ||
    coalesce(prev_event_hash, b"")
)
```

`canonical_json` = sorted keys, no whitespace, `separators=(",", ":")`.

## Verification Flow

```mermaid
flowchart TD
    A[Load all AuditEvents<br/>ORDER BY seq_in_run] --> B{First event?}

    B -->|yes| C[Assert prev_event_hash IS NULL]
    B -->|no| D[Assert prev_event_hash == prior.event_hash]

    C --> E[Recompute event_hash from row content]
    D --> E

    E --> F{Computed == stored?}

    F -->|yes| G{More events?}
    F -->|no| H[MISMATCH DETECTED<br/>report index + details<br/>increment metric]

    G -->|yes| B
    G -->|no| I[CHAIN VALID]
```

## Tamper Detection

If any field of any AuditEvent row is modified after insertion:

1. The recomputed `event_hash` will not match the stored value
2. All subsequent events' `prev_event_hash` will also mismatch
3. The verifier reports the **first** broken link

This detects:
- Payload modification (changing what happened)
- Actor modification (changing who did it)
- Timestamp modification (changing when it happened)
- Row deletion (gap in `seq_in_run`)
- Row insertion (chain fork)

## Immutability Enforcement

| Control | Mechanism |
|---------|-----------|
| No UPDATE on audit_events | DB role `app_rw` has INSERT + SELECT only |
| No DELETE on audit_events | DB role `app_rw` lacks DELETE |
| Serialized writes per run | `SELECT ... FOR UPDATE` on workflow_runs row |
| Monotonic seq_in_run | UNIQUE constraint on `(workflow_run_id, seq_in_run)` |

## Operational Commands

```bash
# Verify a single workflow run
./scripts/opsctl audit verify --workflow-run-id <UUID>

# Batch verify terminal runs
./scripts/opsctl audit verify-batch --sample-size 50 --state completed
```

The scheduled audit verifier runs automatically in the worker process (default: every hour, sample of 10 runs). Mismatches increment `audit_chain_mismatches_total` and log at CRITICAL level.
