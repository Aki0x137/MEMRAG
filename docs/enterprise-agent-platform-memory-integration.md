# MEMRAG Integration For Enterprise Agent Platform Memory Replacement

## Purpose

This document maps the legacy enterprise-agent-platform memory touchpoints to the MEMRAG surfaces that should replace them.

The target integration model is:

- enterprise-agent-platform keeps its own agent execution loop
- MEMRAG becomes the external memory system of record
- callers integrate with `memory-api` over REST or MCP
- BYOD ingestion and knowledge recall are provided by `connector-registry`, `knowledge-ingestion`, and `memory-api`

## Core Integration Rule

The enterprise platform should stop treating memory as an internal combination of:

- `AgentWorkflow` memory activities
- direct `pgvector` access
- direct Redis session/context memory access
- separate `context-hydrator` assembly logic

Instead, it should treat MEMRAG as a single external memory subsystem with one primary entrypoint:

- `memory-api` for L1-L4 memory operations and MCP tools

## Terminology Mapping

| Enterprise term | MEMRAG term | Notes |
|---|---|---|
| `tenant_id` | `workspace_id` | Same isolation boundary; MEMRAG accepts `X-Tenant-ID` as a legacy alias |
| `AgentWorkflow` memory activity | `memory-api` request | Memory is no longer coupled to Temporal workflow execution |
| `ContextHydrator` | `/api/v1/hydrate` | Assembly is inlined behind `memory-api` |
| `agent_memories` in pgvector | `agent_memories` in Qdrant | Same logical L2 role, different storage backend |
| session Redis keys | `/api/v1/session/{session_id}/turns` | External callers should stop reading/writing memory Redis keys directly |

## Replacement Matrix

| Legacy enterprise memory point | Existing role | MEMRAG replacement | Migration note |
|---|---|---|---|
| `activities_memory.recall_memories(agent_id, tenant_id, prompt)` | Recall agent-scoped long-term memory | `POST /api/v1/memories/search` or MCP `recall_memory` | Returns `list[str]`, which matches the enterprise compatibility contract |
| `activities_memory.store_memory(agent_id, tenant_id, final_answer)` | Store new agent memory after response | `POST /api/v1/memories` or MCP `store_memory` | Keep fire-and-forget behavior at caller side if desired |
| `ContextHydrator.fetchRecentSession()` | Read session turns from Redis | `GET /api/v1/session/{session_id}/turns` | MEMRAG owns TTL and large-payload pointer handling |
| session checkpoint writes to Redis | Persist turn history | `POST /api/v1/session/{session_id}/turns` | Stop direct Redis writes from enterprise services |
| `ContextHydrator.assemble()` | Merge session + memories + SOPs into prompt | `POST /api/v1/hydrate` | MEMRAG assembles L1-L4 memory only; SOP injection remains caller-owned unless moved separately |
| no current shared-memory promotion equivalent | Cross-agent workspace sharing | `POST /api/v1/shared` or MCP `promote_finding` | New capability; use for findings that should survive beyond one agent |
| no current shared-memory search equivalent | Workspace-shared recall | `POST /api/v1/shared/search` | New L3 surface for cross-agent recall |
| `kg-service` or custom org knowledge recall path | Retrieve indexed enterprise knowledge | `POST /api/v1/knowledge/search` | Preserves workspace, grant, and agent-scope filtering |
| connector config + sync initiation path | Register source and trigger sync | `connector-registry` + `POST /api/v1/ingest` | Registry owns connector metadata; `memory-api` triggers workflow execution |
| memory MCP tool exposure through internal agent stack | Tool-based memory access | `GET|POST /mcp` | MEMRAG exposes one MCP endpoint for memory tools |

## Exact API Mapping

### 1. Agent Long-Term Memory

Legacy shape:

```python
await recall_memories(agent_id, tenant_id, prompt)
await store_memory(agent_id, tenant_id, final_answer)
```

MEMRAG replacement:

```http
POST /api/v1/memories/search
X-Workspace-ID: <tenant-or-workspace>
X-Agent-ID: <agent_id>
Content-Type: application/json

{"query": "...", "agent_id": "...", "limit": 8}
```

```http
POST /api/v1/memories
X-Workspace-ID: <tenant-or-workspace>
X-Agent-ID: <agent_id>
Content-Type: application/json

{"text": "final answer or extracted memory candidate", "agent_id": "..."}
```

Why this replaces the old path:

- no direct pgvector dependency in enterprise code
- no embedding call orchestration in enterprise code
- no Temporal activity wrapper needed for memory recall/store
- compatibility response behavior is already implemented for enterprise callers

### 2. Session Memory

Legacy shape:

- direct Redis reads of `{tenant_id}:session:{session_id}:messages`
- direct Redis writes for conversation history and related context buffers

MEMRAG replacement:

```http
POST /api/v1/session/{session_id}/turns
GET /api/v1/session/{session_id}/turns
```

Why this replaces the old path:

- enterprise services stop depending on MEMRAG's internal Redis layout
- MEMRAG handles TTL refresh and large-payload indirection
- session state remains portable across language runtimes and external callers

### 3. Context Hydration

Legacy shape:

