# UI Plan: MEMRAG Integration in Enterprise-Agentic-Platform

Target codebase: `examples/enterprise-agentic-platform/`

---

## Current UI Inventory

| App | Route | What exists today |
|-----|-------|-------------------|
| agent-studio | `/knowledge-graphs` | Create/delete KG, ingest URL/file, view node/edge counts |
| agent-studio | `/knowledge-graphs/[id]` | Graph chat (kg-service Q&A), visualiser (nodes/edges), file/URL ingest |
| agent-studio | `/agents` | Create/edit agent wizard with a "Knowledge" step wiring `knowledge_graph_ids` |
| agent-studio | `/agents/[id]` | Agent detail, re-edit all wizard fields |
| admin-console | `/knowledge-graphs` | Cross-tenant list + delete of all structured graphs |
| admin-console | `/mcp-servers` | MCP server CRUD |
| admin-console | `/system-tools`, `/system-skills` | Platform-level resource management |

---

## What Changes and Why

The existing Knowledge Graph surface is built around `kg-service` (structured
node/edge graphs, AI architect chat).  MEMRAG adds a *parallel* org-knowledge
layer (L4 `org_knowledge` in Qdrant) fed by source connectors (GitHub,
Confluence, Slack, RDS schema).  The two systems serve different purposes:

- **Keep `kg-service` surface** — structured graphs, domain modelling, KG
  visualiser → unchanged.
- **Add MEMRAG connector surface** — unstructured document / API sources,
  chunked embedding, hybrid recall → new pages and extensions.

---

## Section A — agent-studio New Pages

### A1 · `/connectors` — Knowledge Source Connectors

**New route**: `apps/agent-studio/src/app/(studio)/connectors/page.tsx`

Lists all connectors for the current workspace (tenant).  Calls the MEMRAG
`connector-registry` (port 8082).

```
┌─────────────────────────────────────────────────────────────┐
│  Knowledge Connectors                          [+ Add Source]│
├───────────┬──────────────┬──────────┬───────────────────────┤
│ Name      │ Type         │ Status   │ Last synced           │
├───────────┼──────────────┼──────────┼───────────────────────┤
│ Eng Docs  │ confluence   │ ● active │ 2026-05-26 14:32 UTC  │
│ Backend   │ github       │ ● active │ 2026-05-27 08:01 UTC  │
│ #support  │ slack        │ ◌ idle   │ 2026-05-24 09:15 UTC  │
│ Prod DB   │ rds_schema   │ ● active │ 2026-05-27 07:00 UTC  │
└───────────┴──────────────┴──────────┴───────────────────────┘
```

**Actions per row**: Edit · Sync now · Delete

**New file**: `apps/agent-studio/src/app/(studio)/connectors/[id]/page.tsx`  
Shows connector detail: config fields (redacted secrets), sync history, chunk
count in `org_knowledge` collection.

**New file**: `apps/agent-studio/src/app/(studio)/connectors/[id]/grants/page.tsx`  
Lists which agents/workspaces have read grants for this connector's data.

#### API calls (add to `lib/api.ts`)

```typescript
const CONNECTOR_REGISTRY =
  process.env.NEXT_PUBLIC_CONNECTOR_REGISTRY_URL ?? "http://localhost:8082";
const MEMORY_API =
  process.env.NEXT_PUBLIC_MEMORY_API_URL ?? "http://localhost:8083";

export const connectorApi = {
  list: () =>
    req<ConnectorDef[]>(CONNECTOR_REGISTRY, "/api/v1/connectors"),
  get: (id: string) =>
    req<ConnectorDef>(CONNECTOR_REGISTRY, `/api/v1/connectors/${id}`),
  create: (body: Partial<ConnectorDef>) =>
    req<ConnectorDef>(CONNECTOR_REGISTRY, "/api/v1/connectors", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  update: (id: string, body: Partial<ConnectorDef>) =>
    req<ConnectorDef>(CONNECTOR_REGISTRY, `/api/v1/connectors/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  delete: (id: string) =>
    req<void>(CONNECTOR_REGISTRY, `/api/v1/connectors/${id}`, { method: "DELETE" }),
  syncNow: (id: string) =>
    req<{ job_id: string }>(CONNECTOR_REGISTRY, `/api/v1/connectors/${id}/sync`, {
      method: "POST",
    }),
  listGrants: (connectorId: string) =>
    req<Grant[]>(CONNECTOR_REGISTRY, `/api/v1/connectors/${connectorId}/grants`),
  addGrant: (connectorId: string, agentId: string) =>
    req<Grant>(CONNECTOR_REGISTRY, `/api/v1/connectors/${connectorId}/grants`, {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId }),
    }),
  removeGrant: (connectorId: string, agentId: string) =>
    req<void>(CONNECTOR_REGISTRY, `/api/v1/connectors/${connectorId}/grants/${agentId}`, {
      method: "DELETE",
    }),
};

