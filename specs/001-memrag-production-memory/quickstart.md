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

The `llm-gateway` container pulls models from the GPU-resident Ollama container automatically
on first start. To pull manually:

```bash
docker compose exec ollama ollama pull qwen3-embedding:4b
docker compose exec ollama ollama pull gemma4:12b
```

---

## 4. Run Database Migrations

```bash
# PostgreSQL migrations (Alembic)
docker compose exec connector-registry python -m alembic upgrade head
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

### Unit tests (inside container)

```bash
docker compose exec agent-workers pytest tests/unit/ -v
```

### Integration tests (full Compose run)

```bash
docker compose -f docker-compose.test.yml up --exit-code-from app --abort-on-container-exit
```

Integration tests start a dedicated `ENVIRONMENT=test` stack with mock external services
(`github-api-mock`, `confluence-api-mock`).

---

## 8. Key Service URLs (dev)

| Service | URL |
|---|---|
| Temporal UI | http://localhost:8088 |
| Prometheus | http://localhost:9090 |
| Qdrant dashboard | http://localhost:6333/dashboard |
| MinIO console | http://localhost:9001 |
| connector-registry API | http://localhost:8082/v1 |
| Ollama API | http://localhost:11434 |

---

## 9. Tear Down

```bash
# Stop and remove containers; preserve volumes (data survives restart)
docker compose down

# Full teardown including volumes
docker compose down -v
```
