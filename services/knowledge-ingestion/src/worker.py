"""Temporal worker bootstrap for knowledge-ingestion workflows."""

from __future__ import annotations

import asyncio
import logging

from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from infra.temporal_client import get_client, get_worker
from workflows.decay_memories import decay_and_archive
from workflows.decay_workflow import DecayMemoriesWorkflow


async def _ensure_decay_schedule() -> None:
    client = await get_client()
    try:
        await client.start_workflow(
            DecayMemoriesWorkflow.run,
            "default-workspace",
            id="decay-memories-nightly",
            task_queue="ingestion-workers",
            cron_schedule="0 2 * * *",
        )
    except (RPCError, WorkflowAlreadyStartedError):
        pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    await _ensure_decay_schedule()
    worker = await get_worker(
        task_queue="ingestion-workers",
        workflows=[DecayMemoriesWorkflow],
        activities=[decay_and_archive],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())