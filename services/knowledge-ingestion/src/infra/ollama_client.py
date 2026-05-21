"""Async Ollama client for ingestion workflows."""

from __future__ import annotations

import os
from typing import Any

import httpx


def _ollama_base_url() -> str:
    return os.getenv("OLLAMA_HOST", "http://ollama:11434").rstrip("/")


class OllamaClient:
    """Thin async client for embeddings and health checks."""

    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = (base_url or _ollama_base_url()).rstrip("/")
        self.timeout = timeout

    async def healthcheck(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/version")
            response.raise_for_status()
            return response.json()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            embeddings: list[list[float]] = []
            for text in texts:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": "qwen3-embedding:4b", "prompt": text},
                )
                response.raise_for_status()
                embeddings.append(response.json()["embedding"])
            return embeddings


def get_client() -> OllamaClient:
    """Return an Ollama client configured from environment."""

    return OllamaClient()
