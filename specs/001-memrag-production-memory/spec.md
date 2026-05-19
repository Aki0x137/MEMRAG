# Feature Specification: MEMRAG — Production Memory, RAG & BYOD Knowledge Platform

**Feature Branch**: `001-memrag-production-memory`  
**Created**: 2026-05-14  
**Status**: Draft  
**Source**: `docs/memory-rag-byod-architecture.md`

All user stories MUST include a container-native validation path and must name the Compose
services or container commands used to prove the story works.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Agent Session Memory with Durable Short-Term Buffer (Priority: P1)

A conversational AI agent is launched to investigate a production incident. During the session
it accumulates conversation turns, tool call results, and reasoning steps in a fast in-memory
buffer. If the workflow is interrupted mid-execution (crash, pause, resume), the agent can
reconstruct its full context window exactly as it was — no information is lost, and the
conversation continues without restarting from scratch.

**Why this priority**: Without a crash-safe session buffer, the entire agentic platform is
unreliable. Every higher-level memory feature depends on session continuity being solved first.

**Independent Test**: Compose services `redis`, `temporal`, `agent-workers` started.
An agent workflow is launched, an artificial interruption is triggered mid-execution, the
workflow is resumed, and the assembled context on resume matches the pre-interruption state.
Delivers value as: agents can run reliably without losing session state.

**Acceptance Scenarios**:

1. **Given** an agent workflow is executing and has accumulated 10+ conversation turns in its
   session buffer, **When** the workflow process is killed and restarted, **Then** the agent
   resumes from exactly where it left off with the full session context intact.

2. **Given** a session buffer key exists in the hot cache, **When** the session exceeds 24
   hours of inactivity, **Then** the key is automatically expired and the storage slot is
   reclaimed with no operator intervention.

3. **Given** a workflow completes normally, **When** its session buffer is inspected,
   **Then** all tool call outputs, reasoning steps, and conversation turns are present in
   order with correct timestamps.

4. **Given** an agent workflow encounters a transient service error during a reasoning step,
   **When** Temporal replays the activity, **Then** the context assembled from the session
   buffer is identical across both the original and replayed executions.

---

### User Story 2 — Agent Builds and Recalls Long-Term Memory Across Sessions (Priority: P1)

An AI agent investigates a slow-query alert on Monday. At the end of the run it saves its
findings as compact, searchable facts. On Thursday the same agent is launched for a related
alert. Before it starts reasoning, it automatically retrieves its most relevant past findings
and uses them to skip re-investigation steps. Near-identical findings from a previous run are
silently deduplicated — the memory store does not grow unboundedly with redundant entries.

**Why this priority**: Long-term per-agent memory is the core differentiator of the MEMRAG
platform. It must work reliably before cross-agent or org-wide features are layered on top.

**Independent Test**: Compose services `qdrant`, `agent-workers`, `llm-gateway` started.
Agent `db-triage` runs a workflow, produces a finding, then runs a second workflow with a
related prompt. The second run's context contains the finding from the first run, sourced from
the vector store. Proves value independently of cross-agent sharing or BYOD.

**Acceptance Scenarios**:

1. **Given** an agent completes a workflow with a substantive final answer, **When** the
   post-completion memory store runs (fire-and-forget), **Then** the finding is stored as one
   or more atomic, searchable facts — not as the raw verbose answer.

2. **Given** an agent stores a finding, **When** the same (or near-identical) finding would
   be stored again within the deduplication window, **Then** the duplicate is silently skipped
   and the memory store count does not increase.

3. **Given** an agent is launched with a new prompt, **When** the workflow starts, **Then**
   its top-5 most semantically relevant past memories are retrieved and included in the context
   before the first reasoning step begins.

4. **Given** an agent's episodic memory entry has not been accessed for 90 days, **When**
   the nightly maintenance job runs, **Then** that entry's decay score is updated and it is
   no longer returned in standard recall queries.

5. **Given** the agent memory store contains 10,000+ entries, **When** a recall query runs,
   **Then** the top-5 results are returned in under 500ms; recall quality (recall@5) MUST be
   ≥ 0.92 compared to exhaustive brute-force search on the same 10,000-entry benchmark
   fixture (ANN is inherently approximate — exact parity with full-table scan is not
   required or expected).

---

### User Story 3 — Agent Promotes Findings to Shared Workspace Memory (Priority: P2)

The DB Triage agent determines that a specific missing index is causing a recurring class of
slow queries across the platform. It promotes this finding to the shared workspace memory pool.
Later that day, the K8s Inspector agent — which knows nothing about the DB Triage agent's
work — is launched for a related incident. It automatically receives the promoted finding in
its context, avoids redundant investigation, and includes the prior finding in its response.

**Why this priority**: Cross-agent sharing multiplies the value of individual agent runs.
It requires both L1 (session) and L2 (per-agent) to be stable, so it comes after P1 stories.

