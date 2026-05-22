"""Temporal worker bootstrap for knowledge-ingestion workflows."""

from __future__ import annotations

import asyncio
import logging

from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from activities.ingestion import (
    chunk_and_embed,
    diff_resources,
    fetch_resources,
    pii_screen,
    update_sync_state,
    upsert_org_knowledge,
)
from infra.temporal_client import get_client, get_worker
from workflows.decay_memories import decay_and_archive
from workflows.decay_workflow import DecayMemoriesWorkflow
from workflows.ingestion import IngestionWorkflow


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
        workflows=[DecayMemoriesWorkflow, IngestionWorkflow],
        activities=[
            decay_and_archive,
            fetch_resources,
            diff_resources,
            chunk_and_embed,
            pii_screen,
            upsert_org_knowledge,
            update_sync_state,
        ],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())