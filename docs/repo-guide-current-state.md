# MEMRAG Repo Guide: Current State

This document is a practical guide to the repository as it exists today. It focuses on the code paths that are already implemented, the places to start reading, and the parts that are still incomplete.

## What This Repo Currently Contains

At the root level, this repository is building a multi-service memory and retrieval platform around four storage layers:

1. Layer 1: short-lived session state in Redis.
2. Layer 2: agent-scoped long-term memory in Qdrant.
3. Layer 3: workspace-shared memory in Qdrant, with optional Graphiti and Neo4j integration.
4. Layer 4: workspace knowledge ingested from external systems such as GitHub and Confluence.

What is implemented today is centered around four working service areas and one partially wired area:

- `services/agent-workers`: Temporal workflow and memory recall and storage logic.
- `services/knowledge-ingestion`: Temporal workflow for connector ingestion, chunking, embedding, PII screening, and archive and decay.
- `services/memory-api`: FastAPI compatibility layer for Layer 2 memory store and search.
- `services/connector-registry`: Go HTTP API for connector CRUD and sharing grants, currently backed by an in-memory mock query layer.
- `services/context-hydrator`: referenced in docs and Compose, but no source tree exists yet.

The repo also contains architecture examples under `examples/`, but those are not the primary implementation surface for the root MEMRAG stack.

## Recommended Read Order

If you are new to the repo, read in this order:

1. `docker-compose.yml`
   This shows the actual runtime topology: infrastructure, service names, ports, environment variables, and optional Graphiti profile services.
2. `specs/001-memrag-production-memory/plan.md`
   This describes the intended architecture and service boundaries.
3. `services/agent-workers/src/workflows/agent_workflow.py`
   This is the best entrypoint for understanding the active memory loop.
4. `services/knowledge-ingestion/src/workflows/ingestion.py`
   This is the best entrypoint for understanding BYOD ingestion.
5. `services/memory-api/src/main.py`
   This shows the current HTTP surface for storing and searching Layer 2 memories.
6. `services/connector-registry/cmd/main.go`
   This shows the current connector management server boot path.

After that, move into tests to see what behavior is actually exercised.

## Repo Map For The Implemented Surface

### Root files

- `docker-compose.yml`: local runtime stack.
- `docker-compose.test.yml`: test overrides plus API mocks and test runner.
- `Dockerfile.test`: top-level test runner image.
- `infra/prometheus/prometheus.yml`: Prometheus scrape configuration.
- `specs/001-memrag-production-memory/`: design, contracts, tasks, and quickstart documents.

### Shared package

- `packages/memrag-shared`: shared Python models and memory layer constants used across Python services.

### Main services

- `services/agent-workers`
- `services/knowledge-ingestion`
- `services/memory-api`
- `services/connector-registry`

### Test-only assets

- `tests/mocks/github-api-mock`
- `tests/mocks/confluence-api-mock`

## Service-By-Service Guide

### 1. Agent Workers

Path: `services/agent-workers`

This is the most important implemented service if you want to understand the current memory behavior.

Start here:

- `src/workflows/agent_workflow.py`
- `src/activities/session.py`
- `src/activities/memory.py`
- `src/recall/`
- `src/memory/`
- `src/tools/promote_finding.py`

What it currently does:

- Restores prior session turns from Redis.
- Recalls Layer 2 agent memories.
- Recalls Layer 3 shared workspace memories.
- Stores new agent memory after each workflow run.
- Optionally promotes findings into shared memory.
- Supports a HITL signal channel on the workflow object.

Important current behavior:

- The workflow fans out in parallel for Layer 2 and Layer 3 recall.
- The returned workflow output is still a simple composed response, not a full LLM orchestration loop.
- Layer 4 recall code exists under `src/recall/layer4.py`, but the current `AgentWorkflow` read path shown in `agent_workflow.py` is centered on session restore plus Layer 2 and Layer 3 recall.

Useful navigation inside this service:

