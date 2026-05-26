# Implementation Plan: MEMRAG — Production Memory, RAG & BYOD Knowledge Platform

**Branch**: `001-memrag-production-memory` | **Date**: 2026-05-14 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/001-memrag-production-memory/spec.md`

---

## Summary

Build a multi-tenant, multi-layer memory and knowledge platform for AI agents. Layer 1
(Redis) buffers the live session; Layer 2 (Qdrant + Mem0) persists per-agent facts with
decay; Layer 3 (Qdrant, upgraded to Graphiti + Neo4j when `GRAPHITI_ENABLED=true`) holds
workspace-shared findings with optional temporal validity and causal chain traversal; Layer 4
(Qdrant) indexes BYOD org knowledge from GitHub, Confluence, Slack, and RDS Schema connectors.
A domain-aware weight matrix blends recall results from all four layers before injection
into the agent prompt. PII is screened by Presidio on every ingestion path. Temporal
orchestrates BYOD ingestion workflows (`IngestionWorkflow`) and nightly memory decay
(`DecayMemoriesWorkflow`) only — both in the `knowledge-ingestion` service. All data within
a workspace is strictly isolated; cross-workspace sharing requires explicit grants. A unified
HTTP service (`memory-api`) exposes all four memory layers via REST and an MCP-compatible
endpoint, enabling any agent framework (including enterprise-agentic-platform) to replace
flat pgvector memory with MEMRAG by updating two HTTP calls, and enabling MCP-native tool
discovery for agents that speak MCP.

**Terminology Note**: "Layer 4" and "org knowledge" refer to the same concept in the memory
model. "Layer 4" refers to the memory layer in the four-layer recall architecture (Layer 1 =
session, L2 = agent, L3 = shared, L4 = org knowledge); "org knowledge" refers to the Qdrant
collection that stores BYOD-indexed content. Both terms are interchangeable throughout this
plan and tasks.

**Stack**: Python 3.11 (memory-api, knowledge-ingestion) · Go 1.22 (connector-registry) · Temporal 1.24.2 · Qdrant v1.9.2 · Mem0 ≥0.1.0 ·
Redis 7.2-alpine · PostgreSQL 16-alpine + pgvector · Presidio ≥2.2.355 · Graphiti (optional,
`graphiti-client≥0.3.0`) · Neo4j 5.20 (optional, Graphiti backend) · Ollama (GPU) ·
PyIceberg ≥0.7.0 / MinIO · boto3/botocore (AWS integrations) · aws-sdk-go-v2
(`config`, `secretsmanager`, `appconfigdata`) · Prometheus v2.52.0 · fastmcp (MCP endpoint)

---

## Technical Context

**Language/Version**: Python 3.11 (application), Go 1.22 (connector-registry)  
**Primary Dependencies**: Temporal 1.24.2, Qdrant v1.9.2, Mem0 ≥0.1.0, Redis 7.2-alpine,
PostgreSQL 16-alpine + pgvector, Presidio ≥2.2.355, PyIceberg ≥0.7.0, boto3/botocore,
aws-sdk-go-v2 (`config`, `secretsmanager`, `appconfigdata`), Prometheus v2.52.0,
qwen3-embedding:4b (Ollama), gemma4:12b (Ollama)  
**Storage**: Qdrant (vector), PostgreSQL (relational), Redis (session cache), AWS S3/MinIO (Iceberg tombstone archive), AWS Secrets Manager (production connector secrets), AWS AppConfig (optional weight/PII config source)  
**Testing**: pytest (Python unit + integration), `docker compose -f docker-compose.test.yml up --exit-code-from app` (full stack)  
**Target Platform**: Linux server (Docker Compose, NVIDIA GPU required for Ollama)  
**Project Type**: Platform / multi-service backend  
**Performance Goals**: p95 recall per layer ≤ 500 ms; p95 context assembly ≤ 200 ms  
**Constraints**: Token budget enforcement inline in `memory-api/assembler.py`; Qdrant eventual consistency via content-hash idempotency; Redis 24h session TTL; grants cache 60s passive TTL; AWS integrations must work against live AWS endpoints in production and MinIO/local mocks in development without code forks  
**Scale/Scope**: Multi-workspace, per-workspace agent isolation; BYOD connectors per workspace

---

## Constitution Check

| Gate | Status | Notes |
|---|---|---|
| All runtime components in Docker Compose, no host execution | **PASS** | 10 always-on Compose services (3 app + 7 infra), plus 2 test-only mocks in `docker-compose.test.yml` and 3 optional `graphiti` profile services: see Project Structure |
| Pinned image tags; health checks; `depends_on: condition: service_healthy` | **PASS** | All runtime images are pinned (e.g., `redis:7.2-alpine`, `qdrant/qdrant:v1.18.0`, `temporalio/auto-setup:1.24.2`, `ollama/ollama:0.21.0`). Health checks required on all new services. |
| GPU inference service with NVIDIA device reservation | **PASS** | `ollama` service uses `deploy.resources.reservations.devices` |
| Container-native test commands | **PASS** | `docker compose exec memory-api pytest tests/` and `docker compose -f docker-compose.test.yml up --exit-code-from app` |
| Config via env vars and named volumes; no hardcoded paths/secrets | **PASS** | `.env` for all secrets; `credential_ref` references secrets store path; named Compose volumes for Qdrant, Postgres, Minio, Redis |

Post-design re-check: all five gates still **PASS** — no architectural changes introduced
violations.

---

## Project Structure

### Documentation (this feature)

```text
specs/001-memrag-production-memory/
├── plan.md              # This file
├── research.md          # Phase 0 output — all unknowns resolved
├── data-model.md        # Phase 1 output — Qdrant, PostgreSQL, Redis, S3 schemas
├── quickstart.md        # Phase 1 output — local stack setup guide
├── contracts/
│   ├── connector_management_api.md   # Phase 1 — FR-032 REST API contract
│   └── context_hydration.md          # Phase 1 — assemble() interface + weight matrix
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
# Python services (pyproject.toml + uv.lock per service)
services/
├── memory-api/            # ALL-LAYER HTTP service: L1–L4 REST + MCP endpoint + context assembly
│   ├── src/
│   │   ├── main.py         # FastAPI app; REST routes + MCP /mcp endpoint (fastmcp)
│   │   └── routes/         # session.py, memories.py, shared.py, knowledge.py, hydrate.py
│   ├── tests/
│   └── pyproject.toml
│
├── knowledge-ingestion/    # Temporal worker: IngestionWorkflow + DecayMemoriesWorkflow only
│   ├── src/
│   │   ├── workflows/      # IngestionWorkflow, DecayMemoriesWorkflow (cron)
│   │   ├── connectors/     # github.py, confluence.py, slack.py, rds_schema.py
│   │   ├── chunker.py      # chonkie + trafilatura; tree-sitter for code
│   │   ├── embedder.py     # qwen3-embedding:4b via Ollama
│   │   └── pii.py          # Presidio detection + redact/drop hard rules
│   ├── tests/
│   └── pyproject.toml
│
├── connector-registry/     # Go 1.22: FR-032 REST API, PostgreSQL CRUD, Temporal signals
│   ├── cmd/registry/
│   ├── internal/
│   │   ├── api/            # HTTP handlers (chi router)
│   │   ├── db/             # sqlc-generated queries
│   │   └── temporal/       # signal client for pii-review endpoint
│   ├── migrations/         # Goose SQL migration files
│   └── go.mod

