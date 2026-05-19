# Research: MEMRAG — Production Memory, RAG & BYOD Knowledge Platform

**Phase 0 — Resolved Unknowns**  
**Branch**: `001-memrag-production-memory`  
**Date**: 2026-05-14

All items below were marked as NEEDS CLARIFICATION during plan drafting and are now resolved.
Each entry records the decision taken, the rationale, and alternatives considered.

---

## 1. Hybrid Search Implementation for Layer 2

**Question**: Mem0 SDK does not expose a hybrid (dense + sparse) search API. FR-004 requires
hybrid search. Can we use Mem0 for recall, or must we implement recall ourselves?

**Decision**: Implement custom hybrid recall for Layer 2. Mem0 SDK is scoped to **store**
and **LLM-based fact extraction only**. Layer 2 recall uses direct Qdrant queries with
dense embedding vectors (qwen3-embedding:4b via Ollama) and sparse BM25 vectors, fused via
Reciprocal Rank Fusion (RRF) using Qdrant's native `sparse_vector` + hybrid query API.

**Rationale**: Qdrant ≥1.7 natively supports hybrid search with named vector types. Mem0's
recall path is a pure cosine-similarity dense search that cannot be extended. Writing
recall directly against Qdrant's API is straightforward and keeps Mem0's extraction and
deduplication (the parts of Mem0 that add real value) intact.

**Alternatives considered**:
- Accept Mem0 recall as-is (dense only): rejected — FR-004 is explicit; keyword-heavy queries
  (error codes, hostnames) perform poorly without sparse component.
- Replace Mem0 entirely with custom extraction: rejected — Mem0's LLM-driven fact extraction
  (episodic/semantic tagging, contradiction detection) is valuable and well-tested.

---

## 2. Qdrant Consistency Model

**Question**: FR-009 edge case implies "no partial or corrupt data" after a failed sync.
Qdrant does not support ACID multi-document transactions. How is this reconciled?

**Decision**: Use eventual consistency via content-hash idempotency (FR-013). The pipeline
makes no "no partial writes" promise. After a failed sync, on retry, `KnowledgeSyncState`
content hashes skip already-indexed resources and only attempt un-committed ones. Eventual
consistency is guaranteed within one subsequent successful sync cycle.

**Rationale**: Qdrant's per-point upsert is atomic; the failure mode is a missed upsert
(not a corrupt upsert). Content-hash idempotency is sufficient for correctness.

**Alternatives considered**:
- Two-phase commit with a staging collection: rejected — significant complexity, no material
  correctness improvement over idempotent retry.

---

## 3. Slack Ingestion Floor and Real-Time Access

**Question**: Original spec had conflicting floors (24h vs 7 days). Architecture doc shows
a 7–30 day window. What is the canonical rule?

**Decision**:
- **Ingestion floor**: 7 days (messages ≥ 7 days old at sync time are indexed).
- **Ingestion ceiling**: None (all messages ≥ 7 days from configured channels are indexed).
- **Recent messages (< 7 days)**: Not ingested. Accessible only via registered MCP Slack
  tool calls at agent runtime (`conversations.history` with a fresh bot token).
- This is a product policy decision, not a technical limitation. It cannot be changed
  through connector configuration.

**Rationale**: A 7-day floor balances freshness (recent messages may be volatile, corrected,
or superseded) against usefulness (week-old discussions carry established signal). Removing
the 30-day ceiling avoids artificially excluding historical channel content.

**Alternatives considered**:
- 24h floor: rejected — contradicted by architecture doc and team preference.
- Keep 30-day ceiling: rejected — no clear reason to discard older indexed messages.

---

## 4. Connector Management API Scope

**Question**: FR-030 HITL requires an operator to call an endpoint to approve/abort a
halted workflow. No such API was in scope initially.

**Decision**: Scope in a minimal connector management REST API (FR-032). Endpoints:
- `POST /connectors` — create connector
- `GET /connectors` — list connectors for workspace
- `GET /connectors/{id}` — get connector detail
- `PATCH /connectors/{id}` — update connector config
- `DELETE /connectors/{id}` — remove connector
- `GET /connectors/{id}/status` — sync status + last error
- `PATCH /connectors/{id}/pii-review` — HITL approve/abort

**Rationale**: Without the HITL endpoint, FR-030 cannot be tested end-to-end. The REST API
is minimal (7 endpoints) and fits naturally in the existing `connector-registry` Go service.

---

## 5. Confluence OAuth 2.0 3-LO in Test Mode

**Question**: Implementing a full OAuth 3-LO server in the `confluence-api-mock` is
non-trivial. Is a simplified auth bypass acceptable?

**Decision**: Full OAuth 3-LO implementation required in the mock. The mock must implement:
- `GET /oauth/authorize` — return auth code redirect
- `POST /oauth/token` — exchange code for access + refresh tokens
- `POST /oauth/token` (with `grant_type=refresh_token`) — token refresh
- Paginated CQL search and page content endpoints

**Rationale**: Confluence OAuth is the primary use case for BYOD. The connector code must
exercise the real OAuth flow in CI. A bypass would leave the most critical production path
untested. The mock is a one-time implementation cost with high long-term CI value.

---

## 6. `contains_pii` Default Value

**Question**: FR-030 references the flag but never specifies a safe default.

**Decision**: Default = `false`. Workspace admins must explicitly set `contains_pii=true`
for sources known to contain PII.

**Rationale**: A `false` default means any PII detection in an undeclared source triggers
an immediate halt and HITL review — the most conservative and safe behaviour. A `true`
default would silently apply redaction rules to all sources, which could mask unexpected
PII exposure in sources the admin believed were clean.

