"""LLM-callable tool: promote a finding to the shared workspace knowledge pool."""

from __future__ import annotations

from temporalio import activity

from activities.memory import _store_shared_finding

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
    """Promote a finding through the active Layer 3 backend."""
    status = await _store_shared_finding(
        workspace_id=workspace_id,
        source_agent_id=source_agent_id,
        finding_text=text,
        episode_metadata={"source_agent_id": source_agent_id},
    )
    return {"status": status}
