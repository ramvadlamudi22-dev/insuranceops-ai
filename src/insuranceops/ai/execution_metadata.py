"""AI workflow execution metadata tracking.

Captures and persists metadata about AI operations within a workflow:
- Which model/provider was used
- Prompt version identifiers
- Execution timing
- Extraction confidence scores
- Audit chain linkage

This metadata is stored alongside StepAttempt records and included
in AuditEvent payloads for full traceability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID


@dataclass(slots=True)
class AIExecutionMetadata:
    """Metadata about a single AI operation within a step.

    Attributes:
        execution_id: Unique identifier for this AI execution.
        workflow_run_id: Parent workflow run.
        step_name: Step that triggered the AI operation.
        operation_type: Type of operation (extraction, summarization, classification).
        provider_name: AI provider that served the request.
        model: Model identifier used.
        prompt_version: Versioned prompt template identifier.
        input_hash: SHA-256 of the input content (for replay detection).
        output_hash: SHA-256 of the output content (for change detection).
        confidence: Overall confidence score (0.0 to 1.0, if applicable).
        latency_ms: Execution time in milliseconds.
        token_usage: Token counts (prompt_tokens, completion_tokens).
        started_at: When the AI operation started.
        completed_at: When the AI operation completed.
        success: Whether the operation completed without error.
        error_code: Error code if the operation failed.
        error_detail: Error detail if the operation failed.
    """

    execution_id: UUID
    workflow_run_id: UUID
    step_name: str
    operation_type: str
    provider_name: str
    model: str
    prompt_version: str
    input_hash: str = ""
    output_hash: str = ""
    confidence: float | None = None
    latency_ms: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    success: bool = True
    error_code: str | None = None
    error_detail: str | None = None

    def to_audit_payload(self) -> dict[str, Any]:
        """Serialize to a dict suitable for AuditEvent payload inclusion.

        Returns:
            Dict with all non-None fields serialized for JSON storage.
        """
        payload: dict[str, Any] = {
            "execution_id": str(self.execution_id),
            "operation_type": self.operation_type,
            "provider_name": self.provider_name,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "latency_ms": round(self.latency_ms, 1),
            "success": self.success,
        }

        if self.confidence is not None:
            payload["confidence"] = round(self.confidence, 4)
        if self.token_usage:
            payload["token_usage"] = self.token_usage
        if self.input_hash:
            payload["input_hash"] = self.input_hash
        if self.output_hash:
            payload["output_hash"] = self.output_hash
        if self.error_code:
            payload["error_code"] = self.error_code
        if self.error_detail:
            payload["error_detail"] = self.error_detail

        return payload


@dataclass(frozen=True, slots=True)
class AIStepMetadata:
    """Aggregated AI metadata for an entire step execution.

    A step may invoke multiple AI operations (OCR + extraction + summarization).
    This aggregates them into a single record attached to the StepAttempt.

    Attributes:
        step_attempt_id: The StepAttempt this metadata belongs to.
        executions: List of individual AI execution records.
        total_latency_ms: Sum of all AI operation latencies.
        total_tokens: Sum of all token usage.
        min_confidence: Lowest confidence across all operations.
        requires_review: Whether any operation flagged for review.
    """

    step_attempt_id: UUID
    executions: list[AIExecutionMetadata]
    total_latency_ms: float
    total_tokens: int
    min_confidence: float | None
    requires_review: bool

    def to_output_ref(self) -> dict[str, Any]:
        """Serialize to a dict suitable for step_attempt.output_ref storage.

        Returns:
            Dict with aggregated AI metadata for persistence.
        """
        return {
            "ai_metadata": {
                "execution_count": len(self.executions),
                "total_latency_ms": round(self.total_latency_ms, 1),
                "total_tokens": self.total_tokens,
                "min_confidence": round(self.min_confidence, 4) if self.min_confidence else None,
                "requires_review": self.requires_review,
                "executions": [e.to_audit_payload() for e in self.executions],
            }
        }


def aggregate_step_metadata(
    step_attempt_id: UUID,
    executions: list[AIExecutionMetadata],
) -> AIStepMetadata:
    """Aggregate individual AI executions into step-level metadata.

    Args:
        step_attempt_id: The parent StepAttempt ID.
        executions: List of AI execution records from this step.

    Returns:
        AIStepMetadata with aggregated metrics.
    """
    total_latency = sum(e.latency_ms for e in executions)
    total_tokens = sum(sum(e.token_usage.values()) for e in executions)

    confidences = [e.confidence for e in executions if e.confidence is not None]
    min_confidence = min(confidences) if confidences else None

    requires_review = any(
        e.confidence is not None and e.confidence < 0.7 for e in executions
    ) or any(not e.success for e in executions)

    return AIStepMetadata(
        step_attempt_id=step_attempt_id,
        executions=executions,
        total_latency_ms=total_latency,
        total_tokens=total_tokens,
        min_confidence=min_confidence,
        requires_review=requires_review,
    )
