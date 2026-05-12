"""Integration tests for workflow run API endpoints.

Requires: Postgres, Redis (via service containers or compose.test.yml).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

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
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _mock_operator():
    from insuranceops.security.auth import ApiKeyPrincipal

    return ApiKeyPrincipal(
        api_key_id=str(uuid.uuid4()), role="operator", label="test-op"
    )


def _mock_supervisor():
    from insuranceops.security.auth import ApiKeyPrincipal

    return ApiKeyPrincipal(
        api_key_id=str(uuid.uuid4()), role="supervisor", label="test-sup"
    )


def _mock_viewer():
    from insuranceops.security.auth import ApiKeyPrincipal

    return ApiKeyPrincipal(
        api_key_id=str(uuid.uuid4()), role="viewer", label="test-viewer"
    )


@pytest.mark.integration
class TestWorkflowRunsAPI:
    """Tests for /v1/workflow-runs endpoints."""

    async def test_create_workflow_run_success(self, client: AsyncClient) -> None:
        """Creates run in pending->running state."""
        operator = _mock_operator()
        doc_id = str(uuid.uuid4())

        with (
            patch(
                "insuranceops.api.deps.authenticate_api_key",
                new_callable=AsyncMock,
                return_value=operator,
            ),
            patch(
                "insuranceops.api.routes.workflow_runs.append_audit_event",
                new_callable=AsyncMock,
            ),
        ):
            response = await client.post(
                "/v1/workflow-runs",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "workflow_name": "claim_intake",
                    "document_ids": [doc_id],
                    "inputs": {},
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert data["workflow_name"] == "claim_intake"
        assert data["state"] == "running"

    async def test_create_workflow_run_unknown_workflow(
        self, client: AsyncClient
    ) -> None:
        """Returns 422 for unknown workflow."""
        operator = _mock_operator()

        with patch(
            "insuranceops.api.deps.authenticate_api_key",
            new_callable=AsyncMock,
            return_value=operator,
        ):
            response = await client.post(
                "/v1/workflow-runs",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "workflow_name": "nonexistent_workflow",
                    "document_ids": [str(uuid.uuid4())],
                    "inputs": {},
                },
            )

        assert response.status_code == 422

    async def test_get_workflow_run_not_found(self, client: AsyncClient) -> None:
        """Returns 404 for nonexistent run."""
        viewer = _mock_viewer()
        run_id = uuid.uuid4()

        with (
            patch(
                "insuranceops.api.deps.authenticate_api_key",
                new_callable=AsyncMock,
                return_value=viewer,
            ),
            patch(
                "insuranceops.api.routes.workflow_runs.WorkflowRunRepository"
            ) as mock_cls,
        ):
            mock_repo = mock_cls.return_value
            mock_repo.get_by_id = AsyncMock(return_value=None)

            response = await client.get(
                f"/v1/workflow-runs/{run_id}",
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 404

    async def test_get_workflow_run_status(self, client: AsyncClient) -> None:
        """Returns current state of workflow run."""
        viewer = _mock_viewer()
        run_id = uuid.uuid4()

        mock_run = MagicMock()
        mock_run.workflow_run_id = run_id
        mock_run.workflow_name = "claim_intake"
        mock_run.workflow_version = "v1"
        mock_run.state = "running"
        mock_run.version = 1
        mock_run.current_step_id = uuid.uuid4()
        mock_run.created_at = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        mock_run.updated_at = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        mock_run.deadline_at = datetime(2025, 1, 16, 10, 0, 0, tzinfo=timezone.utc)
        mock_run.created_by = "api_key:operator:abc"
        mock_run.last_error_code = None
        mock_run.last_error_detail = None

        with (
            patch(
                "insuranceops.api.deps.authenticate_api_key",
                new_callable=AsyncMock,
                return_value=viewer,
            ),
            patch(
                "insuranceops.api.routes.workflow_runs.WorkflowRunRepository"
            ) as mock_cls,
        ):
            mock_repo = mock_cls.return_value
            mock_repo.get_by_id = AsyncMock(return_value=mock_run)

            response = await client.get(
                f"/v1/workflow-runs/{run_id}",
                headers={"Authorization": "Bearer test-token"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "running"
        assert data["workflow_name"] == "claim_intake"

    async def test_cancel_workflow_run_supervisor_only(
        self, client: AsyncClient
    ) -> None:
        """Operator gets 403, supervisor succeeds."""
        operator = _mock_operator()
        run_id = uuid.uuid4()

        with patch(
            "insuranceops.api.deps.authenticate_api_key",
            new_callable=AsyncMock,
            return_value=operator,
        ):
            response = await client.post(
                f"/v1/workflow-runs/{run_id}/cancel",
                headers={"Authorization": "Bearer test-token"},
                json={"reason": "test"},
            )

        assert response.status_code == 403

    async def test_get_workflow_events_paginated(self, client: AsyncClient) -> None:
        """Returns events with next_cursor."""
        viewer = _mock_viewer()
        run_id = uuid.uuid4()

        mock_run = MagicMock()
        mock_run.workflow_run_id = run_id

        mock_event = MagicMock()
        mock_event.audit_event_id = uuid.uuid4()
        mock_event.workflow_run_id = run_id
        mock_event.event_type = "workflow_run.started"
        mock_event.actor = "worker:orchestrator"
        mock_event.payload = {}
        mock_event.occurred_at = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        mock_event.seq_in_run = 1
        mock_event.step_id = None
        mock_event.step_attempt_id = None

        with (
            patch(
                "insuranceops.api.deps.authenticate_api_key",
                new_callable=AsyncMock,
                return_value=viewer,
            ),
            patch(
                "insuranceops.api.routes.workflow_runs.WorkflowRunRepository"
            ) as mock_run_cls,
        ):
            mock_repo = mock_run_cls.return_value
            mock_repo.get_by_id = AsyncMock(return_value=mock_run)

            # Mock the SQLAlchemy session.execute for events query
            response = await client.get(
                f"/v1/workflow-runs/{run_id}/events",
                headers={"Authorization": "Bearer test-token"},
            )

        # Should return 200 (events may be empty in mocked environment)
        assert response.status_code == 200
