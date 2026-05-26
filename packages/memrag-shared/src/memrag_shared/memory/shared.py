"""Shared workspace memory — promote findings to the shared_memories collection."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, cast

from qdrant_client.http import models

from memrag_shared.infra.qdrant_client import get_client
from memrag_shared.memory.sparse import sparse_vector

_DEDUP_THRESHOLD = 0.95


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shared_point_id(workspace_id: str, source_agent_id: str, text: str) -> str:
    digest = hashlib.sha256(
        f"{workspace_id}:{source_agent_id}:{text}".encode("utf-8")
    ).digest()
    return str(uuid.UUID(bytes=digest[:16]))


async def _is_shared_duplicate(
    embedding: list[float],
    workspace_id: str,
    threshold: float = _DEDUP_THRESHOLD,
) -> bool:
    """Return True when a sufficiently similar shared memory already exists."""

    client = get_client()
    query_filter = models.Filter(
        must=[
            models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id)),
        ]
    )
    response = client.query_points(
        collection_name="shared_memories",
        query=embedding,
        using="dense",
        query_filter=query_filter,
        limit=1,
        with_payload=False,
        with_vectors=False,
    )
    points = cast(list[Any], getattr(response, "points", response))
    if not points:
        return False
    return float(getattr(points[0], "score", 0.0) or 0.0) >= threshold


async def promote_to_shared(
    workspace_id: str,
    source_agent_id: str,
    text: str,
    embedding: list[float],
) -> str:
    """Upsert a finding into shared_memories.

    Returns:
        ``"stored"`` when the point was upserted, ``"duplicate"`` when a
        near-identical entry already exists.
    """

    if await _is_shared_duplicate(embedding, workspace_id):
        return "duplicate"

    client = get_client()
    point_id = _shared_point_id(workspace_id, source_agent_id, text)
    now = _utcnow()
    sparse = sparse_vector(text)
    payload: dict[str, Any] = {
        "workspace_id": workspace_id,
        "source_agent_id": source_agent_id,
        "promoted_at": now,
        "content_hash": point_id,
        "text": text,
    }
    client.upsert(
        collection_name="shared_memories",
        points=[
            models.PointStruct(
                id=point_id,
                vector={
                    "dense": embedding,
                    "sparse": models.SparseVector(
                        indices=sparse["indices"],
                        values=sparse["values"],
                    ),
                },
                payload=payload,
            )
        ],
        wait=True,
    )
    return "stored"