- `src/recall/layer2.py`: agent-memory recall.
- `src/recall/layer3.py`: shared-memory recall.
- `src/recall/layer3_graphiti.py`: Graphiti-backed shared recall path.
- `src/recall/layer4.py`: org-knowledge recall helpers.
- `src/memory/mem0_client.py`: memory extraction and storage integration.
- `src/memory/shared.py`: promotion to shared knowledge.
- `src/infra/`: Qdrant, Redis, Ollama, and Temporal clients.

### 2. Knowledge Ingestion

Path: `services/knowledge-ingestion`

This service implements the current BYOD ingestion path.

Start here:

- `src/workflows/ingestion.py`
- `src/workflows/decay_workflow.py`
- `src/activities/ingestion.py`
- `src/activities/upsert.py`
- `src/activities/pii_screen.py`
- `src/connectors/`

What it currently does:

- Fetches content from connectors.
- Diffs resources against stored sync state.
- Chunks content.
- Generates embeddings.
- Screens chunks for PII.
- Upserts resulting chunks into `org_knowledge`.
- Updates sync state after upsert.
- Runs memory decay and archive workflows.

Connector implementations present today:

- GitHub
- Confluence
- Slack
- RDS schema

Useful navigation inside this service:

- `src/chunker.py`: chunking strategy for prose, code, and schema content.
- `src/embedder.py`: embedding helpers, including sparse vectors for hybrid retrieval.
- `src/pii.py`: PII mismatch and screening logic.
- `src/infra/qdrant_init.py`: Qdrant collection setup and bootstrap behavior.
- `src/infra/iceberg_client.py`: archive path for decayed memories.

### 3. Memory API

Path: `services/memory-api`

This service is a thin HTTP compatibility layer over the memory code already living in `agent-workers`.

Start here:

- `src/main.py`
- `tests/smoke_test.py`

What it currently exposes:

- `GET /healthz`
- `POST /api/v1/memories`
- `POST /api/v1/memories/search`

Important current behavior:

- The service dynamically imports Layer 2 memory code from `services/agent-workers`.
- `X-Agent-ID` must match `agent_id` in the request body.
- The current surface is intentionally small and focused on Layer 2 store and search.

This is the fastest service to understand if you want to see a minimal working API surface in the repo.

### 4. Connector Registry

Path: `services/connector-registry`

This service is the management API around connectors and sharing grants.

Start here:

- `cmd/main.go`
- `internal/api/server.go`
- `internal/api/handlers_connector.go`
- `internal/api/handlers_grants.go`
- `internal/db/queries.go`
- `migrations/`

What it currently does:

- Starts an HTTP server on port 8082.
- Exposes health and connector-management routes.
- Handles connector CRUD and sharing grant routes through Go handlers.
- Initializes a Temporal client if available.

Important caveat:

- The server is currently wired to `db.NewMockQueries()`, which is an in-memory implementation.
- SQL migrations and query definitions exist, but the running server is not yet using a real PostgreSQL-backed query layer.

Treat this service as partially implemented: the HTTP shape exists, but the persistence path is not fully wired.

### 5. Context Hydrator

Path: `services/context-hydrator`

This service appears in the plan, Compose, and a service README. However, there is currently no `src/` tree under `services/context-hydrator`.

That means:

- Compose references a service that is not backed by application source yet.
- The intended context assembly layer is still a gap in the current repo state.
- If you are tracing implemented behavior, do not start here.

## Runtime Topology

The local stack is driven by `docker-compose.yml`.

Always-on infrastructure:

- PostgreSQL
- Redis
- Qdrant
- MinIO
- Temporal
- Ollama
- Prometheus

Application services:

- connector-registry on `8082`
- agent-workers on `8080`
- context-hydrator on `8081` but currently missing source
- memory-api on `8083`
- knowledge-ingestion as a worker process

Optional Graphiti profile services:

- Neo4j
- graphiti-server
- graphiti-mcp

Test-only mock services from `docker-compose.test.yml`:

- GitHub API mock on `8085`
- Confluence API mock on `8084`
- top-level test runner service `app`

