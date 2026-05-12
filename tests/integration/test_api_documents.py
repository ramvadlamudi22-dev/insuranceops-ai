"""Integration tests for the document ingest and retrieval API.

Requires: Postgres, Redis (via service containers or compose.test.yml).
"""

from __future__ import annotations

import hashlib
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from insuranceops.api.app import create_app
from insuranceops.config import Settings


def _test_settings() -> Settings:
    return Settings(
        DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/insuranceops_test",
        REDIS_URL="redis://localhost:6379/0",
        API_KEY_HASH_PEPPER="test-pepper",
        ENV="test",
        PAYLOAD_STORAGE_PATH="/tmp/test-payloads",
    )


@pytest.fixture()
def app():
    """Create a test FastAPI app instance."""
    return create_app(settings=_test_settings())


@pytest.fixture()
async def client(app):
    """Create an async test client with app state initialized."""
    from insuranceops.queue.redis_client import create_redis_pool
    from insuranceops.storage.db import create_engine, create_session_factory

    settings = app.state.settings
    engine = create_engine(settings.DATABASE_URL)
    session_factory = create_session_factory(engine)
    redis = await create_redis_pool(settings.REDIS_URL)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis = redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await redis.aclose()
    await engine.dispose()


@pytest.mark.integration
class TestDocumentIngest:
    """Tests for POST /v1/documents endpoint."""

    async def test_ingest_document_requires_auth(self, client: AsyncClient) -> None:
        """POST without Bearer token returns 401."""
        response = await client.post(
            "/v1/documents",
            files={"file": ("test.txt", b"content", "text/plain")},
        )
        assert response.status_code == 401

    async def test_ingest_document_viewer_forbidden(self, client: AsyncClient) -> None:
        """Viewer role returns 403."""
        # Mock the auth to return a viewer principal
        from insuranceops.security.auth import ApiKeyPrincipal

        viewer = ApiKeyPrincipal(api_key_id=str(uuid.uuid4()), role="viewer", label="test-viewer")
        with patch(
            "insuranceops.security.rbac.authenticate_api_key",
            new_callable=AsyncMock,
            return_value=viewer,
        ):
            response = await client.post(
                "/v1/documents",
                headers={"Authorization": "Bearer test-token"},
                files={"file": ("test.txt", b"content", "text/plain")},
            )
        assert response.status_code == 403

    async def test_ingest_document_success(self, client: AsyncClient) -> None:
        """Operator uploads file, gets back document_id and content_hash."""
        from insuranceops.security.auth import ApiKeyPrincipal

        operator = ApiKeyPrincipal(api_key_id=str(uuid.uuid4()), role="operator", label="test-op")
        content = b"Claim Number: CLM-2025-001\nPolicy Number: POL-12345678"

        with (
            patch(
                "insuranceops.security.rbac.authenticate_api_key",
                new_callable=AsyncMock,
                return_value=operator,
            ),
            patch("insuranceops.api.routes.documents.DocumentRepository") as mock_repo_cls,
            patch("insuranceops.api.routes.documents.LocalPayloadStore") as mock_store_cls,
        ):
            mock_repo = mock_repo_cls.return_value
            mock_repo.get_by_content_hash = AsyncMock(return_value=[])
            mock_repo.create = AsyncMock()
            mock_store = mock_store_cls.return_value
            mock_store.write = lambda h, c: f"local://{h.hex()}"

            response = await client.post(
                "/v1/documents",
                headers={"Authorization": "Bearer test-token"},
                files={"file": ("claim.txt", content, "text/plain")},
            )

        assert response.status_code == 201
        data = response.json()
        assert "document_id" in data
        assert "content_hash" in data
        expected_hash = hashlib.sha256(content).hexdigest()
        assert data["content_hash"] == expected_hash

    async def test_ingest_document_too_large(self, client: AsyncClient) -> None:
        """Body exceeding MAX_REQUEST_BYTES returns 413."""
        # The test settings use default MAX_REQUEST_BYTES = 20MB
        # We send content-length header indicating a too-large body
        settings = _test_settings()
        too_large_size = settings.MAX_REQUEST_BYTES + 1

        response = await client.post(
            "/v1/documents",
            headers={
                "Authorization": "Bearer test-token",
                "Content-Length": str(too_large_size),
            },
            content=b"x" * 100,  # actual body doesn't matter, middleware checks header
        )
        assert response.status_code == 413
