"""Workflow orchestrator: manages workflow run lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.audit.chain import append_audit_event
from insuranceops.observability.metrics import workflow_run_duration_seconds
from insuranceops.storage.models import (
    EscalationCaseModel,
    StepAttemptModel,
    StepModel,
    TasksOutboxModel,
    WorkflowRunDocumentModel,
    WorkflowRunModel,
)
from insuranceops.storage.repositories.escalations import EscalationRepository
from insuranceops.storage.repositories.step_attempts import StepAttemptRepository
from insuranceops.storage.repositories.steps import StepRepository
from insuranceops.storage.repositories.workflow_runs import WorkflowRunRepository
from insuranceops.workflows.registry import registry
from insuranceops.workflows.retry import RetryPolicy, compute_backoff_delay
from insuranceops.workflows.steps.base import StepResult


class WorkflowOrchestrator:
    """Central coordination logic for workflow run lifecycle.

    Handles:
    - Starting new workflow runs
    - Advancing runs to the next step on success
    - Retrying steps with exponential backoff
    - Creating escalation cases on failure
    - Resuming after human resolution
    - Cancelling workflow runs
    """

    async def start_workflow_run(
        self,
        session: AsyncSession,
        workflow_name: str,
        workflow_version: str,
        document_ids: list[UUID],
        actor: str,
        correlation_id: str,
        deadline_seconds: int | None = None,
    ) -> WorkflowRunModel:
        """Start a new workflow run.

        Creates the WorkflowRun, Step rows, first StepAttempt,
        outbox entry, and audit event.

        Args:
            session: Active async session within a transaction.
            workflow_name: Name of the workflow to run.
            workflow_version: Version of the workflow.
            document_ids: Document IDs to process.
            actor: Actor string initiating the run.
            correlation_id: Correlation ID for tracing.
            deadline_seconds: Override for workflow deadline (uses definition default if None).

        Returns:
            The created WorkflowRunModel.

        Raises:
            ValueError: If the workflow definition is not found.
        """
        definition = registry.get(workflow_name, workflow_version)
        if definition is None:
            raise ValueError(f"Workflow definition not found: {workflow_name} {workflow_version}")

        now = datetime.now(UTC)
        effective_deadline = deadline_seconds or definition.deadline_seconds

        # Create WorkflowRun
        workflow_run_id = uuid.uuid4()
        workflow_run = WorkflowRunModel(
            workflow_run_id=workflow_run_id,
            workflow_name=workflow_name,
            workflow_version=workflow_version,
            state="pending",
            version=0,
            created_at=now,
            updated_at=now,
            deadline_at=now + timedelta(seconds=effective_deadline),
            created_by=actor,
        )
        run_repo = WorkflowRunRepository(session)
        await run_repo.create(workflow_run)

        # Create workflow_run_documents associations
        for doc_id in document_ids:
            assoc = WorkflowRunDocumentModel(
                workflow_run_id=workflow_run_id,
                document_id=doc_id,
                attached_at=now,
            )
            session.add(assoc)
        await session.flush()

        # Create Step rows for all steps
        step_repo = StepRepository(session)
        step_models: list[StepModel] = []
        for step_def in definition.steps:
            step_id = uuid.uuid4()
            step_model = StepModel(
                step_id=step_id,
                workflow_run_id=workflow_run_id,
                step_name=step_def.step_name,
                step_index=step_def.step_index,
                state="queued",
                max_attempts=step_def.max_attempts,
                escalate_on_failure=step_def.escalate_on_failure,
                retry_policy={
                    "base_delay_s": step_def.retry_policy.base_delay_s,
                    "cap_s": step_def.retry_policy.cap_s,
                    "jitter": step_def.retry_policy.jitter,
                },
                created_at=now,
            )
            step_models.append(step_model)

        await step_repo.create_many(step_models)

        # Create first StepAttempt for step_index=0
        first_step = step_models[0]
        attempt_repo = StepAttemptRepository(session)
        first_attempt_id = uuid.uuid4()
        first_attempt = StepAttemptModel(
            step_attempt_id=first_attempt_id,
            step_id=first_step.step_id,
            step_attempt_number=1,
            state="queued",
            origin="system",
            created_at=now,
        )
        await attempt_repo.create(first_attempt)

        # Update current_step_id
        workflow_run.current_step_id = first_step.step_id
        await session.flush()

        # Insert tasks_outbox row for the first step
        outbox_entry = TasksOutboxModel(
            workflow_run_id=workflow_run_id,
            step_id=first_step.step_id,
            step_attempt_id=first_attempt_id,
            payload={
                "workflow_run_id": str(workflow_run_id),
                "workflow_name": workflow_name,
                "workflow_version": workflow_version,
                "step_id": str(first_step.step_id),
                "step_attempt_id": str(first_attempt_id),
                "step_name": first_step.step_name,
                "handler_name": definition.steps[0].handler_name,
                "correlation_id": correlation_id,
                "document_ids": [str(d) for d in document_ids],
            },
            scheduled_for=now,
            created_at=now,
        )
        session.add(outbox_entry)
        await session.flush()

        # Write AuditEvent
        await append_audit_event(
            session=session,
            workflow_run_id=workflow_run_id,
            event_type="workflow_run.started",
            actor=actor,
            payload={
                "workflow_name": workflow_name,
                "workflow_version": workflow_version,
                "document_ids": [str(d) for d in document_ids],
                "correlation_id": correlation_id,
                "deadline_seconds": effective_deadline,
            },
        )

        # Transition WorkflowRun to running
        workflow_run.state = "running"
        workflow_run.version = 1
        workflow_run.updated_at = datetime.now(UTC)
        await session.flush()

        return workflow_run

    async def advance_workflow(
        self,
        session: AsyncSession,
        workflow_run_id: UUID,
        completed_step_name: str,
        step_result: StepResult,
    ) -> str:
        """Advance a workflow run based on the outcome of a completed step.

        Handles success (advance to next step), retryable failure (schedule retry),
        terminal failure (fail or escalate), and explicit escalation.

        Args:
            session: Active async session within a transaction.
            workflow_run_id: The workflow run to advance.
            completed_step_name: Name of the step that just completed.
            step_result: The result from the step handler.

        Returns:
            The new WorkflowRun state as a string.
        """
        run_repo = WorkflowRunRepository(session)
        step_repo = StepRepository(session)

        workflow_run = await run_repo.get_by_id(workflow_run_id)
        if workflow_run is None:
            raise ValueError(f"WorkflowRun not found: {workflow_run_id}")

        steps = await step_repo.list_by_workflow_run(workflow_run_id)
        current_step = await step_repo.get_by_run_and_name(workflow_run_id, completed_step_name)
        if current_step is None:
            raise ValueError(f"Step not found: {completed_step_name} in run {workflow_run_id}")

        now = datetime.now(UTC)

        if step_result.status == "succeeded":
            return await self._handle_succeeded(
                session=session,
                workflow_run=workflow_run,
                steps=steps,
                current_step=current_step,
                step_result=step_result,
                now=now,
            )
        elif step_result.status == "failed_retryable":
            return await self._handle_failed_retryable(
                session=session,
                workflow_run=workflow_run,
                current_step=current_step,
                step_result=step_result,
                now=now,
            )
        elif step_result.status == "failed_terminal":
            return await self._handle_failed_terminal(
                session=session,
                workflow_run=workflow_run,
                current_step=current_step,
                step_result=step_result,
                now=now,
            )
        elif step_result.status == "escalate":
            return await self._handle_escalate(
                session=session,
                workflow_run=workflow_run,
                current_step=current_step,
                step_result=step_result,
                now=now,
            )
        else:
            raise ValueError(f"Unknown step result status: {step_result.status}")

    async def _get_document_ids(self, session: AsyncSession, workflow_run_id: UUID) -> list[str]:
        """Get document IDs associated with a workflow run.

        Args:
            session: Active async session.
            workflow_run_id: The workflow run to query.

        Returns:
            List of document ID strings.
        """
        result = await session.execute(
            select(WorkflowRunDocumentModel.document_id).where(
                WorkflowRunDocumentModel.workflow_run_id == workflow_run_id
            )
        )
        return [str(row) for row in result.scalars().all()]

    async def _handle_succeeded(
        self,
        session: AsyncSession,
        workflow_run: WorkflowRunModel,
        steps: Any,
        current_step: StepModel,
        step_result: StepResult,
        now: datetime,
    ) -> str:
        """Handle a succeeded step: advance to next step or complete."""
        attempt_repo = StepAttemptRepository(session)

        # Mark current step as succeeded
        current_step.state = "succeeded"
        current_step.ended_at = now
        await session.flush()

        # Find next step by step_index
        next_step: StepModel | None = None
        for step in steps:
            if step.step_index == current_step.step_index + 1:
                next_step = step
                break

        if next_step is None:
            # No more steps - workflow is complete
            workflow_run.state = "completed"
            workflow_run.version += 1
            workflow_run.updated_at = now
            await session.flush()

            # Observe workflow run duration
            duration = (now - workflow_run.created_at).total_seconds()
            workflow_run_duration_seconds.labels(
                workflow_name=workflow_run.workflow_name,
                workflow_version=workflow_run.workflow_version,
                terminal_state="completed",
            ).observe(duration)

            await append_audit_event(
                session=session,
                workflow_run_id=workflow_run.workflow_run_id,
                event_type="workflow_run.completed",
                actor="worker:orchestrator",
                payload={
                    "final_step": current_step.step_name,
                },
                step_id=current_step.step_id,
            )

            return "completed"

        # Create StepAttempt for the next step
        next_attempt_id = uuid.uuid4()
        next_attempt = StepAttemptModel(
            step_attempt_id=next_attempt_id,
            step_id=next_step.step_id,
            step_attempt_number=1,
            state="queued",
            origin="system",
            created_at=now,
        )
        await attempt_repo.create(next_attempt)

        # Update current_step_id
        workflow_run.current_step_id = next_step.step_id
        workflow_run.updated_at = now
        await session.flush()

        # Look up workflow definition for handler_name
        definition = registry.get(workflow_run.workflow_name, workflow_run.workflow_version)
        handler_name = next_step.step_name
        if definition is not None:
            for step_def in definition.steps:
                if step_def.step_name == next_step.step_name:
                    handler_name = step_def.handler_name
                    break

        # Get document_ids for the workflow run
        document_ids = await self._get_document_ids(session, workflow_run.workflow_run_id)

        # Insert outbox row for next step
        outbox_entry = TasksOutboxModel(
            workflow_run_id=workflow_run.workflow_run_id,
            step_id=next_step.step_id,
            step_attempt_id=next_attempt_id,
            payload={
                "workflow_run_id": str(workflow_run.workflow_run_id),
                "workflow_name": workflow_run.workflow_name,
                "workflow_version": workflow_run.workflow_version,
                "step_id": str(next_step.step_id),
                "step_attempt_id": str(next_attempt_id),
                "step_name": next_step.step_name,
                "handler_name": handler_name,
                "correlation_id": "",
                "document_ids": document_ids,
            },
            scheduled_for=now,
            created_at=now,
        )
        session.add(outbox_entry)
        await session.flush()

        await append_audit_event(
            session=session,
            workflow_run_id=workflow_run.workflow_run_id,
            event_type="step.advanced",
            actor="worker:orchestrator",
            payload={
                "from_step": current_step.step_name,
                "to_step": next_step.step_name,
            },
            step_id=next_step.step_id,
            step_attempt_id=next_attempt_id,
        )

        return "running"

    async def _handle_failed_retryable(
        self,
        session: AsyncSession,
        workflow_run: WorkflowRunModel,
        current_step: StepModel,
        step_result: StepResult,
        now: datetime,
    ) -> str:
        """Handle a retryable failure: retry or escalate/fail."""
        attempt_repo = StepAttemptRepository(session)

        # Count existing attempts
        attempts = await attempt_repo.list_by_step(current_step.step_id)
        attempt_count = len(attempts)

        if attempt_count < current_step.max_attempts:
            # Compute backoff delay
            retry_policy_data = current_step.retry_policy or {}
            policy = RetryPolicy(
                base_delay_s=retry_policy_data.get("base_delay_s", 2.0),
                cap_s=retry_policy_data.get("cap_s", 60.0),
                jitter=retry_policy_data.get("jitter", "full"),
            )
            delay = compute_backoff_delay(policy, attempt_count)
            scheduled_for = now + timedelta(seconds=delay)

            # Create new StepAttempt
            new_attempt_id = uuid.uuid4()
            new_attempt = StepAttemptModel(
                step_attempt_id=new_attempt_id,
                step_id=current_step.step_id,
                step_attempt_number=attempt_count + 1,
                state="queued",
                origin="system",
                scheduled_for=scheduled_for,
                created_at=now,
            )
            await attempt_repo.create(new_attempt)

            # Update step state
            current_step.state = "failed_retryable"
            await session.flush()

            # Look up handler_name
            definition = registry.get(workflow_run.workflow_name, workflow_run.workflow_version)
            handler_name = current_step.step_name
            if definition is not None:
                for step_def in definition.steps:
                    if step_def.step_name == current_step.step_name:
                        handler_name = step_def.handler_name
                        break

            # Get document_ids for the workflow run
            document_ids = await self._get_document_ids(session, workflow_run.workflow_run_id)

            # Insert outbox row with scheduled_for
            outbox_entry = TasksOutboxModel(
                workflow_run_id=workflow_run.workflow_run_id,
                step_id=current_step.step_id,
                step_attempt_id=new_attempt_id,
                payload={
                    "workflow_run_id": str(workflow_run.workflow_run_id),
                    "workflow_name": workflow_run.workflow_name,
                    "workflow_version": workflow_run.workflow_version,
                    "step_id": str(current_step.step_id),
                    "step_attempt_id": str(new_attempt_id),
                    "step_name": current_step.step_name,
                    "handler_name": handler_name,
                    "correlation_id": "",
                    "document_ids": document_ids,
                },
                scheduled_for=scheduled_for,
                created_at=now,
            )
            session.add(outbox_entry)
            await session.flush()

            await append_audit_event(
                session=session,
                workflow_run_id=workflow_run.workflow_run_id,
                event_type="step_attempt.retry_scheduled",
                actor="worker:orchestrator",
                payload={
                    "step_name": current_step.step_name,
                    "attempt_number": attempt_count + 1,
                    "delay_seconds": delay,
                    "error_code": step_result.error_code,
                    "error_detail": step_result.error_detail,
                },
                step_id=current_step.step_id,
                step_attempt_id=new_attempt_id,
            )

            return "running"

        # At max attempts: treat as failed_terminal
        return await self._handle_failed_terminal(
            session=session,
            workflow_run=workflow_run,
            current_step=current_step,
            step_result=step_result,
            now=now,
        )

    async def _handle_failed_terminal(
        self,
        session: AsyncSession,
        workflow_run: WorkflowRunModel,
        current_step: StepModel,
        step_result: StepResult,
        now: datetime,
    ) -> str:
        """Handle a terminal failure: escalate or fail the workflow."""
        # Mark step as failed_terminal
        current_step.state = "failed_terminal"
        current_step.ended_at = now
        await session.flush()

        if current_step.escalate_on_failure:
            # Create EscalationCase
            escalation_id = uuid.uuid4()
            escalation = EscalationCaseModel(
                escalation_id=escalation_id,
                workflow_run_id=workflow_run.workflow_run_id,
                step_id=current_step.step_id,
                state="open",
                reason_code=step_result.error_code or "STEP_FAILED_TERMINAL",
                reason_detail=step_result.error_detail,
                expires_at=now + timedelta(hours=24),
                created_at=now,
            )
            esc_repo = EscalationRepository(session)
            await esc_repo.create(escalation)

            # Transition workflow to awaiting_human
            workflow_run.state = "awaiting_human"
            workflow_run.version += 1
            workflow_run.updated_at = now
            workflow_run.last_error_code = step_result.error_code
            workflow_run.last_error_detail = step_result.error_detail
            await session.flush()

            await append_audit_event(
                session=session,
                workflow_run_id=workflow_run.workflow_run_id,
                event_type="escalation.created",
                actor="worker:orchestrator",
                payload={
                    "escalation_id": str(escalation_id),
                    "step_name": current_step.step_name,
                    "reason_code": step_result.error_code or "STEP_FAILED_TERMINAL",
                    "reason_detail": step_result.error_detail,
                },
                step_id=current_step.step_id,
            )

            return "awaiting_human"

        # No escalation: fail the workflow
        workflow_run.state = "failed"
        workflow_run.version += 1
        workflow_run.updated_at = now
        workflow_run.last_error_code = step_result.error_code
        workflow_run.last_error_detail = step_result.error_detail
        await session.flush()

        # Observe workflow run duration
        duration = (now - workflow_run.created_at).total_seconds()
        workflow_run_duration_seconds.labels(
            workflow_name=workflow_run.workflow_name,
            workflow_version=workflow_run.workflow_version,
            terminal_state="failed",
        ).observe(duration)

        await append_audit_event(
            session=session,
            workflow_run_id=workflow_run.workflow_run_id,
            event_type="workflow_run.failed",
            actor="worker:orchestrator",
            payload={
                "step_name": current_step.step_name,
                "error_code": step_result.error_code,
                "error_detail": step_result.error_detail,
            },
            step_id=current_step.step_id,
        )

        return "failed"

    async def _handle_escalate(
        self,
        session: AsyncSession,
        workflow_run: WorkflowRunModel,
        current_step: StepModel,
        step_result: StepResult,
        now: datetime,
    ) -> str:
        """Handle an explicit escalation request from a step."""
        # Create EscalationCase
        escalation_id = uuid.uuid4()
        escalation = EscalationCaseModel(
            escalation_id=escalation_id,
            workflow_run_id=workflow_run.workflow_run_id,
            step_id=current_step.step_id,
            state="open",
            reason_code=step_result.error_code or "STEP_ESCALATED",
            reason_detail=step_result.error_detail,
            expires_at=now + timedelta(hours=24),
            created_at=now,
        )
        esc_repo = EscalationRepository(session)
        await esc_repo.create(escalation)

        # Transition workflow to awaiting_human
        workflow_run.state = "awaiting_human"
        workflow_run.version += 1
        workflow_run.updated_at = now
        workflow_run.last_error_code = step_result.error_code
        workflow_run.last_error_detail = step_result.error_detail
        await session.flush()

        await append_audit_event(
            session=session,
            workflow_run_id=workflow_run.workflow_run_id,
            event_type="escalation.created",
            actor="worker:orchestrator",
            payload={
                "escalation_id": str(escalation_id),
                "step_name": current_step.step_name,
                "reason_code": step_result.error_code or "STEP_ESCALATED",
                "reason_detail": step_result.error_detail,
            },
            step_id=current_step.step_id,
        )

        return "awaiting_human"

    async def resume_after_escalation(
        self,
        session: AsyncSession,
        escalation_id: UUID,
        resolution_payload: dict[str, Any],
        actor: str,
    ) -> str:
        """Resume a workflow after escalation resolution.

        Creates a synthetic human-origin StepAttempt, transitions back to running,
        and advances to the next step.

        Args:
            session: Active async session within a transaction.
            escalation_id: The escalation case being resolved.
            resolution_payload: Data provided by the human resolver.
            actor: Actor string for the resolver.

        Returns:
            The new WorkflowRun state.

        Raises:
            ValueError: If the escalation or related entities are not found.
        """
        esc_repo = EscalationRepository(session)
        step_repo = StepRepository(session)
        run_repo = WorkflowRunRepository(session)
        attempt_repo = StepAttemptRepository(session)

        escalation = await esc_repo.get_by_id(escalation_id)
        if escalation is None:
            raise ValueError(f"EscalationCase not found: {escalation_id}")

        current_step = await step_repo.get_by_id(escalation.step_id)
        if current_step is None:
            raise ValueError(f"Step not found: {escalation.step_id}")

        workflow_run = await run_repo.get_by_id(escalation.workflow_run_id)
        if workflow_run is None:
            raise ValueError(f"WorkflowRun not found: {escalation.workflow_run_id}")

        now = datetime.now(UTC)

        # Resolve the escalation
        escalation.state = "resolved"
        escalation.resolved_by = actor
        escalation.resolved_at = now
        escalation.resolution_payload = resolution_payload
        await session.flush()

        # Create synthetic StepAttempt (origin=human, state=succeeded)
        existing_attempts = await attempt_repo.list_by_step(current_step.step_id)
        new_attempt_number = len(existing_attempts) + 1
        synthetic_attempt_id = uuid.uuid4()
        synthetic_attempt = StepAttemptModel(
            step_attempt_id=synthetic_attempt_id,
            step_id=current_step.step_id,
            step_attempt_number=new_attempt_number,
            state="succeeded",
            origin="human",
            started_at=now,
            ended_at=now,
            created_at=now,
            output_ref=None,
        )
        await attempt_repo.create(synthetic_attempt)

        # Mark step as succeeded
        current_step.state = "succeeded"
        current_step.ended_at = now
        await session.flush()

        # Transition WorkflowRun awaiting_human -> running
        workflow_run.state = "running"
        workflow_run.version += 1
        workflow_run.updated_at = now
        workflow_run.last_error_code = None
        workflow_run.last_error_detail = None
        await session.flush()

        await append_audit_event(
            session=session,
            workflow_run_id=workflow_run.workflow_run_id,
            event_type="escalation.resolved",
            actor=actor,
            payload={
                "escalation_id": str(escalation_id),
                "step_name": current_step.step_name,
                "resolution_payload": resolution_payload,
            },
            step_id=current_step.step_id,
            step_attempt_id=synthetic_attempt_id,
        )

        # Advance to next step
        steps = await step_repo.list_by_workflow_run(workflow_run.workflow_run_id)
        # Use _handle_succeeded to advance (reuse existing logic)
        result = await self._handle_succeeded(
            session=session,
            workflow_run=workflow_run,
            steps=steps,
            current_step=current_step,
            step_result=StepResult(status="succeeded", output=resolution_payload),
            now=now,
        )

        return result

    async def cancel_workflow(
        self,
        session: AsyncSession,
        workflow_run_id: UUID,
        actor: str,
        reason: str | None = None,
    ) -> None:
        """Cancel a workflow run.

        Validates the state is cancellable (running or awaiting_human),
        then transitions to cancelled.

        Args:
            session: Active async session within a transaction.
            workflow_run_id: The workflow run to cancel.
            actor: Actor string performing the cancellation.
            reason: Optional reason for cancellation.

        Raises:
            ValueError: If the workflow is not in a cancellable state or not found.
        """
        run_repo = WorkflowRunRepository(session)
        workflow_run = await run_repo.get_by_id(workflow_run_id)

        if workflow_run is None:
            raise ValueError(f"WorkflowRun not found: {workflow_run_id}")

        cancellable_states = {"running", "awaiting_human"}
        if workflow_run.state not in cancellable_states:
            raise ValueError(
                f"Cannot cancel WorkflowRun in state '{workflow_run.state}'. "
                f"Cancellable states: {sorted(cancellable_states)}"
            )

        now = datetime.now(UTC)
        previous_state = workflow_run.state
        workflow_run.state = "cancelled"
        workflow_run.version += 1
        workflow_run.updated_at = now
        await session.flush()

        # Observe workflow run duration
        duration = (now - workflow_run.created_at).total_seconds()
        workflow_run_duration_seconds.labels(
            workflow_name=workflow_run.workflow_name,
            workflow_version=workflow_run.workflow_version,
            terminal_state="cancelled",
        ).observe(duration)

        await append_audit_event(
            session=session,
            workflow_run_id=workflow_run_id,
            event_type="workflow_run.cancelled",
            actor=actor,
            payload={
                "reason": reason,
                "previous_state": previous_state,
            },
        )
