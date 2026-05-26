<!--
Sync Impact Report for Constitution v1.0.0
Version: Template → 1.0.0 (MAJOR: Initial MEMRAG constitution)
Created: 2026-05-14
Changes:
	- Core Principles: 5 principles established for container-only runtime, uv, contracts, GPU-resident model operations, and container-native validation
	- Infrastructure Requirements: defined mandatory technologies, container runtime policy, configuration, secrets, and observability rules
	- Development Workflow: compose-first local development and container-based testing
	- Governance: amendment process, versioning, and compliance review requirements

Templates updated:
	- plan-template.md: ✅ added container/GPU constitution gate
	- spec-template.md: ✅ added container-native acceptance requirement
	- tasks-template.md: ✅ added container build and compose validation tasks
-->

# MEMRAG Constitution

**Technology Stack**: Docker Compose, pinned container images, uv inside containers, Python 3.11+, MCP, local model runtime (for example Ollama), Qdrant, PostgreSQL  
**Environment**: Container-native development and deployment  
**Goal**: Establish non-negotiable standards for this memory, RAG, and BYOD architecture

---

## Core Principles

### I. Container-Only Runtime Architecture (NON-NEGOTIABLE)

Every service, script, worker, and tool MUST execute inside Docker. The host may start
Compose, edit files, and inspect logs, but runtime execution, dependency installation,
linting, testing, and model serving MUST happen in containers.

**Standards**:
- Each logical runtime component MUST appear as a named service in `docker-compose.yml`
- The full stack MUST start from `docker compose up` and stop cleanly with Compose
- Service commands, helper scripts, and maintenance tasks MUST have container execution paths
- All services MUST define health checks
- Dependent services MUST use `depends_on: condition: service_healthy`
- Image tags MUST be pinned; `latest` tags are forbidden
- Named volumes MUST persist durable state across restarts
- `.env` files MUST provide runtime variables; no hardcoded secrets or host-specific paths in compose
- `.dockerignore` MUST exclude git, cache, test outputs, and venv directories

**Rationale**: Container isolation keeps local, CI, and deployment behavior identical and
removes environment drift.

---

### II. Dependency Management via uv (NON-NEGOTIABLE)

Python dependencies MUST be locked and installed only inside container images or
running containers using `uv`.

**Standards**:
- `pyproject.toml` MUST define all dependencies with version constraints
- `uv.lock` MUST be committed to git and reviewed in all PRs
- Development tools (`pytest`, `ruff`, `mypy`) MUST be in the dev dependency group
- No `pip install` commands are allowed on the host
- Base images MUST use a Python 3.11+ slim variant (for example, `python:3.11-slim`)
- Dependency regeneration MUST happen inside the containerized workflow before merge
- Container build steps MUST avoid unpinned package installs

**Rationale**: Reproducible, auditable, fast environment builds with deterministic
dependency state.

---

### III. Service and Tool Contracts MUST Be Explicit

All service interfaces, MCP tools, ingestion endpoints, and background job inputs MUST define formal request and response schemas.

**Standards**:
- Every service or tool endpoint MUST be documented with input and output schemas
- All endpoints MUST return consistent structured responses
- Inputs MUST be validated before execution; validation errors MUST fail fast with a clear message
- Contract changes MUST be versioned and reviewed before deployment
- Breaking schema changes MUST bump the major version; additive optional fields MUST bump the minor version
- Integration tests MUST verify contract adherence

**Rationale**: MEMRAG relies on stable interfaces between orchestrators, workers, and
tooling; explicit contracts prevent silent failures and breaking changes.

---

### IV. Local Model Operations MUST Be GPU-Resident and Air-Gappable

All inference, embeddings, and model-serving calls MUST run inside containers and MUST
use the GPU when available. No host model runtime and no cloud LLM dependency may be
used for core execution.

