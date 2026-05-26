"""PII screening activity for ingestion workflows."""

from __future__ import annotations

from typing import Any

from infra.postgres_client import get_connection
from pii import PIIDetectedMismatchError, PIIScanner, PII_DROP_SENTINEL


def _audit_detection(
    cursor,
    *,
    connector_id: str,
    workspace_id: str,
    resource_id: str,
    chunk_index: int,
    entity_category: str,
    action_taken: str,
) -> None:
    cursor.execute(
        """
        INSERT INTO pii_audit_log (
            connector_id, workspace_id, resource_id, chunk_index, entity_category, action_taken
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (connector_id, workspace_id, resource_id, chunk_index, entity_category, action_taken),
    )


async def pii_screen(
    chunks: list[dict[str, Any]],
    connector_id: str,
    workspace_id: str,
    pii_config: dict[str, Any] | None = None,
    contains_pii: bool = True,
) -> list[dict[str, Any]]:
    """Screen chunks for PII and persist audit rows."""

    scanner = PIIScanner()
    connection = get_connection()
    screened_chunks: list[dict[str, Any]] = []
    saw_detection = False

    try:
        with connection.cursor() as cursor:
            for chunk_index, chunk in enumerate(chunks):
                text = str(chunk.get("text", ""))
                result = scanner.scan(text, pii_config)
                resource_id = str(chunk.get("metadata", {}).get("resource_id", chunk.get("resource_id", "")))

                if result.findings:
                    saw_detection = True
                for finding in result.findings:
                    _audit_detection(
                        cursor,
                        connector_id=connector_id,
                        workspace_id=workspace_id,
                        resource_id=resource_id,
                        chunk_index=chunk_index,
                        entity_category=finding.entity_category,
                        action_taken=finding.action_taken,
                    )

                if result.dropped or result.sanitized_text == PII_DROP_SENTINEL:
                    continue

                screened_chunks.append(
                    {
                        **chunk,
                        "text": result.sanitized_text,
                        "metadata": {
                            **chunk.get("metadata", {}),
                            "pii_masked": bool(result.findings),
                        },
                    }
                )

            connection.commit()
    finally:
        connection.close()

    if saw_detection and not contains_pii:
        raise PIIDetectedMismatchError(connector_id)

    return screened_chunks