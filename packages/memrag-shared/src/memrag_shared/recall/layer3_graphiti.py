"""Layer 3 — Graphiti-backed shared memory recall via graphiti-server REST API.

Called in place of ``layer3.py`` when ``GRAPHITI_ENABLED=true``.  The existing
Qdrant path in ``layer3.py`` is left entirely unmodified.
"""

from __future__ import annotations

import logging
import os

import httpx

from memrag_shared.layers import LAYER_SHARED, MemoryChunk

log = logging.getLogger(__name__)


async def recall_shared_graphiti(
    workspace_id: str,
    query_text: str,
    top_k: int = 8,
) -> list[MemoryChunk]:
    """Recall shared memories from the Graphiti knowledge graph.

    Args:
        workspace_id: Workspace/tenant identifier used as Graphiti ``group_id``.
        query_text: Natural-language query string.
        top_k: Maximum number of facts to return.

    Returns:
        List of :class:`~memrag_shared.layers.MemoryChunk` objects with
        ``source_type="graphiti"`` and ``layer=LAYER_SHARED``.

    Raises:
        httpx.HTTPError: On non-2xx responses or network errors.  The caller
            is responsible for deciding whether to fall back or propagate.
    """
    server_url = os.getenv(
        "GRAPHITI_SERVER_URL", "http://graphiti-server:8000"
    ).rstrip("/")
    url = f"{server_url}/search/facts"
    params = {
        "group_id": workspace_id,
        "query": query_text,
        "limit": top_k,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    # Graphiti may return a bare list or {"facts": [...]}
    facts: list[dict] = data if isinstance(data, list) else data.get("facts", [])

    chunks: list[MemoryChunk] = []
    for fact in facts:
        text = fact.get("fact", fact.get("content", str(fact)))
        score = float(fact.get("score", 1.0))
        chunks.append(
            MemoryChunk(
                id=fact.get("uuid", ""),
                agent_id="",
                workspace_id=workspace_id,
                text=text,
                source_type="graphiti",
                score=score,
                layer=LAYER_SHARED,
                metadata={"graphiti": True},
            )
        )

    return chunks
