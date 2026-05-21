from infra.redis_client import grants_key, session_key


def test_session_key_matches_schema() -> None:
    assert session_key("workspace-1", "session-9", "messages") == "workspace-1:session:session-9:messages"


def test_grants_key_matches_schema() -> None:
    assert grants_key("workspace-1") == "grants:workspace-1"
