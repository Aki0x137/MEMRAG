"""Temporal activities for knowledge sync state management."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import psycopg2

from infra.postgres_client import get_connection


@dataclass
class ResourceDiff:
    """A resource that has changed and needs re-ingestion."""

    resource_id: str
    content_hash: str


async def diff_resources(
    connector_id: str,
    resources: list[dict],
) -> list[ResourceDiff]:
    """
    Compare provided resources against stored sync state.
    
    Returns only resources where content_hash is new or different.
    """
    if not resources:
        return []

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Fetch stored hashes for this connector
            cur.execute(
                """
                SELECT resource_id, content_hash
                FROM knowledge_sync_state
                WHERE connector_id = %s
                """,
                (connector_id,),
            )
            stored = {row[0]: row[1] for row in cur.fetchall()}

        diffs: list[ResourceDiff] = []
        for resource in resources:
            resource_id = resource["id"]
            content = resource.get("content", b"")
            
            # Compute hash of content
            if isinstance(content, str):
                content = content.encode("utf-8")
            new_hash = hashlib.sha256(content).hexdigest()
            
            # Check if this is new or different
            if resource_id not in stored or stored[resource_id] != new_hash:
                diffs.append(ResourceDiff(resource_id=resource_id, content_hash=new_hash))
        
        return diffs
    finally:
        conn.close()


async def update_sync_state(
    connector_id: str,
    resource_id: str,
    content_hash: str,
) -> None:
    """
    Upsert a single resource's sync state (called after successful ingestion).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_sync_state (connector_id, resource_id, content_hash)
                VALUES (%s, %s, %s)
                ON CONFLICT (connector_id, resource_id) DO UPDATE
                SET content_hash = EXCLUDED.content_hash
                """,
                (connector_id, resource_id, content_hash),
            )
        conn.commit()
    finally:
        conn.close()
