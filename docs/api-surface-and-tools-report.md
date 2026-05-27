# MEMRAG API Surface And Tools Report

## Scope

This report inventories the externally visible APIs, machine-callable tools, and adjacent operational surfaces currently provided by MEMRAG.

It focuses on surfaces implemented inside this repository:

- `memory-api` REST and MCP interfaces
- `connector-registry` HTTP API
- `knowledge-ingestion` worker-facing operational surface
- observability and health endpoints exposed by the stack

## Service Inventory

| Service | Kind | Public Surface | Primary Purpose |
|---|---|---|---|
| `memory-api` | FastAPI HTTP service | REST + MCP + health + metrics | Unified memory, recall, hydration, and ingestion trigger API |
| `connector-registry` | Go HTTP service | REST + health + metrics | Connector registration, lookup, grants, and sync status |
| `knowledge-ingestion` | Temporal worker | Metrics only | Fetch, diff, chunk, PII-screen, embed, and upsert org knowledge |
| `prometheus` | Infra service | Prometheus UI/API | Scrapes exported service metrics |
| `github-api-mock` | Test-only FastAPI service | `/health` + mock GitHub endpoints | Deterministic integration testing |
| `confluence-api-mock` | Test-only FastAPI service | `/health` + mock Confluence endpoints | Deterministic integration testing |

## `memory-api` HTTP Surface

### Common Header Contract

All stateful `memory-api` endpoints use the same routing headers:

- `X-Workspace-ID`: canonical tenant/workspace identifier
- `X-Tenant-ID`: legacy alias for `X-Workspace-ID`
- `X-Agent-ID`: required actor identifier on stateful routes

### Health And Observability

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Simple health response for legacy and operational clients |
| `GET` | `/healthz` | Canonical health probe |
| `GET` | `/metrics` | Prometheus exposition for hydration and chunk-drop metrics |

### Layer 1: Session Buffer

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/session/{session_id}/turns` | Fetch recent turns from Redis-backed session memory |
| `POST` | `/api/v1/session/{session_id}/turns` | Checkpoint turns into the Redis-backed session buffer |

### Layer 2: Agent Long-Term Memory

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/memories` | Store long-term memory for an agent in Qdrant via extracted facts |
| `POST` | `/api/v1/memories/search` | Recall semantically relevant agent memories |

Notes:

- Store accepts both `content` and legacy `text` payload keys.
- Store returns compatibility fields including `status`, `agent_id`, `stored`, `stored_ids`, and `stored_count`.
- Search returns `list[str]` of recalled memory texts.

### Layer 3: Workspace-Shared Memory

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/shared` | Promote a finding into workspace-shared memory |
| `POST` | `/api/v1/shared/search` | Search shared workspace memory |

Notes:

- When `GRAPHITI_ENABLED=true`, promotion and recall can route through Graphiti.
- When Graphiti is disabled or falls through, Qdrant remains the storage/search backend.

### Layer 4: Organization Knowledge

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/knowledge/search` | Search org knowledge with sharing-scope and agent-scope enforcement |

### Context Hydration And Assembly

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/hydrate` | Assemble L1 + L2 + L3 + L4 context into a prompt payload |

Hydration response includes:

- `system_prompt`
- `token_count`
- `layer_stats`
- `failed_layers`
- `citations`

### Ingestion Trigger

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/ingest` | Signal a Temporal ingestion workflow for a connector |

### MCP Endpoint

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/mcp` | MCP compatibility endpoint |
| `POST` | `/mcp` | JSON-RPC MCP tool endpoint |

Supported MCP JSON-RPC methods:

- `initialize` / `mcp/initialize`
- `tools/list`
- `tools/call`

## `memory-api` MCP Tool Surface

These are the machine-callable tools exposed by `/mcp`:

| Tool | Purpose | Required Inputs |
|---|---|---|
| `recall_memory` | Recall agent-specific long-term memory | `workspace_id`, `agent_id`, `query` |
| `store_memory` | Store a new long-term agent memory | `workspace_id`, `agent_id`, `text` |
| `promote_finding` | Promote a finding into shared workspace memory | `workspace_id`, `agent_id`, `text` |
| `search_knowledge` | Search organization knowledge | `workspace_id`, `agent_id`, `query` |

## `connector-registry` HTTP Surface

### Health And Observability

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness/readiness probe |
| `GET` | `/metrics` | Prometheus exposition |

### Connector Management API

Base route: `/v1/connectors`

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/connectors/` | Create connector definition |
| `GET` | `/v1/connectors/` | List connectors for workspace |
| `GET` | `/v1/connectors/{id}` | Fetch a connector by id |
| `PATCH` | `/v1/connectors/{id}` | Update connector configuration |
| `DELETE` | `/v1/connectors/{id}` | Delete connector |
| `GET` | `/v1/connectors/{id}/status` | Retrieve sync/status information |
| `POST` | `/v1/connectors/{id}/grants` | Create an access grant |
| `DELETE` | `/v1/connectors/{id}/grants/{grant_id}` | Revoke an access grant |

Notes:

- Connector routes use `X-Workspace-ID` for workspace scoping.
- This service is the registry/control-plane API for BYOD sources.

## `knowledge-ingestion` Operational Surface

`knowledge-ingestion` is not a general-purpose HTTP API service. It is primarily a Temporal worker.

### Exposed Runtime Surface

| Surface | Purpose |
|---|---|
| Prometheus metrics on `KNOWLEDGE_INGESTION_METRICS_PORT` (default `8080`) | Worker observability |
| Container healthcheck `kill -0 1` | Process liveness |

### Registered Workflow/Activity Capabilities

These are not public REST endpoints, but they are core callable capabilities inside the system:

#### Workflows

- `IngestionWorkflow`
- `DecayMemoriesWorkflow`

#### Activities

- `fetch_resources`
- `diff_resources`
- `chunk_and_embed`
- `pii_screen`
- `upsert_org_knowledge`
- `update_sync_state`
- `decay_and_archive`

## Test-Only Mock API Surfaces

These are intended for integration tests, not production callers.

### `github-api-mock`

- `/health`
- mock GitHub resource endpoints used by connector tests

### `confluence-api-mock`

- `/health`
- mock Confluence token/user/search/content endpoints used by connector tests

## Observability Surface Summary

| Service | Endpoint |
|---|---|
| `memory-api` | `/metrics` |
| `connector-registry` | `/metrics` |
| `knowledge-ingestion` | metrics HTTP server on port `8080` by default |
| `prometheus` | `http://localhost:9090` |

## Tooling Summary

There are two distinct tool surfaces in this repo:

### External, machine-callable tools

- The four MCP tools exposed by `memory-api`

### Internal execution capabilities

- Temporal workflows in `knowledge-ingestion`
- connector lifecycle operations in `connector-registry`
- memory assembly and recall orchestration in `memory-api`

## Important Runtime Notes

- GPU acceleration is concentrated in the `ollama` service. Other services consume model capabilities over HTTP rather than running models locally.
- Live performance benchmarks for SC-001 assume a GPU-resident Ollama model. On hosts without GPU visibility in the benchmark container, the live assertion is skipped and the documented baseline check remains available.

## Enterprise Integration

For a replacement-oriented mapping from the legacy enterprise agent platform memory flow to MEMRAG's production interfaces, see `docs/enterprise-agent-platform-memory-integration.md`.