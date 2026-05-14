"""Tests for AI workflow integration modules.

Covers:
- AI providers (mock)
- OCR abstraction
- Ingestion pipeline
- Summarization
- Review routing
- Execution metadata
"""

from __future__ import annotations

import uuid

import pytest

from insuranceops.ai.execution_metadata import (
    AIExecutionMetadata,
    aggregate_step_metadata,
)
from insuranceops.ai.mock_provider import MockAIProvider, MockOCRProvider
from insuranceops.ai.review import (
    ReviewDecision,
    ReviewItem,
    ReviewRouting,
    ReviewThresholds,
    apply_review_decision,
    evaluate_review_routing,
)
from insuranceops.ai.summarization import (
    SummarizationConfig,
    summarize_claim,
    summarize_escalation,
    summarize_workflow,
)


class TestMockAIProvider:
    """Tests for MockAIProvider."""

    @pytest.mark.asyncio
    async def test_generate_returns_deterministic_response(self):
        provider = MockAIProvider()
        r1 = await provider.generate("test prompt")
        r2 = await provider.generate("test prompt")
        # Same prompt produces same content (deterministic)
        assert r1.content == r2.content
        assert r1.model == r2.model

    @pytest.mark.asyncio
    async def test_generate_different_prompts_different_responses(self):
        provider = MockAIProvider()
        r1 = await provider.generate("prompt A")
        r2 = await provider.generate("prompt B")
        assert r1.content != r2.content

    @pytest.mark.asyncio
    async def test_generate_summary_prompt_contains_summary(self):
        provider = MockAIProvider()
        r = await provider.generate("Please summarize this document")
        assert "Summary" in r.content

    @pytest.mark.asyncio
    async def test_provider_name(self):
        provider = MockAIProvider()
        assert provider.name == "mock_ai"

    @pytest.mark.asyncio
    async def test_response_includes_usage(self):
        provider = MockAIProvider()
        r = await provider.generate("test")
        assert "prompt_tokens" in r.usage
        assert "completion_tokens" in r.usage


class TestMockOCRProvider:
    """Tests for MockOCRProvider."""

    @pytest.mark.asyncio
    async def test_text_content_returns_as_is(self):
        provider = MockOCRProvider()
        content = b"Hello world"
        result = await provider.extract_text(content, "text/plain")
        assert result.full_text == "Hello world"
        assert result.total_pages == 1
        assert result.pages[0].confidence == 1.0

    @pytest.mark.asyncio
    async def test_pdf_content_returns_mock_extraction(self):
        provider = MockOCRProvider()
        content = b"%PDF-1.4 fake content"
        result = await provider.extract_text(content, "application/pdf")
        assert "Mock OCR extraction" in result.full_text
        assert result.total_pages == 1
        assert result.pages[0].confidence < 1.0

    @pytest.mark.asyncio
    async def test_provider_name(self):
        provider = MockOCRProvider()
        assert provider.name == "mock_ocr"

    @pytest.mark.asyncio
    async def test_deterministic_for_same_content(self):
        provider = MockOCRProvider()
        content = b"same bytes"
        r1 = await provider.extract_text(content, "application/pdf")
        r2 = await provider.extract_text(content, "application/pdf")
        assert r1.full_text == r2.full_text


