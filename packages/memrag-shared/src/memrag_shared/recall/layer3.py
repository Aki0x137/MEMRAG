"""Layer 3 — workspace-shared memory recall against Qdrant shared_memories."""

from __future__ import annotations

from typing import Any, cast

from qdrant_client.http import models

from memrag_shared.infra.ollama_client import get_client as get_ollama_client
from memrag_shared.infra.qdrant_client import get_client as get_qdrant_client
from memrag_shared.layers import LAYER_SHARED, MemoryChunk, MemoryType
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
    dense_embedding: list[float],
    sparse_payload: dict[str, list[int] | list[float]],
    query_filter: models.Filter,
    top_k: int,
) -> list[Any]:
    client = get_qdrant_client()
    if hasattr(models, "Prefetch") and hasattr(models, "FusionQuery"):
        response = client.query_points(
            collection_name="shared_memories",
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
            collection_name="shared_memories",
            query=dense_embedding,
            using="dense",
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
    return cast(list[Any], getattr(response, "points", response))


async def recall_shared_memory(
    workspace_id: str,
    query_text: str,
    top_k: int = 8,
    dense_embedding: list[float] | None = None,
    sparse_payload: dict[str, list[int] | list[float]] | None = None,
) -> list[MemoryChunk]:
    """Recall top-*k* shared memories for *query_text*.

    Filters strictly on *workspace_id*, enforcing cross-workspace isolation.
    """

    with record_recall_latency("layer3", workspace_id):
        if dense_embedding is None:
            dense_embedding = (await get_ollama_client().embed([query_text]))[0]
        if sparse_payload is None:
            sparse_payload = sparse_vector(query_text)
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="workspace_id", match=models.MatchValue(value=workspace_id)
                ),
            ]
        )
        points = _hybrid_query(dense_embedding, sparse_payload, query_filter, top_k)

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
                    agent_id=payload.get("source_agent_id", ""),
                    workspace_id=payload.get("workspace_id", workspace_id),
                    text=payload.get("text", ""),
                    content=payload.get("text", ""),
                    memory_type=_parse_memory_type(payload.get("memory_type")),
                    source_type="shared_memory",
                    score=float(score or getattr(scored_point, "score", 0.0) or 0.0),
                    layer=LAYER_SHARED,
                    metadata=payload,
                )
            )

        return chunks
