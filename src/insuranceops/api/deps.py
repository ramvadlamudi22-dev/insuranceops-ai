"""FastAPI dependency injection helpers."""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.config import Settings
from insuranceops.security.auth import ApiKeyPrincipal, authenticate_api_key

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session from the app state session factory."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        request.state.db_session = session
        yield session
        await session.commit()


async def get_redis(request: Request):
    """Return the Redis client from app state."""
    return request.app.state.redis


def get_settings(request: Request) -> Settings:
    """Return the Settings instance from app state."""
    return request.app.state.settings


async def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> ApiKeyPrincipal:
    """Extract and validate Bearer token, return ApiKeyPrincipal."""
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

    return principal


class RequiresRole:
    """Dependency class that validates the principal has one of the allowed roles."""

    def __init__(self, *roles: str) -> None:
        self._roles = roles

    async def __call__(
        self,
        principal: ApiKeyPrincipal = Depends(get_current_principal),
    ) -> ApiKeyPrincipal:
        from insuranceops.observability.metrics import auth_denials_total

        if principal.role not in self._roles:
            auth_denials_total.labels(reason="insufficient_role").inc()
            raise HTTPException(
                status_code=403,
                detail=f"Role '{principal.role}' is not authorized for this endpoint",
            )
        return principal