**Independent Test**: Compose services `qdrant`, `agent-workers`, `llm-gateway` started.
Agent A promotes a finding tagged with a known keyword. Agent B is launched with a query
containing that keyword. Agent B's context includes the promoted finding from Agent A even
though they share no session history. Validates independently of BYOD.

**Acceptance Scenarios**:

1. **Given** an agent is configured with auto-promotion enabled, **When** it completes a
   workflow, **Then** its findings are automatically written to the shared workspace memory
   pool in addition to the per-agent store.

2. **Given** an agent invokes the `promote_finding_to_shared_knowledge` tool during a
   reasoning step, **When** the promotion is confirmed, **Then** the finding becomes
   immediately queryable by other agents in the same workspace.

3. **Given** Agent B runs a recall query against shared memory, **When** Agent A has
   previously promoted a relevant finding to the same workspace, **Then** Agent B's context
   includes that finding with its source attributed as "shared workspace memory" (not "Agent B
   personal memory").

4. **Given** a workspace contains shared memories from multiple agents, **When** an agent
   queries shared memory, **Then** only memories belonging to that workspace are returned —
   memories from other workspaces are never visible.

---

### User Story 4 — Workspace Admin Connects an External Knowledge Source (Priority: P2)

A workspace admin connects the team's GitHub repository to the MEMRAG platform. They select
which file types to include, set a daily sync schedule, and choose a PII sensitivity level.
Within 24 hours, all agents in the workspace can answer questions grounded in the codebase —
without the admin having to manually upload or index any files. Subsequent code pushes trigger
incremental re-ingestion automatically so the index stays fresh.

**Why this priority**: BYOD is the platform's primary enterprise value proposition.
It depends on P1/P2 memory infrastructure being stable.

**Independent Test**: Compose services `connector-registry`, `knowledge-ingestion`,
`qdrant`, `temporal`, `llm-gateway`, `github-api-mock` started. The mock GitHub service
implements the exact GitHub tree and contents API contracts and can simulate push webhook
events locally — no public IP or external GitHub access is required. A GitHub connector is
configured pointing at the mock. An ingestion workflow runs, chunks are written to Qdrant.
An agent workflow is launched with a query about the mock repo content. The agent's context
includes at least one chunk from the ingested repository. Validates the full BYOD pipeline
end-to-end.

**Acceptance Scenarios**:

1. **Given** an admin provides valid credentials and configuration for a GitHub repository,
   **When** the connector is saved, **Then** a full ingestion job starts automatically and
   completes within a time proportional to the repository size (see Success Criteria SC-005).

2. **Given** a webhook push event fires for a connected GitHub repository, **When** the event
   is received, **Then** only files changed in that push are re-ingested — the full repository
   is not re-processed.

3. **Given** a Confluence connector is configured for a set of spaces, **When** a daily sync
   runs, **Then** only pages modified since the last successful sync are fetched and
   re-chunked.

4. **Given** a Slack connector is configured for selected channels, **When** the sync runs,
   **Then** only messages at least 7 days old are indexed from those channels; messages less
   than 7 days old are never fetched or stored by the ingestion pipeline.

5. **Given** an RDS schema connector is configured, **When** it syncs, **Then** exactly
   table names, column definitions, data types, column comments, and foreign key relationships
   are indexed — no row data is ever fetched or stored.

6. **Given** an ingestion job for a resource completes with the same content as the previous
   sync, **When** the pipeline evaluates the content hash, **Then** the resource is skipped
   and no re-embedding or re-indexing occurs.

---

### User Story 5 — PII in Ingested Content is Automatically Detected and Handled (Priority: P2)

A Confluence page contains employee email addresses and one page accidentally contains a
PAN number. When the ingestion pipeline processes these pages, email addresses are
masked before the chunks reach the vector index. The PAN is redacted to a block
character sequence. A PII audit log records what category of sensitive data was found and
what action was taken — but the raw values are never written to any log or database. An agent
querying the knowledge base never sees raw PII in its context.

**Why this priority**: PII safety is a prerequisite to enterprise BYOD adoption.
It must work in-pipeline before any BYOD connector goes to production.

**Independent Test**: Compose services `knowledge-ingestion`, `qdrant` started. A test
document containing known synthetic PII (email, phone, PAN, password) is fed through
the PII scan activity. Verify: (a) output chunks contain no raw PII values, (b) the
`pii_audit_log` table has records with categories and actions but no raw values, (c) a chunk
containing a PASSWORD entity was dropped entirely.

**Acceptance Scenarios**:

1. **Given** a chunk contains an EMAIL address, **When** the PII scanner processes it,
   **Then** the email is replaced with the token `[EMAIL]` in the stored chunk text.

2. **Given** a chunk contains a CREDIT_CARD or BANK_ACCOUNT number, **When** the PII
   scanner processes it, **Then** the value is overwritten with block characters — this
   behaviour cannot be disabled by workspace configuration.

3. **Given** a chunk contains a PASSWORD or SECRET pattern, **When** the PII scanner
   processes it, **Then** the entire chunk is dropped and never written to the vector index.

4. **Given** a PII detection event occurs, **When** the audit record is written, **Then**
   the record contains the entity category, action taken, chunk index, and connector ID —
   but zero raw PII values.

5. **Given** a workspace admin configures a lower sensitivity level for PHONE numbers,
   **When** a chunk containing a PHONE is processed, **Then** the configured action applies
   — but CREDIT_CARD, BANK_ACCOUNT, PASSWORD, and SECRET always use their non-configurable
   actions regardless of workspace settings.

6. **Given** an admin creates a connector with `contains_pii=false`, **When** the PII
   scanner detects any entity in any chunk during ingestion, **Then** the ingestion workflow
   halts immediately, marks the connector `sync_status: pii_detected_mismatch`, and emits
   a human-confirmation event (Temporal signal); ingestion does NOT resume until an operator
   explicitly approves or aborts via the connector management API. Silent redaction does NOT
   occur when the admin declared the source to be PII-free.

---

### User Story 6 — Admins Control Who Can Query a Connected Knowledge Source (Priority: P3)

The HR team connects their Confluence space containing sensitive HR policies. By default it is
private to the HR workspace. They decide to share it with the Compliance workspace. They also
restrict which agents within their own workspace can query it — only agents tagged
`domain:hr` and `domain:compliance` can access the HR knowledge index. The Platform team
marks their public engineering runbooks as `platform_public` so all workspaces benefit
without explicit grants. Changing a sharing scope takes effect immediately for all subsequent
agent queries without re-indexing any content.

**Why this priority**: Access control gates enterprise adoption. It can be built on top of a
working BYOD pipeline (P2 stories) without requiring changes to ingestion logic.

**Independent Test**: Compose services `connector-registry`, `qdrant`, `agent-workers`
started. Two workspaces A and B configured. A source is connected in workspace A with scope
`workspace_internal`. An agent in workspace B queries the org knowledge index. Verify the
workspace A source is absent from workspace B's results. Change scope to `allowlist` with
workspace B on the allowlist. Verify the source now appears in workspace B results.

**Acceptance Scenarios**:

1. **Given** a newly connected source has its default sharing scope (`private`), **When** an
   agent in a different workspace queries the org knowledge index, **Then** no chunks from
   that source appear in the results.

2. **Given** a source's sharing scope is changed from `private` to `workspace_internal`,
   **When** an agent in the owning workspace queries org knowledge, **Then** chunks from that
   source are returned; no changes to the Qdrant index are required.

3. **Given** a source is scoped `allowlist` with workspace B granted access, **When** an
   agent in workspace B queries org knowledge, **Then** chunks from that source are returned;
   when workspace B's grant is revoked, **Then** those chunks no longer appear for workspace B
   agents within one cache-expiry interval (≤60 seconds).

4. **Given** a source has `agent_scope: by_tag` with `allowed_agent_tags: ["domain:hr"]`,
   **When** an agent tagged `domain:hr` queries the source, **Then** it receives results;
   **When** an agent without that tag queries the same source, **Then** no results from that
   source are returned.

5. **Given** a source is marked `platform_public`, **When** any agent on any workspace
   queries org knowledge, **Then** chunks from that source are always included regardless of
   any grants or workspace settings.

---

### User Story 7 — All Four Memory Layers Hydrate Agent Context in Parallel (Priority: P3)

An agent is launched to answer a question about a recurring database performance issue. In the
background, before the first reasoning step, the platform simultaneously retrieves: the
current session conversation turns (Layer 1), the agent's past findings about DB performance
(Layer 2), shared workspace insights about infrastructure components (Layer 3), and relevant
Confluence runbooks and GitHub code snippets from the connected org knowledge base (Layer 4).
By the time the first LLM call fires, all four sources have been merged, re-ranked by source
relevance to this agent's domain, trimmed to fit the context token budget, and assembled into
a single coherent system prompt with citations for org knowledge chunks.

**Why this priority**: Full context hydration requires all four layers to be independently
functional first (P1, P2, P3 stories above). This story validates the integrated assembly.

**Independent Test**: Compose services `redis`, `qdrant`, `agent-workers`, `llm-gateway`,
`context-hydrator`, `temporal` all started. An agent with past personal memories, access to
a workspace with shared memories, and at least one connected org knowledge source is launched.
Inspect the assembled system prompt and verify chunks from all four layers are present, ranked,
and within the configured token budget.

**Acceptance Scenarios**:

1. **Given** an agent workflow starts, **When** the parallel recall fan-out fires, **Then**
   all three non-session recall activities (Layer 2, 3, 4) start simultaneously and results
   from all three are awaited before the first LLM call is made.

2. **Given** all four memory layers return results, **When** context hydration assembles the
   system prompt, **Then** results are ranked using source-type weights specific to the
   agent's declared domain (code, ops, policy, data).

3. **Given** the merged context exceeds the agent's configured token budget, **When** the
   context is trimmed, **Then** the lowest-scoring chunks are removed first and the trimmed
   context still fits within the budget.

4. **Given** org knowledge chunks are included in the context, **When** the system prompt is
   assembled, **Then** each org knowledge chunk includes citation metadata (source type, URL
   or reference, title) so the agent can attribute its answers.

5. **Given** one of the three non-session recall activities times out or fails, **When** the
   hydrator assembles context, **Then** it proceeds with the available layers rather than
   failing the entire workflow — the failed layer is noted in structured logs.

---

### Edge Cases

- What happens when an agent has zero past memories (first run)? — Recall activities return
  empty lists; the workflow continues normally with only the current session context.

- What happens when Qdrant is temporarily unavailable during a recall activity? — The recall
  activity fails after its configured timeout; the workflow proceeds with available layers
  (graceful degradation per US7 AC5).

- What happens when a BYOD connector's credentials expire mid-sync? — The ingestion workflow
  activity fails with an authentication error; the connector is marked `sync_status: error`;
  an alert is emitted. Partial writes may occur but the pipeline is idempotent: on the next
  sync attempt, content-hash comparison (FR-013) skips already-indexed resources; eventual
  consistency is guaranteed within one subsequent sync cycle and no data corruption occurs.

- What happens when a PII scanner detects extremely high PII density in a document (>50% of
  chunks dropped)? — The remaining chunks are ingested normally; the PII audit log records the
  drop rate; the admin is notified via connector sync status that PII density was abnormally
  high for the source.

- What happens when two agents promote near-identical findings to shared memory
  simultaneously? — Standard deduplication applies; only one entry is stored; no race
  condition corrupts the index.

- What happens when a sharing grant is revoked while an agent workflow is mid-execution? —
  The active in-flight workflow completes with the context it already assembled; subsequent
  workflows launched after the revocation cache-expiry (≤60s) will not receive the revoked
  source's chunks.

---

## Requirements *(mandatory)*

### Functional Requirements

#### Core Memory

- **FR-001**: The system MUST persist agent findings as compact, searchable atomic facts after
  each workflow completion without blocking the workflow response.

- **FR-002**: The system MUST deduplicate new memory entries against existing memories before
  storing, using semantic similarity; near-identical entries (similarity ≥ 0.95) MUST be
  silently skipped.

- **FR-003**: The system MUST support two memory entry types — episodic (time-bound events)
  and semantic (general facts) — with distinct decay schedules (episodic: 90 days,
  semantic: 365 days of inactivity).

- **FR-004**: The system MUST recall the top-K most relevant memories for an agent before the
  first reasoning step of every workflow, using hybrid semantic + keyword search.

- **FR-005**: Agents MUST be able to promote findings to a workspace-scoped shared memory
  pool, either automatically (via manifest flag) or explicitly (via LLM-callable tool).

- **FR-006**: Cross-agent shared memory MUST be strictly scoped to the originating workspace;
  no shared memory entry from workspace A MUST ever appear in workspace B's recall results.

- **FR-007**: The session buffer MUST be durably checkpointed at each workflow activity
  boundary so the assembled context window is reconstructable after a crash or replay.
  Payloads larger than 256KB MUST be stored by reference (pointer to external storage, e.g.
  Redis or object store) rather than inlined into Temporal event history, to avoid Temporal's
  per-event and total-history size limits.

- **FR-008**: Session buffer keys MUST expire automatically after 24 hours of inactivity with
  no operator intervention required.

#### BYOD Knowledge Layer

- **FR-009**: The platform MUST support connecting external knowledge sources via a pluggable
  connector framework; each connector MUST implement authenticate, list_resources,
  and fetch_resource operations.

- **FR-010**: The platform MUST ship connectors for: GitHub repositories (code files, READMEs,
  wikis), Confluence spaces (pages), Slack channels (messages at least 7 days old from
  configured channels), and AWS RDS databases (schema metadata only — no row data).

- **FR-011**: Ingestion MUST be background-only. Agents MUST never call external source APIs
  at workflow runtime; all org knowledge access MUST go through the pre-built vector index.

- **FR-012**: The ingestion pipeline MUST support both full sync (initial or manual) and delta
  sync (incremental, for sources that provide change feeds or webhooks).

- **FR-013**: The ingestion pipeline MUST skip re-embedding any resource whose content has not
  changed since the last sync, determined by content hash comparison.

- **FR-014**: The chunking strategy MUST be content-type-aware: code files use AST-aware
  chunking at function/class boundaries; prose uses semantic chunking with overlap; database
  schemas use one-chunk-per-table templates.

- **FR-015**: The Slack connector MUST only ingest messages that are at least 7 days old at
  the time of sync, from workspace-admin-configured channels. Messages less than 7 days old
  MUST NOT be fetched or stored by the ingestion pipeline. Recent Slack messages (< 7 days
  old) MAY be accessed at agent runtime via registered MCP Slack tool calls; this is a
  distinct runtime path and does not constitute indexed knowledge.


#### PII Safety

- **FR-016**: The PII scanner MUST detect EMAIL, PHONE, PERSON_NAME, PAN, UPI ID, DEMAT ID,
  CREDIT_CARD, BANK_ACCOUNT, IP_ADDRESS, HEALTH_INFO, PASSWORD, and SECRET entity categories.

- **FR-017**: CREDIT_CARD and BANK_ACCOUNT entities MUST always be redacted (replaced with
  block characters). This behaviour MUST NOT be overridable by workspace configuration.

- **FR-018**: PASSWORD and SECRET pattern matches MUST always cause the containing chunk to
  be dropped entirely. This behaviour MUST NOT be overridable by workspace configuration.

- **FR-019**: All other PII entity categories MUST have configurable actions (mask, redact, or
  drop) settable at the workspace connector level.

- **FR-020**: The system MUST write a PII audit record for every detection event, recording:
  entity category, action taken, chunk index, connector ID, and timestamp. The audit record
  MUST NOT contain any raw PII values.

#### Knowledge Sharing & Access Control

- **FR-021**: Every connected knowledge source MUST have a sharing scope: `private` (default),
  `workspace_internal`, `allowlist`, or `platform_public`. Scope changes MUST take effect
  within one cache-expiry interval (≤60 seconds) for all new agent queries with no
  re-indexing required.

- **FR-022**: Sharing scope MUST be enforced at query time via vector store payload filtering;
  agents MUST only receive chunks their workspace is authorised to access.

- **FR-023**: Workspace admins MUST be able to restrict query access to specific agents within
  their own workspace by agent ID or agent tag; unmatched agents MUST receive zero results
  from that source.

- **FR-024**: The platform MUST cache active sharing grants per workspace with a maximum
  staleness of 60 seconds to avoid per-query database round-trips. Cache expiry is passive
  (Redis 60s TTL on the `grants:{workspace_id}` key); no active cache invalidation is issued
  on grant changes. A brief over-access window of up to 60 seconds after a revocation event
  is an accepted design tradeoff.

#### Context Hydration

- **FR-025**: At workflow start, the platform MUST fan out recall across all three vector-based
  memory layers (per-agent, shared, org knowledge) in parallel; all three MUST be awaited
  before the first LLM call.

- **FR-026**: Context hydration MUST apply source-type and agent-domain weights when ranking
  merged results from all four layers. When `AgentManifest.domain` is not set, all
  source-type weights MUST default to 1.0 (uniform weighting); domain-specific weights
  only apply when `domain` is explicitly set to one of: `code`, `ops`, `policy`, `data`.
  The canonical weight matrix (derived from §4.6 of the architecture doc) is:

  | source\_type     | `code` | `ops` | `policy` | `data` |
  |------------------|--------|-------|----------|--------|
  | `agent_memory`   | 1.2    | 1.3   | 0.8      | 1.1    |
  | `shared_memory`  | 1.0    | 1.2   | 0.9      | 1.0    |
  | `github`         | 1.5    | 0.9   | 0.5      | 0.8    |
  | `confluence`     | 0.6    | 1.2   | 1.5      | 1.1    |
  | `rds_schema`     | 1.0    | 0.8   | 0.6      | 1.5    |
  | `slack`          | 0.4    | 1.0   | 0.5      | 0.7    |

  `agent_memory`/`shared_memory` rows are Layers 2/3; remaining rows are Layer 4.
  The `data` domain column and `slack` source row are derived from architecture doc
  patterns; all other values are taken directly from §4.6. Layer 1 session turns are
  not ranked by this matrix — see FR-027.

- **FR-027**: Context hydration MUST enforce a per-agent configurable token budget. Layer 1
  session turns are exempt from score-based trimming and are always included first; if session
  turns alone exceed the remaining budget, the oldest turns are removed first. Scored chunks
  from Layers 2, 3, and 4 are then filled into the remaining budget in descending score order;
  excess chunks are removed in ascending score order until the budget is satisfied.

- **FR-028**: Org knowledge chunks included in the assembled context MUST carry citation
  metadata (source type, URL or reference, title).

- **FR-029**: If any individual recall activity fails or times out, context hydration MUST
  proceed with the available layers — a single layer failure MUST NOT abort the workflow.

- **FR-030**: When creating a connector, the workspace admin MUST declare a `contains_pii`
  boolean flag indicating whether the source may contain personal or sensitive data. The
  default value of `contains_pii` is `false` — workspace admins MUST explicitly set it to
  `true` for sources known to contain PII; this opt-in model ensures PII-bearing sources are
  handled by configured redaction rules rather than triggering a halt on first detection.
  If `contains_pii=false` and the PII scanner detects any entity during ingestion, the
  ingestion workflow MUST halt, set connector `sync_status: pii_detected_mismatch`, and
  await a human-confirmation signal before resuming or aborting. Silent redaction MUST NOT
  occur in this case — the mismatch is a consent violation requiring explicit operator
  acknowledgement. This requirement is inspired by the "detect-and-hold" pattern used by
  enterprise LLM platforms (OpenAI Enterprise, Google Vertex AI DLP integration).

- **FR-031**: All connector, ingestion, and agent-worker services MUST support an
  `ENVIRONMENT=test|production` runtime flag. In `test` mode, external connector APIs
  (GitHub, Confluence, Slack, RDS) MUST be served by local mock services that implement
  the exact same API contracts. In `production` mode, live external APIs are used. Code
  MUST function correctly against both without modification beyond the flag. The
  `confluence-api-mock` Compose service MUST implement the complete Confluence OAuth 2.0
  3-LO flow (authorisation code endpoint, token exchange, and token refresh) in addition to
  paginated CQL search and page content endpoints, enabling full end-to-end connector testing
  without a live Atlassian instance (see A-018).

- **FR-032**: The platform MUST expose a connector management REST API providing: connector
  CRUD operations (`POST/GET/PATCH/DELETE /connectors`), connector sync status retrieval
  (`GET /connectors/{id}/status`), and a HITL review endpoint
  (`PATCH /connectors/{id}/pii-review`) that accepts `{"action": "approve" | "abort"}` to
  resume or cancel a halted `pii_detected_mismatch` ingestion workflow. This API is required
  to fulfil the HITL signal flow in FR-030. The UI/frontend for this API remains out of scope.

### Key Entities

- **AgentMemory**: A single atomic fact stored per agent. Has type (episodic/semantic),
  decay score, creation timestamp, and last-accessed timestamp. Scoped to
  `(workspace_id, agent_id)`.

- **SharedMemory**: A promoted finding stored at workspace scope. Queryable by any agent
  within the workspace. Sourced from an agent's completed workflow.

- **KnowledgeConnector**: Configuration record for one connected external source. Holds
  source type, credential reference, crawl configuration, PII configuration, sharing scope,
  and sync schedule. Scoped to a workspace.

- **KnowledgeSyncState**: Per-resource delta sync state record. Records content hash and last
  sync timestamp to enable idempotent incremental ingestion.

- **KnowledgeChunk**: A single indexed document fragment. Carries text, embedding vector,
  source metadata (type, URL, title), PII flag, sharing scope, and agent scope filters.

- **KnowledgeSharingGrant**: An active or pending allowlist grant from one workspace to
  another for a specific connector. Has lifecycle: pending → active → revoked.

- **PIIAuditRecord**: An immutable append-only record of a PII detection event. Contains
  entity category, action, chunk index, connector ID, and timestamp. Never contains raw
  PII values.

- **AgentManifest** (extended): The per-agent configuration object extended to include
  knowledge source filter, top-K override, context token budget, auto-promotion flag, and
  agent domain (code / ops / policy / data).

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An agent that has run at least once can retrieve its most relevant past findings
  at the start of a new workflow within 500ms (p95), measured from the moment the parallel
  recall fan-out starts via the `memory_recall_latency_seconds` Prometheus histogram (labels:
  `layer`, `workspace_id`). Load conditions for p95 measurement are defined operationally
  from observed Prometheus histogram data (quantification deferred to operations phase).

- **SC-002**: Memory deduplication prevents unbounded growth: on a synthetic test corpus of
  10,000 workflow runs where 90% of outputs are within 0.95 cosine similarity of a prior
  entry, the memory store contains no more than 1,100 entries after all runs complete
  (≤11% unique storage rate). Measured against this specific benchmark fixture; no general
  uniqueness guarantee is implied for corpora with different similarity distributions.

- **SC-003**: An agent workflow interrupted mid-execution resumes with its full pre-interruption
  context intact — all Temporal activity outputs and session buffer contents are recoverable
  — with no manual operator intervention required. Large payloads are stored by reference
  (see FR-007) and retrieved on resume; the reconstructed context is semantically identical
  to the pre-interruption state.

- **SC-004**: A finding promoted to shared workspace memory by Agent A is available in Agent
  B's recall results within one workflow round-trip after promotion (i.e., without requiring
  any additional triggers or manual steps). Validated via async integration test: Agent A's
  promotion workflow is awaited to completion; Agent B's workflow is then started and its
  assembled context is asserted to contain the promoted finding (polling with up to 5-second
  timeout).

