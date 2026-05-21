"""Shared layer constants and hydration contract dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LAYER_SESSION = 1
LAYER_AGENT = 2
LAYER_SHARED = 3
LAYER_ORG = 4


@dataclass(slots=True)
class MemoryChunk:
    """Layer 2/3 memory chunk consumed by the context hydrator."""

    text: str
    score: float
    source_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KnowledgeChunk:
    """Layer 4 knowledge chunk consumed by the context hydrator."""

    text: str
    score: float
    source_type: str
    title: str
    url: str | None
    connector_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

