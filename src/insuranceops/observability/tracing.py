"""OpenTelemetry no-op bridge.

If OTEL_EXPORTER_OTLP_ENDPOINT is set in the environment, attempts to configure
OpenTelemetry tracing. Otherwise provides no-op span context manager and decorators.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import wraps
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_tracer: Any = None
_otel_configured = False


def _try_configure_otel() -> bool:
    """Attempt to configure OpenTelemetry if the endpoint is set."""
    global _tracer, _otel_configured

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "insuranceops"})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("insuranceops")
        _otel_configured = True
        return True
    except ImportError:
        return False


# Attempt configuration at module load
_try_configure_otel()


@contextmanager
def span(name: str, **attributes: Any) -> Generator[Any, None, None]:
    """Context manager that creates a span if OTel is configured, otherwise no-op."""
    if _otel_configured and _tracer is not None:
        with _tracer.start_as_current_span(name, attributes=attributes) as s:
            yield s
    else:
        yield None


def traced(name: str | None = None) -> Callable[[F], F]:
    """Decorator that wraps a function in a span if OTel is configured."""

    def decorator(func: F) -> F:
        if not _otel_configured:
            return func

        span_name = name or f"{func.__module__}.{func.__qualname__}"

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(span_name):
                return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def traced_async(name: str | None = None) -> Callable[[F], F]:
    """Decorator that wraps an async function in a span if OTel is configured."""

    def decorator(func: F) -> F:
        if not _otel_configured:
            return func

        span_name = name or f"{func.__module__}.{func.__qualname__}"

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(span_name):
                return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
