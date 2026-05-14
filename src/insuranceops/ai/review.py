"""Human review workflow with confidence-based routing.

Provides:
- Confidence threshold evaluation for extraction results
- Review queue routing decisions
- Approve/reject/reprocess semantics
- Review status tracking

Integrates with the existing EscalationCase model without modifying it.
The review workflow adds a layer of AI-confidence-driven routing on top
of the existing escalation semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from insuranceops.observability.logging import get_logger

logger = get_logger("ai.review")


class ReviewDecision(StrEnum):
    """Possible review decisions."""

    APPROVE = "approve"
    REJECT = "reject"
    REPROCESS = "reprocess"


class ReviewReason(StrEnum):
    """Reasons for routing to manual review."""

    LOW_CONFIDENCE = "low_confidence"
    MISSING_FIELDS = "missing_fields"
    CONFLICTING_FIELDS = "conflicting_fields"
    OCR_QUALITY = "ocr_quality"
    AI_ENHANCEMENT_FAILED = "ai_enhancement_failed"
    POLICY_RULE = "policy_rule"


@dataclass(frozen=True, slots=True)
class ReviewThresholds:
    """Confidence thresholds for review routing.

    Attributes:
        auto_approve_min: Minimum confidence for automatic approval (no review).
        review_required_below: Route to review if any field is below this.
        reject_below: Auto-reject if overall confidence is below this.
        min_required_fields: Minimum number of extracted fields required.
    """

    auto_approve_min: float = 0.9
    review_required_below: float = 0.7
    reject_below: float = 0.3
    min_required_fields: int = 3


@dataclass(frozen=True, slots=True)
class ReviewRouting:
    """Result of the review routing decision.

    Attributes:
        requires_review: Whether manual review is required.
        reasons: Why review was triggered (empty if auto-approved).
        overall_confidence: Computed overall confidence score.
        field_confidences: Per-field confidence breakdown.
        suggested_action: AI-suggested action for the reviewer.
    """

    requires_review: bool
    reasons: list[ReviewReason] = field(default_factory=list)
    overall_confidence: float = 1.0
    field_confidences: dict[str, float] = field(default_factory=dict)
    suggested_action: str = ""


@dataclass(slots=True)
class ReviewItem:
    """A single item in the review queue.

    Attributes:
        review_id: Unique identifier for this review item.
        workflow_run_id: Associated workflow run.
        step_name: Step that triggered review.
        routing: The routing decision that created this item.
        status: Current status (pending, claimed, completed).
        decision: The reviewer's decision (set on completion).
        reviewer_actor: Actor who claimed/completed the review.
        created_at: When the review item was created.
        completed_at: When the review was completed.
        notes: Reviewer notes.
    """

    review_id: UUID
    workflow_run_id: UUID
    step_name: str
    routing: ReviewRouting
    status: str = "pending"
    decision: ReviewDecision | None = None
    reviewer_actor: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    notes: str = ""


def evaluate_review_routing(
    field_confidences: dict[str, float],
    thresholds: ReviewThresholds,
    *,
    ocr_confidence: float | None = None,
    ai_enhancement_succeeded: bool = True,
) -> ReviewRouting:
    """Evaluate whether an extraction result requires manual review.

    This is the core routing decision function. It examines field-level
    confidence scores against configured thresholds and decides whether
    the result can be auto-approved or needs human review.

    Args:
        field_confidences: Mapping of field_name -> confidence score.
        thresholds: Configured confidence thresholds.
        ocr_confidence: Optional OCR-level confidence (if OCR was used).
        ai_enhancement_succeeded: Whether AI enhancement ran successfully.

    Returns:
        ReviewRouting with the decision and reasoning.
    """
    reasons: list[ReviewReason] = []

    # Check minimum field count
    if len(field_confidences) < thresholds.min_required_fields:
        reasons.append(ReviewReason.MISSING_FIELDS)

    # Check per-field confidence
    low_confidence_fields = {
        name: conf
        for name, conf in field_confidences.items()
        if conf < thresholds.review_required_below
    }
    if low_confidence_fields:
        reasons.append(ReviewReason.LOW_CONFIDENCE)

    # Check OCR quality
    if ocr_confidence is not None and ocr_confidence < thresholds.review_required_below:
        reasons.append(ReviewReason.OCR_QUALITY)

    # Check AI enhancement status
    if not ai_enhancement_succeeded:
        reasons.append(ReviewReason.AI_ENHANCEMENT_FAILED)

    # Compute overall confidence
    overall = sum(field_confidences.values()) / len(field_confidences) if field_confidences else 0.0

    # Auto-reject check
    if overall < thresholds.reject_below:
        return ReviewRouting(
            requires_review=True,
            reasons=reasons or [ReviewReason.LOW_CONFIDENCE],
            overall_confidence=overall,
            field_confidences=field_confidences,
            suggested_action="reject",
        )

    # Auto-approve check
    requires_review = len(reasons) > 0 or overall < thresholds.auto_approve_min

    suggested_action = ""
    if requires_review:
        if overall >= thresholds.auto_approve_min * 0.9:
            suggested_action = "likely_approve"
        elif overall < thresholds.reject_below * 1.5:
            suggested_action = "likely_reject"
        else:
            suggested_action = "manual_review"

    logger.info(
        "review_routing_evaluated",
        requires_review=requires_review,
        overall_confidence=round(overall, 3),
        reason_count=len(reasons),
        suggested_action=suggested_action,
    )

    return ReviewRouting(
        requires_review=requires_review,
        reasons=reasons,
        overall_confidence=overall,
        field_confidences=field_confidences,
        suggested_action=suggested_action,
    )


def apply_review_decision(
    review_item: ReviewItem,
    decision: ReviewDecision,
    actor: str,
    notes: str = "",
) -> ReviewItem:
    """Apply a reviewer's decision to a review item.

    Args:
        review_item: The review item to update.
        decision: The reviewer's decision.
        actor: Actor string of the reviewer.
        notes: Optional reviewer notes.

    Returns:
        Updated ReviewItem with decision applied.

    Raises:
        ValueError: If the review item is not in a claimable state.
    """
    if review_item.status == "completed":
        raise ValueError(f"Review {review_item.review_id} is already completed")

    review_item.status = "completed"
    review_item.decision = decision
    review_item.reviewer_actor = actor
    review_item.completed_at = datetime.now(UTC)
    review_item.notes = notes

    logger.info(
        "review_decision_applied",
        review_id=str(review_item.review_id),
        decision=decision.value,
        actor=actor,
    )

    return review_item