- **SC-005**: In `production` mode on a host with GPU-resident embedding (NVIDIA RTX 3080
  or equivalent), a GitHub repository of 1,000 files completes initial full ingestion in
  under 10 minutes; a delta sync for a push event with 10 changed files completes in under
  90 seconds. In `test` mode (CPU and on device dedicated GPU if available, mock services), no ingestion throughput SLA applies
  — only functional correctness is verified.

- **SC-006**: The PII pipeline correctly handles all entities in the defined synthetic test
  corpus (EMAIL, PHONE, PAN, CREDIT_CARD, BANK_ACCOUNT, PASSWORD), where each
  entity is crafted to match Presidio's built-in recogniser patterns. Zero raw PII values
  appear in the vector index or audit log. Detection coverage outside the synthetic corpus
  is best-effort; Presidio false-negative rates for unlabelled credentials, locale-specific
  PAN IDs, and PII embedded in code comments are acknowledged and out of scope for
  this criterion.

- **SC-007**: A sharing scope change (e.g., `private` → `workspace_internal`) propagates to
  all new agent queries within 60 seconds with no re-indexing or service restart required.

- **SC-008**: When one of the three vector recall activities fails at workflow start,
  the remaining workflow completes successfully and delivers a response to the caller — the
  failure of one recall layer does not fail the workflow.

