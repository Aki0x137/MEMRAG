"""Idempotent Qdrant collection bootstrap for all MEMRAG layers."""

from __future__ import annotations

import os

from qdrant_client import QdrantClient
from qdrant_client.http import models


def _qdrant_url() -> str:
    host = os.getenv("QDRANT_HOST", "qdrant:6333")
    if host.startswith("http://") or host.startswith("https://"):
        return host
    return f"http://{host}"


def _client() -> QdrantClient:
    return QdrantClient(url=_qdrant_url(), api_key=os.getenv("QDRANT_API_KEY") or None)


def ensure_collections() -> None:
    client = _client()
    collection_names = {name for collection in client.get_collections().collections for name in [collection.name]}

    vector_config = {"dense": models.VectorParams(size=768, distance=models.Distance.COSINE)}
    sparse_vectors = {"sparse": models.SparseVectorParams(index=models.SparseIndexParams(on_disk=False))}

    for collection_name in ("agent_memories", "shared_memories", "org_knowledge"):
        if collection_name not in collection_names:
            client.create_collection(
                collection_name=collection_name,
                vectors_config=vector_config,
                sparse_vectors_config=sparse_vectors,
            )

    _ensure_payload_indexes(client)


def _ensure_payload_indexes(client: QdrantClient) -> None:
    payload_indexes = {
        "agent_memories": ["workspace_id", "agent_id", "tombstoned"],
        "shared_memories": ["workspace_id"],
        "org_knowledge": ["workspace_id", "connector_id", "sharing_scope", "source_type", "content_hash"],
    }
    for collection_name, fields in payload_indexes.items():
        for field in fields:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
                wait=True,
            )


if __name__ == "__main__":
    ensure_collections()
