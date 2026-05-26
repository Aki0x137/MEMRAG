"""Redis client and key helpers for session/grants storage."""

from __future__ import annotations

import os

from redis import Redis


def get_client() -> Redis:
    """Create a Redis connection using the configured URL."""

    return Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True)


def session_key(workspace_id: str, session_id: str, field: str) -> str:
    """Return a session-cache key matching the data model schema.

    Pattern: ``{workspace_id}:session:{session_id}:{field}``
    """

    return f"{workspace_id}:session:{session_id}:{field}"


def grants_key(workspace_id: str) -> str:
    """Return the Redis key for cached sharing grants.

    Pattern: ``grants:{workspace_id}``
    """

    return f"grants:{workspace_id}"
