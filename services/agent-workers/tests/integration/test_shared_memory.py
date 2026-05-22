"""Integration test for US3: cross-agent shared workspace memory.

Tests:
- Agent A promotes a finding to shared_memories.
- Agent B (same workspace, different agent_id) recalls and finds it.
- Agent C (different workspace_id) recalls and does NOT find it.
- Duplicate promotion returns 'duplicate'.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from memory import shared as shared_module
from recall import layer3


# ---------------------------------------------------------------------------
# Fake infrastructure
# ---------------------------------------------------------------------------

@dataclass
class FakePoint:
    id: str
    vector: dict
    payload: dict
    score: float = 1.0


class FakeQdrant:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, FakePoint]] = {
            "agent_memories": {},
            "shared_memories": {},
        }

    def upsert(self, collection_name: str, points, wait: bool = True) -> None:
        for point in points:
            self.collections.setdefault(collection_name, {})[str(point.id)] = FakePoint(
                id=str(point.id),
                vector=point.vector,
                payload=point.payload,
            )

    def query_points(
        self,
        collection_name: str,
        query=None,
        using: str | None = None,
        query_filter=None,
        limit: int = 10,
        with_payload: bool = True,
        with_vectors: bool = False,
        prefetch=None,
    ):
        points = list(self.collections.get(collection_name, {}).values())

        # Apply payload filters
        if query_filter is not None:
            for condition in query_filter.must:
                key = condition.key
                value = condition.match.value
                points = [p for p in points if p.payload.get(key) == value]

        # Score by raw dot product against dense vector
        query_vector = query
        if using != "dense" and prefetch:
            query_vector = prefetch[0].query

        scored: list[FakePoint] = []
        for point in points:
            dense = point.vector.get("dense", [])
            score = sum(a * b for a, b in zip(query_vector or [], dense, strict=False))
            scored.append(FakePoint(id=point.id, vector=point.vector, payload=point.payload, score=score))

        scored.sort(key=lambda p: p.score, reverse=True)
        return type("Result", (), {"points": scored[:limit]})()


class FakeOllama:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for text in texts:
            base = float(len(text))
            embeddings.append([base, base / 2, 1.0])
        return embeddings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_agent_b_recalls_promoted_finding(monkeypatch) -> None:
    """Agent A promotes; Agent B (same workspace) recalls it with source_type=shared_memory."""
    fake_qdrant = FakeQdrant()
    fake_ollama = FakeOllama()

    monkeypatch.setattr(shared_module, "get_client", lambda: fake_qdrant)
    monkeypatch.setattr(layer3, "get_qdrant_client", lambda: fake_qdrant)
    monkeypatch.setattr(layer3, "get_ollama_client", lambda: fake_ollama)

    text = "canary-finding-XYZ"
    embedding = asyncio.run(fake_ollama.embed([text]))[0]

    # Agent A promotes
    status = asyncio.run(
        shared_module.promote_to_shared(
            workspace_id="workspace-a",
            source_agent_id="agent-a",
            text=text,
            embedding=embedding,
        )
    )
    assert status == "stored"
    assert "shared_memories" in fake_qdrant.collections
    assert len(fake_qdrant.collections["shared_memories"]) == 1

    # Agent B (same workspace, different agent_id) recalls
    recalled = asyncio.run(
        layer3.recall_shared_memory(
            workspace_id="workspace-a",
            query_text=text,
            top_k=5,
        )
    )
    assert recalled, "Agent B should find the promoted finding"
    assert any("canary-finding-XYZ" in chunk.text for chunk in recalled)
    assert all(chunk.source_type == "shared_memory" for chunk in recalled)


def test_agent_c_cross_workspace_isolation(monkeypatch) -> None:
    """Agent C in a different workspace must NOT see workspace-a's shared finding."""
    fake_qdrant = FakeQdrant()
    fake_ollama = FakeOllama()

    monkeypatch.setattr(shared_module, "get_client", lambda: fake_qdrant)
    monkeypatch.setattr(layer3, "get_qdrant_client", lambda: fake_qdrant)
    monkeypatch.setattr(layer3, "get_ollama_client", lambda: fake_ollama)

    text = "canary-finding-XYZ"
    embedding = asyncio.run(fake_ollama.embed([text]))[0]

    # Agent A promotes into workspace-a
    asyncio.run(
        shared_module.promote_to_shared(
            workspace_id="workspace-a",
            source_agent_id="agent-a",
            text=text,
            embedding=embedding,
        )
    )

    # Agent C queries from workspace-c — must get nothing
    recalled_c = asyncio.run(
        layer3.recall_shared_memory(
            workspace_id="workspace-c",
            query_text=text,
            top_k=5,
        )
    )
    assert not recalled_c, "Agent C in workspace-c must not see workspace-a's shared memories"


def test_promote_dedup_returns_duplicate(monkeypatch) -> None:
    """Promoting the same text twice returns 'duplicate' on the second call."""
    fake_qdrant = FakeQdrant()
    fake_ollama = FakeOllama()

    monkeypatch.setattr(shared_module, "get_client", lambda: fake_qdrant)

    text = "unique-insight-ABC"
    embedding = asyncio.run(fake_ollama.embed([text]))[0]

    first = asyncio.run(
        shared_module.promote_to_shared(
            workspace_id="workspace-a",
            source_agent_id="agent-a",
            text=text,
            embedding=embedding,
        )
    )
    assert first == "stored"

    second = asyncio.run(
        shared_module.promote_to_shared(
            workspace_id="workspace-a",
            source_agent_id="agent-a",
            text=text,
            embedding=embedding,
        )
    )
    assert second == "duplicate"
    # Still only one point in the collection
    assert len(fake_qdrant.collections["shared_memories"]) == 1
