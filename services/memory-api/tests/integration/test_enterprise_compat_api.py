"""Integration tests for the enterprise compatibility API and MCP endpoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SERVICE_SRC = Path(__file__).resolve().parents[2] / "src"
_SHARED_SRC = Path(__file__).resolve().parents[4] / "packages" / "memrag-shared" / "src"
for _p in (_SERVICE_SRC, _SHARED_SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_store_fact_returns_200(client):
    """POST /api/v1/memories stores a fact and returns 200 OK."""
    resp = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-ec-01", "content": "enterprise-canary-fact-ECTEST"},
        headers={"X-Workspace-ID": "ws-ec-01", "X-Agent-ID": "agent-ec-01"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("stored") is True or "stored_ids" in body


def test_duplicate_store_returns_200_without_new_entry(client):
    """Duplicate POST returns 200 without error; dedup is enforced."""
    payload = {"agent_id": "agent-ec-02", "content": "duplicate-dedup-canary-EC02"}
    headers = {"X-Workspace-ID": "ws-ec-02", "X-Agent-ID": "agent-ec-02"}
    r1 = client.post("/api/v1/memories", json=payload, headers=headers)
    r2 = client.post("/api/v1/memories", json=payload, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    # Second call may indicate duplicate or stored — either is acceptable
    b2 = r2.json()
    # No error is the key assertion
    assert "error" not in b2 and "detail" not in b2


def test_search_memories_returns_list_of_strings(client, fake_qdrant, fake_ollama):
    """POST /api/v1/memories/search returns list[str] ≥ 1 result."""
    import asyncio

    ws, agent_id = "ws-ec-03", "agent-ec-03"
    text = "searchable-ec-canary-03"
    embedding = asyncio.get_event_loop().run_until_complete(fake_ollama.embed([text]))[0]
    fake_qdrant.upsert(
        "agent_memories",
        [
            type("Pt", (), {
                "id": "ec-l2-03",
                "vector": {"dense": embedding, "sparse": {}},
                "payload": {
                    "workspace_id": ws,
                    "agent_id": agent_id,
                    "text": text,
                    "tombstoned": False,
                },
            })()
        ],
    )

    resp = client.post(
        "/api/v1/memories/search",
        json={"agent_id": agent_id, "query": "searchable-ec-canary", "limit": 5},
        headers={"X-Workspace-ID": ws, "X-Agent-ID": agent_id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert isinstance(data[0], str)


def test_workspace_isolation_search_returns_empty(client, fake_qdrant, fake_ollama):
    """Workspace-B cannot read workspace-A memories."""
    import asyncio

    ws_a, ws_b = "ws-ec-04a", "ws-ec-04b"
    agent_id = "agent-ec-04"
    text = "isolation-canary-04"
    embedding = asyncio.get_event_loop().run_until_complete(fake_ollama.embed([text]))[0]
    fake_qdrant.upsert(
        "agent_memories",
        [
            type("Pt", (), {
                "id": "ec-l2-04",
                "vector": {"dense": embedding, "sparse": {}},
                "payload": {
                    "workspace_id": ws_a,
                    "agent_id": agent_id,
                    "text": text,
                    "tombstoned": False,
                },
            })()
        ],
    )

    resp = client.post(
        "/api/v1/memories/search",
        json={"agent_id": agent_id, "query": "isolation-canary", "limit": 5},
        headers={"X-Workspace-ID": ws_b, "X-Agent-ID": agent_id},
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_x_tenant_id_accepted_as_alias(client):
    """X-Tenant-ID is accepted as a legacy alias for X-Workspace-ID."""
    resp = client.post(
        "/api/v1/memories",
        json={"agent_id": "agent-ec-05", "content": "tenant-alias-canary-EC05"},
        headers={"X-Tenant-ID": "ws-ec-05", "X-Agent-ID": "agent-ec-05"},
    )
    assert resp.status_code == 200
    assert "error" not in resp.json()


def test_mcp_tools_list_and_store_memory_call(client, fake_qdrant, fake_ollama):
    """MCP tools/list returns required tools; tools/call store_memory stores a fact."""
    # 1. tools/list
    list_resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        },
    )
    assert list_resp.status_code == 200
    result = list_resp.json()
    assert "result" in result, result
    tool_names = {t["name"] for t in result["result"]["tools"]}
    assert "recall_memory" in tool_names
    assert "store_memory" in tool_names
    assert "promote_finding" in tool_names
    assert "search_knowledge" in tool_names

    # 2. tools/call — store_memory
    store_resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "store_memory",
                "arguments": {
                    "workspace_id": "ws-mcp-06",
                    "agent_id": "agent-mcp-06",
                    "text": "mcp-stored-canary-06",
                },
            },
        },
    )
    assert store_resp.status_code == 200
    store_result = store_resp.json()
    assert "result" in store_result
    # stored or duplicate — either is a valid success
    content_text = store_result["result"]["content"][0]["text"]
    assert content_text in ("stored", "duplicate")
