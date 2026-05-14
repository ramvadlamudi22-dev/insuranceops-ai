"""Mock AI and OCR providers for development and testing.

These providers return deterministic responses without any external
service dependencies. They are suitable for:
- Local development
- CI testing
- Demonstration workflows

Production deployments swap to real providers via configuration.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from insuranceops.ai.providers import OCRPage, OCRResult, ProviderResponse


class MockAIProvider:
    """Deterministic mock AI provider.

    Returns predictable responses based on input content hashing.
    Temperature is ignored (always deterministic for replay safety).
    """

    @property
    def name(self) -> str:
        return "mock_ai"

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        """Generate a deterministic mock response.

        The response is derived from the prompt content hash to ensure
        replay safety: same prompt always produces same output.
        """
        start = time.perf_counter()

        # Deterministic response based on prompt hash
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        effective_model = model or "mock-model-v1"

        # Generate contextual mock response
        if "summar" in prompt.lower():
            content = (
                f"Summary: This document contains insurance claim information. "
                f"Key findings have been extracted and validated. "
                f"[mock-hash:{prompt_hash}]"
            )
        elif "classif" in prompt.lower():
            content = f"Classification: standard_claim [confidence:0.92] [mock-hash:{prompt_hash}]"
        elif "review" in prompt.lower():
            content = (
                f"Review recommendation: APPROVE. "
                f"All extracted fields match expected patterns. "
                f"[mock-hash:{prompt_hash}]"
            )
        else:
            content = f"Generated response for prompt. [mock-hash:{prompt_hash}]"

        latency_ms = (time.perf_counter() - start) * 1000

        return ProviderResponse(
            content=content,
            model=effective_model,
            prompt_version="mock-v1.0",
            usage={"prompt_tokens": len(prompt.split()), "completion_tokens": len(content.split())},
            latency_ms=latency_ms,
            provider_name=self.name,
            raw_response={"mock": True, "prompt_hash": prompt_hash},
        )


class MockOCRProvider:
    """Deterministic mock OCR provider.

    For text/plain content, returns the content as-is.
    For PDF/image content, returns a mock extraction.
    """

    @property
    def name(self) -> str:
        return "mock_ocr"

    async def extract_text(
        self,
        content: bytes,
        content_type: str,
        *,
        language: str = "en",
        metadata: dict[str, Any] | None = None,
    ) -> OCRResult:
        """Extract text from document bytes (mock implementation).

        For text content types, decodes directly.
        For binary types (PDF, images), returns simulated extraction.
        """
        start = time.perf_counter()

        if content_type.startswith("text/"):
            text = content.decode("utf-8", errors="replace")
            pages = [
                OCRPage(
                    page_number=1,
                    text=text,
                    confidence=1.0,
                    word_count=len(text.split()),
                )
            ]
        else:
            # Mock extraction for binary documents
            content_hash = hashlib.sha256(content).hexdigest()[:8]
            mock_text = (
                f"[Mock OCR extraction from {content_type}]\n"
                f"Document hash: {content_hash}\n"
                f"Claim Number: CLM-MOCK-{content_hash[:6].upper()}\n"
                f"Policy Number: POL-{content_hash[2:10].upper()}\n"
                f"Claimant: Mock Claimant\n"
                f"Date of Loss: 01/01/2025\n"
                f"Claim Type: auto\n"
            )
            pages = [
                OCRPage(
                    page_number=1,
                    text=mock_text,
                    confidence=0.88,
                    word_count=len(mock_text.split()),
                )
            ]

        full_text = "\n".join(p.text for p in pages)
        latency_ms = (time.perf_counter() - start) * 1000

        return OCRResult(
            pages=pages,
            full_text=full_text,
            total_pages=len(pages),
            provider_name=self.name,
            latency_ms=latency_ms,
        )
