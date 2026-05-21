from __future__ import annotations

import json

from activities import session as session_activities


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.operations: list[tuple[str, tuple, dict]] = []

    def set(self, *args, **kwargs):
        self.operations.append(("set", args, kwargs))
        return self

    def execute(self) -> None:
        for name, args, kwargs in self.operations:
            getattr(self.redis, name)(*args, **kwargs)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.expiry: dict[str, int] = {}

    def get(self, key: str):
        return self.data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value
        if ex is not None:
            self.expiry[key] = ex

    def expire(self, key: str, ttl: int) -> None:
        self.expiry[key] = ttl

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)
            self.expiry.pop(key, None)

    def ttl(self, key: str) -> int:
        return self.expiry.get(key, -1)

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)


def test_checkpoint_roundtrip_with_external_payload(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(session_activities, "get_client", lambda: redis)

    turns = [
        {"role": "user", "content": f"turn-{index}-{'x' * 50000}"}
        for index in range(12)
    ]
    session_activities.checkpoint_session("workspace-a", "session-a", turns)

    manifest_key = session_activities.session_key("workspace-a", "session-a", "messages")
    manifest_raw = redis.get(manifest_key)
    assert manifest_raw is not None
    manifest = json.loads(manifest_raw)
    assert manifest["externalized"] is True
    assert len(manifest["external_payload_keys"]) >= 2

    restored = session_activities.fetch_recent_session("workspace-a", "session-a")
    assert restored == turns
    assert redis.ttl(manifest_key) >= 23 * 60 * 60
