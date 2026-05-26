"""Async Ollama client for embeddings, completions, and health checks."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx


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
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/embed",
                json={"model": model, "input": texts},
            )
            response.raise_for_status()
            return response.json()["embeddings"]

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
