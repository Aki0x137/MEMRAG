"""Mem0-backed fact extraction with Qdrant persistence."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from qdrant_client.http import models

from infra.ollama_client import get_client as get_ollama_client
from infra.qdrant_client import get_client as get_qdrant_client
from memory.dedup import is_near_duplicate
from memory.sparse import sparse_vector

try:
    from mem0 import Memory as Mem0Memory
except ImportError:  # pragma: no cover - optional until env is synced
    Mem0Memory = None


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fact_id(workspace_id: str, agent_id: str, fact_text: str) -> str:
    digest = hashlib.sha256(f"{workspace_id}:{agent_id}:{fact_text}".encode("utf-8")).hexdigest()
    return digest


def _build_mem0_config() -> dict[str, Any]:
    """Build Mem0 configuration pointing at the local Ollama instance."""
    ollama_base = os.getenv("OLLAMA_HOST", "http://ollama:11434")
    return {
        "llm": {
            "provider": "ollama",
            "config": {
                "model": os.getenv("OLLAMA_CHAT_MODEL", "gemma4:12b"),
                "ollama_base_url": ollama_base,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:4b"),
                "ollama_base_url": ollama_base,
            },
        },
    }


def _extract_facts_with_fallback(text: str, agent_id: str = "default") -> list[str]:
    if os.getenv("ENVIRONMENT") == "test":
        return [text]

    if os.getenv("MEM0_ENABLED", "false").lower() == "true" and Mem0Memory is not None:
        try:
            memory = Mem0Memory.from_config(_build_mem0_config())
            result = memory.add(
                messages=[{"role": "user", "content": text}],
                agent_id=agent_id,
            )
            facts = [
                entry["memory"]
                for entry in (result.get("results") or [])
                if isinstance(entry, dict) and entry.get("memory")
            ]
            if facts:
                return facts
        except Exception:
            pass

    facts = [segment.strip() for segment in text.replace("\n", ". ").split(".") if segment.strip()]
    return facts or [text]


async def extract_and_store(agent_id: str, workspace_id: str, text: str) -> list[str]:
    """Extract facts from workflow output and store them in Qdrant."""

    facts = _extract_facts_with_fallback(text, agent_id=agent_id)
    embeddings = await get_ollama_client().embed(facts)
    client = get_qdrant_client()

    stored_ids: list[str] = []
    for fact, embedding in zip(facts, embeddings, strict=False):
        if await is_near_duplicate(embedding, workspace_id, agent_id):
            continue

        point_id = _fact_id(workspace_id, agent_id, fact)
        now = _utcnow()
        payload: dict[str, Any] = {
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "memory_type": "semantic",
            "decay_score": 1.0,
            "created_at": now,
            "last_accessed_at": now,
            "content_hash": point_id,
            "tombstoned": False,
            "text": fact,
        }
        sparse = sparse_vector(fact)
        client.upsert(
            collection_name="agent_memories",
            points=[
                models.PointStruct(
                    id=point_id,
                    vector={
                        "dense": embedding,
                        "sparse": models.SparseVector(
                            indices=sparse["indices"],
                            values=sparse["values"],
                        ),
                    },
                    payload=payload,
                )
            ],
            wait=True,
        )
        stored_ids.append(point_id)

    return stored_ids
