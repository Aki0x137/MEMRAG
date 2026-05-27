"""Temporal activities for ingestion workflow."""

from __future__ import annotations

from typing import Any

from temporalio import activity

from activities.sync_state import diff_resources as _diff_resources
from activities.sync_state import update_sync_state as _update_sync_state
from activities.upsert import upsert_org_knowledge as _upsert_org_knowledge
from chunker import chunk
from embedder import embed_batch, embed_sparse


def _infer_content_type(source_type: str, resource_id: str) -> str:
    """Infer content type from source and resource path."""
    if source_type == "rds_schema":
        return "schema"
    ext = resource_id.rsplit(".", 1)[-1].lower() if "." in resource_id else ""
    if ext in ("py", "go", "ts", "js", "java", "rs", "c", "cpp", "h", "rb", "php"):
        return "code"
    if ext in ("md", "txt", "rst", "html", "htm"):
        return "prose"
    if ext in ("sql", "ddl"):
        return "schema"
    if source_type == "github":
        return "code"
    return "prose"


def _make_connector(source_type: str, connector_config: dict):
    """Instantiate the appropriate connector from config."""
    if source_type == "github":
        from connectors.github import GitHubConnector
        return GitHubConnector(config=connector_config)
    if source_type == "confluence":
        from connectors.confluence import ConfluenceConnector
        return ConfluenceConnector(config=connector_config)
    if source_type == "slack":
        from connectors.slack import SlackConnector
        return SlackConnector(config=connector_config)
    if source_type == "rds_schema":
        from connectors.rds_schema import RDSSchemaConnector
        return RDSSchemaConnector(config=connector_config)
    return None


@activity.defn
async def fetch_resources(connector_id: str, connector_config: dict | None = None) -> list[dict]:
    """Fetch all resources from the external connector."""
    if not connector_config:
        activity.logger.warning("fetch_resources: no connector_config provided, returning empty list")
        return []

    source_type = connector_config.get("source_type", "")
    connector = _make_connector(source_type, connector_config)
    if connector is None:
        activity.logger.warning("fetch_resources: unknown source_type %r", source_type)
        return []

    await connector.authenticate()
    resources = await connector.list_resources()

    result: list[dict] = []
    for resource in resources:
        content = await connector.fetch_resource(resource.id)
        if isinstance(content, bytes):
            content_text = content.decode("utf-8", errors="replace")
        else:
            content_text = str(content)
        result.append({
            "id": resource.id,
            "url": resource.url,
            "title": resource.title,
            "last_modified": resource.last_modified,
            "content": content_text,
            "source_type": source_type,
            "content_type": _infer_content_type(source_type, resource.id),
        })

    return result


@activity.defn
async def diff_resources(connector_id: str, resources: list[dict]) -> list[dict]:
    """Return full resource dicts for resources whose content has changed."""
    diffs = await _diff_resources(connector_id, resources)
    diff_map = {d.resource_id: d.content_hash for d in diffs}
    # Return the full original resource dict annotated with the computed content_hash
    return [
        {**resource, "content_hash": diff_map[resource["id"]]}
        for resource in resources
        if resource["id"] in diff_map
    ]


@activity.defn
async def chunk_and_embed(connector_id: str, resource: dict) -> list[dict]:
    """Chunk a resource and generate dense + sparse embeddings."""
    text = resource.get("content", "")
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")

    source_type = resource.get("source_type", "unknown")
    content_type = resource.get("content_type", "text")
    # Pass through the resource-level content hash for sync state tracking
    resource_content_hash = resource.get("content_hash", "")

    chunks_list = chunk(text, source_type, content_type)
    if not chunks_list:
        return []

    dense_embeddings = await embed_batch(chunks_list)
    sparse_vectors = embed_sparse(chunks_list)

    result: list[dict] = []
    for i, (text_chunk, dense, sparse) in enumerate(zip(chunks_list, dense_embeddings, sparse_vectors, strict=False)):
        result.append({
            "text": text_chunk,
            "dense": dense,
            "sparse": sparse,
            "metadata": {
                "resource_id": resource.get("id", ""),
                "content_hash": resource_content_hash,  # resource-level hash for delta sync
                "chunk_index": i,
                "title": resource.get("title", ""),
                "url": resource.get("url"),
                "source_type": source_type,
            },
        })

    return result


@activity.defn
async def pii_screen(
    connector_id: str,
    workspace_id: str,
    chunks: list[dict],
    contains_pii: bool,
) -> list[dict]:
    """Screen chunks for PII; filter/redact as needed (stub until Phase 7)."""
    return chunks


@activity.defn
async def upsert_org_knowledge(
    connector_id: str,
    workspace_id: str,
    chunks_with_embeddings: list[dict[str, Any]],
    connector_config: dict[str, Any],
) -> int:
    """Upsert chunks to org_knowledge Qdrant collection."""
    return await _upsert_org_knowledge(connector_id, workspace_id, chunks_with_embeddings, connector_config)


@activity.defn
async def update_sync_state(
    connector_id: str,
    resource_id: str,
    content_hash: str,
) -> None:
    """Update sync state for a resource after successful ingestion."""
    await _update_sync_state(connector_id, resource_id, content_hash)
