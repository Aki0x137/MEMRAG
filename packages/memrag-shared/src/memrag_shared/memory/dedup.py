"""Deduplication helpers for agent long-term memory."""

from __future__ import annotations

from typing import Any, cast

from qdrant_client.http import models

from memrag_shared.infra.qdrant_client import get_client


async def is_near_duplicate(
    new_embedding: list[float],
    workspace_id: str,
    agent_id: str,
    threshold: float = 0.95,
) -> bool:
    """Return True when a sufficiently close existing memory already exists.

    Queries the ``agent_memories`` collection for the nearest neighbour of
    *new_embedding* filtered by *workspace_id* and *agent_id* (non-tombstoned
    only) and returns ``True`` when the top-1 cosine similarity is ≥
    *threshold*.
    """

    client = get_client()
    query_filter = models.Filter(
        must=[
            models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id)),
            models.FieldCondition(key="agent_id", match=models.MatchValue(value=agent_id)),
            models.FieldCondition(key="tombstoned", match=models.MatchValue(value=False)),
        ]
    )
    response = client.query_points(
        collection_name="agent_memories",
        query=new_embedding,
        using="dense",
        query_filter=query_filter,
        limit=1,
        with_payload=False,
        with_vectors=False,
    )
    points = cast(list[Any], getattr(response, "points", response))
    if not points:
        return False
    return float(points[0].score or 0.0) >= threshold
