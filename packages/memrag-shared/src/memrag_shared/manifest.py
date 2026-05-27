"""Shared agent manifest contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentDomain(str, Enum):
    """Supported ranking domains for context hydration."""

    CODE = "code"
    OPS = "ops"
    POLICY = "policy"
    DATA = "data"


@dataclass(slots=True)
class AgentManifest:
    """Per-agent runtime manifest shared across services."""

    agent_id: str
    workspace_id: str
    domain: AgentDomain | None = None
    knowledge_top_k: int = 8
    context_token_budget: int = 4096
    promote_to_shared: bool = False
    knowledge_source_filter: list[str] = field(default_factory=list)
    agent_tags: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
