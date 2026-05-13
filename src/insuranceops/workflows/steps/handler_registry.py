"""Handler registry: maps handler names to handler instances."""

from __future__ import annotations

from insuranceops.workflows.steps.base import StepHandler
from insuranceops.workflows.steps.complete import CompleteStepHandler
from insuranceops.workflows.steps.extract import ExtractStepHandler
from insuranceops.workflows.steps.ingest import IngestStepHandler
from insuranceops.workflows.steps.route import RouteStepHandler
from insuranceops.workflows.steps.validate import ValidateStepHandler

# Map handler_name strings to handler classes
_HANDLER_MAP: dict[str, type] = {
    "ingest": IngestStepHandler,
    "extract": ExtractStepHandler,
    "validate": ValidateStepHandler,
    "route": RouteStepHandler,
    "complete": CompleteStepHandler,
}


def get_handler(handler_name: str) -> StepHandler:
    """Get a step handler instance by name.

    Args:
        handler_name: The handler name (must be registered in the handler map).

    Returns:
        An instance of the requested step handler.

    Raises:
        KeyError: If the handler_name is not registered.
    """
    handler_cls = _HANDLER_MAP.get(handler_name)
    if handler_cls is None:
        raise KeyError(
            f"No handler registered for name '{handler_name}'. "
            f"Available handlers: {sorted(_HANDLER_MAP.keys())}"
        )
    return handler_cls()  # type: ignore[return-value]
