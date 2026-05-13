"""Per-API-key fixed-window rate limiting via Redis.

Key pattern:
    rate:api_key:<key_id_prefix>:<window_epoch>

Strategy:
    Fixed-window counter using INCR + EXPIRE.
    On exceed: raise HTTP 429 with Retry-After header.
    On Redis unavailability: fail-open (allow the request).
"""

from __future__ import annotations

from insuranceops.observability.logging import get_logger

logger = get_logger("security.rate_limit")


async def check_rate_limit(
    redis_client: object,
    api_key_id: str,
    role: str,
    window_seconds: int,
    max_requests: int,
) -> tuple[bool, int]:
    """Check and increment the rate limit counter for an API key.

    Args:
        redis_client: Async Redis client instance.
        api_key_id: The authenticated API key ID (used in the Redis key).
        role: The role of the API key (for logging only; limit is passed in).
        window_seconds: Duration of the fixed window in seconds.
        max_requests: Maximum requests allowed in the window.

    Returns:
        Tuple of (allowed: bool, retry_after_seconds: int).
        If allowed is False, retry_after_seconds indicates when the window resets.
        On Redis errors, returns (True, 0) to fail-open.
    """
    import time

    import redis.asyncio as redis

    # Compute the current window bucket
    now = int(time.time())
    window_start = now - (now % window_seconds)
    key = f"rate:api_key:{api_key_id[:12]}:{window_start}"

    try:
        client: redis.Redis = redis_client  # type: ignore[assignment]

        # Atomic INCR; returns the new count
        count: int = await client.incr(key)  # type: ignore[misc]

        # Set TTL on first increment (new key)
        if count == 1:
            await client.expire(key, window_seconds + 1)  # type: ignore[misc]

        if count > max_requests:
            # Calculate time until window resets
            retry_after = window_seconds - (now - window_start)
            return False, max(retry_after, 1)

        return True, 0

    except Exception as e:
        # Fail-open: if Redis is unavailable, allow the request
        logger.warning("rate_limit_redis_error", error=str(e), api_key_id=api_key_id[:12])
        return True, 0


def get_max_requests_for_role(
    role: str,
    operator_max: int,
    supervisor_max: int,
    viewer_max: int,
) -> int:
    """Return the rate limit ceiling for a given role.

    Args:
        role: The API key role.
        operator_max: Max requests for operator role.
        supervisor_max: Max requests for supervisor role.
        viewer_max: Max requests for viewer role.

    Returns:
        The max requests allowed per window for this role.
    """
    limits = {
        "operator": operator_max,
        "supervisor": supervisor_max,
        "viewer": viewer_max,
    }
    return limits.get(role, viewer_max)
