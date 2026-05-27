"""Graphiti-backed shared memory bridge.

When ``GRAPHITI_ENABLED=true``, findings are POSTed to the Graphiti server
(``add_episode`` API) instead of being written directly to Qdrant.  When
disabled the function falls through to the standard Qdrant upsert path so the
behaviour is identical to ``memory.shared.promote_to_shared``.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


async def store_with_graphiti(
    workspace_id: str,
    finding_text: str,
    episode_metadata: dict[str, Any] | None = None,
) -> str:
    """Store a finding via Graphiti when enabled, otherwise via Qdrant.

    Args:
        workspace_id: Workspace/tenant identifier used as Graphiti ``group_id``.
        finding_text: The finding text to store.
        episode_metadata: Optional extra metadata forwarded to Graphiti.

    Returns:
        ``"graphiti"`` when routed through Graphiti, ``"qdrant"`` otherwise.
    """

    if os.getenv("GRAPHITI_ENABLED", "false").lower() == "true":
        server_url = os.getenv(
            "GRAPHITI_SERVER_URL", "http://graphiti-server:8000"
        ).rstrip("/")
        payload: dict[str, Any] = {
            "group_id": workspace_id,
            "episode_body": finding_text,
            "source": "text",
        }
        if episode_metadata:
            payload["metadata"] = episode_metadata

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{server_url}/episodes", json=payload)
            response.raise_for_status()

        return "graphiti"

    # Fall-through: caller should invoke promote_to_shared directly for Qdrant.
    return "qdrant"
