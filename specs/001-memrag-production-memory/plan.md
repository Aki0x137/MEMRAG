# Implementation Plan: MEMRAG — Production Memory, RAG & BYOD Knowledge Platform

**Branch**: `001-memrag-production-memory` | **Date**: 2026-05-14 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/001-memrag-production-memory/spec.md`

---

## Summary

Build a multi-tenant, multi-layer memory and knowledge platform for AI agents. Layer 1
(Redis) buffers the live session; Layer 2 (Qdrant + Mem0) persists per-agent facts with
decay; Layer 3 (Qdrant) holds workspace-shared findings; Layer 4 (Qdrant) indexes BYOD
org knowledge from GitHub, Confluence, Slack, and RDS Schema connectors. A domain-aware
weight matrix blends recall results in the context-hydrator before injection into the agent
prompt. PII is screened by Presidio on every ingestion path. Temporal orchestrates async
workflows including daily decay crons and HITL PII review. All data within a workspace is
strictly isolated; cross-workspace sharing requires explicit grants.

**Stack**: Python 3.11 (agent-workers, context-hydrator, knowledge-ingestion, llm-gateway)
· Go 1.22 (connector-registry) · Temporal 1.24.2 · Qdrant v1.9.2 · Mem0 ≥0.1.0 ·
Redis 7.2-alpine · PostgreSQL 16-alpine + pgvector · Presidio ≥2.2.355 · Ollama (GPU) ·
PyIceberg ≥0.7.0 / MinIO · Prometheus v2.52.0

---

## Technical Context

**Language/Version**: Python 3.11 (application), Go 1.22 (connector-registry)  
**Primary Dependencies**: Temporal 1.24.2, Qdrant v1.9.2, Mem0 ≥0.1.0, Redis 7.2-alpine,
PostgreSQL 16-alpine + pgvector, Presidio ≥2.2.355, PyIceberg ≥0.7.0, Prometheus v2.52.0,
qwen3-embedding:4b (Ollama), gemma4:12b (Ollama)  
**Storage**: Qdrant (vector), PostgreSQL (relational), Redis (session cache), S3/MinIO (Iceberg tombstone archive)  
**Testing**: pytest (Python unit + integration), `docker compose -f docker-compose.test.yml up --exit-code-from app` (full stack)  
**Target Platform**: Linux server (Docker Compose, NVIDIA GPU required for Ollama)  
**Project Type**: Platform / multi-service backend  
**Performance Goals**: p95 context assembly ≤ 500 ms; p95 recall per layer ≤ 200 ms  
**Constraints**: Token budget enforcement in context-hydrator; Qdrant eventual consistency via content-hash idempotency; Redis 24h session TTL; grants cache 60s passive TTL  
**Scale/Scope**: Multi-workspace, per-workspace agent isolation; BYOD connectors per workspace

---

## Constitution Check

| Gate | Status | Notes |
|---|---|---|
| All runtime components in Docker Compose, no host execution | **PASS** | 12 Compose services (4 app + 2 test-only mocks + 6 infra): see Project Structure |
| Pinned image tags; health checks; `depends_on: condition: service_healthy` | **PASS** | All infra images pinned (e.g., `redis:7.2-alpine`, `qdrant/qdrant:v1.9.2`, `temporalio/auto-setup:1.24.2`). Health checks required on all new services. |
| GPU inference service with NVIDIA device reservation | **PASS** | `ollama` service uses `deploy.resources.reservations.devices` |
| Container-native test commands | **PASS** | `docker compose exec agent-workers pytest tests/unit/` and `docker compose -f docker-compose.test.yml up --exit-code-from app` |
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
├── agent-workers/          # Temporal worker: AgentWorkflow, HITL signal handler
│   ├── src/
│   │   ├── workflows/      # AgentWorkflow, sub-activities
│   │   ├── recall/         # Layer 1–4 recall activities
│   │   └── memory/         # Mem0 store/extract wrappers, decay activity
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/
│   └── pyproject.toml
│
├── context-hydrator/       # assemble() service: weight matrix re-rank + token-budget trim
│   ├── src/
│   │   ├── assembler.py
│   │   ├── weights.py      # SOURCE_WEIGHT matrix
│   │   └── metrics.py      # Prometheus histogram exports
│   ├── tests/
│   └── pyproject.toml
│
├── knowledge-ingestion/    # Temporal worker: IngestionWorkflow, DecayMemoriesWorkflow
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
docker-compose.yml          # dev stack (13 services)
docker-compose.test.yml     # test stack — mocks substituted for real external APIs
.env.example

# Package shared across Python services
packages/
└── memrag-shared/          # AgentManifest dataclass, layer constants, weight matrix
    └── pyproject.toml
```

