from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

src_path = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(src_path))

from activities.pii_screen import pii_screen
from pii import PIIDetectedMismatchError, PII_DROP_SENTINEL, PIIScanner
from workflows.ingestion import process_ingestion_batch


class _FakeCursor:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self.rows = rows or []
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))

    def fetchall(self) -> list[tuple]:
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self) -> None:
        self.rows: list[tuple] = []
        self.commits = 0
        self.closed = False

    def cursor(self):
        return _FakeCursor(self.rows)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True


def test_scanner_applies_hard_rules() -> None:
    scanner = PIIScanner()
    result = scanner.scan(
        "email jane@example.com card 4111 1111 1111 1111 password=secret-value",
        {"EMAIL_ADDRESS_ACTION": "mask"},
    )

    assert result.findings
    assert any(f.entity_category == "EMAIL_ADDRESS" for f in result.findings)
    assert any(f.entity_category == "CREDIT_CARD" and f.action_taken == "redact" for f in result.findings)
    assert any(f.entity_category == "PASSWORD" and f.action_taken == "drop" for f in result.findings)
    assert result.dropped is True
    assert result.sanitized_text == PII_DROP_SENTINEL


def test_pii_screen_redacts_masks_and_logs(monkeypatch) -> None:
    fake_connection = _FakeConnection()
    monkeypatch.setattr("activities.pii_screen.get_connection", lambda: fake_connection)

    chunks = [
        {
            "text": "Contact jane@example.com or +1 415 555 1212",
            "metadata": {"resource_id": "doc-1", "chunk_index": 0},
        },
        {
            "text": "Do not store password=super-secret or card 4111 1111 1111 1111",
            "metadata": {"resource_id": "doc-2", "chunk_index": 0},
        },
    ]

    screened = asyncio.run(
        pii_screen(
            chunks,
            connector_id="connector-1",
            workspace_id="workspace-1",
            pii_config={"EMAIL_ADDRESS_ACTION": "mask", "PHONE_NUMBER_ACTION": "mask"},
            contains_pii=True,
        )
    )

    assert len(screened) == 1
    assert "[EMAIL]" in screened[0]["text"]
    assert screened[0]["metadata"]["pii_masked"] is True
    assert fake_connection.closed is True


def test_pii_screen_mismatch_raises(monkeypatch) -> None:
    fake_connection = _FakeConnection()
    monkeypatch.setattr("activities.pii_screen.get_connection", lambda: fake_connection)

    chunks = [
        {
            "text": "jane@example.com",
            "metadata": {"resource_id": "doc-1", "chunk_index": 0},
        }
    ]

    with pytest.raises(PIIDetectedMismatchError):
        asyncio.run(
            pii_screen(
                chunks,
                connector_id="connector-1",
                workspace_id="workspace-1",
                pii_config={},
                contains_pii=False,
            )
        )


def test_workflow_helper_resumes_after_hitl_approval() -> None:
    calls: list[bool] = []

    async def fake_activity_runner(activity, *, args, start_to_close_timeout):
        calls.append(args[-1])
        if len(calls) == 1:
            raise PIIDetectedMismatchError("connector-1")
        return [{"text": "[EMAIL]", "metadata": {"pii_masked": True}}]

    async def fake_wait_for_hitl():
        return {"action": "approve"}

    result = asyncio.run(
        process_ingestion_batch(
            fake_activity_runner,
            {
                "connector_id": "connector-1",
                "workspace_id": "workspace-1",
                "chunks": [{"text": "jane@example.com", "metadata": {}}],
                "contains_pii": False,
            },
            wait_for_hitl=fake_wait_for_hitl,
        )
    )

    assert result["status"] == "ok"
    assert result["resumed"] is True
    assert len(calls) == 2


def test_workflow_helper_aborts_on_hitl_rejection() -> None:
    async def fake_activity_runner(activity, *, args, start_to_close_timeout):
        raise PIIDetectedMismatchError("connector-1")

    async def fake_wait_for_hitl():
        return {"action": "abort"}

    result = asyncio.run(
        process_ingestion_batch(
            fake_activity_runner,
            {
                "connector_id": "connector-1",
                "workspace_id": "workspace-1",
                "chunks": [{"text": "jane@example.com", "metadata": {}}],
                "contains_pii": False,
            },
            wait_for_hitl=fake_wait_for_hitl,
        )
    )

    assert result["status"] == "aborted"
    assert result["reason"] == "pii_detected_mismatch"