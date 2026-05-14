# Workflow Lifecycle

## WorkflowRun State Machine

Every WorkflowRun traverses a deterministic state machine. Only the transitions shown below are legal; any other transition is rejected and emits no AuditEvent.

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> running : first Task claimed by worker
    pending --> cancelled : supervisor cancel

    running --> awaiting_human : Step requests escalation
    running --> completed : all Steps succeeded
    running --> failed : terminal Step failure (no escalation)
    running --> cancelled : supervisor cancel

    awaiting_human --> running : EscalationCase resolved
    awaiting_human --> failed : EscalationCase rejected or expired
    awaiting_human --> cancelled : supervisor cancel

    completed --> [*]
    failed --> [*]
    cancelled --> [*]
```

## Step Execution Flow

Each Step within a WorkflowRun follows this sequence:

```mermaid
flowchart TD
    A[StepAttempt created<br/>state: queued] --> B[Task enqueued via outbox]
    B --> C[Worker claims Task<br/>state: in_progress]
    C --> D{Handler outcome}

    D -->|succeeded| E[Step succeeded]
    D -->|failed_retryable| F{attempts < max?}
    D -->|failed_terminal| G{escalate_on_failure?}
    D -->|escalate| H[Create EscalationCase]

    F -->|yes| I[Schedule retry with backoff]
    F -->|no| G

    G -->|yes| H
    G -->|no| J[WorkflowRun failed]

    I --> A
    E --> K{More steps?}
    K -->|yes| A
    K -->|no| L[WorkflowRun completed]

    H --> M[WorkflowRun awaiting_human]
```

## claim_intake_v1 Workflow Steps

The default workflow executes five steps in order:

```mermaid
flowchart LR
    ingest[ingest] --> extract[extract]
    extract --> validate[validate]
    validate --> route[route]
    route --> complete[complete]
```

| Step | Handler | Max Attempts | Escalate on Failure |
|------|---------|--------------|---------------------|
| ingest | ingest | 1 | No |
| extract | extract | 3 | Yes |
| validate | validate | 1 | Yes |
| route | route | 2 | No |
| complete | complete | 1 | No |
