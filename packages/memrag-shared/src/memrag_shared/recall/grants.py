"""Grant loading helpers for organization knowledge access control."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from memrag_shared.infra.redis_client import get_client as get_redis_client, grants_key


@dataclass(slots=True)
class Grant:
    connector_id: str
    grantee_workspace_id: str


def _grants_ttl_seconds() -> int:
    return int(os.getenv("GRANTS_CACHE_TTL_SECONDS", "60"))


def _get_pg_connection():  # pragma: no cover - exercised via runtime/integration
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required to load sharing grants")

    try:
        import psycopg2  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("psycopg2 is required to load sharing grants") from exc

    return psycopg2.connect(dsn)


def _decode_grants(raw_value: str | bytes | None) -> list[Grant]:
    if raw_value is None:
        return []
    raw_text = raw_value.decode("utf-8") if isinstance(raw_value, bytes) else str(raw_value)
    if not raw_text:
        return []
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return []

    grants: list[Grant] = []
    for item in payload:
        connector_id = str(item.get("connector_id", ""))
        grantee_workspace_id = str(item.get("grantee_workspace_id", ""))
        if connector_id and grantee_workspace_id:
            grants.append(Grant(connector_id=connector_id, grantee_workspace_id=grantee_workspace_id))
    return grants


def load_grants(
    workspace_id: str,
    redis_client=None,
    pg_conn=None,
) -> list[Grant]:
    """Load active grants from Redis cache or PostgreSQL."""

    redis_client = redis_client or get_redis_client()
    cache_key = grants_key(workspace_id)
    cached = redis_client.get(cache_key)
    if cached:
        return _decode_grants(cached)

    connection = pg_conn or _get_pg_connection()
    grants: list[Grant] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT connector_id, grantee_workspace_id
                FROM knowledge_sharing_grants
                WHERE grantee_workspace_id = %s AND status = 'active'
                ORDER BY created_at ASC
                """,
                (workspace_id,),
            )
            for connector_id, grantee_workspace_id in cursor.fetchall():
                grants.append(
                    Grant(
                        connector_id=str(connector_id),
                        grantee_workspace_id=str(grantee_workspace_id),
                    )
                )
    finally:
        if pg_conn is None:
            connection.close()

    payload = json.dumps([asdict(grant) for grant in grants])
    if hasattr(redis_client, "setex"):
        redis_client.setex(cache_key, _grants_ttl_seconds(), payload)
    else:
        redis_client.set(cache_key, payload, ex=_grants_ttl_seconds())
    return grants