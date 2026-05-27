"""Layer 2 — long-term agent memory recall against Qdrant agent_memories."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from qdrant_client.http import models

from memrag_shared.infra.ollama_client import get_client as get_ollama_client
from memrag_shared.infra.qdrant_client import get_client as get_qdrant_client
from memrag_shared.layers import LAYER_AGENT, MemoryChunk, MemoryType
from memrag_shared.memory.sparse import sparse_vector
from memrag_shared.metrics import record_recall_latency


def _parse_memory_type(value: str | None) -> MemoryType:
    if not value:
        return MemoryType.FACT
    try:
        return MemoryType(value)
    except ValueError:
        return MemoryType.FACT


def _hybrid_query(
    collection_name: str,
    dense_embedding: list[float],
    sparse_payload: dict[str, list[int] | list[float]],
    query_filter: models.Filter,
    top_k: int,
) -> list[Any]:
    client = get_qdrant_client()
    if hasattr(models, "Prefetch") and hasattr(models, "FusionQuery"):
        response = client.query_points(
            collection_name=collection_name,
            prefetch=[
                models.Prefetch(
                    query=dense_embedding,
                    using="dense",
                    limit=max(top_k * 3, 16),
                ),
                models.Prefetch(
                    query=models.SparseVector(
                        indices=sparse_payload["indices"],
                        values=sparse_payload["values"],
                    ),
                    using="sparse",
                    limit=max(top_k * 3, 16),
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
    else:
        response = client.query_points(
            collection_name=collection_name,
            query=dense_embedding,
            using="dense",
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
    return cast(list[Any], getattr(response, "points", response))


async def recall_agent_memory(
    workspace_id: str,
    agent_id: str,
    query_text: str,
    top_k: int = 8,
    dense_embedding: list[float] | None = None,
    sparse_payload: dict[str, list[int] | list[float]] | None = None,
) -> list[MemoryChunk]:
    """Recall top-*k* agent memories for *query_text* using hybrid search.

    Filters strictly on *workspace_id* and *agent_id*; tombstoned entries are
    excluded.  Updates ``last_accessed_at`` on every hit.
    """

    with record_recall_latency("layer2", workspace_id):
        if dense_embedding is None:
            dense_embedding = (await get_ollama_client().embed([query_text]))[0]
        if sparse_payload is None:
            sparse_payload = sparse_vector(query_text)
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="workspace_id", match=models.MatchValue(value=workspace_id)
                ),
                models.FieldCondition(
                    key="agent_id", match=models.MatchValue(value=agent_id)
                ),
                models.FieldCondition(
                    key="tombstoned", match=models.MatchValue(value=False)
                ),
            ]
        )
        points = _hybrid_query(
            "agent_memories", dense_embedding, sparse_payload, query_filter, top_k
        )
        client = get_qdrant_client()

        chunks: list[MemoryChunk] = []
        for point in points:
            if isinstance(point, tuple):
                scored_point = point[0]
                score = point[1] if len(point) > 1 else None
            else:
                scored_point = point
                score = getattr(point, "score", None)
            payload = getattr(scored_point, "payload", {}) or {}
            chunks.append(
                MemoryChunk(
                    id=str(getattr(scored_point, "id", "")),
                    agent_id=payload.get("agent_id", agent_id),
                    workspace_id=payload.get("workspace_id", workspace_id),
                    text=payload.get("text", ""),
                    content=payload.get("text", ""),
                    memory_type=_parse_memory_type(payload.get("memory_type")),
                    source_type="agent_memory",
                    score=float(score or getattr(scored_point, "score", 0.0) or 0.0),
                    layer=LAYER_AGENT,
                    metadata=payload,
                )
            )

        if chunks:
            client.set_payload(
                collection_name="agent_memories",
                payload={"last_accessed_at": datetime.now(timezone.utc).isoformat()},
                points=[chunk.id for chunk in chunks],
                wait=True,
            )

        return chunks
