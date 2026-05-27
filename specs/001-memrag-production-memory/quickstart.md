# Quickstart: MEMRAG — Production Memory, RAG & BYOD Knowledge Platform

**Branch**: `001-memrag-production-memory`

---

## Prerequisites

| Tool | Required version | Install guide |
|---|---|---|
| Docker Engine | ≥ 24.0 | https://docs.docker.com/engine/install/ |
| Docker Compose | ≥ 2.24 (plugin) | included with Docker Desktop / `apt install docker-compose-plugin` |
| NVIDIA drivers | ≥ 525.x | for GPU-resident Ollama |
| NVIDIA Container Toolkit | latest | https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html |
| `uv` | ≥ 0.4.0 | `curl -Lsf https://astral.sh/uv/install.sh | sh` |
| GNU `make` | any | `apt install make` |

> **CPU-only fallback**: set `OLLAMA_DEVICE=cpu` in `.env`. Remove the `deploy.resources`
> block for the `ollama` service in `docker-compose.yml` if NVIDIA toolkit is unavailable.

---

## 1. Clone & Bootstrap

```bash
git clone <repo-url> memrag
cd memrag

# copy environment template and fill in values
cp .env.example .env
```

Minimum `.env` values:

```dotenv
ENVIRONMENT=dev
WORKSPACE_ID=my-workspace
POSTGRES_PASSWORD=changeme
MINIO_ROOT_PASSWORD=changeme
# GitHub connector (optional for first boot)
GITHUB_TOKEN=
# Confluence connector (uses local mock by default in dev)
CONFLUENCE_BASE_URL=http://confluence-api-mock:8084
# AWS defaults for local MinIO/dev secret mocks
AWS_REGION=us-east-1
AWS_S3_ENDPOINT_URL=http://minio:9000
AWS_SECRETS_MANAGER_PREFIX=/memrag/dev
```

For production-backed AWS integrations, also set the deployment-specific values below before
bringing up ingestion or connector-management flows:

```dotenv
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=
AWS_APP_CONFIG_APPLICATION_ID=
AWS_APP_CONFIG_ENVIRONMENT_ID=
AWS_APP_CONFIG_PROFILE_ID=
AWS_SECRETS_MANAGER_PREFIX=
AWS_RDS_IAM_ENABLED=false
AWS_RDS_REGION=us-east-1
AWS_S3_BUCKET=memrag-archive
```

---

## 2. Start the Stack

```bash
# Pull or build all images (first boot — pulls ~4 GB including Ollama model)
docker compose pull

# Start infra first (Qdrant, Postgres, Redis, MinIO, Temporal, Prometheus)
docker compose up -d qdrant postgres redis minio temporal prometheus

# Wait for Temporal UI to be reachable (usually 20–30 s)
docker compose exec temporal-admin temporal operator namespace create default

# Start all application services
docker compose up -d
```

Verify all services are healthy:

```bash
docker compose ps --format "table {{.Name}}\t{{.Status}}"
```

All containers should show `healthy`. If any show `(health: starting)`, wait 30 s and retry.

---

## 3. Pull the Embedding & LLM Models

The `ollama` container stores and serves the local models used by the stack. To pull them
manually:

```bash
docker compose exec ollama ollama pull qwen3-embedding:4b
docker compose exec ollama ollama pull gemma4:12b
```

---

## 4. Run Database Migrations

```bash
# connector-registry uses goose (Go) for schema migrations
# DATABASE_URL must be set in your .env before running
docker compose run --rm connector-registry /connector-registry migrate
```

---

## 5. Seed Local Test Data

```bash
# Create a local GitHub connector pointing to this repo
docker compose exec connector-registry python scripts/seed_dev_connector.py \
  --type github \
  --workspace-id my-workspace \
  --repo akshay-kumar/MEMRAG

# Trigger a manual sync
docker compose exec knowledge-ingestion python -m ingestion.cli trigger --workspace my-workspace
```

Watch ingestion progress:

```bash
docker compose logs -f knowledge-ingestion
```

---

## 6. Run a Sample Agent Workflow

