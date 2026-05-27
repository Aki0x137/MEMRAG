"""Smoke tests for memory-api FastAPI app using the shared in-process client.

Validates basic health, header validation, and compatibility response fields
without leaking mocks into the rest of the integration suite.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from memrag_shared.layers import MemoryChunk, MemoryType, LAYER_AGENT  # noqa: E402

_fake_chunk = MemoryChunk(
    id="c1",
    agent_id="agent-1",
    workspace_id="ws-1",
    text="relevant fact from memory",
    content="relevant fact from memory",
    memory_type=MemoryType.FACT,
    source_type="agent_memory",
    score=0.9,
    layer=LAYER_AGENT,
    metadata={},
)


def _patch_main(monkeypatch) -> None:
    import main as main_module

    monkeypatch.setattr(
        main_module,
        "extract_and_store",
        AsyncMock(return_value=["fact-id-1"]),
    )
    monkeypatch.setattr(
        main_module,
        "recall_agent_memory",
        AsyncMock(return_value=[_fake_chunk]),
    )


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    print("GET /healthz => 200 OK ✓")


def test_store_memory_ok(client, monkeypatch):
    _patch_main(monkeypatch)
    resp = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-1", "content": "learned that Redis TTL is 24h"},
        headers={"X-Workspace-ID": "ws-1", "X-Agent-ID": "agent-1"},
    )
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["status"] == "ok"
    assert body["agent_id"] == "agent-1"
    print(f"POST /api/v1/memories => 200 OK, stored_count={body['stored_count']} ✓")


def test_store_memory_agent_id_mismatch(client):
    resp = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-1", "content": "some fact"},
        headers={"X-Workspace-ID": "ws-1", "X-Agent-ID": "agent-OTHER"},
    )
    assert resp.status_code == 400, f"Expected 400 for mismatched agent_id, got {resp.status_code}"
    print("POST /api/v1/memories (agent_id mismatch) => 400 ✓")


def test_store_memory_missing_headers(client):
    resp = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-1", "content": "some fact"},
    )
    assert resp.status_code == 400, f"Expected 400 for missing headers, got {resp.status_code}"
    print("POST /api/v1/memories (missing headers) => 400 ✓")


def test_search_memories_ok(client, monkeypatch):
    _patch_main(monkeypatch)
    resp = client.post(
        "/api/v1/memories/search",
        json={"query": "Redis TTL", "agent_id": "agent-1", "limit": 5},
        headers={"X-Workspace-ID": "ws-1", "X-Agent-ID": "agent-1"},
    )
    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    results = resp.json()
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0] == "relevant fact from memory"
    print(f"POST /api/v1/memories/search => 200 OK, results={results} ✓")


def test_search_memories_missing_headers(client):
    resp = client.post(
        "/api/v1/memories/search",
        json={"query": "something", "agent_id": "a"},
    )
    assert resp.status_code == 400
    print("POST /api/v1/memories/search (missing headers) => 400 ✓")
