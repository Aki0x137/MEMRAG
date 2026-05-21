"""Layer 2 long-term memory recall against Qdrant."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from qdrant_client.http import models

from infra.ollama_client import get_client as get_ollama_client
from infra.qdrant_client import get_client as get_qdrant_client
from memory.sparse import sparse_vector


_SHARED_LAYERS_PATH = (
    Path(__file__).resolve().parents[4] / "packages" / "memrag-shared" / "src" / "memrag_shared" / "layers.py"
)
_SHARED_SPEC = importlib.util.spec_from_file_location("memrag_shared.layers", _SHARED_LAYERS_PATH)
if _SHARED_SPEC is None or _SHARED_SPEC.loader is None:
    raise ImportError(f"Unable to load shared layers from {_SHARED_LAYERS_PATH}")
_SHARED_MODULE = importlib.util.module_from_spec(_SHARED_SPEC)
_SHARED_SPEC.loader.exec_module(_SHARED_MODULE)

LAYER_AGENT = _SHARED_MODULE.LAYER_AGENT
MemoryChunk = _SHARED_MODULE.MemoryChunk
MemoryType = _SHARED_MODULE.MemoryType


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
):
    client = get_qdrant_client()
    if hasattr(models, "Prefetch") and hasattr(models, "FusionQuery"):
        response = client.query_points(
            collection_name=collection_name,
            prefetch=[
                models.Prefetch(query=dense_embedding, using="dense", limit=max(top_k * 3, 16)),
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
    return getattr(response, "points", response)


async def recall_agent_memory(
    workspace_id: str,
    agent_id: str,
    query_text: str,
    top_k: int = 8,
) -> list[MemoryChunk]:
    """Recall top-k agent memories for the given query."""

    dense_embedding = (await get_ollama_client().embed([query_text]))[0]
    sparse_payload = sparse_vector(query_text)
    query_filter = models.Filter(
        must=[
            models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id)),
            models.FieldCondition(key="agent_id", match=models.MatchValue(value=agent_id)),
            models.FieldCondition(key="tombstoned", match=models.MatchValue(value=False)),
        ]
    )
    points = cast(list[Any], _hybrid_query("agent_memories", dense_embedding, sparse_payload, query_filter, top_k))
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