export const memoryApi = {
  searchKnowledge: (query: string, limit = 5) =>
    req<{ chunks: KnowledgeChunk[] }>(MEMORY_API, "/api/v1/knowledge/search", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    }),
  searchMemories: (query: string, limit = 10) =>
    req<{ memories: Memory[] }>(MEMORY_API, "/api/v1/memories/search", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    }),
  searchShared: (query: string, limit = 5) =>
    req<{ findings: SharedMemory[] }>(MEMORY_API, "/api/v1/shared/search", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    }),
  getSessionTurns: (sessionId: string) =>
    req<{ turns: Turn[] }>(MEMORY_API, `/api/v1/session/${sessionId}/turns`),
  triggerIngest: (connectorId: string) =>
    req<void>(MEMORY_API, "/api/v1/ingest", {
      method: "POST",
      body: JSON.stringify({ connector_id: connectorId }),
    }),
};
```

#### Type definitions (add to `lib/types.ts`)

```typescript
export interface ConnectorDef {
  id: string;
  name: string;
  type: "github" | "confluence" | "slack" | "rds_schema" | "s3" | "web";
  status: "active" | "idle" | "error" | "syncing";
  config: Record<string, unknown>;  // secrets redacted server-side
  last_synced_at: string | null;
  chunk_count: number;
  workspace_id: string;
}

export interface Grant {
  connector_id: string;
  agent_id: string;
  granted_at: string;
}

export interface KnowledgeChunk {
  id: string;
  content: string;
  source: string;
  score: number;
}

