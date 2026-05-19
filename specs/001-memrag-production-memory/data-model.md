# Data Model: MEMRAG — Production Memory, RAG & BYOD Knowledge Platform

**Branch**: `001-memrag-production-memory`  
**Date**: 2026-05-14

All entities are scoped either to `workspace_id` (multi-tenant boundary) or to
`(workspace_id, agent_id)` where per-agent isolation is required. PostgreSQL stores
relational state; Qdrant stores all vector embeddings.

---

## 1. Qdrant Collections

### 1.1 `agent_memories` — Layer 2: Per-Agent Long-Term Memory

Stores atomic facts extracted from agent workflow completions.

**Qdrant point payload schema**:

```json
{
  "workspace_id": "string",
  "agent_id": "string",
  "memory_type": "episodic | semantic",
  "decay_score": 0.0–1.0,
  "created_at": "ISO8601",
  "last_accessed_at": "ISO8601",
  "content_hash": "sha256-hex",
  "tombstoned": false
}
```

**Vector configuration**:
- `dense`: 768-dimensional float32 (qwen3-embedding:4b)
- `sparse`: Qdrant sparse vector (BM25 token weights)

**Index**: HNSW on `dense`; sparse index on `sparse`. Payload index on
`workspace_id`, `agent_id`, `tombstoned`.

**Decay schedule**:
- `episodic`: score decays after 90 days without access
- `semantic`: score decays after 365 days without access
- Entries with `decay_score < 0.1` are tombstoned and archived to S3 Iceberg

---

### 1.2 `shared_memories` — Layer 3: Cross-Agent Workspace Memory

Stores findings promoted from agent workflows to the shared workspace pool.

**Qdrant point payload schema**:

```json
{
  "workspace_id": "string",
  "source_agent_id": "string",
  "promoted_at": "ISO8601",
  "content_hash": "sha256-hex"
}
```

**Vector configuration**: same as `agent_memories` (dense + sparse).

**Index**: HNSW on `dense`; payload index on `workspace_id`.

---

### 1.3 `org_knowledge` — Layer 4: BYOD Org Knowledge Base

Stores indexed chunks from connected external knowledge sources.

**Qdrant point payload schema**:

```json
{
  "workspace_id": "string",
  "connector_id": "uuid",
  "source_type": "github | confluence | slack | rds_schema",
  "resource_id": "string",
  "chunk_index": 0,
  "title": "string",
  "url": "string | null",
  "sharing_scope": "private | workspace_internal | allowlist | platform_public",
  "allowed_workspace_ids": ["string"],
  "agent_scope": "all | by_id | by_tag",
  "allowed_agent_ids": ["string"],
  "allowed_agent_tags": ["string"],
  "contains_pii": false,
  "pii_masked": false,
  "content_hash": "sha256-hex",
  "last_synced_at": "ISO8601"
}
```

**Vector configuration**: same (dense + sparse).

**Index**: HNSW; payload indexes on `workspace_id`, `connector_id`, `sharing_scope`,
`source_type`, `content_hash`.

---

## 2. PostgreSQL Tables

### 2.1 `knowledge_connectors`

Registry of connected external knowledge sources, one row per connector.

```sql
CREATE TABLE knowledge_connectors (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id     TEXT NOT NULL,
    source_type      TEXT NOT NULL CHECK (source_type IN
                         ('github', 'confluence', 'slack', 'rds_schema')),
    display_name     TEXT NOT NULL,
    credential_ref   TEXT NOT NULL,          -- path to secrets store entry
    config           JSONB NOT NULL,         -- source-specific config (repos, spaces, etc.)
    contains_pii     BOOLEAN NOT NULL DEFAULT FALSE,
    sharing_scope    TEXT NOT NULL DEFAULT 'private'
                         CHECK (sharing_scope IN
                             ('private','workspace_internal','allowlist','platform_public')),
    agent_scope      TEXT NOT NULL DEFAULT 'all'
                         CHECK (agent_scope IN ('all','by_id','by_tag')),
    allowed_agent_ids   TEXT[] NOT NULL DEFAULT '{}',
    allowed_agent_tags  TEXT[] NOT NULL DEFAULT '{}',
    sync_schedule    TEXT,                   -- cron expression; NULL = manual only
    sync_status      TEXT NOT NULL DEFAULT 'pending'
                         CHECK (sync_status IN
                             ('pending','running','ok','error','pii_detected_mismatch')),
    last_synced_at   TIMESTAMPTZ,
    last_error       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON knowledge_connectors (workspace_id);
CREATE INDEX ON knowledge_connectors (sync_status);
```

---

### 2.2 `knowledge_sync_state`

Per-resource delta sync tracking for idempotent incremental ingestion.

```sql
CREATE TABLE knowledge_sync_state (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connector_id     UUID NOT NULL REFERENCES knowledge_connectors(id) ON DELETE CASCADE,
    resource_id      TEXT NOT NULL,          -- path, page ID, channel ID, table name
    content_hash     TEXT NOT NULL,          -- SHA-256 hex of last ingested content
    last_synced_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (connector_id, resource_id)
);

CREATE INDEX ON knowledge_sync_state (connector_id);
```

---

### 2.3 `knowledge_sharing_grants`

Active allowlist grants from one workspace to another for a specific connector.

