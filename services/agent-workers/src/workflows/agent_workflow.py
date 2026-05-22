"""Agent workflow with crash-safe session checkpointing."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class AgentWorkflow:
    """Checkpoint session state around each workflow execution."""

    def __init__(self) -> None:
        self._hitl_response: dict[str, Any] | None = None

    @workflow.signal(name="hitl_response")
    async def hitl_response(self, payload: dict[str, Any]) -> None:
        self._hitl_response = payload

    @workflow.run
    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        workspace_id = params["workspace_id"]
        session_id = params["session_id"]
        agent_id = params["agent_id"]
        prompt = params.get("prompt", "")
        manifest = params.get("manifest") or {}

        existing_turns = await workflow.execute_activity(
            "fetch_recent_session",
            args=[workspace_id, session_id],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # Parallel fan-out: Layer 2 (agent memories) + Layer 3 (shared workspace memories)
        recalled_memories, shared_memories = await asyncio.gather(
            workflow.execute_activity(
                "recall_agent_memory_activity",
                args=[workspace_id, agent_id, prompt, params.get("top_k", 8)],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            ),
            workflow.execute_activity(
                "recall_shared_memory_activity",
                args=[workspace_id, prompt, params.get("top_k", 8)],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            ),
        )

        turns = list(existing_turns)
        turns.extend(params.get("turns") or [])

        all_recalled = list(recalled_memories) + list(shared_memories)

        if params.get("workflow_output"):
            workflow_output = params["workflow_output"]
        elif all_recalled:
            recalled_text = "; ".join(memory.text for memory in all_recalled)
            workflow_output = f"Agent {agent_id} processed: {prompt}\nRelevant memories: {recalled_text}"
        else:
            workflow_output = f"Agent {agent_id} processed: {prompt}"

        # Explicit tool-call path: process any tool calls passed in params (deterministic
        # fallback when native tool calling is unsupported or model output is malformed).
        for tool_call in params.get("tool_calls") or []:
            if tool_call.get("name") == "promote_finding_to_shared_knowledge":
                text = (tool_call.get("arguments") or {}).get("text", "")
                if text:
                    await workflow.execute_activity(
                        "promote_finding_to_shared_knowledge",
                        args=[workspace_id, agent_id, text],
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )

        # Auto-promotion path: if manifest.promote_to_shared=True, fire-and-forget promotion.
        if manifest.get("promote_to_shared") and workflow_output:
            workflow.start_activity(
                "promote_finding_to_shared_knowledge",
                args=[workspace_id, agent_id, workflow_output],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

        workflow.start_activity(
            "store_agent_memory",
            args=[workspace_id, agent_id, workflow_output],
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        turns.append(
            {
                "role": "assistant",
                "content": workflow_output,
                "agent_id": agent_id,
                "recalled_memories": [memory.text for memory in recalled_memories],
                "shared_memories": [memory.text for memory in shared_memories],
            }
        )

        await workflow.execute_activity(
            "checkpoint_session",
            args=[workspace_id, session_id, turns],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        return {
            "workspace_id": workspace_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "recovered_turn_count": len(existing_turns),
            "recalled_memories": [memory.text for memory in recalled_memories],
            "shared_memories": [memory.text for memory in shared_memories],
            "turn_count": len(turns),
            "workflow_output": workflow_output,
            "hitl_response": self._hitl_response,
        }
