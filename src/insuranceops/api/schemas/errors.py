"""Error response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Standard error response model."""

    error_code: str
    message: str
    detail: Any | None = None