- **SC-009**: Context hydration for an agent with results from all four memory layers
  assembles a token-budget-compliant system prompt in under 200ms (p95), measured from when
  all recall results are available to when the assembled prompt is ready for the first LLM
  call.

- **SC-010**: A source connected by workspace A with scope `private` never appears in any
  query result from workspace B agents — validated across 1,000 random cross-workspace query
  pairs in the test suite.

---

## Assumptions

- **A-001**: The platform runs in a single-region, local-dev-first environment using
  Docker Compose. Production targets AWS but the Compose stack is the canonical entrypoint
  for all development and integration testing.

- **A-002**: All LLM inference (embedding generation, memory extraction LLM, agent reasoning
  LLM) runs through a local LLM gateway backed by Ollama-served models. No external cloud
  LLM APIs are required for local operation.

- **A-003**: Temporal is the workflow orchestration layer for both agent execution
  (AgentWorkflow) and knowledge ingestion (IngestionWorkflow). No other orchestration
  framework is used.

- **A-004**: Qdrant is the sole vector store. Three collections are used: `agent_memories`
  (per-agent long-term), `shared_memories` (cross-agent workspace), `org_knowledge` (BYOD).
  PostgreSQL with pgvector is retained for non-vector relational data (workflow events, cost
  tracking, connector registry, PII audit log).

