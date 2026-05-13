"""Role-based access control dependency for FastAPI."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from insuranceops.security.auth import ApiKeyPrincipal, authenticate_api_key

_bearer_scheme = HTTPBearer(auto_error=False)


def requires_role(*roles: str) -> Callable[..., Coroutine[Any, Any, ApiKeyPrincipal]]:
    """Return a FastAPI dependency that enforces role-based access.

    Usage:
        @router.get("/something", dependencies=[Depends(requires_role("operator", "supervisor"))])
        async def something(): ...

    Or as a parameter:
        async def handler(principal: ApiKeyPrincipal = Depends(requires_role("operator"))):
            ...
    """

    async def _dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    ) -> ApiKeyPrincipal:
        from insuranceops.observability.metrics import auth_denials_total, rate_limit_exceeded_total
        from insuranceops.security.rate_limit import check_rate_limit, get_max_requests_for_role

        if credentials is None or not credentials.credentials:
            auth_denials_total.labels(reason="missing_token").inc()
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid Authorization header",
            )

        token = credentials.credentials
        session = request.state.db_session
        settings = request.app.state.settings

        try:
            principal = await authenticate_api_key(
                token=token,
                session=session,
                pepper=settings.API_KEY_HASH_PEPPER,
            )
        except ValueError as e:
            auth_denials_total.labels(reason="invalid_key").inc()
            raise HTTPException(status_code=401, detail=str(e)) from None

        if principal.role not in roles:
            auth_denials_total.labels(reason="insufficient_role").inc()
            raise HTTPException(
                status_code=403,
                detail=f"Role '{principal.role}' is not authorized for this endpoint",
            )

        # Rate limiting (after successful auth)
        if settings.RATE_LIMIT_ENABLED:
            redis_client = request.app.state.redis
            max_requests = get_max_requests_for_role(
                role=principal.role,
                operator_max=settings.RATE_LIMIT_OPERATOR_MAX,
                supervisor_max=settings.RATE_LIMIT_SUPERVISOR_MAX,
                viewer_max=settings.RATE_LIMIT_VIEWER_MAX,
            )
            allowed, retry_after = await check_rate_limit(
                redis_client=redis_client,
                api_key_id=principal.api_key_id,
                role=principal.role,
                window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
                max_requests=max_requests,
            )
            if not allowed:
                rate_limit_exceeded_total.labels(role=principal.role).inc()
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(retry_after)},
                )

        return principal

    return _dependency