class TestReviewRouting:
    """Tests for review routing evaluation."""

    def test_high_confidence_auto_approves(self):
        field_confidences = {
            "claim_number": 0.95,
            "policy_number": 0.92,
            "claimant_name": 0.97,
        }
        routing = evaluate_review_routing(field_confidences, ReviewThresholds())
        assert routing.requires_review is False
        assert routing.overall_confidence > 0.9

    def test_low_confidence_requires_review(self):
        field_confidences = {
            "claim_number": 0.5,
            "policy_number": 0.6,
            "claimant_name": 0.4,
        }
        routing = evaluate_review_routing(field_confidences, ReviewThresholds())
        assert routing.requires_review is True
        assert "low_confidence" in [r.value for r in routing.reasons]

    def test_missing_fields_requires_review(self):
        field_confidences = {
            "claim_number": 0.95,
        }
        routing = evaluate_review_routing(
            field_confidences, ReviewThresholds(min_required_fields=3)
        )
        assert routing.requires_review is True
        assert "missing_fields" in [r.value for r in routing.reasons]

    def test_very_low_confidence_suggests_reject(self):
        field_confidences = {
            "claim_number": 0.1,
            "policy_number": 0.2,
            "claimant_name": 0.15,
        }
        routing = evaluate_review_routing(field_confidences, ReviewThresholds())
        assert routing.requires_review is True
        assert routing.suggested_action == "reject"

    def test_ocr_quality_flag(self):
        field_confidences = {
            "claim_number": 0.95,
            "policy_number": 0.92,
            "claimant_name": 0.97,
        }
        routing = evaluate_review_routing(field_confidences, ReviewThresholds(), ocr_confidence=0.5)
        assert routing.requires_review is True
        assert "ocr_quality" in [r.value for r in routing.reasons]

    def test_ai_enhancement_failure_flag(self):
        field_confidences = {
            "claim_number": 0.95,
            "policy_number": 0.92,
            "claimant_name": 0.97,
        }
        routing = evaluate_review_routing(
            field_confidences, ReviewThresholds(), ai_enhancement_succeeded=False
        )
        assert routing.requires_review is True
        assert "ai_enhancement_failed" in [r.value for r in routing.reasons]

    def test_empty_fields_returns_zero_confidence(self):
        routing = evaluate_review_routing({}, ReviewThresholds())
        assert routing.overall_confidence == 0.0
        assert routing.requires_review is True


class TestApplyReviewDecision:
    """Tests for applying review decisions."""

    def test_approve_sets_completed(self):
        item = ReviewItem(
            review_id=uuid.uuid4(),
            workflow_run_id=uuid.uuid4(),
            step_name="validate",
            routing=ReviewRouting(requires_review=True),
        )
        result = apply_review_decision(item, ReviewDecision.APPROVE, "user:op:1")
        assert result.status == "completed"
        assert result.decision == ReviewDecision.APPROVE
        assert result.reviewer_actor == "user:op:1"

    def test_reject_sets_completed(self):
        item = ReviewItem(
            review_id=uuid.uuid4(),
            workflow_run_id=uuid.uuid4(),
            step_name="validate",
            routing=ReviewRouting(requires_review=True),
        )
        result = apply_review_decision(item, ReviewDecision.REJECT, "user:op:2", "bad doc")
        assert result.decision == ReviewDecision.REJECT
        assert result.notes == "bad doc"

    def test_already_completed_raises(self):
        item = ReviewItem(
            review_id=uuid.uuid4(),
            workflow_run_id=uuid.uuid4(),
            step_name="validate",
            routing=ReviewRouting(requires_review=True),
            status="completed",
        )
        with pytest.raises(ValueError, match="already completed"):
            apply_review_decision(item, ReviewDecision.APPROVE, "user:op:1")


class TestSummarization:
    """Tests for AI summarization."""

    @pytest.mark.asyncio
    async def test_workflow_summary_returns_text(self):
        provider = MockAIProvider()
        config = SummarizationConfig()
        result = await summarize_workflow(
            provider,
            config,
            workflow_name="claim_intake",
            workflow_version="v1",
            state="completed",
            steps_completed=5,
            duration_description="12s",
            extracted_fields={"claim_number": "CLM-001"},
        )
        assert result.summary_text != ""
        assert result.summary_type == "workflow"

    @pytest.mark.asyncio
    async def test_claim_summary_returns_text(self):
        provider = MockAIProvider()
        config = SummarizationConfig()
        result = await summarize_claim(
            provider,
            config,
            claim_fields={"claim_number": "CLM-001", "claim_type": "auto"},
            content_type="text/plain",
            confidence=0.92,
        )
        assert result.summary_text != ""
        assert result.summary_type == "claim"

    @pytest.mark.asyncio
    async def test_escalation_summary_returns_text(self):
        provider = MockAIProvider()
        config = SummarizationConfig()
        result = await summarize_escalation(
            provider,
            config,
            reason_code="LOW_CONFIDENCE",
            reason_detail="Policy number extraction below threshold",
            step_name="validate",
            workflow_name="claim_intake",
            extracted_fields={"claim_number": "CLM-001"},
        )
        assert result.summary_text != ""
        assert result.summary_type == "escalation"

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self):
        provider = MockAIProvider()
        config = SummarizationConfig(enabled=False)
        result = await summarize_workflow(
            provider,
            config,
            workflow_name="test",
            workflow_version="v1",
            state="completed",
            steps_completed=1,
            duration_description="1s",
            extracted_fields={},
        )
        assert result.summary_text == ""

    @pytest.mark.asyncio
    async def test_summarization_is_deterministic(self):
        provider = MockAIProvider()
        config = SummarizationConfig()
        r1 = await summarize_claim(
            provider,
            config,
            claim_fields={"x": "y"},
            content_type="text/plain",
            confidence=0.9,
        )
        r2 = await summarize_claim(
            provider,
            config,
            claim_fields={"x": "y"},
            content_type="text/plain",
            confidence=0.9,
        )
        assert r1.summary_text == r2.summary_text


