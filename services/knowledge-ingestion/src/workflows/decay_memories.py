"""Nightly decay and archival workflow for stale agent memories."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from qdrant_client.http import models
from temporalio import activity


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _half_life(memory_type: str) -> int:
    return 365 if memory_type == "semantic" else 90


def _archive_rows(table: Any, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    if hasattr(table, "append"):
        table.append(rows)
        return
    if hasattr(table, "add_rows"):
        table.add_rows(rows)


@activity.defn
async def decay_and_archive(
    workspace_id: str,
    client: Any | None = None,
    table: Any | None = None,
    now_iso: str | None = None,
) -> int:
    """Decay stale memories, archive weak ones, and delete them from Qdrant."""

    if client is None:
        from infra.qdrant_init import _client as get_qdrant_client

        client = get_qdrant_client()
    if table is None:
        from infra.iceberg_client import get_tombstone_table

        table = get_tombstone_table()
    now = _parse_datetime(now_iso) if now_iso else datetime.now(timezone.utc)

    points, _ = client.scroll(
        collection_name="agent_memories",
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id))]
        ),
        limit=512,
        with_payload=True,
        with_vectors=False,
    )

    archived_rows: list[dict[str, Any]] = []
    delete_ids: list[str] = []
    updated = 0
    for point in points:
        payload = point.payload or {}
        last_accessed_at = _parse_datetime(payload.get("last_accessed_at"))
        days_inactive = max((now - last_accessed_at).days, 0)
        half_life = _half_life(payload.get("memory_type", "episodic"))
        base_score = float(payload.get("decay_score", 1.0))
        decay_score = base_score * math.exp(-(days_inactive / float(half_life)))
        updated += 1
        if decay_score < 0.1:
            archived_rows.append(
                {
                    "workspace_id": payload.get("workspace_id", workspace_id),
                    "agent_id": payload.get("agent_id", ""),
                    "memory_type": payload.get("memory_type", "episodic"),
                    "content": payload.get("text", ""),
                    "decay_score": decay_score,
                    "created_at": payload.get("created_at"),
                    "last_accessed_at": payload.get("last_accessed_at"),
                    "tombstoned_at": now.isoformat(),
                    "content_hash": payload.get("content_hash", str(point.id)),
                }
            )
            delete_ids.append(str(point.id))
            continue

        client.set_payload(
            collection_name="agent_memories",
            payload={"decay_score": decay_score},
            points=[str(point.id)],
            wait=True,
        )

    _archive_rows(table, archived_rows)
    if delete_ids:
        client.delete(
            collection_name="agent_memories",
            points_selector=models.PointIdsList(points=delete_ids),
        )
    return updated
