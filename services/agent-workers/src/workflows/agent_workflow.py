"""Agent workflow with crash-safe session checkpointing."""

from __future__ import annotations

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

        existing_turns = await workflow.execute_activity(
            "fetch_recent_session",
            args=[workspace_id, session_id],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        recalled_memories = await workflow.execute_activity(
            "recall_agent_memory_activity",
            args=[workspace_id, agent_id, prompt, params.get("top_k", 8)],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        turns = list(existing_turns)
        turns.extend(params.get("turns") or [])

        if params.get("workflow_output"):
            workflow_output = params["workflow_output"]
        elif recalled_memories:
            recalled_text = "; ".join(memory.text for memory in recalled_memories)
            workflow_output = f"Agent {agent_id} processed: {prompt}\nRelevant memories: {recalled_text}"
        else:
            workflow_output = f"Agent {agent_id} processed: {prompt}"

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
            "turn_count": len(turns),
            "workflow_output": workflow_output,
            "hitl_response": self._hitl_response,
        }
