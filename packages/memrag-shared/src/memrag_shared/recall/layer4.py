"""Layer 4 org-knowledge recall with sharing-scope enforcement."""

from __future__ import annotations

from typing import Any, cast

from qdrant_client.http import models

from memrag_shared.infra.ollama_client import get_client as get_ollama_client
from memrag_shared.infra.qdrant_client import get_client as get_qdrant_client
from memrag_shared.layers import KnowledgeChunk, KnowledgeType, LAYER_ORG
from memrag_shared.memory.sparse import sparse_vector
from memrag_shared.metrics import record_recall_latency
from memrag_shared.recall.grants import Grant, load_grants


def _parse_knowledge_type(value: str | None) -> KnowledgeType:
    if not value:
        return KnowledgeType.DOCUMENT
    try:
        return KnowledgeType(value)
    except ValueError:
        return KnowledgeType.DOCUMENT


def _hybrid_query(
    dense_embedding: list[float],
    sparse_payload: dict[str, list[int] | list[float]],
    top_k: int,
):
    client = get_qdrant_client()
    if hasattr(models, "Prefetch") and hasattr(models, "FusionQuery"):
        response = client.query_points(
            collection_name="org_knowledge",
            prefetch=[
                models.Prefetch(query=dense_embedding, using="dense", limit=max(top_k * 3, 16)),
                models.Prefetch(
                    query=models.SparseVector(
                        indices=sparse_payload["indices"],
                        values=sparse_payload["values"],
                    ),
                    using="sparse",
                    limit=max(top_k * 3, 16),
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            with_payload=True,
            with_vectors=False,
            limit=max(top_k * 3, 16),
        )
    else:
        response = client.query_points(
            collection_name="org_knowledge",
            query=dense_embedding,
            using="dense",
            with_payload=True,
            with_vectors=False,
            limit=max(top_k * 3, 16),
        )
    return getattr(response, "points", response)


def _agent_scope_allows(payload: dict[str, Any], agent_id: str, agent_tags: list[str]) -> bool:
    scope = str(payload.get("agent_scope", "all") or "all")
    if scope == "all":
        return True
    if scope == "by_id":
        allowed_ids = payload.get("allowed_agent_ids") or []
        return agent_id in allowed_ids
    if scope == "by_tag":
        allowed_tags = set(payload.get("allowed_agent_tags") or [])
        return bool(allowed_tags.intersection(agent_tags))
    return True


def _sharing_scope_allows(
    payload: dict[str, Any],
    workspace_id: str,
    allowed_connector_ids: set[str],
) -> bool:
    sharing_scope = str(payload.get("sharing_scope", "private") or "private")
    connector_id = str(payload.get("connector_id", ""))
    source_workspace_id = str(payload.get("workspace_id", workspace_id))

    if sharing_scope == "platform_public":
        return True
    if sharing_scope == "workspace_internal":
        return source_workspace_id == workspace_id
    if sharing_scope == "allowlist":
        return connector_id in allowed_connector_ids
    if sharing_scope == "private":
        return source_workspace_id == workspace_id or connector_id in allowed_connector_ids
    return source_workspace_id == workspace_id


def _normalise_grants(grants: list[Grant]) -> set[str]:
    return {grant.connector_id for grant in grants}


async def recall_org_knowledge(
    workspace_id: str,
    agent_id: str,
    agent_tags: list[str],
    query_text: str,
    top_k: int = 8,
    grants_cache=None,
    dense_embedding: list[float] | None = None,
    sparse_payload: dict[str, list[int] | list[float]] | None = None,
) -> list[KnowledgeChunk]:
    """Recall organization knowledge with sharing-scope and agent-scope enforcement."""

    with record_recall_latency("layer4", workspace_id):
        if dense_embedding is None:
            dense_embedding = (await get_ollama_client().embed([query_text]))[0]
        if sparse_payload is None:
            sparse_payload = sparse_vector(query_text)
        grants = load_grants(workspace_id, grants_cache)
        allowed_connector_ids = _normalise_grants(grants)

        points = cast(list[Any], _hybrid_query(dense_embedding, sparse_payload, top_k))
        chunks: list[KnowledgeChunk] = []
        seen_ids: set[str] = set()

        for point in points:
            if isinstance(point, tuple):
                scored_point = point[0]
                score = point[1] if len(point) > 1 else None
            else:
                scored_point = point
                score = getattr(point, "score", None)

            payload = getattr(scored_point, "payload", {}) or {}
            if not payload:
                continue
            point_id = str(getattr(scored_point, "id", ""))
            if point_id in seen_ids:
                continue
            if not _sharing_scope_allows(payload, workspace_id, allowed_connector_ids):
                continue
            if not _agent_scope_allows(payload, agent_id, agent_tags):
                continue

            seen_ids.add(point_id)
            text = str(payload.get("text", ""))
            chunks.append(
                KnowledgeChunk(
                    id=point_id,
                    org_id=str(payload.get("workspace_id", workspace_id)),
                    connector_type=str(payload.get("source_type", "org_knowledge")),
                    text=text,
                    content=text,
                    knowledge_type=_parse_knowledge_type(payload.get("knowledge_type")),
                    title=str(payload.get("title", "")),
                    embedding=payload.get("dense_embedding"),
                    source_type=str(payload.get("source_type", "org_knowledge")),
                    score=float(score or getattr(scored_point, "score", 0.0) or 0.0),
                    url=payload.get("url"),
                    connector_id=str(payload.get("connector_id", "")),
                    source_url=payload.get("url"),
                    source_id=str(payload.get("resource_id", "")),
                    workspace_ids=list(payload.get("allowed_workspace_ids") or []),
                    topic_tags=list(payload.get("topic_tags") or []),
                    contains_pii=bool(payload.get("contains_pii", False)),
                    pii_entities=payload.get("pii_entities", {}) or {},
                    metadata={**payload, "layer": LAYER_ORG},
                )
            )
            if len(chunks) >= top_k:
                break

        return chunks