**Standards**:
- Any local model runtime service MUST reserve NVIDIA devices in Compose when GPU inference is required
- Inference services MUST fail fast if GPU access is unavailable
- Model pulls MUST happen inside containers and persist in named volumes
- No API keys to external LLM providers may be used for core execution
- Configuration MUST use environment variables for host, port, and model names
- Fallback model specifications MUST exist in code when env vars are missing
- Network calls are allowed only for approved scraping or data sources; cloud AI APIs are blocked
- Metrics MAY be collected locally; they MUST NOT be sent to external monitoring by default

**Rationale**: GPU-first containerization protects privacy, controls cost, and keeps core
agent execution available offline once models are cached.

---

### V. Testing & Validation MUST Be Container-Native

All tests, linting, type checks, and smoke checks MUST run inside Docker Compose or a
Compose-launched container.

**Standards**:
- Test suite MUST be organized in `tests/` with a structure mirroring the source tree
- Unit tests MUST run in the app container: `docker compose exec app pytest tests/unit/`
- Integration tests MUST run with the full compose stack: `docker compose -f docker-compose.test.yml up --exit-code-from app`
- Linting and type checks MUST run in containers, not on the host
- Test databases MUST be ephemeral and wiped before each test run
- Code coverage MUST be measured in CI; target ≥75% for core modules
- Failing tests MUST block PR merges through CI or hooks
- External HTTP calls MUST be mocked; fixtures MUST include representative samples

**Rationale**: Container-native validation proves the same environment that ships and
prevents host-only drift from hiding failures.

---

## Infrastructure Requirements

### Mandatory Technologies

| Component | Version | Rationale |
|---|---|---|
| Python | 3.11+ | Modern language features, async support, performance |
| Docker | 20.10+ | Container runtime, NVIDIA support |
| Docker Compose | 2.0+ | Service orchestration, health checks, named volumes |
| uv | Latest stable | Fast, reliable, lock-file based dependency management inside containers |
| Local model runtime | Pinned image tag | Local GPU model serving and caching |
| Qdrant | Pinned image tag | Vector DB, on-disk persistence, cosine distance |
| PostgreSQL | 16+ | Relational storage for connector registry, audit metadata, workflow state, and pgvector-backed compatibility paths |
| MCP | Project-defined | Stable tool and service interfaces |

### Recommended Tools

- **Testing**: `pytest`, `pytest-asyncio`, `pytest-cov`
- **Linting**: `ruff` (fast, minimal config)
- **Type checking**: `mypy` (strict mode enforced)
- **Code formatting**: `black` (pyproject.toml: line-length=100)
- **Pre-commit hooks**: `.pre-commit-config.yaml` (ruff, mypy, pytest on staged files)
- **Monitoring**: `prometheus-client` (metrics export, local Prometheus optional)

### Container Runtime Policy

- `docker-compose.yml` MUST be the single runtime entrypoint for the stack
- Every logical service, worker, and tool MUST have a container command path
- Runtime images MUST be pinned to explicit versions; `latest` is forbidden
- Compose services MUST define health checks and use `depends_on: condition: service_healthy`
- Persistent state MUST use named volumes only
- GPU inference services MUST declare NVIDIA reservations in Compose

### Configuration & Secrets MUST Follow 12-Factor App Principles

All dynamic settings MUST be environment variables or config files mounted into
containers; no hardcoded values or host-specific paths are allowed.

**Standards**:
- `OLLAMA_HOST`, `QDRANT_HOST`, and model names MUST be configurable via env vars
- `.env` files MUST NOT be committed; `.env.example` MUST document all required vars
- Secrets (DB credentials, API keys if ever used) MUST use Docker secrets or mounted files, never images
- Compose files MUST avoid host-specific absolute paths where a portable relative path works
- Configuration precedence MUST be: environment variables > `.env` file > code defaults
- Config schema MUST be defined with a Pydantic `Settings` class or YAML schema
- Runtime validation MUST fail startup if required config is missing
- Log level (DEBUG, INFO, WARNING, ERROR) MUST be configurable per service