export interface Memory {
  id: string;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface SharedMemory {
  id: string;
  content: string;
  promoted_by: string;
  created_at: string;
}

export interface Turn {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
}
```

#### Connector creation wizard (sheet / dialog)

Four connector types to support at launch; each shows different config fields:

| Type | Config fields |
|------|---------------|
| `github` | owner, repo, branch, PAT (secret input) |
| `confluence` | base_url, space_key, email, API token (secret) |
| `slack` | workspace name, channel IDs, bot token (secret) |
| `rds_schema` | host, port, database, user, password (secret), include schemas |

Secret fields use `type="password"` with a "reveal" toggle; they are never
returned by the API on GET (the form shows a placeholder `••••••••`).

---

### A2 · Agent Wizard "Knowledge" Step — extend with MEMRAG connectors

**File**: `apps/agent-studio/src/app/(studio)/agents/page.tsx`
**Step**: `"knowledge"` (already exists — `BookOpen` icon, step 6 in `STEPS`)

Today this step shows a multi-select of `knowledge_graph_ids` from `kgApi`.

**Extend** (not replace) it with a second section below the KG multi-select:

```
─── Structured Knowledge Graphs ──────────────
  [×] Product Domain Graph
  [×] Engineering KG

─── MEMRAG Org Knowledge (connectors) ────────
  The agent can search all connector sources
  granted to this workspace automatically.
  [View connectors →]  [Manage grants →]

─── Memory Hydration Preview ──────────────────
  Query: [__________________________] [Test]
  ↳ Shows hydrate response JSON inline
```

The "Memory Hydration Preview" calls `POST /api/v1/hydrate` using the current
wizard's `agent_id` (or a preview placeholder) so the user can verify that the
right context is assembled before saving the agent.

---

### A3 · `/memory` — Memory Explorer (new)

**New route**: `apps/agent-studio/src/app/(studio)/memory/page.tsx`

Three-tab layout:

```
[Agent Memories]  [Shared Findings]  [Org Knowledge]
```

**Agent Memories tab**
- Text search box → calls `POST /api/v1/memories/search`
- Results list: content, metadata, created_at, agent_id
- "Promote to Shared" button on each row → `POST /api/v1/shared`

**Shared Findings tab**
- Text search box → calls `POST /api/v1/shared/search`
- Results list: content, promoted_by, created_at

**Org Knowledge tab**
- Text search box → calls `POST /api/v1/knowledge/search`
- Results list: content, source (connector name + doc URL), score chip

---

## Section B — admin-console New Pages

### B1 · `/connectors` — Platform-wide Connector Admin

**New route**: `apps/admin-console/src/app/(admin)/connectors/page.tsx`

Cross-workspace view of all connectors.  Calls the admin surface of
`connector-registry` with an admin key header.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Connectors (all workspaces)                         [Export] [+Add] │
├────────────┬──────────────┬──────────────┬──────────┬───────────────┤
│ Name       │ Workspace    │ Type         │ Status   │ Chunks        │
├────────────┼──────────────┼──────────────┼──────────┼───────────────┤
│ Eng Docs   │ acme-eng     │ confluence   │ active   │ 14,302        │
│ Backend    │ acme-eng     │ github       │ active   │ 3,891         │
│ #support   │ acme-support │ slack        │ idle     │ 8,100         │
└────────────┴──────────────┴──────────────┴──────────┴───────────────┘
```

Admin actions: Force sync · Revoke all grants · Delete connector + data

#### API (add to admin-console `lib/api.ts`)

```typescript
const CONNECTOR_REGISTRY =
  process.env.NEXT_PUBLIC_CONNECTOR_REGISTRY_URL ?? "http://localhost:8082";

export const adminConnectorApi = {
  listAll: () =>
    adminReq<ConnectorDef[]>(CONNECTOR_REGISTRY, "/admin/connectors"),
  delete: (id: string) =>
    adminReq<void>(CONNECTOR_REGISTRY, `/admin/connectors/${id}`, { method: "DELETE" }),
  forceSync: (id: string) =>
    adminReq<{ job_id: string }>(CONNECTOR_REGISTRY, `/admin/connectors/${id}/sync`, {
      method: "POST",
    }),
};
// adminReq wraps req() with X-Admin-Key header (same pattern as existing adminApi)
```

---

### B2 · `/memory-health` — Memory Layer Health (new)

**New route**: `apps/admin-console/src/app/(admin)/memory-health/page.tsx`

Dashboard showing L1-L4 store stats fetched from MEMRAG's Prometheus metrics
or a dedicated `/admin/stats` endpoint (to be added to `memory-api`):

```
L1 Redis session buffer
  Active sessions:  42    Keys TTL p50: 4.2 min

L2 Agent Memories (Qdrant: agent_memories)
  Total vectors:  1,204,931   Workspaces: 18

L3 Shared Findings (Qdrant: shared_memories)
  Total vectors:    23,451

L4 Org Knowledge (Qdrant: org_knowledge)
  Total vectors:   889,302   Connectors: 7
```

Can be implemented as a simple read-only polling page (30 s interval) that
calls `GET /api/v1/admin/stats` (new lightweight endpoint) or scrapes
Prometheus via the existing `infra/prometheus/` deployment.

---

## Section C — Navigation Updates

### agent-studio sidebar

**File**: `apps/agent-studio/src/components/app-shell.tsx`

Add two new nav items after "Knowledge Graphs":

```diff
 { href: "/knowledge-graphs", label: "Knowledge Graphs", icon: GitFork },
+{ href: "/connectors",       label: "Connectors",       icon: PlugZap },
+{ href: "/memory",           label: "Memory Explorer",  icon: BrainCircuit },
```

Import new Lucide icons: `PlugZap`, `BrainCircuit`.

### admin-console sidebar

Add after "Knowledge Graphs":

```diff
 { href: "/knowledge-graphs", label: "Knowledge Graphs", icon: GitFork },
+{ href: "/connectors",       label: "Connectors",       icon: PlugZap },
+{ href: "/memory-health",    label: "Memory Health",    icon: Activity },
```

---

## Section D — Environment Variables

Both Next.js apps need two new env vars in their `.env.local` / Compose
environment sections:

```bash
NEXT_PUBLIC_CONNECTOR_REGISTRY_URL=http://localhost:8082
NEXT_PUBLIC_MEMORY_API_URL=http://localhost:8083
```

---

## Build Order

1. **`lib/api.ts` additions** (agent-studio + admin-console) — no UI, just
   API client; unblocks all subsequent pages.
2. **`lib/types.ts` additions** — TypeScript types for new entities.
3. **`/connectors` page** (agent-studio) — CRUD with creation wizard.
4. **Agent wizard Knowledge step extension** — wire hydration preview.
5. **`/memory` explorer** (agent-studio) — search tabs.
6. **Admin `/connectors`** — cross-workspace table.
7. **Admin `/memory-health`** — stats dashboard.
8. **Navigation wiring** (`app-shell.tsx` in both apps).
