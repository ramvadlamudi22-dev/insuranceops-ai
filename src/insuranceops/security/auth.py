"""API key authentication."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from insuranceops.storage.models import ApiKeyModel


@dataclass(frozen=True, slots=True)
class ApiKeyPrincipal:
    """Authenticated principal from API key validation."""

    api_key_id: str
    role: str
    label: str

    @property
    def actor_string(self) -> str:
        """Return the canonical actor string for this principal."""
        return f"api_key:{self.role}:{self.api_key_id}"


def compute_key_hash(pepper: str, token: str) -> bytes:
    """Compute sha256(pepper || token) for API key lookup."""
    return hashlib.sha256((pepper + token).encode("utf-8")).digest()


async def authenticate_api_key(token: str, session: AsyncSession, pepper: str) -> ApiKeyPrincipal:
    """Authenticate a raw API key token.

    Computes sha256(pepper || token), looks up in api_keys table by key_hash,
    checks not revoked/expired, updates last_used_at, returns principal.

    Raises:
        ValueError: If key is not found, revoked, or expired.
    """
    key_hash = compute_key_hash(pepper, token)

    result = await session.execute(select(ApiKeyModel).where(ApiKeyModel.key_hash == key_hash))
    api_key = result.scalar_one_or_none()

    if api_key is None:
        raise ValueError("Invalid API key")

    if api_key.revoked_at is not None:
        raise ValueError("API key has been revoked")

    now = datetime.now(UTC)
    if api_key.expires_at is not None and api_key.expires_at <= now:
        raise ValueError("API key has expired")

    # Update last_used_at
    await session.execute(
        update(ApiKeyModel)
        .where(ApiKeyModel.api_key_id == api_key.api_key_id)
        .values(last_used_at=now)
    )

    return ApiKeyPrincipal(
        api_key_id=str(api_key.api_key_id),
        role=api_key.role,
        label=api_key.label,
    )