# Test-only mock services (ENVIRONMENT=test, not part of production image set)
tests/
└── mocks/
    ├── github-api-mock/        # GitHub REST API mock (Go or Python)
    └── confluence-api-mock/    # Confluence REST API mock with full OAuth 2.0 3-LO + CQL

# Compose files
docker-compose.yml          # dev stack (12 always-on services; 3 optional `graphiti` profile services)
docker-compose.test.yml     # test stack — mocks substituted for real external APIs
.env.example

# Package shared across Python services
packages/
└── memrag-shared/          # AgentManifest, layer constants, weight matrix, recall libs
    ├── src/memrag_shared/
    │   ├── manifest.py     # AgentManifest dataclass
    │   ├── weights.py      # SOURCE_WEIGHT matrix + get_weight() helper
    │   ├── layers.py       # layer constants + MemoryChunk / KnowledgeChunk dataclasses
    │   ├── recall/         # layer2.py, layer3.py, layer3_graphiti.py, layer4.py
    │   ├── memory/         # mem0_client.py, shared.py, dedup.py
    │   ├── session/        # session.py (Redis checkpoint + fetch)
    │   ├── assembler.py    # context assembly: weight-matrix re-rank + token-budget trim
    │   └── infra/          # qdrant_client.py, redis_client.py, ollama_client.py
    └── pyproject.toml
