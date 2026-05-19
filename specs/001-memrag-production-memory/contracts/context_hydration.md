# Contract: Context Hydration API

**Service**: `context-hydrator` (Python 3.11, internal Compose service)  
**Feature**: FR-025, FR-026, FR-027, FR-028, FR-029  
**Date**: 2026-05-14

The `context-hydrator` is called by `agent-workers` during `AgentWorkflow` execution after
all parallel recall activities have completed. It is an internal service not exposed through
the public API gateway.

---

## Interface: `assemble()`

Called once per workflow run, after all three parallel recall futures resolve.

### Input

```python
@dataclass
class HydrateRequest:
    workspace_id: str
    session_id: str
    agent_id: str
    agent_tags: list[str]
    domain: str | None           # "code" | "ops" | "policy" | "data" | None
    token_budget: int            # max tokens for the injected context block
    agent_memories: list[MemoryChunk]
    shared_memories: list[MemoryChunk]
    org_knowledge: list[KnowledgeChunk]
    # Layer 1 session turns are fetched internally from Redis

@dataclass
class MemoryChunk:
    text: str
    score: float                 # cosine similarity or RRF fused score
    source_type: str             # "agent_memory" | "shared_memory"
    metadata: dict

@dataclass
class KnowledgeChunk:
    text: str
    score: float
    source_type: str             # "github" | "confluence" | "slack" | "rds_schema"
    title: str
    url: str | None
    connector_id: str
    metadata: dict
```

### Output

```python
@dataclass
class HydrateResponse:
    system_prompt: str           # fully assembled, token-budget-compliant prompt
    token_count: int             # actual token count of system_prompt
    layer_stats: dict            # {"layer1_turns": 3, "layer2_chunks": 4, ...}
    failed_layers: list[str]     # layers that returned empty (timeout/error)
    citations: list[Citation]    # ordered list of org knowledge citations included

@dataclass
class Citation:
    source_type: str
    title: str
    url: str | None
    connector_id: str
    chunk_index: int
```

---

## Assembly Algorithm

1. **Fetch Layer 1**: call `Redis.get({workspace_id}:session:{session_id}:messages)`;
   deserialise turn list. If key missing, Layer 1 = empty.

2. **Re-rank Layer 2/3/4 chunks**:
   - Determine weight multiplier from domain weight matrix (FR-026); default 1.0 if
     `domain` is unset.
   - `weighted_score = chunk.score * SOURCE_WEIGHT[chunk.source_type][domain]`
   - Merge all Layer 2, 3, 4 chunks into a single list; sort by `weighted_score` descending.

3. **Token-budget allocation**:
   - Reserve tokens for: system prompt preamble (fixed ~200 tokens) + citation block.
   - **Layer 1 first**: serialise session turns newest-first. If turns overflow
     `token_budget - reserved`, drop oldest turns until they fit.
   - **Scored chunks**: fill remaining budget with top-ranked chunks until budget exhausted.
     Never partially include a chunk (drop the whole chunk if it would exceed budget).

4. **Citation attachment**: each `KnowledgeChunk` included in the prompt appends a citation
   entry. Citations are listed as a compact block at the end of the assembled prompt.

5. **Failure resilience**: if any of Layer 2, 3, or 4 produced an empty list (timeout or
   error upstream), proceed with available layers. Record the failed layer in `failed_layers`
   and emit a structured warning log.

---

## Prometheus Metrics

The context-hydrator exposes `/metrics` with:

| Metric | Type | Labels | Description |
|---|---|---|---|
| `memory_recall_latency_seconds` | histogram | `layer`, `workspace_id` | Per-layer recall latency (set by agent-workers before calling hydrator) |
| `context_hydration_assembly_ms` | histogram | `workspace_id`, `domain` | Time from all recalls available to assembled prompt ready |
| `context_hydration_budget_tokens_total` | counter | `workspace_id` | Sum of token budgets consumed |
| `context_hydration_chunks_dropped_total` | counter | `workspace_id`, `layer` | Chunks dropped due to token budget overflow |

---

## Source Weight Matrix

```python
SOURCE_WEIGHT: dict[str, dict[str, float]] = {
    "agent_memory":  {"code": 1.2, "ops": 1.3, "policy": 0.8, "data": 1.1},
    "shared_memory": {"code": 1.0, "ops": 1.2, "policy": 0.9, "data": 1.0},
    "github":        {"code": 1.5, "ops": 0.9, "policy": 0.5, "data": 0.8},
    "confluence":    {"code": 0.6, "ops": 1.2, "policy": 1.5, "data": 1.1},
    "rds_schema":    {"code": 1.0, "ops": 0.8, "policy": 0.6, "data": 1.5},
    "slack":         {"code": 0.4, "ops": 1.0, "policy": 0.5, "data": 0.7},
}
```

When `domain` is `None`, `SOURCE_WEIGHT[source_type].get(domain, 1.0)` returns `1.0`
(all weights default to 1.0 — uniform ranking).