## What Is Actually Tested Today

The fastest way to understand the reliable implementation surface is to read the tests.

### Agent worker tests

Path: `services/agent-workers/tests`

Coverage includes:

- session buffer and crash-safe checkpointing
- long-term memory behavior
- shared memory promotion and cross-agent visibility
- workspace isolation
- access-control behavior

Good starting files:

- `tests/integration/test_session_buffer.py`
- `tests/integration/test_long_term_memory.py`
- `tests/integration/test_shared_memory.py`
- `tests/integration/test_access_control.py`
- `tests/unit/test_session_keys.py`

### Knowledge-ingestion tests

Path: `services/knowledge-ingestion/tests/integration`

Coverage includes:

- chunking behavior
- sparse embedding helpers
- deterministic idempotency via content hashes
- Qdrant upsert semantics
- BYOD pipeline behavior
- mock-backed integration coverage for external connectors
- PII pipeline behavior

Good starting files:

- `tests/integration/test_byod_pipeline.py`
- `tests/integration/test_connectors_e2e.py`
- `tests/integration/test_mocks_integration.py`
- `tests/integration/test_pii_pipeline.py`

### Memory API tests

Path: `services/memory-api/tests`

Coverage includes:

- health endpoint
- required header enforcement
- store-memory request validation
- search request validation

Good starting file:

- `tests/smoke_test.py`

## How To Work Through The Repo

Use one of these paths depending on what you need.

### If you want to understand the current memory loop

1. Read `services/agent-workers/src/workflows/agent_workflow.py`.
2. Read `services/agent-workers/src/activities/session.py`.
3. Read `services/agent-workers/src/activities/memory.py`.
4. Read `services/agent-workers/src/recall/layer2.py` and `services/agent-workers/src/recall/layer3.py`.
5. Confirm behavior in `services/agent-workers/tests/integration/`.

### If you want to understand BYOD ingestion

1. Read `services/knowledge-ingestion/src/workflows/ingestion.py`.
2. Read connector implementations in `services/knowledge-ingestion/src/connectors/`.
3. Read chunking, embedding, and PII modules.
4. Confirm behavior in `services/knowledge-ingestion/tests/integration/`.

### If you want to understand the HTTP-facing API

1. Read `services/memory-api/src/main.py`.
2. Follow the dynamic imports back into `services/agent-workers/src/memory/` and `services/agent-workers/src/recall/`.
3. Read `services/memory-api/tests/smoke_test.py`.

### If you want to understand connector administration

1. Read `services/connector-registry/internal/api/server.go`.
2. Read the handler files.
3. Read `internal/db/queries.go` to understand the current in-memory backing.
4. Read `migrations/` to understand the intended relational model.

## Practical Commands

Start the stack:

```bash
docker compose up --build
```

Run the mock-backed test stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up --build --exit-code-from app
```

Inspect a specific service:

```bash
docker compose logs -f agent-workers
docker compose logs -f knowledge-ingestion
docker compose logs -f memory-api
docker compose logs -f connector-registry
```

Run service-local tests from containers after the stack is up:

```bash
docker compose exec agent-workers pytest tests/
docker compose exec knowledge-ingestion pytest tests/
docker compose exec memory-api pytest tests/
```

## Current Caveats

Keep these in mind while navigating the codebase:

- `context-hydrator` is not implemented yet, even though it is referenced in Compose and planning docs.
- `connector-registry` currently uses an in-memory mock query implementation at runtime.
- The root `README.md` is effectively empty right now, so the real source of truth is the service code, Compose files, tests, and spec documents.
- The `examples/` directory contains related systems and reference material, but it is not the primary code path for the root MEMRAG runtime.

## Where To Contribute Next

If you are picking up implementation work, the cleanest next slices are:

1. implement the missing `context-hydrator` source tree,
2. replace `connector-registry` mock queries with real PostgreSQL-backed queries,
3. tighten root-level documentation so the main runtime path is discoverable without reading the spec first.