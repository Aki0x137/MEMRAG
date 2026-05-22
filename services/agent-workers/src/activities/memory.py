"""Temporal activities for long-term memory storage and recall."""

from __future__ import annotations

from temporalio import activity

from memory.mem0_client import extract_and_store
from recall.layer2 import recall_agent_memory
from recall.layer3 import recall_shared_memory


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
