"""Redis-backed session checkpointing for the MEMRAG memory-api.

Functions accept an explicit ``redis`` client so callers (and tests) can
supply their own instance.  Both functions are synchronous; they are called
from async FastAPI handlers where the Redis I/O is fast enough not to block
the event loop.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, cast

from memrag_shared.infra.redis_client import get_client, session_key

SESSION_TTL_SECONDS = 24 * 60 * 60
INLINE_PAYLOAD_LIMIT_BYTES = 256 * 1024
PAYLOAD_CHUNK_SIZE_BYTES = 240 * 1024


def _normalize_turn(turn: Any) -> dict[str, Any]:
    if is_dataclass(turn):
        return asdict(turn)
    if isinstance(turn, dict):
        return turn
    raise TypeError(f"Unsupported turn payload type: {type(turn)!r}")


def _serialize_turns(turns: list[dict[str, Any]]) -> bytes:
    return json.dumps(turns, separators=(",", ":"), default=str).encode("utf-8")


def _load_external_payload(redis_key: str, redis: Any) -> list[dict[str, Any]]:
    manifest_raw = redis.get(redis_key)
    if manifest_raw is None:
        return []

    redis.expire(redis_key, SESSION_TTL_SECONDS)
    manifest = json.loads(cast(str, manifest_raw))
    if not isinstance(manifest, dict) or not manifest.get("external_payload_keys"):
        data = manifest if isinstance(manifest, list) else []
        return [item for item in data if isinstance(item, dict)]

    payload_parts: list[str] = []
    for payload_key in manifest["external_payload_keys"]:
        chunk = redis.get(payload_key)
        if chunk is None:
            continue
        redis.expire(payload_key, SESSION_TTL_SECONDS)
        payload_parts.append(cast(str, chunk))

    if not payload_parts:
        return []

    data = json.loads("".join(payload_parts))
    return [item for item in data if isinstance(item, dict)]


def fetch_recent_session(
    workspace_id: str,
    session_id: str,
    redis: Any = None,
) -> list[dict[str, Any]]:
    """Load recent session turns from Redis and refresh the TTL.

    Args:
        workspace_id: Workspace/tenant identifier.
        session_id: Session identifier.
        redis: Optional pre-created Redis client; a new client is created if
            *None* is supplied.

    Returns:
        List of turn dicts, or an empty list if no session is found.
    """

    if redis is None:
        redis = get_client()
    key = session_key(workspace_id, session_id, "messages")
    return _load_external_payload(key, redis)


def checkpoint_session(
    workspace_id: str,
    session_id: str,
    turns: list[Any],
    redis: Any = None,
) -> None:
    """Persist session turns in Redis, externalising large payloads by chunk.

    Payloads ≤ 256 KB are stored inline; larger payloads are split into 240 KB
    chunks and a pointer manifest is written to the messages key.

    Args:
        workspace_id: Workspace/tenant identifier.
        session_id: Session identifier.
        turns: List of turn dicts or dataclasses.
        redis: Optional pre-created Redis client.
    """

    if redis is None:
        redis = get_client()

    redis_key = session_key(workspace_id, session_id, "messages")
    normalized_turns = [_normalize_turn(turn) for turn in turns]
    payload = _serialize_turns(normalized_turns)

    existing = redis.get(redis_key)
    if existing is not None:
        manifest = json.loads(cast(str, existing))
        if isinstance(manifest, dict):
            old_keys = manifest.get("external_payload_keys") or []
            if old_keys:
                redis.delete(*old_keys)

    if len(payload) <= INLINE_PAYLOAD_LIMIT_BYTES:
        redis.set(redis_key, payload.decode("utf-8"), ex=SESSION_TTL_SECONDS)
        return

    external_payload_keys: list[str] = []
    pipeline = redis.pipeline()
    for index, start in enumerate(range(0, len(payload), PAYLOAD_CHUNK_SIZE_BYTES)):
        chunk = payload[start : start + PAYLOAD_CHUNK_SIZE_BYTES].decode("utf-8")
        payload_key = session_key(workspace_id, session_id, f"payload:{index}")
        external_payload_keys.append(payload_key)
        pipeline.set(payload_key, chunk, ex=SESSION_TTL_SECONDS)

    manifest = {
        "externalized": True,
        "external_payload_keys": external_payload_keys,
        "chunk_count": len(external_payload_keys),
    }
    pipeline.set(redis_key, json.dumps(manifest), ex=SESSION_TTL_SECONDS)
    pipeline.execute()
