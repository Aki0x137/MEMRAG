"""Integration tests for Graphiti KG Layer 3 integration.

All tests use monkeypatched httpx to avoid requiring a live graphiti-server.
The one exception (test #5 — unreachable Graphiti) simulates a connection
failure by patching recall_shared_graphiti to raise.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_SERVICE_SRC = Path(__file__).resolve().parents[2] / "src"
_SHARED_SRC = Path(__file__).resolve().parents[4] / "packages" / "memrag-shared" / "src"
for _p in (_SERVICE_SRC, _SHARED_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Fake Graphiti server HTTP responses
# ---------------------------------------------------------------------------

class _FakeGraphitiResponse:
    """Minimal stub mimicking httpx.Response for graphiti API calls."""

    def __init__(self, data, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict | list:
        return self._data


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_post_shared_with_graphiti_enabled_calls_graphiti_server(client, monkeypatch):
    """POST /api/v1/shared with GRAPHITI_ENABLED=true routes to graphiti server."""
    calls: list[dict] = []

    async def _fake_post(self, url: str, **kwargs) -> _FakeGraphitiResponse:
        calls.append({"url": url, **kwargs})
        return _FakeGraphitiResponse({"uuid": "ep-001"})

    monkeypatch.setenv("GRAPHITI_ENABLED", "true")
    monkeypatch.setenv("GRAPHITI_SERVER_URL", "http://graphiti-fake:8100")

    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)

    resp = client.post(
        "/api/v1/shared",
        json={"agent_id": "agent-gkg-01", "text": "graphiti-canary-finding-01"},
        headers={"X-Workspace-ID": "ws-gkg-01", "X-Agent-ID": "agent-gkg-01"},
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    assert "/episodes" in calls[0]["url"]
    monkeypatch.delenv("GRAPHITI_ENABLED")


def test_post_shared_with_graphiti_disabled_uses_qdrant(client, monkeypatch):
    """POST /api/v1/shared with GRAPHITI_ENABLED=false stores in Qdrant."""
    monkeypatch.setenv("GRAPHITI_ENABLED", "false")

    resp = client.post(
        "/api/v1/shared",
        json={"agent_id": "agent-gkg-02", "text": "qdrant-fallback-finding-02"},
        headers={"X-Workspace-ID": "ws-gkg-02", "X-Agent-ID": "agent-gkg-02"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Should return "stored" or "duplicate" (Qdrant path)
    assert body["status"] in ("stored", "duplicate")
    monkeypatch.delenv("GRAPHITI_ENABLED")


def test_shared_search_graphiti_enabled_calls_recall_graphiti(client, monkeypatch):
    """POST /api/v1/shared/search with GRAPHITI_ENABLED=true calls recall_shared_graphiti."""
    monkeypatch.setenv("GRAPHITI_ENABLED", "true")

    from memrag_shared.layers import LAYER_SHARED, MemoryChunk

    async def _fake_recall_graphiti(workspace_id, query_text, top_k=8):
        return [
            MemoryChunk(
                id="gkg-fact-001",
                agent_id="",
                workspace_id=workspace_id,
                text="graphiti-search-result",
                source_type="graphiti",
                score=0.9,
                layer=LAYER_SHARED,
                metadata={},
            )
        ]

    import main as main_mod
    monkeypatch.setattr(main_mod, "recall_shared_graphiti", _fake_recall_graphiti)

    resp = client.post(
        "/api/v1/shared/search",
        json={"query": "test", "limit": 5},
        headers={"X-Workspace-ID": "ws-gkg-03", "X-Agent-ID": "agent-gkg-03"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["source_type"] == "graphiti"
    monkeypatch.delenv("GRAPHITI_ENABLED")


def test_shared_search_graphiti_disabled_uses_qdrant_path(client, monkeypatch):
    """POST /api/v1/shared/search with GRAPHITI_ENABLED=false uses Qdrant recall."""
    monkeypatch.setenv("GRAPHITI_ENABLED", "false")

    resp = client.post(
        "/api/v1/shared/search",
        json={"query": "qdrant-path-test", "limit": 5},
        headers={"X-Workspace-ID": "ws-gkg-04", "X-Agent-ID": "agent-gkg-04"},
    )
    assert resp.status_code == 200
    # Empty list is fine — no data seeded; key check is no crash
    assert isinstance(resp.json(), list)
    monkeypatch.delenv("GRAPHITI_ENABLED")


def test_hydrate_graphiti_unreachable_adds_to_failed_layers(client, fake_qdrant, fake_ollama, monkeypatch):
    """When Graphiti recall fails, hydrate returns failed_layers including 'graphiti'."""
    monkeypatch.setenv("GRAPHITI_ENABLED", "true")

    import main as main_mod

    async def _unreachable(*args, **kwargs):
        raise ConnectionError("graphiti server unreachable")

    monkeypatch.setattr(main_mod, "recall_shared_graphiti", _unreachable)

    import asyncio
    ws, agent_id = "ws-gkg-05", "agent-gkg-05"
    text = "fallback-hydrate-fact"
    embedding = asyncio.get_event_loop().run_until_complete(fake_ollama.embed([text]))[0]
    fake_qdrant.upsert(
        "agent_memories",
        [
            type("Pt", (), {
                "id": "gkg-l2-05",
                "vector": {"dense": embedding, "sparse": {}},
                "payload": {"workspace_id": ws, "agent_id": agent_id, "text": text},
            })()
        ],
    )

    resp = client.post(
        "/api/v1/hydrate",
        json={"session_id": "sess-gkg-05", "agent_id": agent_id, "query": "fallback"},
        headers={"X-Workspace-ID": ws, "X-Agent-ID": agent_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "graphiti" in body["failed_layers"]
    # system_prompt must not be empty — other layers contributed
    assert body["system_prompt"]
    monkeypatch.delenv("GRAPHITI_ENABLED")
