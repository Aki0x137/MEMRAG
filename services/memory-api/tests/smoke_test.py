"""Smoke tests for memory-api FastAPI app using in-process TestClient.

Validates Phase 6 checkpoint: /healthz works, header validation enforced,
422 on missing required headers.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Add agent-workers/src so _load_module can find mem0_client and layer2
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "agent-workers" / "src"))

# ──────────────────────────────────────────────────────────────
# Patch the module-level callables BEFORE the app is created so
# TestClient doesn't touch the real Qdrant/Ollama.
# ──────────────────────────────────────────────────────────────
import importlib

main_module = importlib.import_module("main")  # loaded with PYTHONPATH=memory-api/src
main_module.extract_and_store = AsyncMock(return_value=["fact-id-1"])

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
main_module.recall_agent_memory = AsyncMock(return_value=[_fake_chunk])

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main_module.app)


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    print("GET /healthz => 200 OK ✓")


def test_store_memory_ok():
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


def test_store_memory_agent_id_mismatch():
    resp = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-1", "content": "some fact"},
        headers={"X-Workspace-ID": "ws-1", "X-Agent-ID": "agent-OTHER"},
    )
    assert resp.status_code == 400, f"Expected 400 for mismatched agent_id, got {resp.status_code}"
    print("POST /api/v1/memories (agent_id mismatch) => 400 ✓")


def test_store_memory_missing_headers():
    resp = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-1", "content": "some fact"},
    )
    assert resp.status_code == 422, f"Expected 422 for missing headers, got {resp.status_code}"
    print("POST /api/v1/memories (missing headers) => 422 ✓")


def test_search_memories_ok():
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


def test_search_memories_missing_headers():
    resp = client.post(
        "/api/v1/memories/search",
        json={"query": "something", "agent_id": "a"},
    )
    assert resp.status_code == 422
    print("POST /api/v1/memories/search (missing headers) => 422 ✓")


if __name__ == "__main__":
    test_healthz()
    test_store_memory_ok()
    test_store_memory_agent_id_mismatch()
    test_store_memory_missing_headers()
    test_search_memories_ok()
    test_search_memories_missing_headers()
    print("\nAll memory-api smoke tests PASSED ✓")
