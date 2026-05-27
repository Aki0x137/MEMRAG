"""Integration tests for US3 — Shared Workspace Memory (T044).

Tests:
- POST /api/v1/shared promotes a finding for workspace A
- POST /api/v1/shared/search with X-Workspace-ID: ws-A finds the finding
- POST /api/v1/shared/search with X-Tenant-ID: ws-B returns empty list (isolation)
- Duplicate promotion returns {"status": "duplicate"}
- X-Agent-ID is required; mismatch returns 400
"""

from __future__ import annotations

WS_A_HEADERS = {"X-Workspace-ID": "ws-A", "X-Agent-ID": "agent-shared"}
WS_B_ALIAS_HEADERS = {"X-Tenant-ID": "ws-B", "X-Agent-ID": "agent-shared"}


def test_promote_and_recall_finding(client, fake_qdrant) -> None:
    canary = "canary-finding-XYZ: RDS connection pool exhaustion root cause identified"

    resp = client.post(
        "/api/v1/shared",
        json={"text": canary, "agent_id": "agent-shared"},
        headers=WS_A_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "stored"

    resp = client.post(
        "/api/v1/shared/search",
        json={"query": "canary-finding-XYZ"},
        headers=WS_A_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()
    assert any("canary-finding-XYZ" in r["text"] for r in results), f"canary not found: {results}"
    assert all(r["source_type"] == "shared_memory" for r in results)


def test_cross_workspace_isolation(client, fake_qdrant) -> None:
    """Workspace B must NOT see workspace A's findings."""
    canary = "ws-isolation-check: secret-finding-for-ws-A"

    client.post(
        "/api/v1/shared",
        json={"text": canary, "agent_id": "agent-shared"},
        headers=WS_A_HEADERS,
    )

    # Search from workspace B using X-Tenant-ID alias
    resp = client.post(
        "/api/v1/shared/search",
        json={"query": "secret-finding-for-ws-A"},
        headers=WS_B_ALIAS_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == [], "workspace B must not see workspace A findings"


def test_duplicate_promotion_returns_duplicate(client, fake_qdrant) -> None:
    text = "duplicate-test: Postgres default max_connections is 100"

    # First promotion
    resp1 = client.post(
        "/api/v1/shared",
        json={"text": text, "agent_id": "agent-shared"},
        headers=WS_A_HEADERS,
    )
    assert resp1.json()["status"] == "stored"

    # Second promotion of identical text — should be rejected as duplicate
    resp2 = client.post(
        "/api/v1/shared",
        json={"text": text, "agent_id": "agent-shared"},
        headers=WS_A_HEADERS,
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "duplicate"


def test_x_tenant_id_alias_on_promote(client) -> None:
    resp = client.post(
        "/api/v1/shared",
        json={"text": "test-finding via tenant alias", "agent_id": "agent-shared"},
        headers={"X-Tenant-ID": "ws-A", "X-Agent-ID": "agent-shared"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] in ("stored", "duplicate")


def test_agent_id_mismatch_returns_400(client) -> None:
    resp = client.post(
        "/api/v1/shared",
        json={"text": "something", "agent_id": "other-agent"},
        headers=WS_A_HEADERS,  # X-Agent-ID is "agent-shared"
    )
    assert resp.status_code == 400


def test_missing_workspace_returns_400(client) -> None:
    resp = client.post(
        "/api/v1/shared",
        json={"text": "something", "agent_id": "agent-shared"},
        headers={"X-Agent-ID": "agent-shared"},
    )
    assert resp.status_code == 400
