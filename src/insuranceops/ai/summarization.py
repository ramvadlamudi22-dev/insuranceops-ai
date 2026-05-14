"""AI-assisted summarization for workflows, claims, and escalations.

Provides configurable summarization with:
- Workflow summary: end-to-end run summary for operator dashboards
- Claim summary: structured claim intake summary
- Escalation summary: context for human reviewers

All summarization uses the AIProvider protocol and is replay-safe
(deterministic at temperature=0).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from insuranceops.ai.providers import AIProvider, ProviderResponse
from insuranceops.observability.logging import get_logger

logger = get_logger("ai.summarization")


@dataclass(frozen=True, slots=True)
class SummaryResult:
    """Result of a summarization operation.

    Attributes:
        summary_text: The generated summary.
        summary_type: Type of summary (workflow, claim, escalation).
        provider_response: Full provider response with metadata.
        latency_ms: Time to generate the summary.
    """

    summary_text: str
    summary_type: str
    provider_response: ProviderResponse
    latency_ms: float


@dataclass(frozen=True, slots=True)
class SummarizationConfig:
    """Configuration for summarization behavior.

    Attributes:
        enabled: Whether summarization is active.
        max_input_chars: Maximum input text length (truncated if exceeded).
        temperature: Sampling temperature (0.0 for deterministic).
        max_tokens: Maximum output tokens.
        prompt_version: Version tag for prompt template tracking.
    """

    enabled: bool = True
    max_input_chars: int = 4000
    temperature: float = 0.0
    max_tokens: int = 512
    prompt_version: str = "v1.0"


# ──────────────────────────────────────────────────────────────────────────────
# Prompt templates (versioned for audit tracking)
# ──────────────────────────────────────────────────────────────────────────────

_WORKFLOW_SUMMARY_PROMPT = """\
Summarize this insurance workflow execution for an operations dashboard.

Workflow: {workflow_name} (version: {workflow_version})
State: {state}
Steps completed: {steps_completed}
Duration: {duration_description}
Extracted fields: {extracted_fields}

Provide a 2-3 sentence operational summary suitable for a queue dashboard.
"""

_CLAIM_SUMMARY_PROMPT = """\
Summarize this insurance claim intake for operator review.

Claim details:
{claim_fields}

Document type: {content_type}
Extraction confidence: {confidence}

Provide a structured summary with: claim type, key parties, amounts if present, \
and any flags for review.
"""

_ESCALATION_SUMMARY_PROMPT = """\
Provide context for a human reviewer handling this escalation.

Escalation reason: {reason_code}
Reason detail: {reason_detail}
Step that failed: {step_name}
Workflow: {workflow_name}
Extracted fields: {extracted_fields}

Summarize why this was escalated and what the reviewer should focus on.
"""


async def summarize_workflow(
    ai_provider: AIProvider,
    config: SummarizationConfig,
    *,
    workflow_name: str,
    workflow_version: str,
    state: str,
    steps_completed: int,
    duration_description: str,
    extracted_fields: dict[str, Any],
) -> SummaryResult:
    """Generate a workflow execution summary.

    Args:
        ai_provider: The AI provider to use.
        config: Summarization configuration.
        workflow_name: Name of the workflow.
        workflow_version: Version of the workflow.
        state: Current/terminal state of the run.
        steps_completed: Number of steps that completed successfully.
        duration_description: Human-readable duration string.
        extracted_fields: Key extracted field values.

    Returns:
        SummaryResult with the generated summary.
    """
    if not config.enabled:
        return _disabled_result("workflow")

    fields_str = ", ".join(f"{k}={v}" for k, v in extracted_fields.items())
    prompt = _WORKFLOW_SUMMARY_PROMPT.format(
        workflow_name=workflow_name,
        workflow_version=workflow_version,
        state=state,
        steps_completed=steps_completed,
        duration_description=duration_description,
        extracted_fields=fields_str or "(none)",
    )

    return await _execute_summary(ai_provider, config, prompt, "workflow")


async def summarize_claim(
    ai_provider: AIProvider,
    config: SummarizationConfig,
    *,
    claim_fields: dict[str, Any],
    content_type: str,
    confidence: float,
) -> SummaryResult:
    """Generate a claim intake summary.

    Args:
        ai_provider: The AI provider to use.
        config: Summarization configuration.
        claim_fields: Extracted claim field values.
        content_type: Document content type.
        confidence: Overall extraction confidence.

    Returns:
        SummaryResult with the generated summary.
    """
    if not config.enabled:
        return _disabled_result("claim")

    fields_str = "\n".join(f"  {k}: {v}" for k, v in claim_fields.items())
    prompt = _CLAIM_SUMMARY_PROMPT.format(
        claim_fields=fields_str or "(no fields extracted)",
        content_type=content_type,
        confidence=f"{confidence:.2f}",
    )

    return await _execute_summary(ai_provider, config, prompt, "claim")


async def summarize_escalation(
    ai_provider: AIProvider,
    config: SummarizationConfig,
    *,
    reason_code: str,
    reason_detail: str | None,
    step_name: str,
    workflow_name: str,
    extracted_fields: dict[str, Any],
) -> SummaryResult:
    """Generate an escalation context summary for human reviewers.

    Args:
        ai_provider: The AI provider to use.
        config: Summarization configuration.
        reason_code: Escalation reason code.
        reason_detail: Human-readable reason detail.
        step_name: Step that triggered escalation.
        workflow_name: Workflow name.
        extracted_fields: Extracted field values for context.

    Returns:
        SummaryResult with the generated summary.
    """
    if not config.enabled:
        return _disabled_result("escalation")

    fields_str = ", ".join(f"{k}={v}" for k, v in extracted_fields.items())
    prompt = _ESCALATION_SUMMARY_PROMPT.format(
        reason_code=reason_code,
        reason_detail=reason_detail or "(no detail)",
        step_name=step_name,
        workflow_name=workflow_name,
        extracted_fields=fields_str or "(none)",
    )

    return await _execute_summary(ai_provider, config, prompt, "escalation")


async def _execute_summary(
    ai_provider: AIProvider,
    config: SummarizationConfig,
    prompt: str,
    summary_type: str,
) -> SummaryResult:
    """Execute a summarization call and return the result."""
    start = time.perf_counter()

    # Truncate prompt if too long
    if len(prompt) > config.max_input_chars:
        prompt = prompt[: config.max_input_chars] + "\n[truncated]"

    try:
        response = await ai_provider.generate(
            prompt,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )

        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "summarization_complete",
            summary_type=summary_type,
            model=response.model,
            latency_ms=round(latency_ms, 1),
        )

        return SummaryResult(
            summary_text=response.content,
            summary_type=summary_type,
            provider_response=response,
            latency_ms=latency_ms,
        )

    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        logger.error(
            "summarization_failed",
            summary_type=summary_type,
            error=str(e),
            latency_ms=round(latency_ms, 1),
        )
        # Fail-safe: return empty summary rather than crashing the workflow
        return SummaryResult(
            summary_text="",
            summary_type=summary_type,
            provider_response=ProviderResponse(
                content="",
                model="error",
                prompt_version=config.prompt_version,
                provider_name=ai_provider.name,
                latency_ms=latency_ms,
            ),
            latency_ms=latency_ms,
        )


def _disabled_result(summary_type: str) -> SummaryResult:
    """Return an empty result when summarization is disabled."""
    return SummaryResult(
        summary_text="",
        summary_type=summary_type,
        provider_response=ProviderResponse(
            content="",
            model="disabled",
            prompt_version="disabled",
            provider_name="none",
        ),
        latency_ms=0.0,
    )
