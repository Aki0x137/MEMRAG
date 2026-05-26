"""Unit tests for Redis key helpers (T030).

Validates that session_key() and grants_key() return the exact key patterns
defined in the data-model.md Redis Key Schema section.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure memrag-shared is importable
_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from memrag_shared.infra.redis_client import grants_key, session_key


def test_session_key_messages_field() -> None:
    key = session_key("ws-001", "sess-abc", "messages")
    assert key == "ws-001:session:sess-abc:messages"


def test_session_key_payload_field() -> None:
    key = session_key("workspace-x", "session-y", "payload:0")
    assert key == "workspace-x:session:session-y:payload:0"


def test_session_key_arbitrary_field() -> None:
    key = session_key("ws", "sess", "meta")
    assert key == "ws:session:sess:meta"


def test_grants_key() -> None:
    key = grants_key("ws-org")
    assert key == "grants:ws-org"


def test_grants_key_various() -> None:
    for ws in ("ws-001", "tenant-abc", "enterprise-corp"):
        key = grants_key(ws)
        assert key == f"grants:{ws}"


def test_session_key_isolation() -> None:
    """Two different workspaces must produce distinct keys for the same session."""
    k1 = session_key("ws-A", "same-session", "messages")
    k2 = session_key("ws-B", "same-session", "messages")
    assert k1 != k2
