"""DecayMemoriesWorkflow definition (no external imports for sandbox compatibility)."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn
class DecayMemoriesWorkflow:
    """Cron workflow that triggers nightly memory decay and archival."""

    @workflow.run
    async def run(self, workspace_id: str) -> int:
        return await workflow.execute_activity(
            "decay_and_archive",
            args=[workspace_id],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
