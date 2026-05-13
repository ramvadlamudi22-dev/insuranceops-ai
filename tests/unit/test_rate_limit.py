"""Tests for per-API-key rate limiting.

Tests the rate_limit module functions using mock Redis clients.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from insuranceops.security.rate_limit import check_rate_limit, get_max_requests_for_role


@pytest.fixture()
def mock_redis():
    """Create a mock async Redis client."""
    client = AsyncMock()
    return client


class TestCheckRateLimit:
    """Tests for check_rate_limit()."""

    @pytest.mark.asyncio
    async def test_allows_request_under_limit(self, mock_redis):
        """First request should be allowed."""
        mock_redis.incr.return_value = 1
        mock_redis.expire.return_value = True

        allowed, retry_after = await check_rate_limit(
            redis_client=mock_redis,
            api_key_id="abc-123-def-456",
            role="operator",
            window_seconds=60,
            max_requests=100,
        )

        assert allowed is True
        assert retry_after == 0
        mock_redis.incr.assert_called_once()
        mock_redis.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_allows_request_at_limit(self, mock_redis):
        """Request at exactly max_requests should still be allowed."""
        mock_redis.incr.return_value = 100  # exactly at limit

        allowed, retry_after = await check_rate_limit(
            redis_client=mock_redis,
            api_key_id="abc-123-def-456",
            role="operator",
            window_seconds=60,
            max_requests=100,
        )

        assert allowed is True
        assert retry_after == 0

    @pytest.mark.asyncio
    async def test_rejects_request_over_limit(self, mock_redis):
        """Request exceeding max_requests should be rejected."""
        mock_redis.incr.return_value = 101  # over limit

        allowed, retry_after = await check_rate_limit(
            redis_client=mock_redis,
            api_key_id="abc-123-def-456",
            role="operator",
            window_seconds=60,
            max_requests=100,
        )

        assert allowed is False
        assert retry_after >= 1

    @pytest.mark.asyncio
    async def test_retry_after_is_bounded(self, mock_redis):
        """Retry-After should not exceed window_seconds."""
        mock_redis.incr.return_value = 200  # way over limit

        allowed, retry_after = await check_rate_limit(
            redis_client=mock_redis,
            api_key_id="abc-123-def-456",
            role="viewer",
            window_seconds=60,
            max_requests=10,
        )

        assert allowed is False
        assert 1 <= retry_after <= 60

    @pytest.mark.asyncio
    async def test_sets_expire_only_on_first_increment(self, mock_redis):
        """EXPIRE should only be called when count == 1 (new key)."""
        mock_redis.incr.return_value = 5  # not first

        await check_rate_limit(
            redis_client=mock_redis,
            api_key_id="abc-123-def-456",
            role="operator",
            window_seconds=60,
            max_requests=100,
        )

        # expire should NOT be called when count > 1
        mock_redis.expire.assert_not_called()

    @pytest.mark.asyncio
    async def test_fail_open_on_redis_error(self, mock_redis):
        """If Redis raises, the request should be allowed (fail-open)."""
        mock_redis.incr.side_effect = ConnectionError("Redis unavailable")

        allowed, retry_after = await check_rate_limit(
            redis_client=mock_redis,
            api_key_id="abc-123-def-456",
            role="operator",
            window_seconds=60,
            max_requests=100,
        )

        assert allowed is True
        assert retry_after == 0

    @pytest.mark.asyncio
    async def test_fail_open_on_timeout(self, mock_redis):
        """If Redis times out, the request should be allowed (fail-open)."""
        mock_redis.incr.side_effect = TimeoutError("Redis timeout")

        allowed, retry_after = await check_rate_limit(
            redis_client=mock_redis,
            api_key_id="abc-123-def-456",
            role="operator",
            window_seconds=60,
            max_requests=100,
        )

        assert allowed is True
        assert retry_after == 0

    @pytest.mark.asyncio
    async def test_key_includes_api_key_prefix(self, mock_redis):
        """Redis key should include the API key ID prefix."""
        mock_redis.incr.return_value = 1
        mock_redis.expire.return_value = True

        await check_rate_limit(
            redis_client=mock_redis,
            api_key_id="abc-123-def-456-ghi-789",
            role="operator",
            window_seconds=60,
            max_requests=100,
        )

        call_args = mock_redis.incr.call_args[0][0]
        assert "rate:api_key:abc-123-def-" in call_args

    @pytest.mark.asyncio
    async def test_key_includes_window_epoch(self, mock_redis):
        """Redis key should include the window start epoch."""
        mock_redis.incr.return_value = 1
        mock_redis.expire.return_value = True

        await check_rate_limit(
            redis_client=mock_redis,
            api_key_id="abc-123-def-456",
            role="operator",
            window_seconds=60,
            max_requests=100,
        )

        call_args = mock_redis.incr.call_args[0][0]
        # Key should end with a numeric epoch
        parts = call_args.split(":")
        assert parts[-1].isdigit()


class TestGetMaxRequestsForRole:
    """Tests for get_max_requests_for_role()."""

    def test_operator_role(self):
        result = get_max_requests_for_role("operator", 1200, 1200, 600)
        assert result == 1200

    def test_supervisor_role(self):
        result = get_max_requests_for_role("supervisor", 1200, 1500, 600)
        assert result == 1500

    def test_viewer_role(self):
        result = get_max_requests_for_role("viewer", 1200, 1200, 600)
        assert result == 600

    def test_unknown_role_gets_viewer_limit(self):
        """Unknown roles get the most restrictive limit (viewer)."""
        result = get_max_requests_for_role("unknown", 1200, 1200, 600)
        assert result == 600
