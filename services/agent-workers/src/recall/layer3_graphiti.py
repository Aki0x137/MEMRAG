"""Layer 3 shared memory recall against Graphiti search_facts."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

import httpx


_SHARED_LAYERS_PATH = (
    Path(__file__).resolve().parents[4] / "packages" / "memrag-shared" / "src" / "memrag_shared" / "layers.py"
)
_SHARED_SPEC = importlib.util.spec_from_file_location("memrag_shared.layers", _SHARED_LAYERS_PATH)
if _SHARED_SPEC is None or _SHARED_SPEC.loader is None:
    raise ImportError(f"Unable to load shared layers from {_SHARED_LAYERS_PATH}")
_SHARED_MODULE = importlib.util.module_from_spec(_SHARED_SPEC)
_SHARED_SPEC.loader.exec_module(_SHARED_MODULE)

LAYER_SHARED = _SHARED_MODULE.LAYER_SHARED
MemoryChunk = _SHARED_MODULE.MemoryChunk
MemoryType = _SHARED_MODULE.MemoryType


def _graphiti_server_url() -> str:
    return os.getenv("GRAPHITI_SERVER_URL", "http://graphiti-server:8100").rstrip("/")


def _fact_text(item: dict[str, Any]) -> str:
    for key in ("fact", "text", "content", "episode_body", "body"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


async def recall_shared_graphiti(
    workspace_id: str,
    query_text: str,
    top_k: int = 8,
) -> list[MemoryChunk]:
    """Recall shared findings from Graphiti for the given workspace/query."""

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_graphiti_server_url()}/search/facts",
            params={"group_id": workspace_id, "query": query_text, "limit": top_k},
        )
        response.raise_for_status()
        payload = response.json()

    if isinstance(payload, list):
        items = payload
    else:
        items = payload.get("results") or payload.get("facts") or payload.get("items") or []

    chunks: list[MemoryChunk] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        text = _fact_text(item)
        if not text:
            continue
        metadata = dict(item)
        chunks.append(
            MemoryChunk(
                id=str(item.get("id") or item.get("uuid") or f"graphiti-{index}"),
                agent_id=str(item.get("agent_id") or item.get("source_agent_id") or ""),
                workspace_id=workspace_id,
                text=text,
                content=text,
                memory_type=MemoryType.FACT,
                source_type="graphiti",
                score=float(item.get("score") or item.get("combined_score") or 0.0),
                layer=LAYER_SHARED,
                metadata=metadata,
            )
        )

    return chunks