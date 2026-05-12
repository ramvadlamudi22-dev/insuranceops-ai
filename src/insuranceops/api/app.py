"""FastAPI application factory."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from insuranceops.config import Settings
from insuranceops.observability.logging import bind_context, configure_logging, correlation_id_var
from insuranceops.observability.metrics import api_request_duration_seconds, api_requests_total
from insuranceops.storage.db import create_engine, create_session_factory


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: setup DB engine, session factory, and Redis pool."""
    settings: Settings = app.state.settings

    # Create database engine and session factory
    engine = create_engine(settings.DATABASE_URL)
    session_factory = create_session_factory(engine)
    app.state.engine = engine
    app.state.session_factory = session_factory

    # Create Redis pool
    from insuranceops.queue.redis_client import create_redis_pool

    redis = await create_redis_pool(settings.REDIS_URL)
    app.state.redis = redis

    configure_logging(settings.LOG_LEVEL)

    yield

    # Cleanup
    await redis.aclose()
    await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = Settings()

    app = FastAPI(
        title="InsuranceOps AI",
        version="0.1.0",
        lifespan=_lifespan,
    )
    app.state.settings = settings

    # ──────────────────────────────────────────────────────────────────────────
    # Middleware
    # ──────────────────────────────────────────────────────────────────────────

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next) -> Response:
        """Attach a correlation ID to each request."""
        cid = request.headers.get("X-Correlation-Id")
        if not cid:
            cid = str(uuid.uuid4())
        correlation_id_var.set(cid)
        bind_context(correlation_id=cid)
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = cid
        return response

    @app.middleware("http")
    async def request_size_limit_middleware(request: Request, call_next) -> Response:
        """Reject requests exceeding MAX_REQUEST_BYTES."""
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.MAX_REQUEST_BYTES:
            return JSONResponse(
                status_code=413,
                content={
                    "error_code": "REQUEST_TOO_LARGE",
                    "message": f"Request body exceeds {settings.MAX_REQUEST_BYTES} bytes",
                },
            )
        return await call_next(request)

    @app.middleware("http")
    async def request_timing_middleware(request: Request, call_next) -> Response:
        """Record request duration and increment request counter."""
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        route = request.url.path
        method = request.method
        status = str(response.status_code)

        api_request_duration_seconds.labels(route=route, method=method).observe(duration)
        api_requests_total.labels(route=route, method=method, status=status).inc()

        return response

    # ──────────────────────────────────────────────────────────────────────────
    # Exception handlers
    # ──────────────────────────────────────────────────────────────────────────

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error_code": "NOT_FOUND", "message": "Resource not found"},
        )

    @app.exception_handler(500)
    async def internal_error_handler(request: Request, exc) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error_code": "INTERNAL_ERROR", "message": "Internal server error"},
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Include route modules
    # ──────────────────────────────────────────────────────────────────────────

    from insuranceops.api.routes.documents import router as documents_router
    from insuranceops.api.routes.escalations import router as escalations_router
    from insuranceops.api.routes.health import router as health_router
    from insuranceops.api.routes.metrics import router as metrics_router
    from insuranceops.api.routes.workflow_runs import router as workflow_runs_router

    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(documents_router)
    app.include_router(workflow_runs_router)
    app.include_router(escalations_router)

    return app
