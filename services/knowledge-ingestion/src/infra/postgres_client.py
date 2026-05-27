"""PostgreSQL client for knowledge-ingestion service."""

from __future__ import annotations

import os

import psycopg2


def get_connection() -> psycopg2.extensions.connection:
    """Get a PostgreSQL connection."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        database=os.getenv("POSTGRES_DB", "memrag"),
        user=os.getenv("POSTGRES_USER", "memrag"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )
