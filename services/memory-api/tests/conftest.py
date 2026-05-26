"""Shared test fixtures for memory-api integration tests.

Provides fake Redis, Qdrant, and Ollama infrastructure so tests can run
without live service dependencies.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure the service src/ and memrag-shared src/ are importable
_SERVICE_SRC = Path(__file__).resolve().parents[1] / "src"
_SHARED_SRC = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "memrag-shared"
    / "src"
)
for _p in (_SERVICE_SRC, _SHARED_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from main import app  # noqa: E402


# ---------------------------------------------------------------------------
# Fake Redis
# ---------------------------------------------------------------------------


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.ops: list[tuple[str, tuple, dict]] = []

    def set(self, *args, **kwargs):
        self.ops.append(("set", args, kwargs))
        return self

    def execute(self) -> None:
        for name, args, kwargs in self.ops:
            getattr(self.redis, name)(*args, **kwargs)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.expiry: dict[str, int] = {}

    def get(self, key: str):
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value
        if ex is not None:
            self.expiry[key] = ex

    def expire(self, key: str, ttl: int) -> None:
        self.expiry[key] = ttl

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)
            self.expiry.pop(key, None)

    def ttl(self, key: str) -> int:
        return self.expiry.get(key, -1)

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)


# ---------------------------------------------------------------------------
# Fake Qdrant
# ---------------------------------------------------------------------------


from dataclasses import dataclass, field  # noqa: E402


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
        **kwargs,
    ):
        points = list(self.collections.get(collection_name, {}).values())
        if query_filter is not None:
            for condition in getattr(query_filter, "must", []):
                key = condition.key
                value = condition.match.value
                points = [p for p in points if p.payload.get(key) == value]

        query_vector = query
        if using != "dense" and prefetch:
            query_vector = prefetch[0].query

        scored: list[FakePoint] = []
        for point in points:
            dense = point.vector.get("dense", [])
            dot = sum(a * b for a, b in zip(query_vector or [], dense, strict=False))
            scored.append(FakePoint(id=point.id, vector=point.vector, payload=point.payload, score=dot))

        scored.sort(key=lambda p: p.score, reverse=True)
        return type("Result", (), {"points": scored[:limit]})()

    def set_payload(self, collection_name: str, payload: dict, points, wait: bool = True) -> None:
        for pid in points:
            if str(pid) in self.collections.get(collection_name, {}):
                self.collections[collection_name][str(pid)].payload.update(payload)

    def scroll(self, collection_name: str, scroll_filter=None, limit: int = 100, **kwargs):
        points = list(self.collections.get(collection_name, {}).values())
        return points[:limit], None

    def delete(self, collection_name: str, points_selector) -> None:
        for pid in getattr(points_selector, "points", []):
            self.collections.get(collection_name, {}).pop(str(pid), None)


# ---------------------------------------------------------------------------
# Fake Ollama
# ---------------------------------------------------------------------------


class FakeOllama:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for text in texts:
            base = float(len(text))
            embeddings.append([base, base / 2.0, 1.0])
        return embeddings


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_redis():
    return FakeRedis()


@pytest.fixture()
def fake_qdrant():
    return FakeQdrant()


@pytest.fixture()
def fake_ollama():
    return FakeOllama()


@pytest.fixture()
def client(fake_redis, fake_qdrant, fake_ollama, monkeypatch):
    """Return a TestClient with all infrastructure mocked out."""
    import memrag_shared.infra.redis_client as redis_mod
    import memrag_shared.infra.qdrant_client as qdrant_mod
    import memrag_shared.infra.ollama_client as ollama_mod
    import memrag_shared.memory.dedup as dedup_mod
    import memrag_shared.memory.mem0_client as mem0_mod
    import memrag_shared.memory.shared as shared_mod
    import memrag_shared.recall.layer2 as l2_mod
    import memrag_shared.recall.layer3 as l3_mod

    monkeypatch.setattr(redis_mod, "get_client", lambda: fake_redis)
    monkeypatch.setattr(qdrant_mod, "get_client", lambda: fake_qdrant)
    monkeypatch.setattr(ollama_mod, "get_client", lambda: fake_ollama)

    # Patch qdrant get_client in each module that calls it directly
    monkeypatch.setattr(dedup_mod, "get_client", lambda: fake_qdrant)
    monkeypatch.setattr(mem0_mod, "get_qdrant_client", lambda: fake_qdrant)
    monkeypatch.setattr(mem0_mod, "get_ollama_client", lambda: fake_ollama)
    monkeypatch.setattr(shared_mod, "get_client", lambda: fake_qdrant)
    monkeypatch.setattr(l2_mod, "get_qdrant_client", lambda: fake_qdrant)
    monkeypatch.setattr(l2_mod, "get_ollama_client", lambda: fake_ollama)
    monkeypatch.setattr(l3_mod, "get_qdrant_client", lambda: fake_qdrant)
    monkeypatch.setattr(l3_mod, "get_ollama_client", lambda: fake_ollama)

    # main.py also imports get_redis at the module level for session routes
    import main as main_mod
    monkeypatch.setattr(main_mod, "get_redis", lambda: fake_redis)

    return TestClient(app)
