# Enterprise-Agentic-Platform → MEMRAG Integration Checklist

Concrete file-by-file changes against the actual codebase in
`examples/enterprise-agentic-platform/`.  Work through the phases in order;
each later phase depends on the one before.

---

## Phase 0 — Environment & Dependencies

### 0-A · `services/agent-workers/requirements.txt`

Remove the two Postgres-vector packages (MEMRAG owns embeddings and storage):

```diff
-psycopg2-binary>=2.9.9
-pgvector>=0.2.4
```

`httpx` is already present — the new memory activities use it.

### 0-B · Compose / deployment environment variables

Add to the `agent-workers` service environment (wherever it is defined —
`docker-compose.yml`, Helm values, K8s Deployment):

```yaml
MEMORY_API_URL: http://memory-api:8083   # MEMRAG unified endpoint
# X-Workspace-ID is the canonical MEMRAG header; the value comes from tenant_id
# (see Phase 1 — no rename needed in the app layer if the adapter maps it)
```

Remove (MEMRAG handles embeddings internally):

```
EMBEDDING_MODEL
EMBEDDING_DIMENSIONS
```

`POSTGRES_URL` is still needed by other services (agent-registry, kg-service)
but is **no longer required by agent-workers** after this migration.

---

## Phase 1 — Replace `activities_memory.py`

**File**: `services/agent-workers/activities_memory.py`

### What exists today

| Symbol | Behaviour |
|--------|-----------|
| `get_db_connection()` | Opens `psycopg2` connection to Postgres with `pgvector` |
| `normalize_embedding_dimensions()` | Truncates / pads embedding to match `EMBEDDING_DIMENSIONS` env var |
| `get_embedding_model()` / `get_litellm_api_key()` | Reads env vars for the local LLM gateway |
| `recall_memories(query, agent_id, limit)` | Embeds `query` via LLM gateway, queries `agent_memories` pgvector column with `<=>` operator |
| `store_memory(content, agent_id, metadata)` | Embeds `content`, inserts into `agent_memories` |

### Replace entire file with MEMRAG HTTP activities

```python
# services/agent-workers/activities_memory.py  (full replacement)
import logging
import os
from temporalio import activity
import httpx

MEMORY_API = os.getenv("MEMORY_API_URL", "http://memory-api:8083")


def _headers(workspace_id: str, agent_id: str) -> dict:
    # MEMRAG uses X-Workspace-ID (canonical); X-Tenant-ID is accepted as alias.
    # Agent-workers know the value as tenant_id — map it here.
    return {
        "X-Workspace-ID": workspace_id,
        "X-Agent-ID":     agent_id,
        "Content-Type":   "application/json",
    }


@activity.defn
async def recall_memories(query: str, agent_id: str, limit: int = 3,
                           workspace_id: str = "default-tenant") -> list[str]:
    """Retrieves semantically relevant memories via MEMRAG /memories/search."""
    logging.info(f"[MEMRAG] Recalling memories for agent {agent_id}: {query[:80]}")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{MEMORY_API}/api/v1/memories/search",
                headers=_headers(workspace_id, agent_id),
                json={"query": query, "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()
            return [m["content"] for m in data.get("memories", [])]
    except Exception as e:
        logging.error(f"[MEMRAG] recall_memories failed: {e}")
        return []


@activity.defn
async def store_memory(content: str, agent_id: str, metadata: dict = None,
                        workspace_id: str = "default-tenant") -> bool:
    """Stores a new observation in MEMRAG L2 agent memory."""
    logging.info(f"[MEMRAG] Storing memory for agent {agent_id}: {content[:60]}")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{MEMORY_API}/api/v1/memories",
                headers=_headers(workspace_id, agent_id),
                json={"content": content, "metadata": metadata or {}},
            )
            resp.raise_for_status()
            return True
    except Exception as e:
        logging.error(f"[MEMRAG] store_memory failed: {e}")
        return False
```

**Checkpoint**: existing callers in `workflows.py` call
`"recall_memories"` / `"store_memory"` by string name (Temporal activity
registration) and pass `(prompt, agent_id)` — the new signatures are
backward-compatible because `workspace_id` defaults to `"default-tenant"`.
No workflow code changes are required for Phase 1 to be functional.

---

## Phase 2 — Thread `workspace_id` Through Workflows