---

## 7. Recall Latency Measurement ("under normal load")

**Question**: SC-001 referenced "normal load" without a concrete definition.

**Decision**: Remove the vague qualifier. Instrument recall latency via Prometheus histogram
`memory_recall_latency_seconds` with labels `{layer, workspace_id}`. The 500ms p95 target
is validated from the histogram. Load conditions are defined operationally from Prometheus
data during the operations phase (deferred).

**Implementation**: All agent-worker and context-hydrator containers expose `/metrics`.
Key histograms: `memory_recall_latency_seconds`, `context_hydration_assembly_ms`.

---

## 8. SC-004 Test Mechanism

**Question**: SC-004 says "within one workflow round-trip" — this is not a wall-clock bound
and is difficult to assert in a test.

**Decision**: Validate via **async integration test**:
1. Run Agent A's `store_memory_with_promotion` activity; await Temporal workflow completion.
2. Start Agent B's workflow immediately after.
3. Assert Agent B's assembled context contains Agent A's promoted finding within 5 seconds
   (polling assertion with 500ms intervals).

**Test framework**: Temporal's Python test harness (`temporalio.testing.WorkflowEnvironment`)
for isolated async workflow testing. Full integration test uses `docker-compose.test.yml`.

---

## 9. Memory Tombstone Archival

**Question**: A-012 mentioned "minimum threshold" for tombstoning without specifying the
value or the archival mechanism.

**Decision**:
- **Threshold**: decay score < `0.1` triggers tombstoning.
- **Archival**: Before deletion from Qdrant, tombstoned entries are written to
  `s3://memrag-archive/memory-tombstones/` as an Apache Iceberg table, partitioned by
  `workspace_id` and `tombstone_date`.
- Iceberg write uses PyIceberg + boto3; local dev uses MinIO as S3-compatible backend.
- The `DecayMemoriesWorkflow` manages this in two phases: (1) write to Iceberg, (2) delete
  from Qdrant. Iceberg write failure aborts the workflow without Qdrant deletion.

**Alternatives considered**:
- Soft-delete flag (keep in Qdrant, filter on queries): rejected — unbounded collection
  growth; compliance auditing requirements need cold storage separation.
- Parquet on S3 without Iceberg: rejected — no schema evolution support; Iceberg provides
  time-travel and partition pruning for compliance queries.

---

## 10. Context Hydration Weight Matrix and Layer 1 Token Budget

**Question**: FR-026 referenced a domain weight matrix; FR-027 didn't specify how Layer 1
(session turns) participates in token budget trimming.

**Decision — Weight matrix** (derived from §4.6 of `docs/memory-rag-byod-architecture.md`,
`data` domain and `slack` source type derived from architectural patterns):

| source\_type     | `code` | `ops` | `policy` | `data` |
|------------------|--------|-------|----------|--------|
| `agent_memory`   | 1.2    | 1.3   | 0.8      | 1.1    |
| `shared_memory`  | 1.0    | 1.2   | 0.9      | 1.0    |
| `github`         | 1.5    | 0.9   | 0.5      | 0.8    |
| `confluence`     | 0.6    | 1.2   | 1.5      | 1.1    |
| `rds_schema`     | 1.0    | 0.8   | 0.6      | 1.5    |
| `slack`          | 0.4    | 1.0   | 0.5      | 0.7    |

**Decision — Layer 1 token budget**:
- Session turns are **not ranked by the weight matrix**. They are always included first.
- If session turns alone overflow the token budget, the **oldest turns are removed first**
  (FIFO eviction by turn timestamp) until the session block fits.
- Scored chunks from Layers 2, 3, 4 fill the remaining budget in descending weighted score
  order. Excess chunks are dropped in ascending score order.

**Alternatives considered**:
- Assign session turns a fixed high score (e.g., 999.0) so they rank first in the unified
  sorted list: rejected — conceptually muddled; session turns are not comparable to recalled
  facts and should never be dropped due to competition with L2/L3/L4 chunks.

---

## Technology Selection Summary

| Component | Library / Service | Version / Image | Licence |
|---|---|---|---|
| Workflow orchestration | Temporal | `temporalio/auto-setup:1.24.2` | MIT |
| Vector store | Qdrant | `qdrant/qdrant:v1.9.2` | Apache 2.0 |
| Memory SDK (store/extract) | mem0ai | `>=0.1.0` | Apache 2.0 |
| Embeddings | qwen3-embedding:4b (Ollama) | ollama image, model pulled at runtime | MIT / Apache 2.0 |
| Session buffer | Redis | `redis:7.2-alpine` | BSD |
| Relational DB | PostgreSQL | `postgres:16-alpine` | PostgreSQL Licence |
| PII detection | Microsoft Presidio | `>=2.2.355` | MIT |
| Code chunking | tree-sitter | `>=0.21.0` | MIT |
| Semantic chunking | chonkie | `>=0.3.0` | MIT |
| HTML extraction | trafilatura | `>=1.8.0` | Apache 2.0 |
| Iceberg archival | pyiceberg + boto3 | `>=0.7.0` | Apache 2.0 |
| Local S3 (dev) | MinIO | `minio/minio:RELEASE.2024-05-01T01-11-10Z` | AGPL-3.0 (server) |
| Connector registry | Go 1.22 | custom service | — |
| Agent workers | Python 3.11 | custom service | — |
| Context hydrator | Python 3.11 | custom service | — |
| Knowledge ingestion | Python 3.11 | custom service | — |
| Metrics | Prometheus | `prom/prometheus:v2.52.0` | Apache 2.0 |
