"""Temporal activities for upserting chunks to Qdrant org_knowledge."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from qdrant_client.http import models

from infra.qdrant_client import get_client as get_qdrant_client


async def upsert_org_knowledge(
    connector_id: str,
    workspace_id: str,
    chunks_with_embeddings: list[dict[str, Any]],
    connector_config: dict[str, Any],
) -> int:
    """
    Upsert chunks to the org_knowledge Qdrant collection.
    
    Args:
        connector_id: UUID of the connector.
        workspace_id: Workspace this connector belongs to.
        chunks_with_embeddings: List of dicts with 'text', 'dense', 'sparse', 'metadata'.
        connector_config: Connector configuration (source_type, sharing_scope, etc.).
        
    Returns:
        Number of points upserted.
    """
    if not chunks_with_embeddings:
        return 0

    client = get_qdrant_client()
    points: list[models.PointStruct] = []
    now = datetime.now(timezone.utc).isoformat()

    for chunk in chunks_with_embeddings:
        text = chunk.get("text", "")
        dense = chunk.get("dense", [])
        sparse = chunk.get("sparse", {})
        metadata = chunk.get("metadata", {})

        # Use content hash as deterministic point ID for idempotency
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        payload: dict[str, Any] = {
            "workspace_id": workspace_id,
            "connector_id": connector_id,
            "source_type": connector_config.get("source_type", "unknown"),
            "resource_id": metadata.get("resource_id", ""),
            "chunk_index": metadata.get("chunk_index", 0),
            "title": metadata.get("title", ""),
            "url": metadata.get("url", None),
            "sharing_scope": connector_config.get("sharing_scope", "private"),
            "allowed_workspace_ids": connector_config.get("allowed_workspace_ids", []),
            "agent_scope": connector_config.get("agent_scope", "all"),
            "allowed_agent_ids": connector_config.get("allowed_agent_ids", []),
            "allowed_agent_tags": connector_config.get("allowed_agent_tags", []),
            "contains_pii": connector_config.get("contains_pii", False),
            "pii_masked": metadata.get("pii_masked", False),
            "content_hash": content_hash,
            "last_synced_at": now,
            "text": text,
        }

        points.append(
            models.PointStruct(
                id=content_hash,  # Deterministic ID
                vector={
                    "dense": dense,
                    "sparse": models.SparseVector(
                        indices=sparse.get("indices", []),
                        values=sparse.get("values", []),
                    ),
                },
                payload=payload,
            )
        )

    client.upsert(
        collection_name="org_knowledge",
        points=points,
        wait=True,
    )

    return len(points)
