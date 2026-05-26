# Tasks: MEMRAG — Production Memory, RAG & BYOD Knowledge Platform

**Input**: Design documents from `specs/001-memrag-production-memory/`  
**Prerequisites**: plan.md ✅ · spec.md ✅ · research.md ✅ · data-model.md ✅ · contracts/ ✅ · quickstart.md ✅

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton, all 12 Compose services, Dockerfiles, dependency manifests,
and environment config. No application logic — just the container runtime plumbing every
subsequent phase depends on.

- [x] T001 Create top-level directory layout per plan.md: `services/`, `packages/`, `tests/mocks/`, `infra/` at repo root (no top-level `mock-services/` — mocks live under `tests/`)
- [x] T002 Create `docker-compose.yml` with core services (qdrant, postgres, redis, temporal, minio, prometheus, ollama, knowledge-ingestion, connector-registry, memory-api, and two test-only mocks added only in `docker-compose.test.yml`); pin all image tags; add named volumes for qdrant, postgres, redis, minio; add `ENVIRONMENT` and `OLLAMA_HOST` env vars on every application service; pass through shared AWS runtime env needed by later phases (`AWS_REGION`, credentials/session token, AppConfig IDs, Secrets Manager settings, S3/Iceberg settings). Note: `agent-workers` and `context-hydrator` services removed from Compose — see T006/T007.
- [x] T003 [P] Add GPU reservation block (`deploy.resources.reservations.devices`) and health check to `ollama` service in `docker-compose.yml`
- [x] T004 [P] Add health checks and `depends_on: condition: service_healthy` for all application services on their infra dependencies in `docker-compose.yml`
- [x] T005 [P] Create `docker-compose.test.yml` skeleton: inherits base Compose, overrides `ENVIRONMENT=test`, replaces GitHub/Confluence/Slack with `github-api-mock` (port 8085) and `confluence-api-mock` (port 8084)
- [x] T006 ~~[P] Create `Dockerfile` for `services/agent-workers/`~~ — **REMOVED**: `agent-workers` Temporal worker eliminated. Library code (memory/, recall/) moves to `packages/memrag-shared/`; HTTP interface is provided by `memory-api`. No separate agent-workers container.
- [x] T007 ~~[P] Create `Dockerfile` for `services/context-hydrator/`~~ — **REMOVED**: `context-hydrator` service eliminated. Assembly logic (`assembler.py`, `weights.py`) moves to `packages/memrag-shared/` and is called inline by `memory-api`'s `/api/v1/hydrate` endpoint.
- [x] T008 [P] Create `Dockerfile` for `services/knowledge-ingestion/` using `python:3.11-slim`; `uv sync --frozen`; CMD runs Temporal worker
- [x] T009 [P] Create `Dockerfile` for `services/connector-registry/` using `golang:1.22-alpine` multi-stage build; final stage `gcr.io/distroless/static`; expose port 8082
- [x] T010 [P] Create `pyproject.toml` + `uv.lock` stub for `packages/memrag-shared/`; include Python AWS runtime deps required by shared config loaders (`boto3`, `botocore`); create `packages/memrag-shared/src/memrag_shared/__init__.py`
- [x] T011 [P] Create `.env.example` with all required variables: `ENVIRONMENT`, `WORKSPACE_ID`, `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `GITHUB_TOKEN`, `CONFLUENCE_BASE_URL`, `TEMPORAL_HOST`, `QDRANT_HOST`, `REDIS_URL`, `OLLAMA_HOST`, `OLLAMA_DEVICE`, `AWS_REGION`, credentials/session token, AppConfig IDs, Secrets Manager prefixes, and S3/Iceberg settings

**Checkpoint**: `docker compose build` succeeds for all services; `docker compose up -d qdrant postgres redis` starts and passes health checks.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared library, DB migrations, Qdrant collection init, Redis utils, and Ollama
connectivity validation. ALL user story phases depend on this phase being complete.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T012 Create `packages/memrag-shared/src/memrag_shared/manifest.py`: `AgentManifest` dataclass with fields `agent_id`, `workspace_id`, `domain` (`code|ops|policy|data|None`), `knowledge_top_k` (default 8), `context_token_budget`, `promote_to_shared` (bool), `knowledge_source_filter`, `agent_tags`
- [x] T013 [P] Create `packages/memrag-shared/src/memrag_shared/weights.py`: reads 6×4 domain weight matrix from `WEIGHTS_CONFIG_SOURCE` env var (supports `aws-appconfig` or `env-file`); if `aws-appconfig`: fetches from AWS AppConfig application/environment/configuration profile using `boto3`/`botocore`; if `env-file`: reads from `.weights.json` or `$WEIGHTS_FILE` path; falls back to defaults from FR-026; `get_weight(source_type, domain) -> float` helper that queries the loaded config (returns 1.0 when domain is None); includes reload mechanism for AppConfig using deployment token/version polling
- [x] T014 [P] Create `packages/memrag-shared/src/memrag_shared/layers.py`: constants `LAYER_SESSION=1`, `LAYER_AGENT=2`, `LAYER_SHARED=3`, `LAYER_ORG=4`; `MemoryChunk` and `KnowledgeChunk` dataclasses matching `contracts/context_hydration.md`
- [x] T015 Create `services/connector-registry/migrations/` with Goose SQL files for all 5 PostgreSQL tables: `001_knowledge_connectors.sql`, `002_knowledge_sync_state.sql`, `003_knowledge_sharing_grants.sql`, `004_pii_audit_log.sql`, `005_workflow_executions.sql` — exact DDL from `data-model.md`
- [x] T016 Create `services/connector-registry/cmd/migrate/main.go`: runs Goose migrations on startup via `connector-registry` Compose service `command`; reads `DATABASE_URL` from env; initialises shared AWS SDK config (`aws-sdk-go-v2/config`) so later subcommands can reuse region/credential resolution consistently
- [x] T017 [P] Create `packages/memrag-shared/src/memrag_shared/infra/qdrant_client.py`: thin wrapper around `qdrant-client`; reads `QDRANT_HOST` from env; exposes `get_client() -> QdrantClient`. (Originally placed in `services/agent-workers/`; moved to `memrag-shared` so both `memory-api` and `knowledge-ingestion` share the same client.)
- [x] T018 Create `services/knowledge-ingestion/src/infra/qdrant_init.py`: script that creates (idempotently) all three Qdrant collections (`agent_memories`, `shared_memories`, `org_knowledge`) with named vectors `dense` (768-dim cosine) and `sparse` (BM25 sparse index) and required payload indexes per `data-model.md`; run as Compose service `command` before worker start
- [x] T019 [P] Create `packages/memrag-shared/src/memrag_shared/infra/redis_client.py`: Redis connection factory reading `REDIS_URL`; `session_key(workspace_id, session_id, field) -> str` helper returning correct key pattern from `data-model.md`; `grants_key(workspace_id) -> str`. (Originally in `services/agent-workers/`; moved to `memrag-shared`.)
- [x] T020 [P] Create `packages/memrag-shared/src/memrag_shared/infra/ollama_client.py`: thin async HTTP client reading `OLLAMA_HOST`; `embed(texts: list[str]) -> list[list[float]]` (calls `POST /api/embeddings`, model `qwen3-embedding:4b`); `complete(messages: list[dict]) -> str` (calls `POST /api/chat`, model `gemma4:12b`); validates `OLLAMA_HOST` is reachable on service startup with a `GET /api/version` health probe. (Note: MEMRAG itself does not call `complete()` for LLM inference — that is the consuming agent's responsibility. `complete()` is included for test utilities and future LLM-powered fact extraction paths only.)
- [x] ~~T021 [P] Create `services/agent-workers/src/infra/temporal_client.py`~~ — **REMOVED**: No Temporal worker for `agent-workers`; client factory for the agent-workers task queue is not needed.
- [x] T022 [P] Create `services/knowledge-ingestion/src/infra/temporal_client.py`: same pattern as T021 but task queue `"ingestion-workers"`; also creates `services/knowledge-ingestion/src/infra/ollama_client.py` (same thin Ollama client as T020)
- [x] T023 Create `services/connector-registry/internal/db/`: `go.mod` (module `memrag/connector-registry`); `sqlc.yaml` config; hand-write or sqlc-generate typed queries for `knowledge_connectors` CRUD and `knowledge_sharing_grants` CRUD matching `contracts/connector_management_api.md`; add `internal/aws/` helpers backed by `aws-sdk-go-v2` for Secrets Manager credential resolution and optional AppConfig-backed connector defaults
- [x] T024 [P] Create `services/knowledge-ingestion/src/infra/iceberg_client.py`: PyIceberg `load_catalog()` pointing at MinIO (`s3://memrag-archive/`) in local dev and AWS S3 in production; wire `boto3`/`botocore` session setup from env (`AWS_REGION`, credentials/session token, optional custom endpoint); `get_tombstone_table() -> Table`; creates table if absent using `data-model.md` schema (partitioned by `workspace_id, days(tombstoned_at)`)

