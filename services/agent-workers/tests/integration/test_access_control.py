from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

src_path = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(src_path))

from recall import grants as grants_module
from recall import layer4


@dataclass
class FakePoint:
    id: str
    vector: dict
    payload: dict
    score: float = 1.0


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if not entry:
            return None
        value, expires_at = entry
        if expires_at is not None and time.time() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def setex(self, key: str, ttl: int, value: str):
        self._store[key] = (value, time.time() + ttl)


class FakePGCursor:
    def __init__(self, grants: list[dict]) -> None:
        self._grants = grants
        self._rows: list[tuple[str, str]] = []

    def execute(self, query: str, params: tuple = ()) -> None:
        workspace_id = params[0]
        self._rows = [
            (row["connector_id"], row["grantee_workspace_id"])
            for row in self._grants
            if row["grantee_workspace_id"] == workspace_id and row["status"] == "active"
        ]

    def fetchall(self) -> list[tuple[str, str]]:
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakePGConn:
    def __init__(self, grants: list[dict]) -> None:
        self.grants = grants
        self.closed = False

    def cursor(self):
        return FakePGCursor(self.grants)

    def close(self) -> None:
        self.closed = True


class FakeQdrant:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, FakePoint]] = {"org_knowledge": {}}

    def upsert(self, collection_name: str, points, wait: bool = True) -> None:
        for point in points:
            self.collections.setdefault(collection_name, {})[str(point.id)] = FakePoint(
                id=str(point.id), vector=point.vector, payload=point.payload
            )

    def query_points(self, collection_name: str, **kwargs):
        points = list(self.collections.get(collection_name, {}).values())
        return type("Result", (), {"points": points})()


class FakeOllama:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text) % 7) + 1.0, 0.5, 0.25] for text in texts]


def _seed_org_point(
    qdrant: FakeQdrant,
    *,
    point_id: str,
    workspace_id: str,
    connector_id: str,
    sharing_scope: str,
    text: str,
    source_type: str = "github",
    agent_scope: str = "all",
    allowed_agent_ids: list[str] | None = None,
    allowed_agent_tags: list[str] | None = None,
) -> None:
    qdrant.collections["org_knowledge"][point_id] = FakePoint(
        id=point_id,
        vector={"dense": [1.0, 1.0, 1.0], "sparse": {"indices": [0], "values": [1.0]}},
        payload={
            "workspace_id": workspace_id,
            "connector_id": connector_id,
            "sharing_scope": sharing_scope,
            "source_type": source_type,
            "agent_scope": agent_scope,
            "allowed_agent_ids": allowed_agent_ids or [],
            "allowed_agent_tags": allowed_agent_tags or [],
            "title": f"{point_id}.md",
            "url": f"https://example.test/{point_id}",
            "text": text,
            "knowledge_type": "document",
        },
        score=0.99,
    )


def test_recall_org_knowledge_honors_grants_and_agent_scope(monkeypatch) -> None:
    fake_qdrant = FakeQdrant()
    fake_ollama = FakeOllama()
    fake_redis = FakeRedis()
    grants_store = [
        {"connector_id": "", "grantee_workspace_id": "workspace-b", "status": "active"}
    ]
    fake_pg = FakePGConn(grants_store)

    _seed_org_point(
        fake_qdrant,
        point_id="private-1",
        workspace_id="workspace-a",
        connector_id="connector-private",
        sharing_scope="private",
        text="canary-finding-XYZ",
    )

    monkeypatch.setattr(layer4, "get_qdrant_client", lambda: fake_qdrant)
    monkeypatch.setattr(layer4, "get_ollama_client", lambda: fake_ollama)
    monkeypatch.setattr(grants_module, "get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(grants_module, "_get_pg_connection", lambda: fake_pg)
    monkeypatch.setenv("GRANTS_CACHE_TTL_SECONDS", "1")

    # No grant yet for workspace-b; the private chunk must remain hidden.
    recalled_before = asyncio.run(
        layer4.recall_org_knowledge(
            workspace_id="workspace-b",
            agent_id="agent-b",
            agent_tags=["ops"],
            query_text="canary-finding-XYZ",
            top_k=5,
            grants_cache=fake_redis,
        )
    )
    assert not recalled_before

    # Grant the connector to workspace-b and wait for the 1s cache TTL to expire.
    grants_store[0]["connector_id"] = "connector-private"
    time.sleep(1.1)

    recalled_after = asyncio.run(
        layer4.recall_org_knowledge(
            workspace_id="workspace-b",
            agent_id="agent-b",
            agent_tags=["ops"],
            query_text="canary-finding-XYZ",
            top_k=5,
            grants_cache=fake_redis,
        )
    )
    assert any("canary-finding-XYZ" in chunk.text for chunk in recalled_after)

    # Revoke and wait for cache expiry again; access should disappear.
    grants_store[0]["status"] = "revoked"
    time.sleep(1.1)

    recalled_revoked = asyncio.run(
        layer4.recall_org_knowledge(
            workspace_id="workspace-b",
            agent_id="agent-b",
            agent_tags=["ops"],
            query_text="canary-finding-XYZ",
            top_k=5,
            grants_cache=fake_redis,
        )
    )
    assert not recalled_revoked

    # Tag-scoped access works for matching tags and rejects non-matching tags.
    tag_qdrant = FakeQdrant()
    _seed_org_point(
        tag_qdrant,
        point_id="tagged-1",
        workspace_id="workspace-a",
        connector_id="connector-tagged",
        sharing_scope="workspace_internal",
        text="tagged-only-insight",
        agent_scope="by_tag",
        allowed_agent_tags=["legal"],
    )
    monkeypatch.setattr(layer4, "get_qdrant_client", lambda: tag_qdrant)

    recalled_tagged = asyncio.run(
        layer4.recall_org_knowledge(
            workspace_id="workspace-a",
            agent_id="agent-a",
            agent_tags=["legal"],
            query_text="tagged-only-insight",
            top_k=5,
            grants_cache=fake_redis,
        )
    )
    assert any(chunk.text == "tagged-only-insight" for chunk in recalled_tagged)

    recalled_untagged = asyncio.run(
        layer4.recall_org_knowledge(
            workspace_id="workspace-a",
            agent_id="agent-a",
            agent_tags=["sales"],
            query_text="tagged-only-insight",
            top_k=5,
            grants_cache=fake_redis,
        )
    )
    assert not recalled_untagged