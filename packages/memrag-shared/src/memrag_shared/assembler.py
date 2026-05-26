"""Context assembler — merges all four memory layers into a token-budget prompt.

Called inline by ``memory-api``'s ``POST /api/v1/hydrate`` handler after the
parallel L1–L4 recall fan-out has resolved.

Algorithm (per contract context_hydration.md):
1. Apply the domain/source weight matrix to L2/L3/L4 chunks and sort desc.
2. Allocate Layer 1 session turns (FIFO oldest-drop when over budget).
3. Fill remaining budget with scored chunks (never partially include a chunk).
4. Append a citations block for every ``KnowledgeChunk`` included.
5. Return ``HydrateResponse``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from memrag_shared.layers import KnowledgeChunk, MemoryChunk
from memrag_shared.weights import get_weight

log = logging.getLogger(__name__)

# ─── token constants ────────────────────────────────────────────────────────

# Tokens reserved for the system preamble (header text before any context).
_PREAMBLE_TOKENS = 200
# Fraction of the remaining budget to reserve for Layer 1 turns.
_L1_SHARE = 0.5


# ─── public dataclasses ─────────────────────────────────────────────────────


@dataclass
class HydrateRequest:
    """Input for :func:`assemble`.

    All chunk lists are pre-fetched by the hydrate handler; ``session_turns``
    contains the raw ``{role, content}`` dicts fetched from Redis.
    """

    workspace_id: str
    session_id: str
    agent_id: str
    query: str
    domain: str | None = None
    token_budget: int = 4096
    agent_tags: list[str] = field(default_factory=list)
    # Pre-fetched layer data — populated by the hydrate handler
    session_turns: list[dict] = field(default_factory=list)
    agent_memories: list[MemoryChunk] = field(default_factory=list)
    shared_memories: list[MemoryChunk] = field(default_factory=list)
    org_knowledge: list[KnowledgeChunk] = field(default_factory=list)


@dataclass
class Citation:
    """A single source citation attached to the assembled system prompt."""

    source_type: str
    title: str
    url: str | None
    connector_id: str
    chunk_index: int


@dataclass
class HydrateResponse:
    """Output of :func:`assemble`."""

    system_prompt: str
    token_count: int
    layer_stats: dict
    failed_layers: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)


# ─── internal helpers ────────────────────────────────────────────────────────


def _count_tokens(text: str) -> int:
    """Approximate token count using whitespace tokenisation.

    Good enough for budget enforcement; avoids a tiktoken dependency.
    """
    return max(1, len(text.split()))


# ─── public API ──────────────────────────────────────────────────────────────


def assemble(
    request: HydrateRequest,
    failed_layers: list[str] | None = None,
) -> HydrateResponse:
    """Assemble a token-budget-compliant system prompt from all four layers.

    Args:
        request: Pre-populated :class:`HydrateRequest` including chunk lists
            fetched by the hydrate handler and session turns from Redis.
        failed_layers: Layer names that failed recall (passed in from caller).

    Returns:
        :class:`HydrateResponse` ready to be serialised and returned to the
        calling agent.
    """
    failed: list[str] = list(failed_layers or [])
    budget = max(request.token_budget, _PREAMBLE_TOKENS + 10)
    remaining = budget - _PREAMBLE_TOKENS

    # ── Layer 1: session turns (newest-first; FIFO oldest-drop on overflow) ──
    turns = list(request.session_turns)  # original order: oldest first
    l1_budget = int(remaining * _L1_SHARE)

    turns_included: list[dict] = []
    turns_tokens = 0
    # Walk newest-first so we keep the most recent turns.
    for turn in reversed(turns):
        line = f"{turn.get('role', 'user')}: {turn.get('content', '')}"
        tc = _count_tokens(line)
        if turns_tokens + tc <= l1_budget:
            turns_included.insert(0, turn)  # maintain chronological order
            turns_tokens += tc
        # Oldest turns silently dropped — expected by spec.

    remaining -= turns_tokens

    # ── Layers 2–4: weight, merge, sort ──────────────────────────────────────
    scored: list[tuple[float, MemoryChunk | KnowledgeChunk, str]] = []

    for chunk in request.agent_memories:
        w = get_weight(chunk.source_type, request.domain)
        scored.append((chunk.score * w, chunk, "layer2"))

    for chunk in request.shared_memories:
        w = get_weight(chunk.source_type, request.domain)
        scored.append((chunk.score * w, chunk, "layer3"))

    for chunk in request.org_knowledge:
        raw_score = chunk.score if chunk.score is not None else 1.0
        w = get_weight(chunk.source_type, request.domain)
        scored.append((raw_score * w, chunk, "layer4"))

    scored.sort(key=lambda x: x[0], reverse=True)

    included: list[tuple[MemoryChunk | KnowledgeChunk, str]] = []
    dropped: dict[str, int] = {"layer2": 0, "layer3": 0, "layer4": 0}

    for _weighted_score, chunk, layer_name in scored:
        tc = _count_tokens(chunk.text)
        if remaining >= tc:
            included.append((chunk, layer_name))
            remaining -= tc
        else:
            dropped[layer_name] = dropped.get(layer_name, 0) + 1
            log.debug(
                "Dropped %s chunk (budget exhausted, layer=%s)", chunk.__class__.__name__, layer_name
            )

    # ── Build system prompt ───────────────────────────────────────────────────
    lines: list[str] = [
        "You are a helpful AI assistant with access to the following context:",
        "",
    ]

    if turns_included:
        lines.append("## Recent Session")
        for turn in turns_included:
            role = turn.get("role", "user").capitalize()
            content = turn.get("content", "")
            lines.append(f"{role}: {content}")
        lines.append("")

    citations: list[Citation] = []
    chunk_index = 0

    if included:
        lines.append("## Memory & Knowledge Context")
        for chunk, _layer in included:
            if isinstance(chunk, KnowledgeChunk):
                lines.append(f"[{chunk_index + 1}] ({chunk.source_type}) {chunk.text}")
                citations.append(
                    Citation(
                        source_type=chunk.source_type,
                        title=chunk.title or "",
                        url=chunk.url,
                        connector_id=chunk.connector_id,
                        chunk_index=chunk_index,
                    )
                )
            else:
                lines.append(f"({chunk.source_type}) {chunk.text}")
            chunk_index += 1
        lines.append("")

    if citations:
        lines.append("## Citations")
        for cit in citations:
            url_part = f" ({cit.url})" if cit.url else ""
            lines.append(f"[{cit.chunk_index + 1}] {cit.title}{url_part} via {cit.source_type}")

    system_prompt = "\n".join(lines)
    token_count = _count_tokens(system_prompt) + _PREAMBLE_TOKENS

    layer_stats: dict = {
        "layer1_turns": len(turns_included),
        "layer2_chunks": sum(1 for _, lyr in included if lyr == "layer2"),
        "layer3_chunks": sum(1 for _, lyr in included if lyr == "layer3"),
        "layer4_chunks": sum(1 for _, lyr in included if lyr == "layer4"),
    }

    return HydrateResponse(
        system_prompt=system_prompt,
        token_count=token_count,
        layer_stats=layer_stats,
        failed_layers=failed,
        citations=citations,
    )