```

**Structure decision**: Multi-service layout with per-service `pyproject.toml` (uv-managed)
and one Go module. Shared Python types AND library logic in `packages/memrag-shared` so both
`memory-api` and `knowledge-ingestion` import the same implementations without duplication.

**Scope boundary**: `services/` contains three core application services:
`memory-api` (all-layer HTTP+MCP interface), `knowledge-ingestion` (Temporal BYOD worker),
`connector-registry` (Go REST API for connector management). The former `agent-workers`
Temporal worker is eliminated — its library code moved to `memrag-shared` and exposed via
`memory-api`. The former `context-hydrator` separate service is eliminated — its assembly
logic moved into `memrag-shared/assembler.py` and called inline by `memory-api`'s
`/api/v1/hydrate` endpoint. LLM inference is provided by the GPU-resident `ollama` container;
all Python services call Ollama at `OLLAMA_HOST` directly. Mock services used in
`ENVIRONMENT=test` live under `tests/mocks/`. Example agents that *consume* the MEMRAG APIs
belong in `examples/`; the existing `examples/enterprise-agentic-platform/` contains a
reference `AgentWorkflow` that can replace its `activities_memory.py` with HTTP calls to
MEMRAG's `memory-api`.

---

## Service Inventory

| Service | Image base | Port(s) | Role |
|---|---|---|---|
| `memory-api` | `python:3.11-slim` (built) | 8083 | All-layer HTTP service: L1–L4 REST endpoints + MCP tool endpoint + context assembly (`/api/v1/hydrate`); imports `memrag-shared` directly |
| `knowledge-ingestion` | `python:3.11-slim` (built) | — | Temporal worker: `IngestionWorkflow` (BYOD + PII + HITL), `DecayMemoriesWorkflow` (nightly cron) |
| `connector-registry` | `golang:1.22-alpine` (built) | 8082 | Connector CRUD REST API + HITL signal relay + AWS AppConfig/Secrets Manager clients |
| `github-api-mock` *(test only)* | `python:3.11-slim` (built) | 8085 | GitHub REST API mock (`tests/mocks/`) |
| `confluence-api-mock` *(test only)* | `python:3.11-slim` (built) | 8084 | Confluence OAuth 3-LO + CQL mock (`tests/mocks/`) |
| `ollama` | `ollama/ollama:0.21.0` | 11434 | GPU-resident LLM + embedding inference |
| `qdrant` | `qdrant/qdrant:v1.18.0` | 6333 | Vector DB (3 collections) |
| `postgres` | `postgres:16-alpine` | 5432 | Relational store |
| `redis` | `redis:7.2-alpine` | 6379 | Session cache + grants cache |
| `temporal` | `temporalio/auto-setup:1.24.2` | 7233 | Workflow engine (BYOD ingestion + decay cron only) |
| `minio` | `minio/minio:RELEASE.2024-05-10T01-41-38Z` | 9000/9001 | S3-compatible archive (dev) |
| `prometheus` | `prom/prometheus:v2.52.0` | 9090 | Metrics scrape + storage |
| `graphiti-server` *(optional, `graphiti` Compose profile)* | `zep/graphiti-server:0.3` | 8100 | Graphiti temporal KG engine; only active when `GRAPHITI_ENABLED=true` |
| `graphiti-mcp` *(optional, `graphiti` Compose profile)* | `zep/graphiti-mcp:0.3` | 8101 | Graphiti native MCP server; can be registered in an external `mcp-registry` from enterprise-agentic-platform |
| `neo4j` *(optional, `graphiti` Compose profile)* | `neo4j:5.20` | 7474/7687 | Graph DB backing Graphiti; named volume `neo4j_data` |

---

## Key Workflows

### HTTP Request Flow in `memory-api`

```
External agent (any language / any framework) or MCP client
  ↓ HTTP POST or MCP tool call