**Structure decision**: Multi-service layout with per-service `pyproject.toml` (uv-managed)
and one Go module. Shared Python types in `packages/memrag-shared` to avoid duplication of
`AgentManifest` and the weight matrix across service boundaries.

**Scope boundary**: `services/` contains only the four core memory-layer services
(agent-workers, context-hydrator, knowledge-ingestion, connector-registry). LLM inference
is provided by the GPU-resident `ollama` container; all Python services call Ollama directly
at `OLLAMA_HOST` — no extra gateway proxy is owned by this repo. Mock services used in
`ENVIRONMENT=test` live under `tests/mocks/` and are not production images. Example agents
that *consume* the MEMRAG APIs (demonstrating the full agentic loop) belong in `examples/`;
the existing `examples/a1-agent-engine/` already contains a reference `AgentWorkflow`
implementation.

---

## Service Inventory

| Service | Image base | Port(s) | Role |
|---|---|---|---|
| `agent-workers` | `python:3.11-slim` (built) | — | Temporal worker (memory recall/store activities) |
| `context-hydrator` | `python:3.11-slim` (built) | 8081 | assemble() RPC; exposes `/metrics` |
| `knowledge-ingestion` | `python:3.11-slim` (built) | — | Temporal worker (IngestionWorkflow, DecayMemoriesWorkflow) |
| `connector-registry` | `golang:1.22-alpine` (built) | 8082 | Connector CRUD REST API + HITL signal relay |
| `github-api-mock` *(test only)* | `python:3.11-slim` (built) | 8085 | GitHub REST API mock (`tests/mocks/`) |
| `confluence-api-mock` *(test only)* | `python:3.11-slim` (built) | 8084 | Confluence OAuth 3-LO + CQL mock (`tests/mocks/`) |
| `ollama` | `ollama/ollama:latest`* | 11434 | GPU-resident LLM + embedding inference |
| `qdrant` | `qdrant/qdrant:v1.9.2` | 6333 | Vector DB (3 collections) |
| `postgres` | `postgres:16-alpine` | 5432 | Relational store |
| `redis` | `redis:7.2-alpine` | 6379 | Session cache + grants cache |
| `temporal` | `temporalio/auto-setup:1.24.2` | 7233 | Workflow engine |
| `minio` | `minio/minio:RELEASE.2024-05-10T01-41-38Z` | 9000/9001 | S3-compatible archive (dev) |
| `prometheus` | `prom/prometheus:v2.52.0` | 9090 | Metrics scrape + storage |

*Ollama pin: use `ollama/ollama:0.1.44` or latest stable tag; confirm before implementation.

---

## Key Workflows

### `AgentWorkflow` (Temporal)

```
START → fetchRecentSession (Layer 1, Redis)
      → parallel: [recallAgentMemory (Layer 2), recallSharedMemory (Layer 3), recallOrgKnowledge (Layer 4)]
      → assemble (context-hydrator)
      → callLLM (Ollama via OLLAMA_HOST — called directly by agent-workers)
      → storeMemory (Mem0 extract + Qdrant upsert)
      → optionally: promoteToShared (Layer 3 upsert)
END
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
| Separate `connector-registry` in Go | FR-032 requires a stable REST API with fast CRUD and Temporal signal relay; Go is idiomatic for this pattern in the existing `packages/go-shared` | Python FastAPI could work but would duplicate the Go Temporal client already in the shared package |
| Mem0 for store/extract only; custom Qdrant hybrid recall | Mem0's built-in recall doesn't support hybrid BM25+dense with RRF; A-005 resolution | Using Mem0 recall would forfeit dense+sparse fusion and the domain weight matrix |
| 3 Qdrant collections (not 1) | Access control scoping differs: agent-scoped vs workspace-scoped vs cross-workspace; separate collections allow payload index isolation without cross-tenant leakage | A single collection with a filter field would require careful payload index sizing and increases risk of misconfigured multi-tenant filter bugs |
| PyIceberg + MinIO for tombstone archive | Compliance requirement for audit trail before deletion from Qdrant | Writing tombstones to PostgreSQL would conflict with the append-only constraint and grow unboundedly |
