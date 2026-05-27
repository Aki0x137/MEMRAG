"""Async Ollama client for embeddings, completions, and health checks."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


_EMBED_CACHE: dict[tuple[str, tuple[str, ...]], tuple[float, list[list[float]]]] = {}
_EMBED_IN_FLIGHT: dict[tuple[str, tuple[str, ...]], asyncio.Future[list[list[float]]]] = {}
_EMBED_CACHE_LOCK = asyncio.Lock()


def _embed_cache_ttl_seconds() -> float:
    return float(os.getenv("OLLAMA_EMBED_CACHE_TTL_SECONDS", "300"))


def _embed_cache_limit() -> int:
    return int(os.getenv("OLLAMA_EMBED_CACHE_MAX_ITEMS", "512"))


def _copy_embeddings(embeddings: list[list[float]]) -> list[list[float]]:
    return [list(vector) for vector in embeddings]


def _prune_embed_cache(now: float) -> None:
    ttl = _embed_cache_ttl_seconds()
    expired = [key for key, (ts, _value) in _EMBED_CACHE.items() if now - ts > ttl]
    for key in expired:
        _EMBED_CACHE.pop(key, None)

    overflow = len(_EMBED_CACHE) - _embed_cache_limit()
    if overflow > 0:
        oldest_keys = sorted(_EMBED_CACHE, key=lambda key: _EMBED_CACHE[key][0])[:overflow]
        for key in oldest_keys:
            _EMBED_CACHE.pop(key, None)


def _ollama_base_url() -> str:
    return os.getenv("OLLAMA_HOST", "http://ollama:11434").rstrip("/")


@dataclass(slots=True)
class ToolCall:
    """Parsed tool call emitted by the LLM runtime."""

    name: str
    arguments: dict[str, Any]


class OllamaClient:
    """Thin async client for embeddings, chat completion, and health checks."""

    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = (base_url or _ollama_base_url()).rstrip("/")
        self.timeout = timeout

    async def healthcheck(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/version")
            response.raise_for_status()
            return response.json()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        model = os.getenv("OLLAMA_EMBED_MODEL", "qwen3-embedding:4b")
        cache_key = (model, tuple(texts))
        now = time.monotonic()

        async with _EMBED_CACHE_LOCK:
            cached = _EMBED_CACHE.get(cache_key)
            if cached and now - cached[0] <= _embed_cache_ttl_seconds():
                return _copy_embeddings(cached[1])

            in_flight = _EMBED_IN_FLIGHT.get(cache_key)
            if in_flight is None:
                loop = asyncio.get_running_loop()
                in_flight = loop.create_future()
                _EMBED_IN_FLIGHT[cache_key] = in_flight
                owner = True
            else:
                owner = False

        if not owner:
            return _copy_embeddings(await in_flight)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/embed",
                    json={"model": model, "input": texts},
                )
                response.raise_for_status()
                embeddings = response.json()["embeddings"]

                async with _EMBED_CACHE_LOCK:
                    _EMBED_CACHE[cache_key] = (time.monotonic(), _copy_embeddings(embeddings))
                    _prune_embed_cache(time.monotonic())
                    future = _EMBED_IN_FLIGHT.pop(cache_key, None)
                    if future is not None and not future.done():
                        future.set_result(_copy_embeddings(embeddings))

                return embeddings
            except Exception as exc:
                async with _EMBED_CACHE_LOCK:
                    future = _EMBED_IN_FLIGHT.pop(cache_key, None)
                    if future is not None and not future.done():
                        future.set_exception(exc)
                raise

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str = "gemma4:12b",
    ) -> str:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            message = data.get("message", {})
            return message.get("content", "")

    async def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str = "gemma4:12b",
    ) -> tuple[str, list[ToolCall]]:
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {})
        tool_calls = self._parse_tool_calls(message)
        if not tool_calls and tools:
            tool_calls = self._parse_json_fallback(message.get("content", ""))
        return message.get("content", ""), tool_calls

    def _parse_tool_calls(self, message: dict[str, Any]) -> list[ToolCall]:
        parsed: list[ToolCall] = []
        for tool_call in message.get("tool_calls", []) or []:
            function = tool_call.get("function", {})
            name = function.get("name")
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    continue
            if name and isinstance(arguments, dict):
                parsed.append(ToolCall(name=name, arguments=arguments))
        return parsed

    def _parse_json_fallback(self, content: str) -> list[ToolCall]:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return []

        if isinstance(payload, dict):
            payload = [payload]

        parsed: list[ToolCall] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = item.get("tool") or item.get("name")
            arguments = item.get("arguments", {})
            if name and isinstance(arguments, dict):
                parsed.append(ToolCall(name=name, arguments=arguments))
        return parsed


def get_client() -> OllamaClient:
    """Return an Ollama client configured from environment."""

    return OllamaClient()
