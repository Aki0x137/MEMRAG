from __future__ import annotations

from dataclasses import dataclass

from activities import memory as memory_activities
from activities.memory import store_agent_memory
from knowledge_ingestion_stub import decay_and_archive
from memory import dedup as dedup_module
from memory import mem0_client
from recall import layer2


@dataclass
class FakePoint:
    id: str
    vector: dict
    payload: dict
    score: float = 1.0


class FakeQdrant:
    def __init__(self) -> None:
        self.collections = {"agent_memories": {}}
        self.archived_rows: list[dict] = []

    def upsert(self, collection_name: str, points, wait: bool = True) -> None:
        for point in points:
            self.collections.setdefault(collection_name, {})[str(point.id)] = FakePoint(
                id=str(point.id),
                vector=point.vector,
                payload=point.payload,
            )

    def query_points(self, collection_name: str, query, using: str | None = None, query_filter=None, limit: int = 10, with_payload: bool = True, with_vectors: bool = False, prefetch=None):
        points = list(self.collections.get(collection_name, {}).values())
        if query_filter is not None:
            for condition in query_filter.must:
                key = condition.key
                value = condition.match.value
                points = [point for point in points if point.payload.get(key) == value]
        if using == "dense" or prefetch is not None:
            scored = []
            query_vector = query
            if using != "dense":
                query_vector = prefetch[0].query if prefetch else []
            for point in points:
                dense = point.vector["dense"]
                numerator = sum(left * right for left, right in zip(query_vector, dense, strict=False))
                scored.append(FakePoint(id=point.id, vector=point.vector, payload=point.payload, score=numerator))
            points = sorted(scored, key=lambda point: point.score, reverse=True)
        return type("Result", (), {"points": points[:limit]})

    def set_payload(self, collection_name: str, payload: dict, points, wait: bool = True) -> None:
        for point_id in points:
            self.collections[collection_name][str(point_id)].payload.update(payload)

    def scroll(self, collection_name: str, scroll_filter=None, limit: int = 100, offset=None, with_payload: bool = True, with_vectors: bool = False):
        points = list(self.collections.get(collection_name, {}).values())
        if scroll_filter is not None:
            for condition in scroll_filter.must:
                points = [point for point in points if point.payload.get(condition.key) == condition.match.value]
        return points[:limit], None

    def delete(self, collection_name: str, points_selector) -> None:
        for point_id in points_selector.points:
            self.collections.get(collection_name, {}).pop(str(point_id), None)


class FakeOllama:
    async def embed(self, texts):
        embeddings = []
        for text in texts:
            base = float(len(text))
            embeddings.append([base, base / 2, 1.0])
        return embeddings


class FakeTable:
    def __init__(self, sink: list[dict]) -> None:
        self.sink = sink

    def append(self, rows: list[dict]) -> None:
        self.sink.extend(rows)


def test_long_term_memory_store_recall_dedup_and_decay(monkeypatch) -> None:
    fake_qdrant = FakeQdrant()
    fake_ollama = FakeOllama()

    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setattr(mem0_client, "get_qdrant_client", lambda: fake_qdrant)
    monkeypatch.setattr(mem0_client, "get_ollama_client", lambda: fake_ollama)
    monkeypatch.setattr(dedup_module, "get_client", lambda: fake_qdrant)
    monkeypatch.setattr(layer2, "get_qdrant_client", lambda: fake_qdrant)
    monkeypatch.setattr(layer2, "get_ollama_client", lambda: fake_ollama)
    monkeypatch.setattr(memory_activities, "extract_and_store", mem0_client.extract_and_store)

    import asyncio

    asyncio.run(store_agent_memory("workspace-a", "agent-a", "database index missing"))
    recalled = asyncio.run(layer2.recall_agent_memory("workspace-a", "agent-a", "database index missing", top_k=5))

    assert recalled
    assert recalled[0].text == "database index missing"
    original_count = len(fake_qdrant.collections["agent_memories"])

    asyncio.run(store_agent_memory("workspace-a", "agent-a", "database index missing"))
    assert len(fake_qdrant.collections["agent_memories"]) == original_count

    point = next(iter(fake_qdrant.collections["agent_memories"].values()))
    point.payload["last_accessed_at"] = "2024-01-01T00:00:00+00:00"
    fake_archive_rows = []
    asyncio.run(decay_and_archive("workspace-a", client=fake_qdrant, table=FakeTable(fake_archive_rows), now_iso="2026-05-21T00:00:00+00:00"))
    assert fake_archive_rows
    assert not fake_qdrant.collections["agent_memories"]
