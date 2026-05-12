"""Health check routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe - always returns ok."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Readiness probe - checks DB and Redis connectivity."""
    errors: list[str] = []

    # Check database
    try:
        session_factory = request.app.state.session_factory
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        errors.append(f"database: {str(e)}")

    # Check Redis
    try:
        redis = request.app.state.redis
        await redis.ping()
    except Exception as e:
        errors.append(f"redis: {str(e)}")

    if errors:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "errors": errors},
        )

    return JSONResponse(
        status_code=200,
        content={"status": "ok"},
    )