**Rationale**: Portable configuration keeps the same container stack usable across dev,
test, and production without code changes.

### Observability & Logging MUST Be Structured

Logs MUST be machine-readable JSON; human readability is secondary.

**Standards**:
- Logging MUST use Python `logging` with a JSON formatter (for example, `python-json-logger`)
- Every log line MUST include timestamp, level, module, function, message, and context
- Service execution MUST log: service name, model used when relevant, latency, and status
- Tool calls MUST log: tool name, input, output, execution time, success/error status
- Errors MUST include full traceback; sensitive data MUST be redacted
- Log level DEBUG MUST be safe to enable in production and MUST not dump payloads
- Container logs MUST be collected via `docker logs` or stdout/stderr
- No log files may be written to disk inside containers

**Rationale**: Distributed debugging requires structured logs that can be aggregated and
filtered without relying on host-local files.

---

## Development Workflow

### Local Development

1. Clone repo
2. Copy `.env.example` to `.env` and fill required values
3. Build and start the full stack: `docker compose up -d --build`
4. Check health: `docker compose ps` (all HEALTHY)
5. Run tests: `docker compose exec app pytest tests/`

### Code Changes & Testing

- Feature branch: `git checkout -b feature/my-feature`
- Make changes, commit with descriptive message
- Run linter in container: `docker compose exec app ruff check --fix src/`
- Run type checker in container: `docker compose exec app mypy src/ --strict`
- Run tests in container: `docker compose exec app pytest tests/ -v`
- Verify no logs errors: `docker compose logs --tail=50 app | grep ERROR`
- Commit tests + source together, never test-only commits
- PR title MUST be clear and describe the user-facing change

### Before Merge

- All tests pass in CI through Compose-based runs
- Code coverage ≥75% for modified modules
- No hardcoded values, all config via env vars
- Dockerfile and compose changes must keep health checks and dependency ordering aligned
- Compose config MUST validate with `docker compose config`
- GPU reservation must remain present for inference services
- uv.lock must be updated if dependencies changed
- Constitution compliance verified (see Governance section)

---

## Governance

### Constitution Authority

This constitution supersedes all ad-hoc practices, confluence docs, and team conventions.
Any conflicts resolved in favor of constitution; team MUST follow.

### Amendment Process

1. **Proposal**: Open issue with title `CONSTITUTION` + detailed rationale
2. **Discussion**: Minimum 2 days for team feedback; document objections
3. **Decision**: Consensus preferred; majority approval if consensus blocked
4. **Version Bump**:
	 - MAJOR: Principle removed or fundamentally redefined
	 - MINOR: New principle or significant clarification
	 - PATCH: Wording improvements, typo fixes
5. **Implementation**: Update constitution file, all dependent templates, and guidance docs
6. **Enforcement**: Next sprint enforces updated rules; retroactive changes flagged in PRs

### Compliance Verification

- **Pre-commit hook** MUST validate: pyproject.toml syntax, Docker Compose config, Dockerfile best practices, env var naming
- **CI MUST verify**: All tests pass in Compose, code coverage ≥75%, no hardcoded secrets
- **Code review MUST check**: contract stability, config management, logging standards, container healthchecks, GPU reservations for inference services
- **Monthly audit**: Spot-check PRs against principles; document any violations

### Non-Compliance Response

1. First violation: Issue flagged, author asked to remediate
2. Second violation (same principle): Mandatory sync with tech lead before merge
3. Third violation: Escalate to project lead; may block PR

---

## References & Runbooks

- **Runtime Guidance**: See `docs/memory-rag-byod-architecture.md` for the architecture and execution model
- **Project Overview**: See `README.md`

---

**Version**: 1.0.0 | **Ratified**: 2026-05-14 | **Last Amended**: 2026-05-14