- **A-005**: Mem0 SDK wraps per-agent memory **store** and LLM-based fact extraction for
  Layer 2. **Recall** for Layer 2 bypasses Mem0 and uses direct Qdrant queries with a custom
  hybrid search implementation (dense embedding + sparse BM25 vectors, fused via RRF),
  enabling FR-004 hybrid search while preserving Mem0's extraction and deduplication logic.
  Layers 3 and 4 use direct Qdrant queries with custom filter and hybrid search logic.

- **A-006**: Redis serves as the in-session hot buffer (Layer 1) with 24-hour TTL. No
  alternative key-value store is considered.

- **A-007**: Connector credentials are stored by reference only (path to a secrets store
  entry, not the raw secret value) in the connector registry database. For local development,
  a local secrets mock is used; AWS Secrets Manager is the production secrets provider.

- **A-008**: Graphiti temporal knowledge graph (for relationship-aware cross-agent memory) is
  explicitly deferred to a future phase. This spec does not include Graphiti.

- **A-009**: The Slack connector indexes messages from admin-configured channels that are at
  least 7 days old at the time of sync. There is no maximum age ceiling — all messages older
  than 7 days from configured channels are eligible for indexing. Messages less than 7 days
  old are never fetched or stored by the ingestion pipeline; this is a product policy
  decision, not a technical limitation, and cannot be changed through connector configuration.
  Recent messages MAY be accessed at agent runtime via registered MCP Slack tool calls
  (FR-015).