class TestExecutionMetadata:
    """Tests for AI execution metadata tracking."""

    def test_to_audit_payload_includes_required_fields(self):
        meta = AIExecutionMetadata(
            execution_id=uuid.uuid4(),
            workflow_run_id=uuid.uuid4(),
            step_name="extract",
            operation_type="ocr",
            provider_name="mock_ocr",
            model="ocr",
            prompt_version="n/a",
            confidence=0.88,
            latency_ms=150.5,
            token_usage={"prompt_tokens": 10, "completion_tokens": 20},
        )
        payload = meta.to_audit_payload()
        assert payload["operation_type"] == "ocr"
        assert payload["provider_name"] == "mock_ocr"
        assert payload["confidence"] == 0.88
        assert payload["latency_ms"] == 150.5
        assert payload["token_usage"] == {"prompt_tokens": 10, "completion_tokens": 20}

    def test_to_audit_payload_excludes_none_fields(self):
        meta = AIExecutionMetadata(
            execution_id=uuid.uuid4(),
            workflow_run_id=uuid.uuid4(),
            step_name="extract",
            operation_type="extraction",
            provider_name="stub",
            model="stub_extractor",
            prompt_version="1.0.0",
        )
        payload = meta.to_audit_payload()
        assert "error_code" not in payload
        assert "confidence" not in payload

    def test_aggregate_step_metadata_computes_totals(self):
        executions = [
            AIExecutionMetadata(
                execution_id=uuid.uuid4(),
                workflow_run_id=uuid.uuid4(),
                step_name="extract",
                operation_type="ocr",
                provider_name="mock_ocr",
                model="ocr",
                prompt_version="n/a",
                confidence=0.88,
                latency_ms=100.0,
                token_usage={"prompt_tokens": 5},
            ),
            AIExecutionMetadata(
                execution_id=uuid.uuid4(),
                workflow_run_id=uuid.uuid4(),
                step_name="extract",
                operation_type="extraction",
                provider_name="stub",
                model="stub",
                prompt_version="1.0",
                confidence=0.95,
                latency_ms=50.0,
                token_usage={"prompt_tokens": 0},
            ),
        ]
        step_meta = aggregate_step_metadata(uuid.uuid4(), executions)
        assert step_meta.total_latency_ms == 150.0
        assert step_meta.total_tokens == 5
        assert step_meta.min_confidence == 0.88
        assert step_meta.requires_review is False  # both above 0.7

    def test_aggregate_low_confidence_requires_review(self):
        executions = [
            AIExecutionMetadata(
                execution_id=uuid.uuid4(),
                workflow_run_id=uuid.uuid4(),
                step_name="extract",
                operation_type="extraction",
                provider_name="stub",
                model="stub",
                prompt_version="1.0",
                confidence=0.5,
                latency_ms=10.0,
            ),
        ]
        step_meta = aggregate_step_metadata(uuid.uuid4(), executions)
        assert step_meta.requires_review is True

    def test_to_output_ref_serializes_correctly(self):
        executions = [
            AIExecutionMetadata(
                execution_id=uuid.uuid4(),
                workflow_run_id=uuid.uuid4(),
                step_name="extract",
                operation_type="ocr",
                provider_name="mock",
                model="ocr",
                prompt_version="1",
                latency_ms=10.0,
            ),
        ]
        step_meta = aggregate_step_metadata(uuid.uuid4(), executions)
        output = step_meta.to_output_ref()
        assert "ai_metadata" in output
        assert output["ai_metadata"]["execution_count"] == 1
