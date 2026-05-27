from __future__ import annotations

import pytest

import memrag_shared.recall.grants as grants_module


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

    def cursor(self):
        return FakePGCursor(self.grants)

    def close(self) -> None:
        return None


def _seed_org_point(
    fake_qdrant,
    *,
    point_id: str,
    workspace_id: str,
    connector_id: str,
    sharing_scope: str,
    text: str,
    agent_scope: str = "all",
    allowed_agent_ids: list[str] | None = None,
    allowed_agent_tags: list[str] | None = None,
) -> None:
    fake_qdrant.collections["org_knowledge"][point_id] = type(
        "Point",
        (),
        {
            "id": point_id,
            "vector": {"dense": [1.0, 1.0, 1.0], "sparse": {"indices": [0], "values": [1.0]}},
            "payload": {
                "workspace_id": workspace_id,
                "connector_id": connector_id,
                "sharing_scope": sharing_scope,
                "source_type": "github",
                "agent_scope": agent_scope,
                "allowed_agent_ids": allowed_agent_ids or [],
                "allowed_agent_tags": allowed_agent_tags or [],
                "title": f"{point_id}.md",
                "url": f"https://example.test/{point_id}",
                "text": text,
                "knowledge_type": "document",
            },
            "score": 0.99,
        },
    )()


@pytest.fixture()
def grant_store(monkeypatch, fake_redis):
    grants = [{"connector_id": "", "grantee_workspace_id": "ws-B", "status": "active"}]
    fake_pg = FakePGConn(grants)
    monkeypatch.setenv("GRANTS_CACHE_TTL_SECONDS", "1")
    monkeypatch.setattr(grants_module, "get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(grants_module, "_get_pg_connection", lambda: fake_pg)
    return grants


def test_private_knowledge_hidden_without_grant_then_visible_with_grant(
    client,
    fake_qdrant,
    fake_redis,
    grant_store,
) -> None:
    _seed_org_point(
        fake_qdrant,
        point_id="private-1",
        workspace_id="ws-A",
        connector_id="connector-private",
        sharing_scope="private",
        text="canary-finding-XYZ",
    )

    before = client.post(
        "/api/v1/knowledge/search",
        headers={"X-Workspace-ID": "ws-B", "X-Agent-ID": "agent-b"},
        json={"query": "canary-finding-XYZ", "agent_tags": ["ops"], "limit": 5},
    )
    assert before.status_code == 200
    assert before.json() == []

    grant_store[0]["connector_id"] = "connector-private"
    fake_redis.delete(grants_module.grants_key("ws-B"))

    after = client.post(
        "/api/v1/knowledge/search",
        headers={"X-Tenant-ID": "ws-B", "X-Agent-ID": "agent-b"},
        json={"query": "canary-finding-XYZ", "agent_tags": ["ops"], "limit": 5},
    )
    assert after.status_code == 200
    assert any(item["text"] == "canary-finding-XYZ" for item in after.json())


def test_revoked_grant_and_agent_scope_are_enforced(
    client,
    fake_qdrant,
    fake_redis,
    grant_store,
) -> None:
    _seed_org_point(
        fake_qdrant,
        point_id="tagged-1",
        workspace_id="ws-A",
        connector_id="connector-private",
        sharing_scope="private",
        text="tagged-only-insight",
        agent_scope="by_tag",
        allowed_agent_tags=["legal"],
    )
    grant_store[0]["connector_id"] = "connector-private"

    allowed = client.post(
        "/api/v1/knowledge/search",
        headers={"X-Workspace-ID": "ws-B", "X-Agent-ID": "agent-b"},
        json={"query": "tagged-only-insight", "agent_tags": ["legal"], "limit": 5},
    )
    assert allowed.status_code == 200
    assert any(item["text"] == "tagged-only-insight" for item in allowed.json())

    denied = client.post(
        "/api/v1/knowledge/search",
        headers={"X-Workspace-ID": "ws-B", "X-Agent-ID": "agent-b"},
        json={"query": "tagged-only-insight", "agent_tags": ["sales"], "limit": 5},
    )
    assert denied.status_code == 200
    assert denied.json() == []

    grant_store[0]["status"] = "revoked"
    fake_redis.delete(grants_module.grants_key("ws-B"))

    revoked = client.post(
        "/api/v1/knowledge/search",
        headers={"X-Workspace-ID": "ws-B", "X-Agent-ID": "agent-b"},
        json={"query": "tagged-only-insight", "agent_tags": ["legal"], "limit": 5},
    )
    assert revoked.status_code == 200
    assert revoked.json() == []