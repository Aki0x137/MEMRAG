"""Temporal activities for long-term memory storage and recall."""

from __future__ import annotations

import os
from typing import Any

import httpx
from temporalio import activity

from infra.ollama_client import get_client as get_ollama_client
from memory.mem0_client import extract_and_store
from memory.shared import promote_to_shared
from recall.layer2 import recall_agent_memory
from recall.layer3 import recall_shared_memory


def _graphiti_enabled() -> bool:
    return os.getenv("GRAPHITI_ENABLED", "false").lower() == "true"


def _graphiti_server_url() -> str:
    return os.getenv("GRAPHITI_SERVER_URL", "http://graphiti-server:8100").rstrip("/")


async def _store_shared_finding(
    workspace_id: str,
    source_agent_id: str,
    finding_text: str,
    episode_metadata: dict[str, Any] | None = None,
) -> str:
    metadata = dict(episode_metadata or {})
    metadata.setdefault("source_agent_id", source_agent_id)
    metadata.setdefault("agent_id", source_agent_id)

    if _graphiti_enabled():
        payload = {
            "group_id": workspace_id,
            "content": finding_text,
            "episode_body": finding_text,
            "metadata": metadata,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{_graphiti_server_url()}/episodes", json=payload)
            response.raise_for_status()
        return "stored"

    embedding = (await get_ollama_client().embed([finding_text]))[0]
    return await promote_to_shared(
        workspace_id=workspace_id,
        source_agent_id=source_agent_id,
        text=finding_text,
        embedding=embedding,
    )


@activity.defn
async def store_agent_memory(workspace_id: str, agent_id: str, workflow_output: str) -> list[str]:
    """Extract facts from a workflow result and store them asynchronously."""

    return await extract_and_store(agent_id=agent_id, workspace_id=workspace_id, text=workflow_output)


@activity.defn
async def recall_agent_memory_activity(
    workspace_id: str,
    agent_id: str,
    query_text: str,
    top_k: int = 8,
):
    """Temporal activity wrapper for long-term memory recall."""

    return await recall_agent_memory(workspace_id=workspace_id, agent_id=agent_id, query_text=query_text, top_k=top_k)


@activity.defn
async def recall_shared_memory_activity(
    workspace_id: str,
    query_text: str,
    top_k: int = 8,
):
    """Temporal activity wrapper for Layer 3 shared memory recall."""

    return await recall_shared_memory(workspace_id=workspace_id, query_text=query_text, top_k=top_k)


@activity.defn
async def store_with_graphiti(
    workspace_id: str,
    finding_text: str,
    episode_metadata: dict[str, Any] | None = None,
) -> str:
    """Store a Layer 3 finding via Graphiti when enabled, otherwise fall back to Qdrant."""

    metadata = dict(episode_metadata or {})
    source_agent_id = str(metadata.get("source_agent_id") or metadata.get("agent_id") or "unknown-agent")
    return await _store_shared_finding(
        workspace_id=workspace_id,
        source_agent_id=source_agent_id,
        finding_text=finding_text,
        episode_metadata=metadata,
    )