memory-api FastAPI service
  ║
  ╠══ L1 session: direct Redis GET/SET via memrag-shared/session.py
  ╠══ L2 recall:  Qdrant hybrid search via memrag-shared/recall/layer2.py
  ╠══ L2 store:   Mem0 extract + Qdrant upsert via memrag-shared/memory/mem0_client.py
  ╠══ L3 recall:  Qdrant shared_memories (or Graphiti search_facts when GRAPHITI_ENABLED=true)
  ╠══ L3 store:   Qdrant shared_memories upsert (or Graphiti add_episode when enabled)
  ╠══ L4 recall:  Qdrant org_knowledge with grants filter via memrag-shared/recall/layer4.py
  └══ hydrate:    asyncio.gather(L1–L4) → memrag-shared/assembler.py (weight-matrix re-rank
                 + token-budget trim) → HydrateResponse with citations
```

### `IngestionWorkflow` (Temporal, triggered by connector-registry)

```
START → fetchResources (connector-specific scraper)
      → diffResources (content-hash against knowledge_sync_state)
      → for each changed resource:
            → chunk → embed → pii_screen
            → if pii and contains_pii=false: SIGNAL pii_detected_mismatch → await hitl_response
            → upsert to org_knowledge Qdrant + update knowledge_sync_state
END
```

### `DecayMemoriesWorkflow` (Temporal cron `0 2 * * *`)

```
START → scan agent_memories by workspace (batch scroll)
      → recompute decay_score (time-weighted formula)
      → bulk update decay_score in Qdrant
      → for score < 0.1: archive to S3 Iceberg → delete from Qdrant