**File**: `services/agent-workers/workflows.py`

Today `tenant_id` is pulled from the request dict and threaded through every
activity call.  MEMRAG's canonical header is `X-Workspace-ID`; the value is
the same string.  The activities already accept `workspace_id` (added in
Phase 1). Wire it in three places:

### 2-A · `_orchestrated_run()` — recall call (line ~148)

```diff
-        recall_handle = workflow.start_activity(
-            "recall_memories",
-            args=[prompt, agent_id],
+        recall_handle = workflow.start_activity(
+            "recall_memories",
+            args=[prompt, agent_id, 3, tenant_id],   # workspace_id = tenant_id
             start_to_close_timeout=timedelta(seconds=8),
             retry_policy=RetryPolicy(maximum_attempts=1),
         )
```

### 2-B · `_orchestrated_run()` — store call (line ~518)

```diff
-            workflow.start_activity(
-                "store_memory",
-                args=[f"Observation for '{prompt}': {final_answer}", agent_id],
+            workflow.start_activity(
+                "store_memory",
+                args=[f"Observation for '{prompt}': {final_answer}", agent_id, None, tenant_id],
                 start_to_close_timeout=timedelta(seconds=10),
             )
```

### 2-C · `_react_loop()` — store call (line ~889)

```diff
-            workflow.start_activity(
-                "store_memory",
-                args=[f"Observation for '{prompt[:100]}': {final_answer[:300]}", agent_id],
+            workflow.start_activity(
+                "store_memory",
+                args=[f"Observation for '{prompt[:100]}': {final_answer[:300]}", agent_id, None, tenant_id],
                 start_to_close_timeout=timedelta(seconds=10),
             )
```

### 2-D · `_manifest_assistant_run()` — store call (line ~1036)

```diff
-            workflow.start_activity(
-                "store_memory",
-                args=[f"Observation for '{prompt}': {final_answer}", agent_id],
+            workflow.start_activity(
+                "store_memory",
+                args=[f"Observation for '{prompt}': {final_answer}", agent_id, None, tenant_id],
                 start_to_close_timeout=timedelta(seconds=10),
             )
```

---

## Phase 3 — Add Session Turn Tracking (new activity)

**File**: `services/agent-workers/activities_memory.py`

MEMRAG's L1 layer (`/api/v1/session/{id}/turns`) replaces any
Redis-direct session writes.  Add two new activities after the existing ones:

```python
@activity.defn
async def log_session_turn(session_id: str, role: str, content: str,
                            workspace_id: str = "default-tenant",
                            agent_id: str = "unknown") -> None:
    """Appends a turn to the MEMRAG session buffer (L1 Redis)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{MEMORY_API}/api/v1/session/{session_id}/turns",
                headers=_headers(workspace_id, agent_id),
                json={"role": role, "content": content},
            )
            resp.raise_for_status()
    except Exception as e:
        logging.warning(f"[MEMRAG] log_session_turn failed (non-fatal): {e}")


@activity.defn
async def hydrate_context(prompt: str, session_id: str,
                           workspace_id: str = "default-tenant",
                           agent_id: str = "unknown") -> dict:
    """Returns assembled L1-L4 context from MEMRAG for a given query."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{MEMORY_API}/api/v1/hydrate",
                headers=_headers(workspace_id, agent_id),
                json={"query": prompt, "session_id": session_id},
            )
            resp.raise_for_status()
            return resp.json()   # keys: session_turns, memories, shared, knowledge
    except Exception as e:
        logging.error(f"[MEMRAG] hydrate_context failed: {e}")
        return {}
```

**File**: `services/agent-workers/main.py`

Register the new activities (line ~73):

```diff
-    from activities_memory import recall_memories, store_memory
+    from activities_memory import recall_memories, store_memory, log_session_turn, hydrate_context
```

```diff
-    activities=[..., recall_memories, store_memory, ...]
+    activities=[..., recall_memories, store_memory, log_session_turn, hydrate_context, ...]
```

---

## Phase 4 — Replace KG Recall with `knowledge/search`

**File**: `services/agent-workers/workflows.py`

Agents with `knowledge_graph_ids` currently route to `kg-service` for
entity recall.  Replace with MEMRAG org knowledge search.

Find `_build_react_tools` (around line 533) — locate the branch that adds
a `kg-search` tool definition and replace the downstream call:

