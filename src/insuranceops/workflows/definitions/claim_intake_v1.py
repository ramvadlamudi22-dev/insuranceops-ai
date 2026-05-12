"""claim_intake_v1 workflow definition."""

from __future__ import annotations

from insuranceops.workflows.registry import StepDefinition, WorkflowDefinition, registry
from insuranceops.workflows.retry import RetryPolicy

claim_intake_v1 = WorkflowDefinition(
    workflow_name="claim_intake",
    workflow_version="v1",
    deadline_seconds=3600,
    steps=(
        StepDefinition(
            step_name="ingest",
            handler_name="ingest",
            step_index=0,
            max_attempts=1,
            escalate_on_failure=False,
            retry_policy=RetryPolicy(),
            timeout_seconds=30,
        ),
        StepDefinition(
            step_name="extract",
            handler_name="extract",
            step_index=1,
            max_attempts=3,
            escalate_on_failure=True,
            retry_policy=RetryPolicy(base_delay_s=2.0, cap_s=30.0, jitter="full"),
            timeout_seconds=30,
        ),
        StepDefinition(
            step_name="validate",
            handler_name="validate",
            step_index=2,
            max_attempts=1,
            escalate_on_failure=True,
            retry_policy=RetryPolicy(),
            timeout_seconds=30,
        ),
        StepDefinition(
            step_name="route",
            handler_name="route",
            step_index=3,
            max_attempts=2,
            escalate_on_failure=False,
            retry_policy=RetryPolicy(),
            timeout_seconds=30,
        ),
        StepDefinition(
            step_name="complete",
            handler_name="complete",
            step_index=4,
            max_attempts=1,
            escalate_on_failure=False,
            retry_policy=RetryPolicy(),
            timeout_seconds=30,
        ),
    ),
)

# Register at module import time
registry.register(claim_intake_v1)
