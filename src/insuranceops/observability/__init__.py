"""Observability module: structured logging, Prometheus metrics, and tracing."""

from insuranceops.observability.logging import bind_context, get_logger
from insuranceops.observability.metrics import (
    api_request_duration_seconds,
    api_requests_total,
    auth_denials_total,
)

__all__ = [
    "bind_context",
    "get_logger",
    "api_request_duration_seconds",
    "api_requests_total",
    "auth_denials_total",
]
