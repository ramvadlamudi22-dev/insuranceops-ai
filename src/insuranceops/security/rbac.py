"""Role-based access control dependency for FastAPI."""

from __future__ import annotations

from typing import Sequence

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from insuranceops.security.auth import ApiKeyPrincipal, authenticate_api_key

_bearer_scheme = HTTPBearer(auto_error=False)


def requires_role(*roles: str):
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
        from insuranceops.observability.metrics import auth_denials_total

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
            raise HTTPException(status_code=401, detail=str(e))

        if principal.role not in roles:
            auth_denials_total.labels(reason="insufficient_role").inc()
            raise HTTPException(
                status_code=403,
                detail=f"Role '{principal.role}' is not authorized for this endpoint",
            )

        return principal

    return _dependency
