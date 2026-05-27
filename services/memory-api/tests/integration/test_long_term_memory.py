"""Integration tests for US2 — Agent Long-Term Memory (T039).

Tests:
- POST /api/v1/memories stores facts in Qdrant
- POST /api/v1/memories/search recalls semantically similar facts
- Near-duplicate inputs are rejected (Qdrant point count unchanged)
- X-Tenant-ID alias accepted on both endpoints
- X-Agent-ID mismatch returns 400
"""

from __future__ import annotations

import pytest

HEADERS = {"X-Workspace-ID": "ws-A", "X-Agent-ID": "agent-mem"}
TENANT_ALIAS_HEADERS = {"X-Tenant-ID": "ws-A", "X-Agent-ID": "agent-mem"}


def test_store_and_recall_memory(client, fake_qdrant) -> None:
    resp = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-mem", "content": "Redis uses LRU eviction by default"},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["stored"] is True
    assert len(data["stored_ids"]) >= 1

    # Recall with semantically related query
    resp = client.post(
        "/api/v1/memories/search",
        json={"query": "cache eviction policy", "agent_id": "agent-mem"},
        headers=HEADERS,
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()
    assert isinstance(results, list)
    assert len(results) >= 1
    assert any("Redis" in r or "LRU" in r or "eviction" in r for r in results)


def test_dedup_prevents_duplicate_storage(client, fake_qdrant) -> None:
    content = "PostgreSQL supports JSONB for semi-structured data"

    resp1 = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-mem", "content": content},
        headers=HEADERS,
    )
    assert resp1.status_code == 200
    assert resp1.json()["stored"] is True

    count_before = len(fake_qdrant.collections.get("agent_memories", {}))

    # Submit identical content — should be treated as duplicate
    resp2 = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-mem", "content": content},
        headers=HEADERS,
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    # Either stored=False with reason=duplicate, or stored=True (if embedding differs)
    # The fake Ollama returns deterministic embeddings from text length, so identical
    # text → identical embedding → dedup kicks in
    assert data2.get("stored") is False or data2.get("reason") == "duplicate"

    count_after = len(fake_qdrant.collections.get("agent_memories", {}))
    assert count_after == count_before, "Qdrant point count must not increase on duplicate"


def test_x_tenant_id_alias_store(client) -> None:
    resp = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-mem", "content": "Finding via tenant alias"},
        headers=TENANT_ALIAS_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["stored"] is True


def test_x_tenant_id_alias_search(client, fake_qdrant) -> None:
    # Store something first using X-Workspace-ID
    client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-mem", "content": "Tenant alias search test"},
        headers=HEADERS,
    )

    resp = client.post(
        "/api/v1/memories/search",
        json={"query": "tenant alias search", "agent_id": "agent-mem"},
        headers=TENANT_ALIAS_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)


def test_agent_id_mismatch_returns_400(client) -> None:
    resp = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-other", "content": "something"},
        headers=HEADERS,  # X-Agent-ID is "agent-mem"
    )
    assert resp.status_code == 400


def test_missing_workspace_returns_400(client) -> None:
    resp = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-mem", "content": "something"},
        headers={"X-Agent-ID": "agent-mem"},
    )
    assert resp.status_code == 400


def test_missing_agent_id_returns_400(client) -> None:
    resp = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-mem", "content": "something"},
        headers={"X-Workspace-ID": "ws-A"},
    )
    assert resp.status_code == 400