- **A-010**: For the initial BYOD connector set, only GitHub, Confluence, Slack, and AWS RDS
  schema are supported. Additional connector types (Snowflake, BigQuery, SharePoint, Notion)
  are deferred to a subsequent feature increment.

- **A-011**: When `AgentManifest.domain` is not set, context hydration applies uniform
  source-type weights (1.0 for all sources). Domain-specific weights from the weight matrix
  (Section 4.6 of architecture doc) only activate when `domain` is explicitly one of:
  `code`, `ops`, `policy`, `data`.

- **A-012**: The memory decay maintenance job is implemented as a Temporal cron workflow
  (`DecayMemoriesWorkflow`, scheduled `0 2 * * *` UTC). It runs a `decay_memories_batch`
  activity that updates decay scores for episodic entries older than 90 days and semantic
  entries older than 365 days since last access, then tombstones entries with a decay score
  below `0.1` so they are excluded from standard recall queries. Tombstoned entries are
  archived to an S3 bucket in Apache Iceberg table format
  (`s3://memrag-archive/memory-tombstones/`) before deletion from the Qdrant collection,
  enabling cold-storage retrieval and compliance auditing.

- **A-013**: Sharing grant cache invalidation uses passive Redis TTL expiry (60s TTL on
  `grants:{workspace_id}`). No active cache purge is issued when a grant is created or
  revoked. Up to 60 seconds of over-access after revocation is an accepted tradeoff in
  exchange for simplicity. If this tradeoff becomes unacceptable, active invalidation can
  be added without changing the spec's functional requirements.

