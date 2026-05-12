"""Async Redis connection pool factory."""

from __future__ import annotations

import redis.asyncio as redis


async def create_redis_pool(
    url: str, max_connections: int = 20
) -> redis.Redis:
    """Create an async Redis client with a connection pool.

    Args:
        url: Redis connection URL (e.g., redis://localhost:6379/0).
        max_connections: Maximum connections in the pool.

    Returns:
        An async Redis client instance.
    """
    pool = redis.ConnectionPool.from_url(
        url,
        max_connections=max_connections,
        decode_responses=False,
    )
    return redis.Redis(connection_pool=pool)