- `ContextHydrator` fetches session memory
- `ContextHydrator` injects recalled memories into the system prompt
- assembly is a separate service hop

MEMRAG replacement:

```http
POST /api/v1/hydrate
X-Workspace-ID: <tenant-or-workspace>
X-Agent-ID: <agent_id>
Content-Type: application/json

{
  "session_id": "...",
  "query": "...",
  "agent_id": "...",
  "domain": "code",
  "token_budget": 4096,
  "agent_tags": ["..."]
}
```

What remains caller-owned:

- skill SOP injection
- non-memory tool result formatting
- final prompt composition around the returned `system_prompt`, if the enterprise runtime wants additional wrapper text

What MEMRAG now owns:

- L1 session recall
- L2 agent memory recall
- L3 shared-memory recall
- L4 org knowledge recall
- weighted assembly and token-budget enforcement
- citations and failed-layer reporting

### 4. Shared Memory Between Agents

Legacy state:

- the prior platform flow kept memory scoped to `(tenant_id, agent_id)`
- there was no first-class shared-memory promotion path

MEMRAG replacement:

```http
POST /api/v1/shared
POST /api/v1/shared/search
```

Use this when one agent produces a finding that should become available to other agents in the same workspace.

### 5. Organization Knowledge And BYOD

Legacy state:

- enterprise architecture expected separate knowledge and connector components
- memory and knowledge flows were not unified behind a single memory boundary

MEMRAG replacement:

- register connectors via `connector-registry`
- trigger ingestion via `POST /api/v1/ingest`
- retrieve indexed organization knowledge via `POST /api/v1/knowledge/search`

This gives the enterprise platform one retrieval path for indexed external knowledge while keeping ingestion asynchronous in the worker layer.

### 6. MCP Tool Integration

If the enterprise agent runtime prefers tool-native access instead of direct REST calls, register MEMRAG's MCP endpoint:

- `GET /mcp`
- `POST /mcp`

Available tools:

- `recall_memory`
- `store_memory`
- `promote_finding`
- `search_knowledge`

This is the cleanest replacement when the enterprise platform already has MCP client support.

## Recommended Integration Cutover

### Phase 1: Replace L2 Memory Calls

Replace:

- `recall_memories(...)`
- `store_memory(...)`

With:

- `POST /api/v1/memories/search`
- `POST /api/v1/memories`

This is the lowest-risk cut because it preserves the old `list[str]` recall contract.

### Phase 2: Replace Direct Session Redis Access

Replace:

- direct reads/writes to session Redis keys

With:

- `POST /api/v1/session/{session_id}/turns`
- `GET /api/v1/session/{session_id}/turns`

### Phase 3: Replace Context Hydration Service Calls

Replace:

- separate `ContextHydrator` service or local assembly path for memory recall

With:

- `POST /api/v1/hydrate`

### Phase 4: Add New Shared And Org Knowledge Paths

Adopt:

- `POST /api/v1/shared`
- `POST /api/v1/shared/search`
- `POST /api/v1/knowledge/search`

This extends the enterprise platform beyond the original per-agent memory design.

## Header And Identity Contract

Enterprise callers should standardize on these headers:

- `X-Workspace-ID`: preferred workspace header
- `X-Agent-ID`: required actor identifier

Compatibility fallback:

- `X-Tenant-ID` is still accepted anywhere `X-Workspace-ID` is accepted

Practical recommendation:

- continue sending `tenant_id` from enterprise code, but map it to `X-Workspace-ID` in the integration adapter layer
- keep `X-Tenant-ID` only as a backward-compatibility bridge during rollout

## What Should Not Be Reimplemented In Enterprise Code

Do not carry these forward into the replacement integration:

- direct vector-store queries for memory recall
- direct Redis session-memory reads/writes against MEMRAG-owned keys
- separate memory-specific Temporal activities for synchronous recall/store
- a separate context-hydrator service just for memory assembly

Those are precisely the concerns MEMRAG is now meant to absorb.

## Minimal Adapter Examples

### REST Adapter

```python
import requests

BASE = "http://memory-api:8083"

def search_agent_memory(tenant_id: str, agent_id: str, query: str) -> list[str]:
    response = requests.post(
        f"{BASE}/api/v1/memories/search",
        headers={"X-Workspace-ID": tenant_id, "X-Agent-ID": agent_id},
        json={"query": query, "agent_id": agent_id},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()
```

### Hydration Adapter

```python
def hydrate_context(tenant_id: str, agent_id: str, session_id: str, query: str) -> dict:
    response = requests.post(
        f"{BASE}/api/v1/hydrate",
        headers={"X-Workspace-ID": tenant_id, "X-Agent-ID": agent_id},
        json={
            "session_id": session_id,
            "agent_id": agent_id,
            "query": query,
            "token_budget": 4096,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()
```

## Readiness Notes

- The replacement boundary is already implemented and validated in MEMRAG's integration suite.
- The enterprise compatibility contract for L2 memory is covered by `test_enterprise_compat_api.py`.
- On this host, the GPU-enforced benchmark now executes in the rebuilt test-runner container instead of skipping; the current measured result is `p95=1.093s`, so runtime performance still needs improvement before SC-001 can be claimed on this machine.