"""AI provider abstraction layer.

Defines the protocol for AI providers (LLM, OCR, summarization) and
ships a local mock provider for development and testing.

No vendor lock-in: providers are swappable via configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """Response from an AI provider call.

    Attributes:
        content: The generated content (text, structured data, etc.).
        model: Model identifier used for this call.
        prompt_version: Versioned prompt template identifier.
        usage: Token usage or equivalent cost metrics.
        latency_ms: Wall-clock execution time in milliseconds.
        provider_name: Name of the provider that served the request.
        raw_response: Raw provider response for debugging (optional).
    """

    content: str
    model: str
    prompt_version: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: float = 0.0
    provider_name: str = ""
    raw_response: dict[str, Any] | None = None


class AIProvider(Protocol):
    """Protocol for AI providers.

    All AI capabilities (summarization, extraction enhancement, classification)
    route through this interface. Implementations can wrap OpenAI, Bedrock,
    local models, or mock responses.
    """

    @property
    def name(self) -> str:
        """Provider name identifier."""
        ...

    async def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderResponse:
        """Generate a response from the AI provider.

        Args:
            prompt: The input prompt text.
            model: Optional model override (uses provider default if None).
            temperature: Sampling temperature (0.0 = deterministic).
            max_tokens: Maximum response tokens.
            metadata: Additional provider-specific parameters.

        Returns:
            ProviderResponse with generated content and execution metadata.
        """
        ...


class OCRProvider(Protocol):
    """Protocol for OCR (Optical Character Recognition) providers.

    Extracts text content from image and PDF documents.
    """

    @property
    def name(self) -> str:
        """Provider name identifier."""
        ...

    async def extract_text(
        self,
        content: bytes,
        content_type: str,
        *,
        language: str = "en",
        metadata: dict[str, Any] | None = None,
    ) -> OCRResult:
        """Extract text from document bytes.

        Args:
            content: Raw document bytes (PDF, image).
            content_type: MIME type of the input.
            language: Expected language for OCR hints.
            metadata: Additional provider-specific parameters.

        Returns:
            OCRResult with extracted text and page information.
        """
        ...


@dataclass(frozen=True, slots=True)
class OCRPage:
    """Extracted text from a single page.

    Attributes:
        page_number: 1-based page number.
        text: Extracted text content.
        confidence: OCR confidence score (0.0 to 1.0).
        word_count: Number of words extracted.
    """

    page_number: int
    text: str
    confidence: float
    word_count: int


@dataclass(frozen=True, slots=True)
class OCRResult:
    """Result of OCR processing on a document.

    Attributes:
        pages: List of page-level extraction results.
        full_text: Concatenated text from all pages.
        total_pages: Total number of pages processed.
        provider_name: Name of the OCR provider used.
        latency_ms: Processing time in milliseconds.
    """

    pages: list[OCRPage]
    full_text: str
    total_pages: int
    provider_name: str
    latency_ms: float = 0.0
