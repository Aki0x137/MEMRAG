"""Ingestion workflow for BYOD knowledge sources."""

from __future__ import annotations

import importlib
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy


async def process_ingestion_batch(
    activity_runner,
    params: dict[str, Any],
    *,
    wait_for_hitl=None,
) -> dict[str, Any]:
    """Thin async helper that wraps the pii_screen activity call with HITL resume logic.

    Used in integration tests to verify the HITL halt-and-approve/abort path without
    running a full Temporal worker.  The *activity_runner* callable has the same
    signature as ``workflow.execute_activity``:
        await activity_runner(activity_fn, *, args, start_to_close_timeout)
    """
    pii_screen_fn = importlib.import_module("activities.pii_screen").pii_screen
    PIIDetectedMismatchError = importlib.import_module("pii").PIIDetectedMismatchError

    chunks = params["chunks"]
    connector_id = params["connector_id"]
    workspace_id = params["workspace_id"]
    contains_pii = params.get("contains_pii", False)
    pii_config = params.get("pii_config", {})

    try:
        screened = await activity_runner(
            pii_screen_fn,
            args=[chunks, connector_id, workspace_id, pii_config, contains_pii],
            start_to_close_timeout=timedelta(minutes=5),
        )
    except PIIDetectedMismatchError:
        if wait_for_hitl is None:
            return {"status": "aborted", "reason": "pii_detected_mismatch"}
        hitl_response = await wait_for_hitl()
        if hitl_response.get("action") == "abort":
            return {"status": "aborted", "reason": "pii_detected_mismatch"}
        # Retry with contains_pii=True after HITL approval
        screened = await activity_runner(
            pii_screen_fn,
            args=[chunks, connector_id, workspace_id, pii_config, True],
            start_to_close_timeout=timedelta(minutes=5),
        )
        return {"status": "ok", "chunks": screened, "resumed": True}

    return {"status": "ok", "chunks": screened, "resumed": False}


@workflow.defn
class IngestionWorkflow:
    """Orchestrate connector-driven ingestion with full/delta sync support."""

    def __init__(self) -> None:
        self._hitl_response: dict[str, Any] | None = None

    @workflow.signal(name="pii_halt")
    async def pii_halt_signal(self, payload: dict[str, Any]) -> None:
        """Signal from HITL endpoint when PII mismatch detected."""
        self._hitl_response = payload

    @workflow.run
    async def run(self, params: dict[str, Any]) -> dict[str, Any]:
        connector_id = params["connector_id"]
        workspace_id = params["workspace_id"]
        contains_pii = params.get("contains_pii", False)
        sync_mode = params.get("sync_mode", "full")  # "full" or "delta"

        # Activity 1: Fetch resources from external system
        resources = await workflow.execute_activity(
            "fetch_resources",
            args=[connector_id, params.get("connector_config", {})],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # Activity 2: Diff against known sync state
        changed_resources = await workflow.execute_activity(
            "diff_resources",
            args=[connector_id, resources],
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if not changed_resources:
            return {
                "connector_id": connector_id,
                "workspace_id": workspace_id,
                "sync_status": "ok",
                "chunks_processed": 0,
                "resources_changed": 0,
                "message": "No changes detected (full idempotency via content-hash)",
            }

        # Activity 3: For each changed resource, chunk and embed
        chunk_batches = []
        for resource in changed_resources:
            chunks_with_embeddings = await workflow.execute_activity(
                "chunk_and_embed",
                args=[connector_id, resource],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            chunk_batches.extend(chunks_with_embeddings)

        # Activity 4: Screen for PII (may halt)
        screened_chunks = await workflow.execute_activity(
            "pii_screen",
            args=[connector_id, workspace_id, chunk_batches, contains_pii],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        # Activity 5: Upsert to org_knowledge
        upserted_count = await workflow.execute_activity(
            "upsert_org_knowledge",
            args=[connector_id, workspace_id, screened_chunks, params.get("connector_config", {})],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # Activity 6: Update sync state once per resource (dedup by resource_id)
        seen_resources: set[str] = set()
        for chunk in screened_chunks:
            resource_id = chunk.get("metadata", {}).get("resource_id", "")
            content_hash = chunk.get("metadata", {}).get("content_hash", "")
            if resource_id and content_hash and resource_id not in seen_resources:
                seen_resources.add(resource_id)
                await workflow.execute_activity(
                    "update_sync_state",
                    args=[connector_id, resource_id, content_hash],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )

        return {
            "connector_id": connector_id,
            "workspace_id": workspace_id,
            "sync_status": "ok",
            "chunks_processed": upserted_count,
            "resources_changed": len(changed_resources),
            "sync_mode": sync_mode,
        }