- **A-014**: `workspace_id` in this spec maps 1:1 to `tenant_id` in the a1-agent-engine
  codebase (`services/agent-workers/models.py`, `workflows.py`). They represent the same
  isolation boundary. MEMRAG uses `workspace_id` as the canonical term; `tenant_id` is
  retained as an alias in legacy schemas and activity signatures.

- **A-015**: Mem0 SDK performs deduplication at the individual extracted-fact level. When a
  finding is decomposed into N atomic facts, each fact is independently checked against
  existing entries (similarity ≥ 0.95 → skip). Partial storage (some facts new, some
  skipped) is the expected normal case. The store operation always returns success regardless
  of how many facts were stored vs. skipped; no per-fact result is surfaced to callers.

- **A-016**: When `promote_to_shared=true`, findings are stored in BOTH `agent_memories`
  and `shared_memories` Qdrant collections independently. Per-collection dedup applies
  within each collection but not across them — near-identical content may coexist in both.
  This is intentional: the two collections serve distinct recall paths.

- **A-017**: For local development and integration testing, a `github-api-mock` service
  implementing the GitHub REST API contract (tree, contents, webhooks) is provided as a
  Compose service. The GitHub connector is written against the API contract and works
  against both the mock and the live GitHub API, selected by `ENVIRONMENT` flag.