```diff
 # In the tool router dict inside _build_react_tools:
-"kg-search": lambda args: _call_kg_service(graph_id, args["query"])
+"kg-search": lambda args: _call_memrag_knowledge(workspace_id, agent_id, args["query"])
```

Add helper at module level or in `activities_agent.py`:

```python
# activities_agent.py — add at bottom

@activity.defn
async def search_org_knowledge(query: str, workspace_id: str, agent_id: str,
                                limit: int = 5) -> list[str]:
    """Searches MEMRAG L4 org knowledge (BYOD connectors)."""
    import httpx, os, logging
    memory_api = os.getenv("MEMORY_API_URL", "http://memory-api:8083")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{memory_api}/api/v1/knowledge/search",
                headers={"X-Workspace-ID": workspace_id, "X-Agent-ID": agent_id,
                         "Content-Type": "application/json"},
                json={"query": query, "limit": limit},
            )
            resp.raise_for_status()
            return [c["content"] for c in resp.json().get("chunks", [])]
    except Exception as e:
        logging.error(f"[MEMRAG] search_org_knowledge failed: {e}")
        return []
```

---

## Phase 5 — Wire Connector-Registry for Knowledge Ingestion

The existing `kg-service` manages structured Neo4j graphs.  The MEMRAG
`connector-registry` (port 8082) + `knowledge-ingestion` Temporal worker
replace the ingest pipeline for document/URL sources.

**File**: `services/agent-workers/activities_agent.py` — no change needed.
Connector CRUD is a management-plane operation (see UI plan); the runtime only
calls `knowledge/search`.

**Admin console `lib/api.ts`** (if it has an admin-api for KG): add the
connector-registry client (see UI plan, Section B).

---

## Phase 6 — Remove Unused Infrastructure

Once all agents are validated against MEMRAG, remove:

| Item | Location | Action |
|------|----------|--------|
| `agent_memories` Postgres table | DB migrations | Drop table |
| `pgvector` extension | Postgres init SQL | Remove if no other consumer |
| `get_db_connection()`, `normalize_embedding_dimensions()` | `activities_memory.py` | Already removed in Phase 1 |
| `POSTGRES_URL` env var | `agent-workers` Compose service | Remove |
| `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | `agent-workers` Compose service | Remove |
| `psycopg2-binary`, `pgvector` | `requirements.txt` | Already removed in Phase 0 |

---

## Regression Test: `test/test_workflows.py`

**File**: `services/agent-workers/test/test_workflows.py`

Lines 66, 92, 149, 280 mock `recall_memories` and `store_memory` directly.
After Phase 1 the mocks must simulate HTTP responses rather than embedding
calls.  Replace patterns like:

```python
# Before (mocks OpenAI embedding + psycopg2 cursor)
mock_embed.return_value = ...

# After (mock httpx.AsyncClient.post for MEMRAG endpoints)
with respx.mock:
    respx.post("http://memory-api:8083/api/v1/memories/search").mock(
        return_value=httpx.Response(200, json={"memories": []})
    )
    respx.post("http://memory-api:8083/api/v1/memories").mock(
        return_value=httpx.Response(201, json={"id": "m-test"})
    )
```

`respx` is already in `requirements.txt`.

---

## Quick Validation Sequence

```bash
# 1. Start MEMRAG stack
cd /path/to/MEMRAG
docker compose up -d

# 2. Smoke-test recall (no memories yet → empty list OK)
curl -s -X POST http://localhost:8083/api/v1/memories/search \
  -H "X-Workspace-ID: default-tenant" \
  -H "X-Agent-ID: agent-smoke" \
  -H "Content-Type: application/json" \
  -d '{"query":"test","limit":3}' | jq .

# 3. Store a memory
curl -s -X POST http://localhost:8083/api/v1/memories \
  -H "X-Workspace-ID: default-tenant" \
  -H "X-Agent-ID: agent-smoke" \
  -H "Content-Type: application/json" \
  -d '{"content":"The sky is blue","metadata":{}}' | jq .

# 4. Recall it back
curl -s -X POST http://localhost:8083/api/v1/memories/search \
  -H "X-Workspace-ID: default-tenant" \
  -H "X-Agent-ID: agent-smoke" \
  -H "Content-Type: application/json" \
  -d '{"query":"color of sky","limit":3}' | jq '.memories[].content'
```
