"""Complete step handler: signals workflow completion with AI summary."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.ai.mock_provider import MockAIProvider
from insuranceops.ai.summarization import SummarizationConfig, summarize_workflow
from insuranceops.observability.logging import get_logger
from insuranceops.workflows.steps.base import StepContext, StepResult

logger = get_logger("workflow.steps.complete")


class CompleteStepHandler:
    """Signals the workflow orchestrator to transition to completed state.

    Generates an AI-assisted workflow summary on completion for
    operator dashboards. Summary generation is fail-safe: if it fails,
    the workflow still completes successfully.
    """

    def __init__(self) -> None:
        self._ai_provider = MockAIProvider()
        self._summarization_config = SummarizationConfig()

    async def handle(self, context: StepContext, session: AsyncSession) -> StepResult:
        """Signal workflow completion and generate summary.

        Args:
            context: Step context with previous_outputs from all steps.
            session: Active database session.

        Returns:
            StepResult with succeeded status and workflow summary.
        """
        # Gather extracted fields from previous steps
        extracted_fields: dict[str, Any] = {}
        extract_output = context.previous_outputs.get("extract")
        if extract_output and isinstance(extract_output, dict):
            raw_fields = extract_output.get("fields", {})
            extracted_fields = {name: data.get("value", "") for name, data in raw_fields.items()}

        # Generate workflow summary (fail-safe)
        summary_text = ""
        try:
            summary_result = await summarize_workflow(
                ai_provider=self._ai_provider,
                config=self._summarization_config,
                workflow_name=context.workflow_name,
                workflow_version="v1",
                state="completed",
                steps_completed=len(context.previous_outputs) + 1,
                duration_description="completed",
                extracted_fields=extracted_fields,
            )
            summary_text = summary_result.summary_text
        except Exception as e:
            # Fail-safe: summary generation failure does not block completion
            logger.warning("complete_summary_failed", error=str(e))

        return StepResult(
            status="succeeded",
            output={
                "completed": True,
                "summary": summary_text,
                "fields_extracted": len(extracted_fields),
            },
        )
