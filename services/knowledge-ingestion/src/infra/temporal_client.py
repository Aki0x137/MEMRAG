"""Temporal client helpers for knowledge-ingestion."""

from __future__ import annotations

import concurrent.futures
import os
from typing import Any, Sequence

from temporalio.client import Client
from temporalio.worker import Worker


def _temporal_target() -> str:
    return os.getenv("TEMPORAL_HOST", "temporal:7233")


async def get_client() -> Client:
    """Create a Temporal client connected to the configured server."""

    return await Client.connect(_temporal_target())


async def get_worker(
    task_queue: str = "ingestion-workers",
    workflows: Sequence[type[Any]] | None = None,
    activities: Sequence[Any] | None = None,
) -> Worker:
    """Create a Temporal worker bound to the ingestion queue."""

    client = await get_client()
    return Worker(
        client,
        task_queue=task_queue,
        workflows=list(workflows or []),
        activities=list(activities or []),
        activity_executor=concurrent.futures.ThreadPoolExecutor(max_workers=10),
    )
