"""Integration tests for US1 — Agent Session Memory (T029).

Tests:
- POST /api/v1/session/{id}/turns checkpoints turns (including 500 KB payload)
- GET  /api/v1/session/{id}/turns retrieves all turns including large external payloads
- Redis key TTL is refreshed to ≥ 23 h
- Workspace isolation: workspace-B returns empty list for workspace-A's session
- X-Tenant-ID header works as a legacy alias for X-Workspace-ID
- X-Agent-ID is passed on both requests
"""

from __future__ import annotations


POST_HEADERS = {"X-Workspace-ID": "ws-A", "X-Agent-ID": "agent-001"}
TENANT_ALIAS_HEADERS = {"X-Tenant-ID": "ws-A", "X-Agent-ID": "agent-001"}
WS_B_HEADERS = {"X-Workspace-ID": "ws-B", "X-Agent-ID": "agent-001"}


def _make_turns(count: int = 12, large_idx: int = 5) -> list[dict]:
    turns = []
    for i in range(count):
        if i == large_idx:
            content = "x" * 500_000
        else:
            content = f"turn-{i}-content"
        turns.append({"role": "user" if i % 2 == 0 else "assistant", "content": content})
    return turns


def test_checkpoint_and_retrieve_session(client) -> None:
    session_id = "sess-001"
    turns = _make_turns(12, large_idx=5)

    resp = client.post(
        f"/api/v1/session/{session_id}/turns",
        json={"turns": turns},
        headers=POST_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["stored"] == 12

    resp = client.get(
        f"/api/v1/session/{session_id}/turns",
        headers=POST_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    retrieved = resp.json()
    assert len(retrieved) == 12
    assert retrieved[5]["content"] == "x" * 500_000


def test_session_ttl_refreshed(client, fake_redis) -> None:
    session_id = "sess-ttl"
    turns = _make_turns(3, large_idx=99)

    client.post(
        f"/api/v1/session/{session_id}/turns",
        json={"turns": turns},
        headers=POST_HEADERS,
    )

    # Read back to trigger TTL refresh
    client.get(f"/api/v1/session/{session_id}/turns", headers=POST_HEADERS)

    from memrag_shared.infra.redis_client import session_key
    key = session_key("ws-A", session_id, "messages")
    ttl = fake_redis.ttl(key)
    assert ttl >= 23 * 60 * 60, f"Expected TTL >= 23h, got {ttl}s"


def test_workspace_isolation(client) -> None:
    session_id = "sess-iso"
    turns = _make_turns(3, large_idx=99)

    client.post(
        f"/api/v1/session/{session_id}/turns",
        json={"turns": turns},
        headers=POST_HEADERS,
    )

    resp = client.get(
        f"/api/v1/session/{session_id}/turns",
        headers=WS_B_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json() == [], "Workspace B should not see Workspace A's session"


def test_x_tenant_id_alias_on_get(client, fake_redis) -> None:
    session_id = "sess-alias"
    turns = _make_turns(4, large_idx=99)

    # Store with X-Workspace-ID
    client.post(
        f"/api/v1/session/{session_id}/turns",
        json={"turns": turns},
        headers=POST_HEADERS,
    )

    # Retrieve with X-Tenant-ID alias — should return same data
    resp = client.get(
        f"/api/v1/session/{session_id}/turns",
        headers=TENANT_ALIAS_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 4


def test_x_tenant_id_alias_on_post(client) -> None:
    session_id = "sess-alias-post"
    turns = _make_turns(2, large_idx=99)

    resp = client.post(
        f"/api/v1/session/{session_id}/turns",
        json={"turns": turns},
        headers=TENANT_ALIAS_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["stored"] == 2


def test_missing_workspace_header_returns_400(client) -> None:
    resp = client.get(
        "/api/v1/session/any-session/turns",
        headers={"X-Agent-ID": "agent-001"},
    )
    assert resp.status_code == 400


def test_missing_agent_id_returns_400(client) -> None:
    resp = client.get(
        "/api/v1/session/any-session/turns",
        headers={"X-Workspace-ID": "ws-A"},
    )
    assert resp.status_code == 400