```python
# From your local machine with uv:
uv run python examples/run_agent.py \
  --workspace-id my-workspace \
  --query "How does the hybrid recall work in Layer 2?"
```

Or via the Temporal UI at `http://localhost:8088`.

---

## 7. Run Tests

### Unit / integration tests (host-side, requires uv venv)

```bash
# memory-api integration tests (fastest — no Docker required)
source .venv/bin/activate
cd services/memory-api && python -m pytest tests/integration/ -v --tb=short
```

### Full-stack integration tests (Docker Compose)

```bash
docker compose -f docker-compose.test.yml up --exit-code-from app --abort-on-container-exit
```

Integration tests start a dedicated `ENVIRONMENT=test` stack with mock external services
(`github-api-mock`, `confluence-api-mock`).

---

## 8. Optional: Graphiti Knowledge-Graph Layer (L3)

Graphiti adds a Neo4j-backed temporal knowledge-graph as an alternative to the default
Qdrant L3 shared-memory layer.  It is gated behind `GRAPHITI_ENABLED` and runs as an
opt-in Docker profile so it does **not** affect standard deployments.

### 8a. Start the Graphiti services

```bash
docker compose --profile graphiti up -d neo4j graphiti-server graphiti-mcp
```

Wait for Neo4j to become healthy (≈ 30 s):

```bash
docker compose ps neo4j    # State: healthy
```

Browse the Neo4j graph at **http://localhost:7474**
(default credentials: `neo4j` / `memrag-neo4j`).

### 8b. Enable Graphiti in `.env`

```dotenv
GRAPHITI_ENABLED=true
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=memrag-neo4j
GRAPHITI_SERVER_URL=http://graphiti-server:8000
GRAPHITI_MCP_SERVER_URL=http://graphiti-mcp:8200
MEMORY_API_MCP_URL=http://memory-api:8083/mcp
```

Restart `memory-api` to pick up the new env vars:

```bash
docker compose restart memory-api
```

### 8c. Verify Graphiti is wired

Promote a finding and confirm it lands in the knowledge graph:

```bash
curl -s -X POST http://localhost:8083/api/v1/shared/promote \
  -H "Content-Type: application/json" \
  -H "X-Workspace-ID: ws-demo" \
  -H "X-Agent-ID: agent-demo" \
  -d '{"text": "LLMs benefit from structured memory retrieval"}' | jq .
```

Search shared memory (routes through Graphiti when enabled):

```bash
curl -s -X POST http://localhost:8083/api/v1/shared/search \
  -H "Content-Type: application/json" \
  -H "X-Workspace-ID: ws-demo" \
  -H "X-Agent-ID: agent-demo" \
  -d '{"query": "memory retrieval", "limit": 5}' | jq .
```

### 8d. Enterprise-compat MCP endpoint

The `memory-api` exposes a Model Context Protocol JSON-RPC endpoint at `POST /mcp`.

List available tools:

```bash
curl -s -X POST http://localhost:8083/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | jq .tools[].name
```

Call a tool (e.g. `recall_memory`):

```bash
curl -s -X POST http://localhost:8083/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "recall_memory",
      "arguments": {
        "workspace_id": "ws-demo",
        "agent_id": "agent-demo",
        "query": "memory retrieval",
        "limit": 5
      }
    }
  }' | jq .result
```

---

## 9. Key Service URLs (dev)

| Service | URL |
|---|---|
| Temporal UI | http://localhost:8088 |
| Prometheus | http://localhost:9090 |
| Qdrant dashboard | http://localhost:6333/dashboard |
| MinIO console | http://localhost:9001 |
| connector-registry API | http://localhost:8082/v1 |
| Ollama API | http://localhost:11434 |
| memory-api | http://localhost:8083 |
| Neo4j browser (graphiti profile) | http://localhost:7474 |
| Graphiti server (graphiti profile) | http://localhost:8100 |

---

## 10. Tear Down

```bash
# Stop and remove containers; preserve volumes (data survives restart)
docker compose down

# Full teardown including volumes
docker compose down -v

# Stop graphiti profile services only
docker compose --profile graphiti down
```
