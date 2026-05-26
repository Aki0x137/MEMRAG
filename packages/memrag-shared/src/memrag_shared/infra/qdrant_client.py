"""Thin Qdrant client wrapper for memrag-shared."""

from __future__ import annotations

import os

from qdrant_client import QdrantClient


def _qdrant_url() -> str:
    host = os.getenv("QDRANT_HOST", "qdrant:6333")
    if host.startswith("http://") or host.startswith("https://"):
        return host
    return f"http://{host}"


def get_client() -> QdrantClient:
    """Create a Qdrant client from environment configuration."""

    api_key = os.getenv("QDRANT_API_KEY") or None
    return QdrantClient(url=_qdrant_url(), api_key=api_key)