END
```

---

## Complexity Tracking

> No Constitution Check violations — this section documents intentional architectural
> decisions that add services but are justified by requirements.

| Decision | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| No Temporal for L1–3 memory operations | Temporal is justified only for long-running HITL workflows and at-least-once delivery guarantees. L1–3 memory ops are 10–50ms synchronous I/O calls; LLM inference (500ms–10s) dominates agent turn latency. Adding a Temporal activity wrapper around Redis GET/SET or Qdrant upsert gains nothing and removes the ability to call the memory platform from any HTTP client | A Temporal activity wrapper with retry/timeout is achievable but moves responsibility for retry logic into the orchestration layer when simple HTTP retries at the caller are equally effective and simpler to debug |
| REST + MCP (not gRPC) for `memory-api` | MCP (Model Context Protocol, 2025-06-18 spec) uses JSON-RPC over HTTP+SSE — gRPC is incompatible. REST enables universal adoption across every language, SDK, and agent framework with no generated stubs. LLM inference dominates latency; the 5–20ms REST vs gRPC protocol difference is negligible. REST is human-readable and easy to debug | gRPC is faster for high-throughput internal calls but requires proto files on every client, breaks MCP compatibility, and adds toolchain friction with no latency benefit at agent turn timescales where embedding + Qdrant queries (50–150ms combined) are dwarfed by LLM inference |
| `memory-api` as primary integration surface covering all four layers | External agents need one endpoint to replace their memory layer — not four separate services. A single HTTP service with well-named routes is discoverable and testable; each route delegates to `memrag-shared` library functions | Separate per-layer HTTP services (e.g., `session-api`, `memory-api`, `shared-api`, `knowledge-api`) would quadruple operational surface and require agents to know which service handles which layer |
| Context assembly inlined into `memory-api` (not separate `context-hydrator` service) | Assembly is a synchronous CPU-bound calculation (weight-matrix multiply + token-count loop) taking <5ms. Externalizing it as a separate service adds a network hop toward the SC-009 200ms p95 budget and doubles deployment surface with zero isolation benefit | A separate `context-hydrator` HTTP service could scale independently but assembly has no I/O — it cannot be the bottleneck that warrants a dedicated pod |
| `agent-workers` Temporal service eliminated | MEMRAG is a memory platform, not an agent executor. The `AgentWorkflow` tried to do both memory operations AND LLM inference in one Temporal class, coupling MEMRAG's internal delivery mechanism to every external agent's execution model. External agents (enterprise-agentic-platform, Claude, etc.) already have their own execution loops; they should call MEMRAG's HTTP API for memory, not inherit MEMRAG's workflow | Keeping `AgentWorkflow` would require every external agent to be rewritten as a MEMRAG Temporal workflow — the opposite of a reusable platform |
| Separate `connector-registry` in Go | FR-032 requires a stable REST API with fast CRUD and Temporal signal relay; Go is idiomatic for this pattern in the existing `packages/go-shared` | Python FastAPI could work but would duplicate the Go Temporal client already in the shared package |
| AWS SDK split by runtime | Python services own S3/Iceberg archive writes and RDS schema reads naturally via boto3/botocore + DB drivers; Go service owns AppConfig/Secrets Manager access for admin/config flows via aws-sdk-go-v2 | Forcing all AWS interactions through a single runtime would introduce cross-service coupling and unnecessary proxy APIs |
| Mem0 for store/extract only; custom Qdrant hybrid recall | Mem0's built-in recall doesn't support hybrid BM25+dense with RRF; A-005 resolution | Using Mem0 recall would forfeit dense+sparse fusion and the domain weight matrix |
| 3 Qdrant collections (not 1) | Access control scoping differs: agent-scoped vs workspace-scoped vs cross-workspace; separate collections allow payload index isolation without cross-tenant leakage | A single collection with a filter field would require careful payload index sizing and increases risk of misconfigured multi-tenant filter bugs |
| PyIceberg + MinIO for tombstone archive | Compliance requirement for audit trail before deletion from Qdrant | Writing tombstones to PostgreSQL would conflict with the append-only constraint and grow unboundedly |
| Graphiti + Neo4j as optional L3 backend (feature-gated) | FR-033 requires temporal validity windows and conflict resolution for shared findings — capabilities that Qdrant and PostgreSQL cannot provide; Graphiti (Apache 2.0, 25k+ stars) ships these battle-tested under one dependency | Implementing temporal edges + conflict resolution manually in Qdrant payload fields would require custom deduplication, conflict detection, and traversal logic duplicating what Graphiti already provides; building a custom `kg-service` (as in enterprise-agentic-platform) yields an inferior subset of Graphiti without temporal validity or MCP-native integration |
| `graphiti` Compose profile (opt-in) | Neo4j is a heavy stateful dependency; most development and testing scenarios do not require graph memory — the existing Qdrant L3 path is fully functional without it | Always-on would add ≈1.5 GB RAM overhead and slow `docker compose up` for developers not testing graph features |
| `memory-api` as unified all-layer HTTP+MCP service | FR-035 enterprise compatibility API, L1–L4 REST, MCP endpoint, and context assembly all share the same headers (`X-Workspace-ID`/`X-Agent-ID`, with legacy `X-Tenant-ID` alias support), auth model, and Prometheus metrics path; collocating them in one service avoids cross-service coupling and simplifies deployment | Splitting into per-layer micro-services (`session-api`, `memory-api`, `shared-api`, `knowledge-api`) would quadruple operational surface and require callers to route by layer |
