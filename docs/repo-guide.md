# MEMRAG Repo Guide

This repository is a multi-service MEMRAG workspace. The cleanest way to approach it is to separate what is already implemented from what is still scaffolded, then work from the shared contracts outward into the services that consume them.

## What exists today

| Area | Status | Notes |
|---|---|---|
| `services/agent-workers/` | Implemented | Temporal worker with session checkpointing, long-term memory recall/store, and a nightly decay/archive workflow. |
| `services/knowledge-ingestion/` | Partially implemented | Temporal worker bootstrap and decay workflow are present; the broader connector ingestion pipeline is not in place yet. |
| `services/connector-registry/` | Implemented baseline | Go HTTP service with `/health` and `/v1/connectors`, Postgres-backed store code, and migrations for connectors, sync state, grants, audit, and workflow execution tracking. |
| `services/context-hydrator/` | Scaffolded | README and compose wiring exist, but there is no source implementation yet. |
| `packages/memrag-shared/` | Implemented | Shared contracts for agent manifests, layer constants, memory chunk models, and source weights. |
| `tests/mocks/` | Planned in compose | The test compose file references GitHub and Confluence mocks, but the workspace does not currently contain their implementations. |
| Root `main.py` | Placeholder | Simple hello-world stub, not a real application entrypoint. |

## Recommended way to read the repo

Start with `packages/memrag-shared/` to understand the common data model. The shared package defines the four memory layers, the agent manifest contract, and the source weighting model used across the rest of the stack.

Next, read `services/agent-workers/` because that is where the most complete runtime behavior lives today. The worker bootstrap wires the activities into Temporal, `AgentWorkflow` checkpoints session state in Redis, recalls agent memory from the long-term store, and persists new memory from workflow output.

Then check `services/connector-registry/` to understand how connectors and grants are modeled in Postgres. Even though the HTTP surface is still minimal, the migrations and store layer show the intended shape of the BYOD registry.

Finally, inspect `services/knowledge-ingestion/` and `services/context-hydrator/` as the next pieces to complete. The ingestion service already owns the nightly decay path, while the hydrator is currently only a shell around the intended assembly API.

## Practical development order

1. Keep the shared contract stable in `packages/memrag-shared/`.
2. Extend `services/agent-workers/` only after the shared models are updated.
3. Use `services/connector-registry/` as the source of truth for connector metadata, sync state, and sharing grants.
4. Fill in `services/context-hydrator/` once the recall and registry shapes are settled.
5. Add ingestion connectors and mocks last, because those depend on the service contracts above.

## Current implementation notes

- Session memory is checkpointed into Redis with a 24-hour TTL and payload chunking for large sessions.
- Long-term agent memory is recalled and stored through the Temporal worker activities in `services/agent-workers/`.
- Nightly decay/archive is already wired through `services/knowledge-ingestion/` and uses Qdrant plus a tombstone archive path.
- Connector CRUD is present at the storage layer, but the HTTP API surface is still very small.
- The repo is set up as a Python uv workspace with shared packages and separate service roots.

## Useful entrypoints

- Root workspace definition: `pyproject.toml`
- Agent worker bootstrap: `services/agent-workers/src/worker.py`
- Agent workflow: `services/agent-workers/src/workflows/agent_workflow.py`
- Session checkpointing activities: `services/agent-workers/src/activities/session.py`
- Memory recall/store activities: `services/agent-workers/src/activities/memory.py`
- Ingestion worker bootstrap: `services/knowledge-ingestion/src/worker.py`
- Nightly decay workflow: `services/knowledge-ingestion/src/workflows/decay_workflow.py`
- Connector registry HTTP entrypoint: `services/connector-registry/cmd/main.go`
- Shared layer and manifest contracts: `packages/memrag-shared/src/memrag_shared/`

## How to run the stack

The top-level Compose files are the main orchestration path for local work.

- Development stack: `docker compose up --build`
- Test stack: `docker compose -f docker-compose.yml -f docker-compose.test.yml up --build`

The first command brings up the infrastructure and application services together. The second adds the test-only mocks and the test runner container.

## What to treat as next work

The biggest gap is the missing implementation for `services/context-hydrator/`, followed by the broader connector ingestion pipeline. If you are continuing the buildout, those two areas should come after the shared package and worker behavior are stabilized.