- **A-018**: A `confluence-api-mock` Compose service is provided for `ENVIRONMENT=test` mode.
  It implements the Confluence REST API including: OAuth 2.0 3-LO flow (authorisation code
  endpoint, token exchange endpoint, and token refresh endpoint), paginated CQL content search
  (`/wiki/rest/api/content/search`), and page content fetch
  (`/wiki/rest/api/content/{id}?expand=body.storage`). This mock eliminates the need for a
  live Atlassian instance in CI and local development, and is the primary test path for the
  Confluence connector (FR-031).

- **A-019**: All agent-worker and context-hydrator services expose Prometheus metrics on
  `/metrics`. Key instrumentation includes the `memory_recall_latency_seconds` histogram
  (per-layer, per-`workspace_id`) and the `context_hydration_assembly_ms` histogram.
  Grafana dashboards are deferred to the operations phase; metric collection is required
  from initial deployment.

---

## Out of Scope

- Graphiti temporal knowledge graph integration (see Section 9 of architecture doc — explicitly
  deferred).
- Snowflake, BigQuery, SharePoint, Notion, or other BYOD connector types beyond the initial
  four (GitHub, Confluence, Slack, RDS schema).
- Real-time Slack message ingestion (messages < 7 days old are never indexed by the ingestion
  pipeline — by design; recent messages are accessible via MCP tool calls at agent runtime).
- Pre-indexing of database row data from any relational source into the knowledge vector
  index (row data MAY be queried live at agent runtime via registered MCP database tools;
  see FR-015).
- Multi-region deployment, active-active failover, or horizontal Qdrant clustering.
- UI/frontend for the connector management admin interface (API-first; UI is a separate
  feature).
- Email or push notification delivery for sync error alerts (alerts emitted to structured
  logs only in this increment).

---

## Clarifications

### Session 2026-05-14

- Q: Edge case — no partial data promise: Qdrant has no transactions → A: Use eventual consistency; content-hash idempotency ensures no corruption; partial writes are acknowledged, retried cleanly; eventual consistency guaranteed within one subsequent sync cycle.
- Q: FR-004 hybrid search incompatible with Mem0 SDK recall (A-005) → A: Write hybrid recall ourselves; Mem0 for store/extraction only; Layer 2 recall = direct Qdrant with custom dense+sparse hybrid (BM25, fused via RRF).
- Q: FR-015 24h floor vs A-009/US4 AC4 7-day floor inconsistency for Slack → A: Ingestion floor = 7 days; messages < 7 days available via MCP tool calls only; no upper age ceiling on ingestion.
- Q: FR-030 HITL depends on connector management API that was Out of Scope → A: Scope it in; minimal connector management REST API (CRUD, status, HITL approval endpoint PATCH /connectors/{id}/pii-review).
- Q: FR-031 Confluence OAuth 3-LO mock disproportionately complex → A: Full implementation required; confluence-api-mock must implement complete OAuth 3-LO flow; Confluence ingestion is the primary use case.
- Q: `contains_pii` default value unspecified → A: Default = `false` (safe default; forces explicit opt-in for PII-bearing sources).
- Q: SC-001 "under normal load" undefined → A: Add Prometheus metrics (`memory_recall_latency_seconds` histogram) for recall latency measurement; load definition deferred to operations phase.
- Q: SC-004 "one workflow round-trip" not a wall-clock bound — how to test? → A: Async integration tests; Agent A promotion awaited to completion, Agent B workflow started, context polled for finding (up to 5-second timeout).
- Q: Tombstone threshold + archival mechanism undefined (A-012) → A: Archive to S3 Apache Iceberg (`s3://memrag-archive/memory-tombstones/`) before deletion from Qdrant; threshold = decay score < 0.1.
- Q: Token budget Layer 1 session turns have no score; FR-027 trim ordering undefined → A: Session turns exempt from score-based trimming (oldest removed first if over budget); scored chunks from L2/L3/L4 fill remaining budget; weight matrix derived from §4.6 of architecture doc with `data` domain and `slack` source type added.
