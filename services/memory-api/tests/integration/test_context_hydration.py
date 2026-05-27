"""Integration tests for POST /api/v1/hydrate — four-layer context hydration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SERVICE_SRC = Path(__file__).resolve().parents[2] / "src"
_SHARED_SRC = Path(__file__).resolve().parents[4] / "packages" / "memrag-shared" / "src"
for _p in (_SERVICE_SRC, _SHARED_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Helpers — seed layer data
# ---------------------------------------------------------------------------

def _seed_l1_turns(fake_redis, workspace_id: str, session_id: str, turns: list[dict]) -> None:
    key = f"{workspace_id}:session:{session_id}:messages"
    fake_redis.data[key] = json.dumps(turns)


def _seed_l2_chunk(fake_qdrant, fake_ollama, workspace_id: str, agent_id: str, text: str) -> None:
    import asyncio
    embedding = asyncio.get_event_loop().run_until_complete(fake_ollama.embed([text]))[0]

    fake_qdrant.upsert(
        "agent_memories",
        [
            type("Pt", (), {
                "id": f"l2-{abs(hash(text)) % 10**9}",
                "vector": {"dense": embedding, "sparse": {}},
                "payload": {
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "text": text,
                    "tombstoned": False,
                },
            })()
        ],
    )


def _seed_l3_chunk(fake_qdrant, fake_ollama, workspace_id: str, text: str) -> None:
    import asyncio
    embedding = asyncio.get_event_loop().run_until_complete(fake_ollama.embed([text]))[0]
    fake_qdrant.upsert(
        "shared_memories",
        [
            type("Pt", (), {
                "id": f"l3-{abs(hash(text)) % 10**9}",
                "vector": {"dense": embedding, "sparse": {}},
                "payload": {"workspace_id": workspace_id, "text": text, "tombstoned": False},
            })()
        ],
    )


def _seed_l4_chunk(fake_qdrant, fake_ollama, workspace_id: str, text: str) -> None:
    import asyncio
    embedding = asyncio.get_event_loop().run_until_complete(fake_ollama.embed([text]))[0]
    fake_qdrant.upsert(
        "org_knowledge",
        [
            type("Pt", (), {
                "id": f"l4-{abs(hash(text)) % 10**9}",
                "vector": {"dense": embedding, "sparse": {}},
                "payload": {
                    "workspace_id": workspace_id,
                    "text": text,
                    "title": "Test Doc",
                    "source_type": "github",
                    "connector_id": "c-001",
                    "sharing_scope": "workspace_internal",
                    "agent_scope": "all",
                    "url": "https://example.com/doc",
                    "tombstoned": False,
                },
            })()
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_hydrate_includes_all_four_layers(client, fake_redis, fake_qdrant, fake_ollama):
    """HydrateResponse.system_prompt contains content from all 4 layers."""
    ws = "ws-hydrate-01"
    agent_id = "agent-hydrate-01"
    session_id = "sess-001"

    _seed_l1_turns(fake_redis, ws, session_id, [{"role": "user", "content": "L1-canary-turn"}])
    _seed_l2_chunk(fake_qdrant, fake_ollama, ws, agent_id, "L2-canary-fact")
    _seed_l3_chunk(fake_qdrant, fake_ollama, ws, "L3-canary-shared")
    _seed_l4_chunk(fake_qdrant, fake_ollama, ws, "L4-canary-knowledge")

    resp = client.post(
        "/api/v1/hydrate",
        json={
            "session_id": session_id,
            "agent_id": agent_id,
            "query": "canary",
        },
        headers={"X-Workspace-ID": ws, "X-Agent-ID": agent_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    prompt = body["system_prompt"]
    assert "L1-canary-turn" in prompt
    assert "L2-canary-fact" in prompt
    assert "L3-canary-shared" in prompt
    assert "L4-canary-knowledge" in prompt


def test_hydrate_token_count_within_budget(client, fake_redis, fake_qdrant, fake_ollama):
    """token_count ≤ token_budget."""
    ws = "ws-hydrate-02"
    agent_id = "agent-hydrate-02"
    session_id = "sess-002"
    _seed_l2_chunk(fake_qdrant, fake_ollama, ws, agent_id, "budget test fact " * 20)

    resp = client.post(
        "/api/v1/hydrate",
        json={"session_id": session_id, "agent_id": agent_id, "query": "budget", "token_budget": 200},
        headers={"X-Workspace-ID": ws, "X-Agent-ID": agent_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_count"] <= 200 + 50  # small tolerance for preamble constant


def test_hydrate_citations_present_for_l4(client, fake_qdrant, fake_ollama):
    """citations list is non-empty when L4 knowledge chunks are included."""
    ws = "ws-hydrate-03"
    agent_id = "agent-hydrate-03"
    _seed_l4_chunk(fake_qdrant, fake_ollama, ws, "citation-canary-doc")

    resp = client.post(
        "/api/v1/hydrate",
        json={"session_id": "sess-003", "agent_id": agent_id, "query": "citation"},
        headers={"X-Workspace-ID": ws, "X-Agent-ID": agent_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["citations"]) >= 1
    cit = body["citations"][0]
    assert cit["source_type"] == "github"
    assert cit["connector_id"] == "c-001"


def test_hydrate_l3_failure_adds_failed_layer(client, fake_qdrant, fake_ollama, monkeypatch):
    """When L3 recall throws, failed_layers includes 'layer3' and response still succeeds."""
    ws = "ws-hydrate-04"
    agent_id = "agent-hydrate-04"
    _seed_l2_chunk(fake_qdrant, fake_ollama, ws, agent_id, "fallback-fact")

    import main as main_mod

    async def _fail(*args, **kwargs):
        raise RuntimeError("simulated L3 Qdrant partition")

    monkeypatch.setattr(main_mod, "recall_shared_memory", _fail)

    resp = client.post(
        "/api/v1/hydrate",
        json={"session_id": "sess-004", "agent_id": agent_id, "query": "fallback"},
        headers={"X-Workspace-ID": ws, "X-Agent-ID": agent_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "layer3" in body["failed_layers"]
    assert body["system_prompt"]  # prompt is still non-empty


def test_hydrate_layer_stats_counts_are_correct(client, fake_qdrant, fake_ollama, fake_redis):
    """layer_stats dict contains per-layer chunk counts."""
    ws = "ws-hydrate-05"
    agent_id = "agent-hydrate-05"
    _seed_l2_chunk(fake_qdrant, fake_ollama, ws, agent_id, "stat-fact-one")

    resp = client.post(
        "/api/v1/hydrate",
        json={"session_id": "sess-005", "agent_id": agent_id, "query": "stat"},
        headers={"X-Workspace-ID": ws, "X-Agent-ID": agent_id},
    )
    assert resp.status_code == 200
    stats = resp.json()["layer_stats"]
    assert "layer1_turns" in stats
    assert "layer2_chunks" in stats
    assert "layer3_chunks" in stats
    assert "layer4_chunks" in stats
    assert stats["layer2_chunks"] >= 1
