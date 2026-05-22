"""LLM-callable tool: promote a finding to the shared workspace knowledge pool."""

from __future__ import annotations

from temporalio import activity

from infra.ollama_client import get_client as get_ollama_client
from memory.shared import promote_to_shared

# Tool schema for model-aware tool calling (Ollama native + JSON fallback).
PROMOTE_FINDING_TOOL_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": "promote_finding_to_shared_knowledge",
        "description": (
            "Promote an important finding or insight to the shared workspace memory "
            "so other agents in the same workspace can recall it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The finding or insight to promote.",
                }
            },
            "required": ["text"],
        },
    },
}


@activity.defn
async def promote_finding_to_shared_knowledge(
    workspace_id: str,
    source_agent_id: str,
    text: str,
) -> dict:
    """Generate an embedding for *text* and promote it to shared_memories."""
    embedding = (await get_ollama_client().embed([text]))[0]
    status = await promote_to_shared(
        workspace_id=workspace_id,
        source_agent_id=source_agent_id,
        text=text,
        embedding=embedding,
    )
    return {"status": status}
