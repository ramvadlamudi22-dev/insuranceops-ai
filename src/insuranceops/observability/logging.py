"""Structured logging configuration with structlog."""

from __future__ import annotations

import contextvars
from typing import Any

import structlog

from insuranceops.security.redaction import redact_sensitive_fields

# Context variables for log enrichment
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)
workflow_run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "workflow_run_id", default=""
)
step_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("step_id", default="")
step_attempt_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "step_attempt_id", default=""
)
actor_var: contextvars.ContextVar[str] = contextvars.ContextVar("actor", default="")


def add_context_vars(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Inject context variables into every log event."""
    ctx_mapping = {
        "correlation_id": correlation_id_var,
        "workflow_run_id": workflow_run_id_var,
        "step_id": step_id_var,
        "step_attempt_id": step_attempt_id_var,
        "actor": actor_var,
    }
    for key, var in ctx_mapping.items():
        value = var.get("")
        if value:
            event_dict.setdefault(key, value)
    return event_dict


def bind_context(**kwargs: str) -> None:
    """Set context variables for log enrichment.

    Args:
        correlation_id: Request correlation ID
        workflow_run_id: Current workflow run ID
        step_id: Current step ID
        step_attempt_id: Current step attempt ID
        actor: Actor string performing the action
    """
    var_map = {
        "correlation_id": correlation_id_var,
        "workflow_run_id": workflow_run_id_var,
        "step_id": step_id_var,
        "step_attempt_id": step_attempt_id_var,
        "actor": actor_var,
    }
    for key, value in kwargs.items():
        if key in var_map:
            var_map[key].set(value)


def configure_logging(log_level: str = "INFO") -> None:
    """Configure structlog with JSON renderer and standard processors."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            add_context_vars,
            redact_sensitive_fields,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a named structured logger."""
    return structlog.get_logger(name)
