"""Temporal worker bootstrap for agent-workers."""

from __future__ import annotations

import asyncio
import logging

from activities.memory import (
    recall_agent_memory_activity,
    recall_shared_memory_activity,
    store_agent_memory,
    store_with_graphiti,
)
from activities.session import checkpoint_session, fetch_recent_session
from infra.temporal_client import get_worker
from tools.promote_finding import promote_finding_to_shared_knowledge
from workflows.agent_workflow import AgentWorkflow


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    worker = await get_worker(
        task_queue="agent-workers",
        workflows=[AgentWorkflow],
        activities=[
            fetch_recent_session,
            checkpoint_session,
            recall_agent_memory_activity,
            recall_shared_memory_activity,
            store_agent_memory,
            store_with_graphiti,
            promote_finding_to_shared_knowledge,
        ],
    )
    await worker.run()



if __name__ == "__main__":
    asyncio.run(main())