**Checkpoint**: `docker compose up -d` starts all infra services healthy; migrations run; Qdrant collections exist; Ollama responds to `GET $OLLAMA_HOST/api/version` from inside each application container.

---

## Phase 3: US1 — Agent Session Memory with Durable Short-Term Buffer (Priority: P1) 🎯 MVP

**Goal**: The `memory-api` service exposes `POST /api/v1/session/{id}/turns` and `GET /api/v1/session/{id}/turns` endpoints backed by Redis. Any HTTP client (any language, any agent framework) can checkpoint conversation turns and retrieve the full session on restart — no Temporal dependency for session memory.

**Independent Test**:
```bash
docker compose up -d redis memory-api
# Checkpoint 12 turns, restart memory-api, verify all turns retrievable
curl -X POST http://localhost:8083/api/v1/session/sess-001/turns ...
docker compose restart memory-api
curl http://localhost:8083/api/v1/session/sess-001/turns  # → all 12 turns
docker compose exec memory-api pytest tests/integration/test_session_buffer.py -v
```

- [x] T025 [US1] Create `packages/memrag-shared/src/memrag_shared/session/session.py`: `fetch_recent_session(workspace_id, session_id, redis) -> list[Turn]` — reads `{workspace_id}:session:{session_id}:messages` from Redis; returns empty list on miss; sets 24h TTL on key read. Implement `GET /api/v1/session/{id}/turns` endpoint in `memory-api` that calls this function, accepting `X-Workspace-ID` or legacy alias `X-Tenant-ID`, and also accepting `X-Agent-ID` for correlation/audit parity.
- [x] T026 [US1] Append `checkpoint_session(workspace_id, session_id, turns: list[Turn], redis)` to `packages/memrag-shared/src/memrag_shared/session/session.py`: serialises turns to JSON, writes to Redis key, refreshes 24h TTL; if payload > 256KB, stores bytes at `{workspace_id}:session:{session_id}:payload:{idx}` and records pointer list in messages key; on retrieval, fetches by pointer and reconstructs full context. Implement `POST /api/v1/session/{id}/turns` endpoint in `memory-api` that calls this function, accepting `X-Workspace-ID` or legacy alias `X-Tenant-ID`, and also accepting `X-Agent-ID` for correlation/audit parity.
- [x] ~~T027 [US1] Create `AgentWorkflow` Temporal workflow~~ — **REMOVED**: `AgentWorkflow` does not exist in MEMRAG. MEMRAG is a memory platform; external agents call `memory-api` REST or MCP endpoints for memory operations and manage their own execution loops.
- [x] ~~T028 [US1] `services/agent-workers/src/worker.py`~~ — **REMOVED**: No Temporal worker for agent-workers; the service is eliminated. `knowledge-ingestion` remains the only service with a Temporal worker.
- [x] T029 [US1] Create `services/memory-api/tests/integration/test_session_buffer.py`: calls `POST /api/v1/session/{id}/turns` with 12 turns including one 500KB payload (stored by pointer); calls `GET /api/v1/session/{id}/turns`; asserts all 12 turns returned with external payloads fetched by pointer; asserts Redis key TTL ≥ 23h; tests `X-Workspace-ID` isolation (workspace B sees empty list for workspace A's session); tests `X-Tenant-ID` as a legacy alias for `X-Workspace-ID`; passes `X-Agent-ID` on both requests.
- [x] T030 [US1] Create `packages/memrag-shared/tests/unit/test_session_keys.py`: asserts `session_key()` and `grants_key()` return exact key patterns from `data-model.md` Redis Key Schema section

**Checkpoint**: `docker compose exec memory-api pytest tests/integration/test_session_buffer.py` passes. `GET /api/v1/session/{id}/turns` and `POST /api/v1/session/{id}/turns` functional; any HTTP client can checkpoint and retrieve session context.

---

## Phase 4: US2 — Agent Builds and Recalls Long-Term Memory Across Sessions (Priority: P1)

**Goal**: Agent findings are extracted to atomic facts via Mem0, stored in Qdrant `agent_memories` with deduplication via `POST /api/v1/memories`. Future calls recall top-K via hybrid search through `POST /api/v1/memories/search`. Nightly cron decays stale entries (kept in `knowledge-ingestion` Temporal worker). All L2 operations are direct library calls from `memory-api` — no Temporal intermediary.

**Independent Test**:
```bash
docker compose up -d qdrant memory-api ollama redis
docker compose exec memory-api pytest tests/integration/test_long_term_memory.py -v
```

- [x] T031 [US2] Create `packages/memrag-shared/src/memrag_shared/memory/mem0_client.py`: wraps `mem0ai.Memory` SDK; `extract_and_store(agent_id, workspace_id, text) -> list[str]` (fact IDs); `ENVIRONMENT=test` disables LLM extraction and stores raw text for deterministic tests; reads Qdrant host from env. Called by `memory-api`'s `POST /api/v1/memories` handler.
- [x] T033 [US2] Create `packages/memrag-shared/src/memrag_shared/recall/layer2.py`: `recall_agent_memory(workspace_id, agent_id, query_text, top_k=8) -> list[MemoryChunk]`; embeds query via `ollama_client.embed()` (calls Ollama `qwen3-embedding:4b` directly); queries Qdrant `agent_memories` with named-vector hybrid search (`dense` + `sparse` BM25, fused via Qdrant `prefetch` + `query` RRF); filters on `workspace_id`, `agent_id`, `tombstoned=false`. Called by `memory-api`'s `POST /api/v1/memories/search` handler.
- [x] T034 [US2] Create `packages/memrag-shared/src/memrag_shared/memory/dedup.py`: `is_near_duplicate(new_embedding, workspace_id, agent_id, threshold=0.95) -> bool`; runs a nearest-neighbour query against `agent_memories`; returns True if any result has cosine similarity ≥ 0.95; called by `extract_and_store` before Qdrant upsert.
- [x] T035 [US2] Implement async `POST /api/v1/memories` handler in `memory-api`: validates `X-Workspace-ID` or legacy alias `X-Tenant-ID`, plus `X-Agent-ID`; calls `memrag-shared` `extract_and_store(workspace_id, agent_id, content)`; adds `last_accessed_at` update on every successful recall hit; returns `200 OK` with `{"stored": true}` or `{"stored": false, "reason": "duplicate"}` for near-duplicate inputs. The handler is async and safe for non-blocking use by consuming agent runtimes; no Temporal intermediary is introduced.
- [x] ~~T036 [US2] Update `AgentWorkflow`~~ — **REMOVED**: `AgentWorkflow` does not exist in MEMRAG. External agents call `POST /api/v1/memories` to store and `POST /api/v1/memories/search` to recall via `memory-api`. No Temporal intermediary.
- [x] T037 [US2] Create `services/knowledge-ingestion/src/workflows/decay_memories.py`: `DecayMemoriesWorkflow` Temporal cron workflow (schedule `"0 2 * * *"`); activity `decay_and_archive(workspace_id)` — scroll `agent_memories` by batch; recompute `decay_score` (linear: `score * exp(-days_inactive / half_life)`, half_life=90 for episodic, 365 for semantic); bulk-update payload; for `decay_score < 0.1`: write row to S3 Iceberg tombstone table, delete point from Qdrant
- [x] T038 [US2] Register `DecayMemoriesWorkflow` in `services/knowledge-ingestion/src/worker.py`; add cron schedule on worker startup
- [x] T039 [US2] Create `services/memory-api/tests/integration/test_long_term_memory.py`: calls `POST /api/v1/memories` with output text; calls `POST /api/v1/memories/search` with semantically similar query; asserts response `list[str]` includes fact from first call; calls `POST /api/v1/memories` again with identical content; asserts Qdrant point count unchanged (dedup enforced); asserts decay workflow (run separately in knowledge-ingestion) sets score < 0.1 on artificially aged entries.

**Checkpoint**: `docker compose exec memory-api pytest tests/integration/test_long_term_memory.py` passes. `POST /api/v1/memories` and `POST /api/v1/memories/search` functional; L2 store+recall works independently of sharing or BYOD.

---

## Phase 5: US3 — Agent Promotes Findings to Shared Workspace Memory (Priority: P2)

**Goal**: `POST /api/v1/shared` (promote) and `POST /api/v1/shared/search` (recall) endpoints in `memory-api` back the workspace-shared `shared_memories` Qdrant collection. Promotion is also exposed as the MCP `promote_finding` tool. Cross-workspace isolation enforced at query time.

**Independent Test**:
```bash
docker compose up -d qdrant memory-api ollama redis
docker compose exec memory-api pytest tests/integration/test_shared_memory.py -v
```

- [x] T040 [US3] Create `packages/memrag-shared/src/memrag_shared/recall/layer3.py`: `recall_shared_memory(workspace_id, query_text, top_k=8) -> list[MemoryChunk]`; hybrid Qdrant search against `shared_memories`; filters strictly on `workspace_id`; same dense+sparse RRF pattern as Layer 2. Called by `memory-api`'s `POST /api/v1/shared/search` handler.
- [x] T041 [US3] Create `packages/memrag-shared/src/memrag_shared/memory/shared.py`: `promote_to_shared(workspace_id, source_agent_id, text, embedding)` — upserts point to `shared_memories` with `workspace_id`, `source_agent_id`, `promoted_at`, `content_hash`; checks dedup (0.95 threshold) against existing `shared_memories` before upsert. Called by `memory-api`'s `POST /api/v1/shared` handler.
- [x] T042 [US3] Implement async `POST /api/v1/shared` handler in `memory-api`: validates `X-Workspace-ID` or legacy alias `X-Tenant-ID`, plus `X-Agent-ID`; calls `memrag-shared` `promote_to_shared(workspace_id, agent_id, text, embedding)`; returns `{"status": "stored" | "duplicate"}`. Also expose `promote_finding` as an MCP tool via the `/mcp` endpoint so LLM agents can call it directly.
- [x] ~~T043 [US3] Update `AgentWorkflow`~~ — **REMOVED**: `AgentWorkflow` does not exist in MEMRAG. Agents call `POST /api/v1/shared` directly (HTTP) or use the MCP `promote_finding` tool. Auto-promotion on manifest flag is an agent-side responsibility managed by the calling agent framework.
- [x] T044 [US3] Create `services/memory-api/tests/integration/test_shared_memory.py`: calls `POST /api/v1/shared` with `X-Workspace-ID: ws-A`, `X-Agent-ID`, and finding containing "canary-finding-XYZ"; calls `POST /api/v1/shared/search` with `X-Workspace-ID: ws-A` and that keyword; asserts response includes finding with `source_type="shared_memory"`; calls `POST /api/v1/shared/search` with `X-Tenant-ID: ws-B`; asserts response is empty (cross-workspace isolation, alias path included).

**Checkpoint**: `docker compose exec memory-api pytest tests/integration/test_shared_memory.py` passes. `POST /api/v1/shared` and `POST /api/v1/shared/search` functional; cross-agent sharing works; cross-workspace isolation holds.

---

## Phase 6: US8 + US9 — Graphiti Foundation & Enterprise Compatibility API (Priority: P3)

**Goal**: Optional Neo4j/Graphiti services for Layer 3 KG-backed recall, Graphiti-backed shared-memory adapters, and the `memory-api` foundation for the unified HTTP+MCP surface. Phase 6 owns Compose/profile wiring, Graphiti promotion plumbing, manifest updates, and non-hydration compatibility routes. Full `/api/v1/hydrate` delivery remains in Phase 10.

**Independent Test**:
```bash
docker compose --profile graphiti up -d neo4j graphiti-server graphiti-mcp memory-api qdrant redis
docker compose ps neo4j graphiti-server graphiti-mcp memory-api
curl http://localhost:8083/healthz
# Verify all 4-layer routes and MCP endpoint registered
curl http://localhost:8083/api/v1/session/test-001/turns
```

- [x] T083 Add `graphiti-server`, `neo4j`, `graphiti-mcp` to `docker-compose.yml` under a `graphiti` Compose profile; pin `graphiti-server` to `zep/graphiti-server:0.3`, `graphiti-mcp` to `zep/graphiti-mcp:0.3`, `neo4j` to `neo4j:5.20`; add named volume `neo4j_data`; configure `graphiti-server` with `OPENAI_BASE_URL=http://ollama:11434` and `OPENAI_MODEL=gemma4:12b` (routes LLM extraction through the existing Ollama service using the default chat model); add `GRAPHITI_ENABLED`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `GRAPHITI_SERVER_URL` env vars to `memory-api`; `GRAPHITI_ENABLED` defaults to `false`. Note: stale `agent-workers` ownership was removed; no `agent-workers` service exists in the target architecture.
- [ ] T084 `[P]` Expand `services/memory-api/` to be the all-layer HTTP+MCP service:
  **Layer 1** (session): `GET /api/v1/session/{id}/turns`, `POST /api/v1/session/{id}/turns` — calls `memrag-shared/session/session.py`;
  **Layer 2** (agent memory): `POST /api/v1/memories` (store), `POST /api/v1/memories/search` (recall) — calls `memrag-shared/memory/mem0_client.py` and `memrag-shared/recall/layer2.py`;
  **Layer 3** (shared): `POST /api/v1/shared` (promote), `POST /api/v1/shared/search` (recall) — calls `memrag-shared/memory/shared.py` and `memrag-shared/recall/layer3.py`;
  **Layer 4** (org knowledge): `POST /api/v1/knowledge/search` (recall), `POST /api/v1/ingest` (trigger BYOD via Temporal `IngestionWorkflow` signal);
  **Assembly**: `POST /api/v1/hydrate` — `asyncio.gather(L1–L4)` → `memrag-shared/assembler.py` → `HydrateResponse`;
  **MCP endpoint**: `GET|POST /mcp` — JSON-RPC over HTTP+SSE (MCP 2025-06-18 spec) using `fastmcp`; exposes `recall_memory`, `store_memory`, `promote_finding`, `search_knowledge` as MCP tools;
  All stateful endpoints accept `X-Workspace-ID` and `X-Agent-ID` headers, and MUST accept `X-Tenant-ID` as a legacy alias for `X-Workspace-ID`; `/memories/search` response is `list[str]` for enterprise `activities_memory.py` compatibility.
- [x] T085 Create `packages/memrag-shared/src/memrag_shared/memory/graphiti.py`: plain async function `store_with_graphiti(workspace_id, finding_text, episode_metadata)` (no Temporal `@activity.defn` decorator) — when `GRAPHITI_ENABLED=true`, POSTs to `graphiti-server:8100/episodes` (`add_episode` API) with `group_id=workspace_id`; when `GRAPHITI_ENABLED=false`, falls through to Qdrant `shared_memories` upsert; single `if os.getenv("GRAPHITI_ENABLED") == "true":` gate at function entry. Called by `memory-api`'s `POST /api/v1/shared` handler.
- [ ] T086 `[P]` Create `packages/memrag-shared/src/memrag_shared/recall/layer3_graphiti.py`: `recall_shared_graphiti(workspace_id, query_text, top_k=8) -> list[MemoryChunk]`; calls `GET graphiti-server:8100/search/facts?group_id={workspace_id}&query={query_text}&limit={top_k}`; maps Graphiti `FactResult` objects to `MemoryChunk` (layer=LAYER_SHARED, source=`"graphiti"`); only called when `GRAPHITI_ENABLED=true`; existing `layer3.py` Qdrant path is unmodified. Marked not done until ownership is implemented under `memrag-shared` rather than the removed `agent-workers` service.
- [x] T088 `[P]` Update `packages/memrag-shared/src/memrag_shared/manifest.py`: add optional `mcp_servers: list[str] = field(default_factory=list)` field to `AgentManifest`; this field is used by consuming agent frameworks (not by MEMRAG internally) to configure which external MCP servers an agent should connect to alongside MEMRAG's own `/mcp` endpoint; add `GRAPHITI_MCP_SERVER_URL` and `MEMORY_API_MCP_URL` env vars to `.env.example`; document that MEMRAG itself IS an MCP server via `memory-api`'s `/mcp` endpoint, and that `graphiti-mcp` can be registered separately in an external `mcp-registry`; MEMRAG does not introduce a local `mcp-registry` service.

**Checkpoint**: `docker compose --profile graphiti up -d neo4j graphiti-server graphiti-mcp memory-api qdrant redis` starts all services successfully. `GET /healthz` → `{"status":"ok"}`; Graphiti profile wiring, Graphiti env configuration, and the non-hydration `memory-api` compatibility surface are reachable. Full `/api/v1/hydrate` delivery remains tracked in Phase 10. `GRAPHITI_ENABLED=false` preserves the pre-Graphiti Layer 3 Qdrant-backed behavior.

---

## Phase 7: US4 — Workspace Admin Connects an External Knowledge Source (Priority: P2)

**Goal**: Full BYOD pipeline: connector-registry CRUD API, four connectors (GitHub/Confluence/Slack/RDS), content-type-aware chunker, embedder, `IngestionWorkflow` with full/delta sync, idempotent content-hash dedup, local mock services for GitHub and Confluence.

**Independent Test**:
```bash
docker compose -f docker-compose.test.yml up -d connector-registry knowledge-ingestion qdrant temporal ollama github-api-mock confluence-api-mock
docker compose exec knowledge-ingestion pytest tests/integration/test_byod_pipeline.py -v
```

- [x] T045 [US4] Create `services/connector-registry/internal/api/server.go`: chi router; register handlers for `POST /v1/connectors`, `GET /v1/connectors`, `GET /v1/connectors/{id}`, `PATCH /v1/connectors/{id}`, `DELETE /v1/connectors/{id}`, `GET /v1/connectors/{id}/status`; POST request schema includes `contains_pii` boolean field (default: false); reads `X-Workspace-ID` header for all requests
- [x] T046 [P] [US4] Create `services/connector-registry/internal/api/handlers_connector.go`: implement all five connector CRUD handlers using sqlc-generated DB queries from T023; validate POST request schema includes `contains_pii` field; `POST` sets `sync_status="pending"` and enqueues `IngestionWorkflow` via Temporal client; `DELETE` enqueues Qdrant background cleanup task
- [x] T047 [P] [US4] Create `services/connector-registry/internal/temporal/client.go`: Temporal Go client factory; accepts `contains_pii` boolean from connector config when enqueueing `IngestionWorkflow`; resolves connector credential references through `aws-sdk-go-v2/service/secretsmanager` in production (local secret mock in dev/test); `SignalWorkflow(runID, signalName, payload)` helper for HITL endpoint (T064); `StartIngestionWorkflow(connectorID, workspaceID, containsPII)` helper
- [x] T048 [US4] Create `services/knowledge-ingestion/src/connectors/base.py`: `BaseConnector` abstract class with `authenticate()`, `list_resources() -> list[Resource]`, `fetch_resource(resource_id) -> bytes` abstract methods; `Resource` dataclass with `id`, `url`, `title`, `last_modified`
- [x] T049 [P] [US4] Create `services/knowledge-ingestion/src/connectors/github.py`: `GitHubConnector(BaseConnector)` — reads `GITHUB_TOKEN` (or `GITHUB_API_BASE_URL` for mock); `list_resources`: GitHub Trees API for configured repo+branch+extensions; `fetch_resource`: Contents API; respects `ENVIRONMENT=test` by pointing at `github-api-mock:8085`
- [x] T050 [P] [US4] Create `services/knowledge-ingestion/src/connectors/confluence.py`: `ConfluenceConnector(BaseConnector)` — OAuth 2.0 3-LO token exchange via `CONFLUENCE_BASE_URL`; `list_resources`: CQL search `space IN (...)` with `lastModified > {last_sync}`; `fetch_resource`: page content endpoint; respects `ENVIRONMENT=test` by pointing at `confluence-api-mock:8084`
- [x] T051 [P] [US4] Create `services/knowledge-ingestion/src/connectors/slack.py`: `SlackConnector(BaseConnector)` — `list_resources`: conversations.history for configured channels; hard-filter: `message.ts < (now - 7 days)`; never fetches messages < 7 days old (FR-015, A-009)
- [x] T052 [P] [US4] Create `services/knowledge-ingestion/src/connectors/rds_schema.py`: `RDSSchemaConnector(BaseConnector)` — resolves connection metadata from connector config and AWS Secrets Manager reference; supports standard PostgreSQL credentials and optional AWS RDS IAM auth token generation via `boto3`; connects via `psycopg2`; `list_resources`: queries `information_schema.tables`; `fetch_resource`: fetches columns, data types, column comments, foreign keys for one table; NEVER queries row data
- [x] T053 [US4] Create `services/knowledge-ingestion/src/chunker.py`: `chunk(text, source_type, content_type) -> list[str]`; code files → tree-sitter AST chunking at function/class boundaries; prose → chonkie semantic chunking with overlap; RDS schema → one chunk per table template (table name + column defs + FK summary)
- [x] T054 [US4] Create `services/knowledge-ingestion/src/embedder.py`: `embed_batch(texts: list[str]) -> list[list[float]]`; calls Ollama `qwen3-embedding:4b` directly via `ollama_client.embed()` (no intermediate gateway); returns list of 768-dim float32 vectors; also `embed_sparse(texts) -> list[dict]` using BM25 tokenisation for sparse vector weights
- [x] T055 [US4] Create `services/knowledge-ingestion/src/workflows/ingestion.py`: `IngestionWorkflow` Temporal workflow; activities: `fetch_resources(connector_id)` → `diff_resources(connector_id, resources)` (content-hash comparison vs `knowledge_sync_state`) → for each changed: `chunk_and_embed(resource)` → `pii_screen(chunks)` → `upsert_org_knowledge(connector_id, chunks)` → `update_sync_state(connector_id, resource_id, content_hash)`; supports `full_sync` and `delta_sync` modes
- [x] T056 [US4] Create `services/knowledge-ingestion/src/activities/sync_state.py`: `diff_resources` — queries `knowledge_sync_state` table via PostgreSQL; returns only resources where `content_hash != stored_hash` or resource is new; `update_sync_state` — upserts `(connector_id, resource_id, content_hash)` after successful ingestion
- [x] T057 [US4] Create `services/knowledge-ingestion/src/activities/upsert.py`: `upsert_org_knowledge(connector_id, chunks_with_embeddings, connector_config)` — upserts Qdrant `org_knowledge` points with full payload from `data-model.md` (workspace_id, source_type, sharing_scope, agent_scope, etc.); uses `content_hash` as deterministic point ID for idempotency
- [x] T058 [US4] Create `tests/mocks/github-api-mock/`: FastAPI app implementing GitHub REST Trees API (`GET /repos/{owner}/{repo}/git/trees/{sha}?recursive=1`) and Contents API (`GET /repos/{owner}/{repo}/contents/{path}`); returns synthetic repo fixture with 10 Python files; push webhook simulator endpoint; Dockerfile in same directory
- [x] T059 [US4] Create `tests/mocks/confluence-api-mock/`: FastAPI app implementing: OAuth 2.0 authorization endpoint (`GET /oauth/authorize`), token exchange (`POST /oauth/token`), token refresh (`POST /oauth/token` with `grant_type=refresh_token`), CQL search (`GET /rest/api/content/search?cql=...`), page content (`GET /rest/api/content/{id}?expand=body.storage`); returns 5 synthetic pages; implements full 3-LO flow per A-018 and FR-031; Dockerfile in same directory
- [x] T060 [US4] Create `services/knowledge-ingestion/tests/integration/test_byod_pipeline.py`: creates GitHub connector in ENVIRONMENT=test pointing at github-api-mock; triggers IngestionWorkflow; polls until `sync_status=ok`; asserts ≥10 Qdrant points in `org_knowledge` with correct `workspace_id` and `connector_id`; triggers delta sync with no changes; asserts no new points added (idempotency via content-hash). Does same for confluence and rds via mocks.

**Checkpoint**: ✅ COMPLETE
- `docker compose exec knowledge-ingestion pytest tests/integration/test_byod_pipeline.py -v` → **8/8 PASSING** (added `test_ingestion_activity_chain_full_then_delta`)
- `docker compose exec knowledge-ingestion pytest tests/integration/test_connectors_e2e.py -v` → **11/11 PASSING**
- `docker compose exec knowledge-ingestion pytest tests/integration/test_mocks_integration.py -v` → **12/12 PASSING** (GitHub mock: 4 tests, Confluence mock: 4 tests, Core imports: 4 tests)
- **Total Phase 7: 31/31 tests passing, 0 failures, no import errors**
- Full BYOD pipeline end-to-end: connector → ingest → chunk → embed → upsert → verify
- All four connectors (GitHub, Confluence, Slack, RDS) instantiate and authenticate
- Mock services (GitHub, Confluence) fully functional with FastAPI TestClient
- Deterministic content-hash deduplication tested and working
- **Activity chain E2E**: all 6 ingestion activities called in sequence with in-memory fakes; full sync (5 files → ≥5 Qdrant points, 5 sync-state entries) + delta sync (0 new points) validated
- Idempotency verified: delta sync with no changes produces identical results

---

## Phase 8: US5 — PII Detection and Handling (Priority: P2)

**Goal**: Presidio screens every chunk before Qdrant upsert. Hard rules for CREDIT_CARD/BANK_ACCOUNT (redact) and PASSWORD/SECRET (drop chunk) are non-overridable. All other categories use configurable actions. `pii_audit_log` records events with no raw values. `pii_detected_mismatch` halts workflow and awaits HITL signal. Connector-registry exposes `PATCH /connectors/{id}/pii-review`.

**Independent Test**:
```bash
docker compose up -d knowledge-ingestion qdrant postgres
docker compose exec knowledge-ingestion pytest tests/integration/test_pii_pipeline.py -v
```

- [x] T061 [US5] Create `services/knowledge-ingestion/src/pii.py`: `PIIScanner` class; initialises `presidio_analyzer.AnalyzerEngine` with all 12 entity recognisers; `scan(chunk_text, pii_config) -> PIIResult`; pii_config specifies per-entity category actions (mask, redact, drop) fetched from env vars or AppConfig (e.g., `PII_EMAIL_ACTION`, `PII_PHONE_ACTION`); apply hard rules first (CREDIT_CARD/BANK_ACCOUNT → redact; PASSWORD/SECRET → drop) override any config; apply configurable actions for remaining entities; return sanitised text or DROP sentinel; never log raw detected values
- [x] T062 [US5] Create `services/knowledge-ingestion/src/activities/pii_screen.py`: `pii_screen(chunks, connector_id, workspace_id, pii_config) -> list[Chunk]`; calls `PIIScanner.scan` per chunk; writes `pii_audit_log` row to PostgreSQL for each detection event (entity_category, action_taken, chunk_index, connector_id — no raw PII); returns filtered chunk list (dropped chunks excluded); if `contains_pii=False` and any detection occurs: raise `PIIDetectedMismatchError` with connector_id
- [x] T063 [US5] Update `IngestionWorkflow` in `services/knowledge-ingestion/src/workflows/ingestion.py` to call `pii_screen` after chunking; catch `PIIDetectedMismatchError`: set connector `sync_status=pii_detected_mismatch` via connector-registry API; emit Temporal `pii_halt` signal; `await workflow.wait_condition(lambda: self.hitl_response is not None)`; if `hitl_response.action="abort"` → raise; if `"approve"` → resume ingestion pipeline with `contains_pii` treated as `True` for this sync
- [x] T064 [US5] Add `PATCH /v1/connectors/{id}/pii-review` handler in `services/connector-registry/internal/api/handlers_connector.go`: validates `action` field (`approve|abort`); returns `409` if connector not in `pii_detected_mismatch` state; sends Temporal `hitl_response` signal to the waiting `IngestionWorkflow` run via T047 client; updates `sync_status` accordingly
- [x] T065 [US5] Create `services/knowledge-ingestion/tests/integration/test_pii_pipeline.py`: feeds synthetic chunks containing EMAIL, CREDIT_CARD, PASSWORD, PHONE through `pii_screen`; asserts: EMAIL → `[EMAIL]` token; CREDIT_CARD → block chars; PASSWORD chunk absent from output; `pii_audit_log` has 3 rows with no raw values; Qdrant `org_knowledge` contains 0 raw PII in stored payloads; tests HITL halt: creates connector with `contains_pii=False`, triggers ingestion with PII-bearing content, asserts `sync_status=pii_detected_mismatch`, sends approve signal, asserts ingestion resumes

**Checkpoint**: `docker compose exec knowledge-ingestion pytest tests/integration/test_pii_pipeline.py` passes. US5 functional: zero raw PII in index or audit log; hard rules apply; HITL halt and resume helper path work.

---

## Phase 9: US6 — Knowledge Access Control (Priority: P3)

**Goal**: Sharing scope (`private`, `workspace_internal`, `allowlist`, `platform_public`) enforced at Qdrant query time via payload filters. Grants cached in Redis with 60s passive TTL. Agent-scoped access via `agent_scope` payload filter. Scope changes take effect within ≤60 seconds.

**Independent Test**:
```bash
docker compose up -d connector-registry qdrant memory-api redis postgres
docker compose exec memory-api pytest tests/integration/test_access_control.py -v
```

- [x] T066 [US6] Create `packages/memrag-shared/src/memrag_shared/recall/layer4.py`: `recall_org_knowledge(workspace_id, agent_id, agent_tags, query_text, top_k=8, grants_cache=None) -> list[KnowledgeChunk]`; loads grants from Redis `grants:{workspace_id}` (60s TTL, miss → query PostgreSQL `knowledge_sharing_grants` and populate cache); builds Qdrant payload filter: `sharing_scope IN (workspace_internal, platform_public) OR (sharing_scope=allowlist AND connector_id IN allowed_connector_ids) OR (sharing_scope=private AND workspace_id=this_workspace)`; adds `agent_scope` filter when `agent_scope=by_id/by_tag`; hybrid search on `org_knowledge`. Called by `memory-api`'s `POST /api/v1/knowledge/search` handler.
- [x] T067 [US6] Create `packages/memrag-shared/src/memrag_shared/recall/grants.py`: `load_grants(workspace_id, redis_client, pg_conn) -> list[Grant]`; checks Redis `grants:{workspace_id}` first; on miss fetches `knowledge_sharing_grants WHERE grantee_workspace_id=? AND status='active'` from PostgreSQL; writes to Redis with 60s TTL; `Grant` dataclass with `connector_id`, `grantee_workspace_id`. Called by `recall_org_knowledge` in `layer4.py`.
- [x] T068 [US6] Add sharing-grants sub-resource handlers in `services/connector-registry/internal/api/handlers_grants.go`: `POST /v1/connectors/{id}/grants` — inserts `knowledge_sharing_grants` row with `status=active`; `DELETE /v1/connectors/{id}/grants/{grant_id}` — sets `status=revoked`; neither endpoint invalidates Redis cache (passive TTL expiry is the sole invalidation mechanism per FR-024)
- [x] T069 [US6] Create `services/memory-api/tests/integration/test_access_control.py`: creates two workspace contexts A and B; seeds `org_knowledge` point with `sharing_scope=private` for workspace A; calls `POST /api/v1/knowledge/search` with `X-Workspace-ID: ws-B` (and alias path `X-Tenant-ID: ws-B` in a companion assertion); asserts 0 results; creates grant A→B in PostgreSQL; waits 1s (TTL mock set to 1s in test env); calls `POST /api/v1/knowledge/search` again with ws-B; asserts chunk returned; revokes grant; waits 1s; asserts 0 again; tests `agent_scope=by_tag`: asserts agent with matching tag gets results, agent without tag gets 0.

**Checkpoint**: `docker compose exec memory-api pytest tests/integration/test_access_control.py` passes. US6 functional: scope enforcement and grant lifecycle correct; passive TTL grant-cache behavior validated via `POST /api/v1/knowledge/search`.

**Security Boundary**: Revoked grants remain cached in Redis for up to 60 seconds after revocation; all subsequent workflows launched after cache expiry will respect the new scope. This is an accepted SLA tradeoff to avoid per-query database round-trips (see FR-024).

---

## Phase 10: US7 — Full Four-Layer Context Hydration (Priority: P3)

**Goal**: `memory-api`'s `POST /api/v1/hydrate` endpoint fans out L1–L4 recall in parallel using `asyncio.gather`, then calls `memrag-shared/assembler.py` for domain-weighted re-ranking and token-budget enforcement. Prometheus metrics exposed directly from `memory-api`. Single layer failure → graceful degradation with `failed_layers` in response.

**Independent Test**:
```bash
docker compose up -d redis qdrant memory-api ollama postgres
docker compose exec memory-api pytest tests/integration/test_context_hydration.py -v
```

- [ ] T070 [US7] Create `packages/memrag-shared/src/memrag_shared/assembler.py`: `assemble(request: HydrateRequest) -> HydrateResponse`; merges Layer 1 turns + Layer 2/3/4 chunks; applies `SOURCE_WEIGHT` matrix from `memrag-shared/weights.py`; sorts by `weighted_score` desc; allocates token budget (Layer 1 FIFO oldest-drop first if overflow; then scored chunks fill remainder; never partially include a chunk); appends citations block for KnowledgeChunks; returns `HydrateResponse` with `system_prompt`, `token_count`, `layer_stats`, `failed_layers`, `citations`. Called inline by `memory-api`'s `/api/v1/hydrate` handler.
- [ ] T071 [US7] Add `prometheus_client` histograms to `memory-api`: `context_hydration_assembly_ms` (labels: `workspace_id`, `domain`); `context_hydration_chunks_dropped_total` (labels: `workspace_id`, `layer`); `memory_recall_latency_seconds` per layer (labels: `layer`, `workspace_id`); expose via `GET /metrics` on `memory-api` port 8083; add `prometheus-client` to `services/memory-api/pyproject.toml`.
- [ ] T072 [US7] Add `POST /api/v1/hydrate` endpoint to `services/memory-api/src/main.py` (or `routes/hydrate.py`): accepts `HydrateRequest` JSON; uses `asyncio.gather` for parallel L1–L4 recall with per-layer error catching recording to `failed_layers`; calls `memrag-shared.assembler.assemble()`; records `context_hydration_assembly_ms` histogram observation; returns `HydrateResponse` JSON. Replaces the separate `context-hydrator` service entirely.
- [ ] T073 [US7] Implement the parallel recall fan-out inside `memory-api`'s `/api/v1/hydrate` handler using `asyncio.gather(*[recall_session(), recall_agent_memory(), recall_shared_memory(), recall_org_knowledge()])`, with per-coroutine exception catching; failed coroutines record their layer name to `failed_layers`; all successful results forwarded to `assembler.assemble()`. No Temporal parallel activities — plain Python async concurrency is sufficient.
- [ ] T074 [US7] Add `memory_recall_latency_seconds` Prometheus histogram (labels: `layer`, `workspace_id`) instrumentation in each `memrag-shared` recall module (`layer2.py`, `layer3.py`, `layer4.py`, `session.py`); each function measures its own wall time and records to the shared `prometheus-client` instance; histograms scraped from `memory-api`'s `/metrics` endpoint.
- [ ] T075 [US7] Create `services/memory-api/tests/integration/test_context_hydration.py`: seeds Layer 1 turns in Redis; seeds Layer 2 facts in `agent_memories` Qdrant; seeds Layer 3 finding in `shared_memories`; seeds Layer 4 chunk in `org_knowledge`; calls `POST /api/v1/hydrate`; asserts `HydrateResponse.system_prompt` contains content from all four layers; asserts `token_count` ≤ configured budget; asserts `citations` present for Layer 4 chunk; re-runs with Layer 3 Qdrant unreachable (mock partition); asserts response has `failed_layers=["layer3"]` and non-empty `system_prompt`.

**Checkpoint**: `docker compose exec memory-api pytest tests/integration/test_context_hydration.py` passes. `POST /api/v1/hydrate` functional: all four layers hydrate in parallel; budget enforced; one layer failure returns `failed_layers` without aborting the response.

---

## Phase 11: US8 + US9 — Graphiti Workflow Integration & Validation (Priority: P3)

**Goal**: Wire the optional Graphiti Layer 3 path into the `memory-api` request paths and
hydration fan-out, then validate both the Graphiti-backed knowledge graph path and the
enterprise compatibility API end to end.

**Independent Test**:
```bash
# Graphiti path
docker compose --profile graphiti up -d neo4j graphiti-server graphiti-mcp memory-api qdrant redis
docker compose exec memory-api pytest tests/integration/test_graphiti_kg.py -v

# Enterprise compat API + MCP endpoint
docker compose up -d memory-api qdrant redis
docker compose exec memory-api pytest tests/integration/test_enterprise_compat_api.py -v
```

- [ ] T087 Update `memory-api`'s `/api/v1/hydrate` L3 fan-out and `POST /api/v1/shared/search` handler: when `GRAPHITI_ENABLED=true`, call `recall_shared_graphiti` (from `memrag-shared/recall/layer3_graphiti.py`) in place of `recall_shared_memory` for the L3 slot in `asyncio.gather`; catch `recall_shared_graphiti` exceptions and add `"graphiti"` to `failed_layers`; when `GRAPHITI_ENABLED=false`, path is unchanged. No `AgentWorkflow` update needed — MEMRAG has no `AgentWorkflow`.
- [ ] T089 `[P]` Create `services/memory-api/tests/integration/test_graphiti_kg.py`: 5 tests — (1) `POST /api/v1/shared` with `GRAPHITI_ENABLED=true` creates a node+temporal edge in Neo4j via `add_episode`; (2) a contradicting finding updates the prior edge's `t_invalid` and creates a new active edge; (3) `POST /api/v1/shared/search` returns connected findings via graph traversal; (4) `GRAPHITI_ENABLED=false` uses Qdrant L3 path unchanged; (5) Graphiti server unreachable adds `"graphiti"` to `failed_layers` in `/api/v1/hydrate` response without aborting; uses a live `graphiti-server` + `neo4j` via `docker compose --profile graphiti`.
- [ ] T090 `[P]` Create `services/memory-api/tests/integration/test_enterprise_compat_api.py`: 6 tests — (1) `POST /api/v1/memories` stores a fact, `200 OK`; (2) duplicate POST returns `200 OK` without new entry (dedup enforced); (3) `POST /api/v1/memories/search` returns `list[str]` ≥ 1 result; (4) workspace isolation: search with workspace-B headers returns empty list; (5) `X-Tenant-ID` is accepted as a legacy alias for `X-Workspace-ID`; (6) `POST /mcp` with `tools/list` method returns JSON-RPC response listing `recall_memory`, `store_memory`, `promote_finding`, `search_knowledge`, and `POST /mcp` with `tools/call` for `store_memory` stores a fact that is subsequently retrievable via `POST /api/v1/memories/search`.
- [ ] T091 `[P]` Update `docker-compose.test.yml`: add `--profile graphiti` services (graphiti-server, neo4j, graphiti-mcp) for integration tests that require `GRAPHITI_ENABLED=true`; add `memory-api` to the default test stack; add `test_graphiti_kg.py` and `test_enterprise_compat_api.py` to the `app` service test runner command
- [ ] T092 `[P]` Update `quickstart.md`: add Graphiti section — how to start with `docker compose --profile graphiti up -d`; how to register the `graphiti-mcp` server in the external `mcp-registry` from enterprise-agentic-platform; how to verify Neo4j browser at `localhost:7474`; how to call the enterprise compat API with `curl`; add `GRAPHITI_ENABLED`, `NEO4J_URI`, `NEO4J_PASSWORD`, `GRAPHITI_SERVER_URL` to `.env.example`

**Checkpoint**: `docker compose --profile graphiti exec memory-api pytest tests/integration/test_graphiti_kg.py` passes. `docker compose exec memory-api pytest tests/integration/test_enterprise_compat_api.py` passes. `GRAPHITI_ENABLED=false` stack continues to pass all prior phase tests unchanged.

---

## Phase 12: Polish & Cross-Cutting Concerns

**Purpose**: Full integration test suite, Prometheus scrape config, `.env.example` completeness, and quickstart validation.

- [ ] T076 [P] Create `infra/prometheus/prometheus.yml` scrape config: targets for `memory-api:8083/metrics`, `knowledge-ingestion:8080/metrics`, `connector-registry:8082/metrics`; scrape interval 15s; add to `prometheus` Compose service as mounted volume. (`agent-workers` and `context-hydrator` are eliminated; all application memory metrics now scraped from `memory-api`.)
- [ ] T077 [P] Create `tests/e2e/test_independent_suites_idempotent.py`: runs all independent test suites from Phases 3–11 that declare one in sequence with fresh `docker compose` stack between runs; verifies each phase test passes idempotently with no cross-test data leakage (confirms phase isolation assumption)
- [ ] T078 Complete `docker-compose.test.yml`: add `github-api-mock` (from `tests/mocks/github-api-mock/`) and `confluence-api-mock` (from `tests/mocks/confluence-api-mock/`) services; override `GITHUB_API_BASE_URL`, `CONFLUENCE_BASE_URL`, `SLACK_API_BASE_URL` env vars on `knowledge-ingestion` to point at mocks; set `ENVIRONMENT=test` on all application services; add `app` service that runs `pytest tests/` and exits
- [ ] T079 Create end-to-end integration test `tests/e2e/test_full_stack.py` that validates: (a) connector create → ingest → recall chain via `POST /api/v1/knowledge/search`; (b) PII detection halt + HITL approve; (c) scope change propagates within 60s via `POST /api/v1/knowledge/search`; (d) full four-layer hydration via `POST /api/v1/hydrate` with all layers populated; (e) MCP tool call via `POST /mcp` for `store_memory` and subsequent REST retrieval via `POST /api/v1/memories/search`; run via `docker compose -f docker-compose.test.yml up --exit-code-from app`
- [ ] T080 [P] Define and document both: (a) p95 baseline for `memory_recall_latency_seconds` under synthetic 1,000-entry memory store with concurrent 10-agent recall load; and (b) BYOD ingestion throughput baseline for SC-005 (`1,000`-file GitHub full sync under 10 minutes; `10`-file delta sync under 90 seconds on a GPU-resident host). Record both as performance benchmark fixtures for regression testing.
- [ ] T081 [P] Verify `.env.example` has entries for every env var referenced across all service code; fill in any gaps discovered during T078–T080, including AWS region/credentials/session token, AppConfig IDs, Secrets Manager prefixes, MinIO endpoint overrides, and S3 bucket/table settings
- [ ] T082 [P] Run through `quickstart.md` steps in a clean environment; update any command that fails or has changed since plan; confirm `docker compose ps --format "table {{.Name}}\t{{.Status}}"` shows all healthy

**Checkpoint**: `docker compose -f docker-compose.test.yml up --exit-code-from app --abort-on-container-exit` exits 0. All 10 core services healthy, plus 2 test mock services when the test stack is used. Prometheus scrapes all configured memory-layer service metrics endpoints.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — **BLOCKS all user story phases**
- **Phase 3 (US1, P1)**: Depends on Phase 2 — can start immediately after
- **Phase 4 (US2, P1)**: Depends on Phase 2 — can run in parallel with Phase 3
- **Phase 5 (US3, P2)**: Depends on Phases 3 and 4 complete (needs session + L2 recall in workflow)
- **Phase 6 (US8+US9 Foundation, P3)**: Depends on Phase 5 complete; `memory-api` (T084) can start after Phase 4 complete independently if desired
- **Phase 7 (US4, P2)**: Depends on Phase 2 — can run in parallel with Phases 3, 4, and 6 (connector-registry and ingestion are independent of session/L2 and Graphiti foundation)
- **Phase 8 (US5, P2)**: Depends on Phase 7 (PII runs inside IngestionWorkflow)
- **Phase 9 (US6, P3)**: Depends on Phase 7 (needs org_knowledge chunks to enforce scope on)
- **Phase 10 (US7, P3)**: Depends on Phases 3, 4, 5, 7, 9 all complete (all runtime recall layers must exist)
- **Phase 11 (US8+US9 Integration, P3)**: Depends on Phases 6 and 10 complete; T090 can execute as soon as T084 is ready, but T087/T089/T091/T092 wait on full hydration
- **Phase 12 (Polish)**: Depends on all prior phases complete

### User Story Dependencies

```
Phase 2 (Foundation)
  ├── Phase 3 (US1) ──────────────────────────────────────────────┐
  ├── Phase 4 (US2) ──────────────────────────────────────────────┤─► Phase 5 (US3)
  ├── Phase 6 (US8+US9 Foundation) ───────────────────────────────────────────────────────┐
  │                                                                                       │
  └── Phase 7 (US4) ──► Phase 8 (US5)                                                     │
                     └── Phase 9 (US6) ────────────────────────────────────────────────────┘─► Phase 10 (US7)

Phase 4 (US2) ──► T084 (memory-api) ───────────────────────────────────────────────────────┐
Phase 6 (US8+US9 Foundation) ───────────────────────────────────────────────────────────────┤─► Phase 11 (US8+US9 Integration)
Phase 10 (US7) ──────────────────────────────────────────────────────────────────────────────┘

Phase 11 (US8+US9 Integration) ─► Phase 12 (Polish)
```

### Parallel Opportunities Per Phase

**Phase 1**: T003–T011 all parallelisable after T001 and T002 are done  
**Phase 2**: T012 first; T013/T014 in parallel; T015/T016 sequential; T017/T018/T019/T020/T021/T022/T023/T024 all parallelisable  
**Phase 6 (US8+US9 Foundation)**: T083 first (Compose/profile wiring); T084/T085/T086/T088 in parallel after T083  
**Phase 7 (US4)**: T045 first; T046–T047 then; T048 (BaseConnector) before T049–T052 (four connectors in parallel); T053–T054 after T048; T058–T059 (mocks) in parallel with implementations  
**Phase 8 (US5)**: T060 → T061 → T062; T063 can run in parallel with T060–T062  
**Phase 11 (US8+US9 Integration)**: T087 first; T089 after T085/T086/T087; T090 after T084; T091 after T089/T090; T092 after T088/T091  
**Phase 12**: T076/T077/T081/T082 in parallel after T078/T079/T080

### MVP Scope (Phases 1–4 only)

The minimum viable slice that delivers independent value:
1. **Phase 1**: Container plumbing
2. **Phase 2**: Foundation
3. **Phase 3 (US1)**: Session memory — agents don't lose context on crash
4. **Phase 4 (US2)**: Long-term memory — agents recall past findings across sessions

BYOD, PII, sharing, and full hydration are layered on after MVP is stable.

---

## Summary

| | Count |
|---|---|
| **Total tasks** | 91 |
| **Phase 1 (Setup)** | 11 |
| **Phase 2 (Foundational)** | 13 |
| **Phase 3 (US1 — Session Memory)** | 6 |
| **Phase 4 (US2 — Long-Term Memory)** | 8 |
| **Phase 5 (US3 — Shared Memory)** | 5 |
| **Phase 6 (US8+US9 — Graphiti Foundation + Compat API)** | 5 |
| **Phase 7 (US4 — BYOD Connectors)** | 16 |
| **Phase 8 (US5 — PII Detection)** | 5 |
| **Phase 9 (US6 — Access Control)** | 4 |
| **Phase 10 (US7 — Context Hydration)** | 6 |
| **Phase 11 (US8+US9 — Graphiti Integration + Validation)** | 5 |
| **Phase 12 (Polish)** | 7 |
| **Parallelisable tasks [P]** | 35 |
| **MVP scope (Phases 1–4)** | 38 tasks |

---

## Appendix A: Requirements Traceability Matrix (RTM)

Mapping of 36 functional requirements (FR-001 to FR-036) and 12 success criteria (SC-001 to SC-012) to implementing tasks.

| Requirement | Description | Implementing Task(s) |
|---|---|---|
| **FR-001** | Memory persistence as atomic facts | T031, T035 |
| **FR-002** | Deduplication before store | T034, T041 |
| **FR-003** | Episodic vs semantic memory types | T031 (via decay scoring) |
| **FR-004** | Top-K recall for agent | T033 (L2), T040 (L3), T066 (L4) |
| **FR-005** | Promote findings to shared memory | T041, T042, T043 |
| **FR-006** | Cross-workspace isolation for shared memory | T040, T066 |
| **FR-007** | Session buffer durability at activity boundaries | T025, T026 |
| **FR-008** | 24h session TTL with auto-expiry | T026, T008 |
| **FR-009** | Pluggable connector abstraction | T048 |
| **FR-010** | 4 built-in connectors (GitHub, Confluence, Slack, RDS) | T049, T050, T051, T052 |
| **FR-011** | Background-only ingestion (no sync calls) | T055 |
| **FR-012** | Full + delta sync modes | T055, T056 |
| **FR-013** | Content-hash idempotency skips re-embed | T056, T057 |
| **FR-014** | Content-type-aware chunking (AST, semantic, schema) | T053 |
| **FR-015** | Slack 7-day message cutoff | T051 |
| **FR-016** | Detect 12 PII entity categories | T061 |
| **FR-017** | Hard redact CREDIT_CARD, BANK_ACCOUNT | T061, T062 |
| **FR-018** | Hard drop PASSWORD, SECRET chunks | T061, T062 |
| **FR-019** | Configurable actions for other PII | T061 |
| **FR-020** | PII audit log (no raw values) | T062, T065 |
| **FR-021** | 4 sharing scopes (private, workspace_internal, allowlist, platform_public) | T057, T066 |
| **FR-022** | Scope enforcement at query time (payload filters) | T066 |
| **FR-023** | Agent-scoped access restrictions (by_id, by_tag) | T066, T023 |
| **FR-024** | Grants cache 60s TTL (passive expiry) | T067, T068 |
| **FR-025** | Parallel fan-out of 3 layer recalls | T073 |
| **FR-026** | Source-type + domain weights for ranking | T013, T070 |
| **FR-027** | Per-agent token budget enforcement | T070 |
| **FR-028** | Citations for org knowledge chunks | T070 |
| **FR-029** | Graceful degradation on layer failure | T073, T075 |
| **FR-030** | `contains_pii` declaration at connector create | T045, T046, T047, T062 |
| **FR-031** | OAuth 2.0 3-LO Confluence connector | T050, T059 |
| **FR-032** | Connector REST API (CRUD + pii-review) | T045, T046, T064 |
| **FR-033** | Graphiti L3 backend with temporal validity (t_valid/t_invalid) | T083, T085, T086, T087 |
| **FR-034** | Graphiti MCP tools via external `mcp-registry` | T083, T088 |
| **FR-035** | Unified HTTP+MCP memory API with legacy `X-Tenant-ID` alias support | T084, T090, T070, T072 |
| **FR-036** | `GRAPHITI_ENABLED` feature gate, zero regression when false | T085, T086, T087, T089 |
| | | |
| **SC-001** | p95 recall latency < 500ms (GPU-resident embedding) | T080 (benchmark), T074 (instrumentation) |
| **SC-002** | Dedup prevents unbounded growth | T039 (test) |
| **SC-003** | Resume with full pre-interruption context | T029 (test with 500KB payload overflow) |
| **SC-004** | Promoted finding available to other agents (same workspace) | T044 (test) |
| **SC-005** | GitHub full sync < 10 min, 10-file delta sync < 90s on GPU-resident host | T060, T080 |
| **SC-006** | PII pipeline handles all 12 entities correctly | T065 (test) |
| **SC-007** | Scope change propagates within 60s | T069 (test with TTL mock) |
| **SC-008** | Workflow succeeds when one vector layer fails | T075 (test with layer down) |
| **SC-009** | 4-layer context assembly respects token budget | T075 (test) |
| **SC-010** | Private source never visible cross-workspace | T069, T044 (isolation tests) |
| **SC-011** | Graphiti causal chain traversal ≤3 hops returns in < 1s p95 | T089 (test with 50-node synthetic graph) |
| **SC-012** | Enterprise compat API identical contract to `activities_memory.py` | T090 (test) |
