# Worker Architecture

## Process Topology

InsuranceOps AI runs as a single Docker image with two process types:

```mermaid
flowchart TB
    subgraph "Docker Image: insuranceops-ai"
        subgraph "API Process (uvicorn)"
            api[FastAPI app<br/>port 8000]
            api_mw[Middleware:<br/>correlation-id, size-limit, timing]
            api_routes[Routes:<br/>/v1/documents, /v1/workflow-runs,<br/>/v1/escalations, /healthz, /readyz, /metrics]
        end

        subgraph "Worker Process"
            loop[Worker Loop<br/>claim-process-ACK]
            reaper[Reaper Loop<br/>reclaim stuck tasks]
            scheduler[Scheduler Loop<br/>mature delayed tasks]
            outbox[Outbox Relay<br/>drain tasks_outbox to Redis]
            verifier[Audit Verifier Loop<br/>sample chain verification]
        end
    end

    subgraph "State Stores"
        pg[(PostgreSQL<br/>source of truth)]
        redis[(Redis<br/>queue + coordination)]
        fs[(Filesystem<br/>document payloads)]
    end

    api --> pg
    api --> redis
    loop --> pg
    loop --> redis
    reaper --> redis
    scheduler --> redis
    outbox --> pg
    outbox --> redis
    verifier --> pg
    loop --> fs
    api --> fs
```

## Worker Concurrent Tasks

The worker process runs five concurrent async tasks, each independently controllable:

| Task | Purpose | Interval | Advisory Lock | CLI Flag to Disable |
|------|---------|----------|---------------|---------------------|
| Worker Loop | Claim and process tasks | Continuous (5s block timeout) | No | N/A (always runs) |
| Reaper | Reclaim stuck inflight tasks | 15s | No | `--no-reaper` |
| Scheduler | Promote delayed tasks to ready | 5s | Yes (Postgres) | `--no-scheduler` |
| Outbox Relay | Drain tasks_outbox to Redis | 2s | Yes (Postgres) | `--no-outbox` |
| Audit Verifier | Verify hash chains on sample | 3600s (configurable) | No | `--no-audit-verifier` |

## Worker Loop: Claim-Process-ACK

```mermaid
sequenceDiagram
    participant R as Redis
    participant W as Worker
    participant DB as PostgreSQL
    participant H as Step Handler

    W->>R: BRPOPLPUSH ready -> inflight:worker-id
    R-->>W: task payload (or timeout)

    W->>DB: Load StepAttempt, Step, WorkflowRun
    W->>DB: UPDATE step_attempt SET state='in_progress'

    W->>H: handler.handle(context, session)
    H-->>W: StepResult (succeeded/failed_retryable/failed_terminal/escalate)

    W->>DB: BEGIN: update attempt + step + audit_event + outbox
    W->>DB: COMMIT

    W->>R: LREM inflight:worker-id (ACK)
```

## Graceful Shutdown

On SIGTERM/SIGINT:
1. Shutdown event is set
2. All loop tasks check the event and exit their wait cycles
3. In-progress task finishes its current handler call
4. All tasks are cancelled
5. Redis and DB connections are closed
6. Process exits 0