```sql
CREATE TABLE knowledge_sharing_grants (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connector_id     UUID NOT NULL REFERENCES knowledge_connectors(id) ON DELETE CASCADE,
    grantee_workspace_id  TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending','active','revoked')),
    granted_at       TIMESTAMPTZ,
    revoked_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (connector_id, grantee_workspace_id)
);

CREATE INDEX ON knowledge_sharing_grants (connector_id);
CREATE INDEX ON knowledge_sharing_grants (grantee_workspace_id, status);
```

---

### 2.4 `pii_audit_log`

Immutable, append-only record of PII detection events during ingestion.
No raw PII values are ever stored.

```sql
CREATE TABLE pii_audit_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connector_id     UUID NOT NULL,          -- no FK: immutable even after connector delete
    workspace_id     TEXT NOT NULL,
    resource_id      TEXT NOT NULL,
    chunk_index      INTEGER NOT NULL,
    entity_category  TEXT NOT NULL,          -- EMAIL, PHONE, CREDIT_CARD, etc.
    action_taken     TEXT NOT NULL           -- masked, redacted, dropped
                         CHECK (action_taken IN ('masked','redacted','dropped')),
    detected_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON pii_audit_log (connector_id, detected_at);
CREATE INDEX ON pii_audit_log (workspace_id, detected_at);
```

---

### 2.5 `workflow_executions`

Agent and ingestion workflow execution metadata (lightweight event log).

```sql
CREATE TABLE workflow_executions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    temporal_run_id  TEXT NOT NULL UNIQUE,
    workflow_type    TEXT NOT NULL,          -- 'AgentWorkflow', 'IngestionWorkflow', 'DecayMemoriesWorkflow'
    workspace_id     TEXT NOT NULL,
    agent_id         TEXT,                   -- NULL for ingestion/decay workflows
    connector_id     UUID,                   -- NULL for agent workflows
    status           TEXT NOT NULL,          -- 'running', 'completed', 'failed', 'cancelled'
    started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at     TIMESTAMPTZ,
    error_message    TEXT
);

CREATE INDEX ON workflow_executions (workspace_id, started_at DESC);
CREATE INDEX ON workflow_executions (connector_id, started_at DESC);
```

---

## 3. Redis Key Schema

All keys are namespaced by `workspace_id` and `session_id` or `workspace_id` alone
for grants cache.

```
{workspace_id}:session:{session_id}:messages         24h TTL — conversation turns (JSON list)
{workspace_id}:session:{session_id}:tool_results     24h TTL — tool call outputs (JSON map)
{workspace_id}:session:{session_id}:context          24h TTL — assembled context window (string)
grants:{workspace_id}                                 60s TTL — sharing grants JSON array
```

**Session keys**: set on every activity boundary write; TTL is refreshed on each write.
A session key expiring does not affect the Temporal workflow (durable in event history);
it only clears the hot-cache representation used by `fetchRecentSession()`.

**Grants cache**: set on first query after expiry; always loaded from PostgreSQL on cache
miss. Passive TTL only — no active invalidation on grant changes.

---

## 4. S3 Iceberg Table

### `s3://memrag-archive/memory-tombstones/`

Apache Iceberg table for cold-storage archival of tombstoned memory entries before
deletion from Qdrant.

**Schema**:

```
workspace_id       string         NOT NULL
agent_id           string         NOT NULL
memory_type        string         NOT NULL   episodic | semantic
content            string         NOT NULL   original text of the memory fact
decay_score        float          NOT NULL   score at tombstone time
created_at         timestamp_tz   NOT NULL
last_accessed_at   timestamp_tz   NOT NULL
tombstoned_at      timestamp_tz   NOT NULL
content_hash       string         NOT NULL   SHA-256 hex
```

**Partitioning**: `PARTITION BY (workspace_id, days(tombstoned_at))`

**Access pattern**: compliance audit queries by `workspace_id + date range`;
cold retrieval of individual entries by `content_hash`.

**Local dev**: MinIO S3-compatible endpoint (`http://minio:9000`) with bucket
`memrag-archive`. Same PyIceberg client code works against both MinIO and AWS S3.

---

## 5. Entity Relationships

```
knowledge_connectors ─┬─< knowledge_sync_state    (1:N, connector FK)
                       ├─< knowledge_sharing_grants (1:N, connector FK)
                       └─< pii_audit_log            (1:N, connector_id only — no FK, immutable)

workflow_executions ──── (no FK to connectors — append-only, preserved after connector delete)

Qdrant collections (no FK cross-reference — consistency maintained via content_hash):
  agent_memories    ← workspace_id + agent_id (no PostgreSQL row)
  shared_memories   ← workspace_id + source_agent_id (no PostgreSQL row)
  org_knowledge     ← connector_id references knowledge_connectors.id (logical, not enforced)
```

---

## 6. State Transition Diagrams

### `knowledge_connectors.sync_status`

```
pending ──► running ──► ok
                    └──► error ──► running (retry)
                    └──► pii_detected_mismatch ──► running (operator approves)
                                               └──► (deleted / aborted)
```

### `knowledge_sharing_grants.status`

```
pending ──► active ──► revoked
```

### Memory decay lifecycle (Qdrant `agent_memories`)

```
active (decay_score 1.0)
  └── nightly cron: score updated
        └── decay_score < 0.1
              └── tombstoned=true (excluded from recall)
                    └── archived to S3 Iceberg
                          └── deleted from Qdrant
```
