"""MEMRAG Memory API — unified HTTP service for all 4 memory layers.

Layers handled by this service:
  L1 — Session buffer   : GET/POST /api/v1/session/{id}/turns      (Redis)
  L2 — Agent memory     : POST /api/v1/memories[/search]           (Qdrant)
  L3 — Shared memory    : POST /api/v1/shared[/search]             (Qdrant/Graphiti)
  L4 — Org knowledge    : POST /api/v1/knowledge/search            (Qdrant)
  Assembly              : POST /api/v1/hydrate                     (all 4 layers)
  Ingestion trigger     : POST /api/v1/ingest                      (Temporal signal)
  MCP endpoint          : GET|POST /mcp                            (JSON-RPC 2025-06-18)

Header contract (all stateful endpoints):
  X-Workspace-ID  — primary workspace/tenant identifier
  X-Tenant-ID     — legacy alias; accepted wherever X-Workspace-ID is accepted
  X-Agent-ID      — required on all stateful endpoints including L1
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from memrag_shared.assembler import HydrateRequest as AssemblerRequest
from memrag_shared.assembler import assemble
from memrag_shared.infra.ollama_client import get_client as get_ollama
from memrag_shared.infra.qdrant_client import get_client as get_qdrant
from memrag_shared.infra.redis_client import get_client as get_redis
from memrag_shared.memory.graphiti import store_with_graphiti
from memrag_shared.memory.mem0_client import extract_and_store
from memrag_shared.memory.sparse import sparse_vector
from memrag_shared.memory.shared import promote_to_shared
from memrag_shared.recall.layer2 import recall_agent_memory
from memrag_shared.recall.layer3 import recall_shared_memory
from memrag_shared.recall.layer3_graphiti import recall_shared_graphiti
from memrag_shared.recall.layer4 import recall_org_knowledge
from memrag_shared.session.session import checkpoint_session, fetch_recent_session

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics (optional — silently absent when prometheus_client not
# installed so tests don't need it)
# ---------------------------------------------------------------------------

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

    _hydration_ms = Histogram(
        "context_hydration_assembly_ms",
        "Time to assemble hydrated context (ms)",
        labelnames=["workspace_id", "domain"],
    )
    _chunks_dropped = Counter(
        "context_hydration_chunks_dropped_total",
        "Chunks dropped due to token budget overflow",
        labelnames=["workspace_id", "layer"],
    )
    _PROMETHEUS_ENABLED = True
except Exception:  # pragma: no cover  # ImportError or registry collision
    _PROMETHEUS_ENABLED = False


# ---------------------------------------------------------------------------
# MCP tool definitions (JSON-RPC 2025-06-18 spec)
# ---------------------------------------------------------------------------

_MCP_TOOLS: list[dict] = [
    {
        "name": "recall_memory",
        "description": "Recall agent-specific long-term memories from Qdrant.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["workspace_id", "agent_id", "query"],
        },
    },
    {
        "name": "store_memory",
        "description": "Store a new memory in long-term agent storage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["workspace_id", "agent_id", "text"],
        },
    },
    {
        "name": "promote_finding",
        "description": "Promote a finding to workspace-shared memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["workspace_id", "agent_id", "text"],
        },
    },
    {
        "name": "search_knowledge",
        "description": "Search the organisation knowledge base (L4).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "agent_id": {"type": "string"},
                "query": {"type": "string"},
                "agent_tags": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["workspace_id", "agent_id", "query"],
        },
    },
]

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

async def _ensure_qdrant_collections() -> None:  # pragma: no cover
    """Create memory collections when app starts.

    The vector dimensions are discovered by issuing a single test embedding so
    they always match the configured OLLAMA_EMBED_MODEL.
    """
    import logging
    from qdrant_client.http import models as qmodels

    log = logging.getLogger(__name__)
    try:
        test_vecs = await get_ollama().embed(["init"])
        dim = len(test_vecs[0])
    except Exception as exc:  # noqa: BLE001
        log.warning("Skipping Qdrant collection init — Ollama unavailable: %s", exc)
        return

    qdrant = get_qdrant()
    try:
        existing = {c.name for c in qdrant.get_collections().collections}
    except Exception as exc:  # noqa: BLE001
        log.warning("Skipping Qdrant collection init — Qdrant unavailable: %s", exc)
        return

    for col in ("agent_memories", "shared_memories", "org_knowledge"):
        if col not in existing:
            qdrant.create_collection(
                collection_name=col,
                vectors_config={"dense": qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE)},
                sparse_vectors_config={"sparse": qmodels.SparseVectorParams()},
            )
            log.info("Created Qdrant collection '%s' (dim=%d)", col, dim)


@asynccontextmanager
async def _lifespan(_: FastAPI):
    await _ensure_qdrant_collections()
    yield


app = FastAPI(title="MEMRAG Memory API", version="0.3.0", lifespan=_lifespan)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    if not _PROMETHEUS_ENABLED:
        raise HTTPException(status_code=404, detail="Metrics unavailable")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Header helpers
# ---------------------------------------------------------------------------


def _resolve_workspace(
    x_workspace_id: str | None,
    x_tenant_id: str | None,
) -> str:
    """Return the effective workspace ID from either header.

    Raises 400 when neither header is present.
    """
    workspace_id = x_workspace_id or x_tenant_id
    if not workspace_id:
        raise HTTPException(
            status_code=400,
            detail="Either X-Workspace-ID or X-Tenant-ID header is required",
        )
    return workspace_id


def _require_agent_id(x_agent_id: str | None) -> str:
    if not x_agent_id:
        raise HTTPException(
            status_code=400,
            detail="X-Agent-ID header is required",
        )
    return x_agent_id


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/healthz")
@app.get("/health")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# L1 — Session buffer
# ---------------------------------------------------------------------------


class TurnItem(BaseModel):
    role: str = Field(min_length=1)
    content: str = Field(min_length=1)


class CheckpointRequest(BaseModel):
    turns: list[TurnItem]


@app.get("/api/v1/session/{session_id}/turns")
async def get_session_turns(
    session_id: str,
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_agent_id: str | None = Header(default=None, alias="X-Agent-ID"),
) -> list[dict[str, Any]]:
    workspace_id = _resolve_workspace(x_workspace_id, x_tenant_id)
    _require_agent_id(x_agent_id)
    redis = get_redis()
    return fetch_recent_session(workspace_id, session_id, redis)


@app.post("/api/v1/session/{session_id}/turns", status_code=200)
async def post_session_turns(
    session_id: str,
    body: CheckpointRequest,
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_agent_id: str | None = Header(default=None, alias="X-Agent-ID"),
) -> dict[str, Any]:
    workspace_id = _resolve_workspace(x_workspace_id, x_tenant_id)
    _require_agent_id(x_agent_id)
    redis = get_redis()
    turns_raw = [t.model_dump() for t in body.turns]
    checkpoint_session(workspace_id, session_id, turns_raw, redis)
    return {"session_id": session_id, "stored": len(turns_raw)}


# ---------------------------------------------------------------------------
# L2 — Agent (long-term) memory
# ---------------------------------------------------------------------------


class StoreMemoryRequest(BaseModel):
    agent_id: str | None = None
    content: str | None = None
    text: str | None = None
    metadata: dict[str, Any] | None = None

    def resolved_content(self) -> str:
        content = self.content or self.text
        if not content:
            raise HTTPException(
                status_code=422,
                detail="Either content or text must be provided",
            )
        return content


class SearchMemoriesRequest(BaseModel):
    query: str = Field(min_length=1)
    agent_id: str | None = None
    limit: int = Field(default=8, ge=1, le=50)


@app.post("/api/v1/memories")
async def store_memory(
    request: StoreMemoryRequest,
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_agent_id: str | None = Header(default=None, alias="X-Agent-ID"),
) -> dict[str, Any]:
    workspace_id = _resolve_workspace(x_workspace_id, x_tenant_id)
    agent_id = _require_agent_id(x_agent_id)
    request_agent_id = request.agent_id or agent_id
    if request.agent_id and request.agent_id != agent_id:
        raise HTTPException(
            status_code=400,
            detail="X-Agent-ID header must match the agent_id in the request body",
        )
    content = request.resolved_content()
    stored_ids = await extract_and_store(
        agent_id=request_agent_id,
        workspace_id=workspace_id,
        text=content,
    )
    if not stored_ids:
        return {
            "status": "ok",
            "agent_id": request_agent_id,
            "stored": False,
            "reason": "duplicate",
            "stored_ids": [],
            "stored_count": 0,
        }
    return {
        "status": "ok",
        "agent_id": request_agent_id,
        "stored": True,
        "stored_ids": stored_ids,
        "stored_count": len(stored_ids),
    }


@app.post("/api/v1/memories/search", response_model=list[str])
async def search_memories(
    request: SearchMemoriesRequest,
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_agent_id: str | None = Header(default=None, alias="X-Agent-ID"),
) -> list[str]:
    workspace_id = _resolve_workspace(x_workspace_id, x_tenant_id)
    agent_id = _require_agent_id(x_agent_id)
    request_agent_id = request.agent_id or agent_id
    if request.agent_id and request.agent_id != agent_id:
        raise HTTPException(
            status_code=400,
            detail="X-Agent-ID header must match the agent_id in the request body",
        )
    chunks = await recall_agent_memory(
        workspace_id=workspace_id,
        agent_id=request_agent_id,
        query_text=request.query,
        top_k=request.limit,
    )
    return [chunk.text for chunk in chunks]


# ---------------------------------------------------------------------------
# L3 — Shared (workspace) memory
# ---------------------------------------------------------------------------


class PromoteFindingRequest(BaseModel):
    text: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None


class SearchSharedRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=50)


class SearchKnowledgeRequest(BaseModel):
    query: str = Field(min_length=1)
    agent_tags: list[str] = Field(default_factory=list)
    limit: int = Field(default=8, ge=1, le=50)


@app.post("/api/v1/shared")
async def promote_finding(
    request: PromoteFindingRequest,
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_agent_id: str | None = Header(default=None, alias="X-Agent-ID"),
) -> dict[str, Any]:
    workspace_id = _resolve_workspace(x_workspace_id, x_tenant_id)
    agent_id = _require_agent_id(x_agent_id)
    if request.agent_id != agent_id:
        raise HTTPException(
            status_code=400,
            detail="X-Agent-ID header must match the agent_id in the request body",
        )
    graphiti_enabled = os.getenv("GRAPHITI_ENABLED", "false").lower() == "true"
    if graphiti_enabled:
        storage_backend = await store_with_graphiti(
            workspace_id=workspace_id,
            finding_text=request.text,
            episode_metadata=request.metadata,
        )
        if storage_backend == "qdrant":
            # Graphiti returned "qdrant" fall-through — also store in Qdrant
            embedding = (await get_ollama().embed([request.text]))[0]
            storage_backend = await promote_to_shared(
                workspace_id=workspace_id,
                source_agent_id=agent_id,
                text=request.text,
                embedding=embedding,
            )
        return {"status": storage_backend}

    # GRAPHITI_ENABLED=false: Qdrant-only path (unchanged behaviour)
    embedding = (await get_ollama().embed([request.text]))[0]
    status = await promote_to_shared(
        workspace_id=workspace_id,
        source_agent_id=agent_id,
        text=request.text,
        embedding=embedding,
    )
    return {"status": status}


@app.post("/api/v1/shared/search", response_model=list[dict])
async def search_shared(
    request: SearchSharedRequest,
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_agent_id: str | None = Header(default=None, alias="X-Agent-ID"),
) -> list[dict[str, Any]]:
    workspace_id = _resolve_workspace(x_workspace_id, x_tenant_id)
    _require_agent_id(x_agent_id)
    graphiti_enabled = os.getenv("GRAPHITI_ENABLED", "false").lower() == "true"
    if graphiti_enabled:
        try:
            chunks = await recall_shared_graphiti(
                workspace_id=workspace_id,
                query_text=request.query,
                top_k=request.limit,
            )
        except Exception:  # noqa: BLE001
            log.exception("Graphiti recall failed — returning empty L3 list")
            chunks = []
    else:
        chunks = await recall_shared_memory(
            workspace_id=workspace_id,
            query_text=request.query,
            top_k=request.limit,
        )
    return [
        {
            "text": c.text,
            "source_type": c.source_type,
            "score": c.score,
            "workspace_id": c.workspace_id,
        }
        for c in chunks
    ]


# ---------------------------------------------------------------------------
# L4 — Organization knowledge
# ---------------------------------------------------------------------------


@app.post("/api/v1/knowledge/search", response_model=list[dict])
async def search_knowledge(
    request: SearchKnowledgeRequest,
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_agent_id: str | None = Header(default=None, alias="X-Agent-ID"),
) -> list[dict[str, Any]]:
    workspace_id = _resolve_workspace(x_workspace_id, x_tenant_id)
    agent_id = _require_agent_id(x_agent_id)
    chunks = await recall_org_knowledge(
        workspace_id=workspace_id,
        agent_id=agent_id,
        agent_tags=request.agent_tags,
        query_text=request.query,
        top_k=request.limit,
    )
    return [
        {
            "text": chunk.text,
            "title": chunk.title,
            "source_type": chunk.source_type,
            "score": chunk.score,
            "url": chunk.url,
            "connector_id": chunk.connector_id,
            "workspace_id": chunk.org_id,
        }
        for chunk in chunks
    ]


# ---------------------------------------------------------------------------
# Context Hydration — POST /api/v1/hydrate
# ---------------------------------------------------------------------------


class HydrateRequestBody(BaseModel):
    session_id: str = Field(min_length=1)
    agent_id: str | None = None
    query: str = Field(min_length=1)
    domain: str | None = None
    token_budget: int = Field(default=4096, ge=100, le=32768)
    agent_tags: list[str] = Field(default_factory=list)


@app.post("/api/v1/hydrate")
async def hydrate(
    body: HydrateRequestBody,
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_agent_id: str | None = Header(default=None, alias="X-Agent-ID"),
) -> dict[str, Any]:
    workspace_id = _resolve_workspace(x_workspace_id, x_tenant_id)
    agent_id = _require_agent_id(x_agent_id)
    request_agent_id = body.agent_id or agent_id
    if body.agent_id and body.agent_id != agent_id:
        raise HTTPException(
            status_code=400,
            detail="X-Agent-ID header must match agent_id in request body",
        )

    failed_layers: list[str] = []
    graphiti_enabled = os.getenv("GRAPHITI_ENABLED", "false").lower() == "true"
    query_embedding = (await get_ollama().embed([body.query]))[0]
    query_sparse = sparse_vector(body.query)

    # ── L1: session turns from Redis ──────────────────────────────────────────
    async def _get_l1() -> list[dict]:
        try:
            return fetch_recent_session(workspace_id, body.session_id, get_redis())
        except Exception:  # noqa: BLE001
            return []

    # ── L2: agent memories ───────────────────────────────────────────────────
    async def _get_l2() -> list:
        try:
            result = await recall_agent_memory(
                workspace_id=workspace_id,
                agent_id=request_agent_id,
                query_text=body.query,
                top_k=8,
                dense_embedding=query_embedding,
                sparse_payload=query_sparse,
            )
            return result
        except Exception:  # noqa: BLE001
            failed_layers.append("layer2")
            return []

    # ── L3: shared memory (Qdrant or Graphiti) ────────────────────────────────
    async def _get_l3() -> list:
        try:
            if graphiti_enabled:
                result = await recall_shared_graphiti(
                    workspace_id=workspace_id,
                    query_text=body.query,
                    top_k=8,
                )
            else:
                result = await recall_shared_memory(
                    workspace_id=workspace_id,
                    query_text=body.query,
                    top_k=8,
                    dense_embedding=query_embedding,
                    sparse_payload=query_sparse,
                )
            return result
        except Exception:  # noqa: BLE001
            layer_label = "graphiti" if graphiti_enabled else "layer3"
            failed_layers.append(layer_label)
            return []

    # ── L4: org knowledge ────────────────────────────────────────────────────
    async def _get_l4() -> list:
        try:
            result = await recall_org_knowledge(
                workspace_id=workspace_id,
                agent_id=request_agent_id,
                agent_tags=body.agent_tags,
                query_text=body.query,
                top_k=8,
                dense_embedding=query_embedding,
                sparse_payload=query_sparse,
            )
            return result
        except Exception:  # noqa: BLE001
            failed_layers.append("layer4")
            return []

    t_start = time.monotonic()
    l1_turns, l2_chunks, l3_chunks, l4_chunks = await asyncio.gather(
        _get_l1(), _get_l2(), _get_l3(), _get_l4()
    )
    assembly_ms = (time.monotonic() - t_start) * 1000.0

    if _PROMETHEUS_ENABLED:
        _hydration_ms.labels(
            workspace_id=workspace_id,
            domain=body.domain or "none",
        ).observe(assembly_ms)

    req = AssemblerRequest(
        workspace_id=workspace_id,
        session_id=body.session_id,
        agent_id=request_agent_id,
        query=body.query,
        domain=body.domain,
        token_budget=body.token_budget,
        agent_tags=body.agent_tags,
        session_turns=l1_turns,
        agent_memories=l2_chunks,
        shared_memories=l3_chunks,
        org_knowledge=l4_chunks,
    )
    response = assemble(req, failed_layers=failed_layers)

    if _PROMETHEUS_ENABLED:
        for layer_name, count in {
            "layer2": len(l2_chunks),
            "layer3": len(l3_chunks),
            "layer4": len(l4_chunks),
        }.items():
            dropped = count - response.layer_stats.get(
                f"{layer_name}_chunks", count
            )
            if dropped > 0:
                _chunks_dropped.labels(
                    workspace_id=workspace_id, layer=layer_name
                ).inc(dropped)

    layer_stats = dict(response.layer_stats)
    layer_stats.update(
        {
            "layer1": layer_stats.get("layer1_turns", 0),
            "layer2": layer_stats.get("layer2_chunks", 0),
            "layer3": layer_stats.get("layer3_chunks", 0),
            "layer4": layer_stats.get("layer4_chunks", 0),
        }
    )

    return {
        "system_prompt": response.system_prompt,
        "token_count": response.token_count,
        "layer_stats": layer_stats,
        "failed_layers": response.failed_layers,
        "citations": [
            {
                "source_type": c.source_type,
                "title": c.title,
                "url": c.url,
                "connector_id": c.connector_id,
                "chunk_index": c.chunk_index,
            }
            for c in response.citations
        ],
    }


# ---------------------------------------------------------------------------
# BYOD ingestion trigger — POST /api/v1/ingest
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    connector_id: str = Field(min_length=1)
    sync_mode: str = Field(default="delta")


@app.post("/api/v1/ingest", status_code=202)
async def trigger_ingest(
    body: IngestRequest,
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_agent_id: str | None = Header(default=None, alias="X-Agent-ID"),
) -> dict[str, Any]:
    """Signal a BYOD IngestionWorkflow via Temporal (or return 501 if unavailable)."""
    workspace_id = _resolve_workspace(x_workspace_id, x_tenant_id)
    _require_agent_id(x_agent_id)

    temporal_host = os.getenv("TEMPORAL_HOST", "")
    if not temporal_host:
        raise HTTPException(
            status_code=501,
            detail="Temporal not configured — TEMPORAL_HOST env var is not set",
        )

    try:
        import temporalio.client as temporal_client_mod  # type: ignore[import]

        client = await temporal_client_mod.Client.connect(temporal_host)
        handle = client.get_workflow_handle_for(
            workflow_id=f"ingestion-{body.connector_id}"
        )
        await handle.signal("sync_now", body.sync_mode)
        return {
            "queued": True,
            "connector_id": body.connector_id,
            "workspace_id": workspace_id,
            "sync_mode": body.sync_mode,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"Temporal signal failed: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# MCP endpoint — GET|POST /mcp  (JSON-RPC 2025-06-18 spec)
# ---------------------------------------------------------------------------


@app.get("/mcp")
@app.post("/mcp")
async def mcp_endpoint(request: Request) -> dict[str, Any]:
    """Minimal JSON-RPC 2025-06-18 MCP handler.

    Supports:
      * ``initialize``      — returns server capabilities + tool list
      * ``tools/list``      — returns the four MEMRAG MCP tools
      * ``tools/call``      — dispatches one of the four tools
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    method = payload.get("method", "")
    rpc_id = payload.get("id", 1)

    def _ok(result: Any) -> dict:
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    def _err(code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": code, "message": message},
        }

    if method in ("initialize", "mcp/initialize"):
        return _ok(
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "MEMRAG Memory API", "version": "0.3.0"},
                "tools": _MCP_TOOLS,
            }
        )

    if method == "tools/list":
        return _ok({"tools": _MCP_TOOLS})

    if method == "tools/call":
        params = payload.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        try:
            content = await _dispatch_mcp_tool(tool_name, arguments)
            return _ok({"content": [{"type": "text", "text": content}]})
        except HTTPException as exc:
            return _err(-32600, exc.detail)
        except Exception as exc:  # noqa: BLE001
            return _err(-32603, str(exc))

    return _err(-32601, f"Method not found: {method}")


async def _dispatch_mcp_tool(name: str, args: dict[str, Any]) -> str:
    """Execute an MCP tool and return a plain-text result."""
    if name == "recall_memory":
        workspace_id = args["workspace_id"]
        agent_id = args["agent_id"]
        query = args["query"]
        limit = int(args.get("limit", 8))
        chunks = await recall_agent_memory(
            workspace_id=workspace_id,
            agent_id=agent_id,
            query_text=query,
            top_k=limit,
        )
        return "\n---\n".join(c.text for c in chunks) or "(no results)"

    if name == "store_memory":
        workspace_id = args["workspace_id"]
        agent_id = args["agent_id"]
        text = args["text"]
        ids = await extract_and_store(
            agent_id=agent_id,
            workspace_id=workspace_id,
            text=text,
        )
        return "stored" if ids else "duplicate"

    if name == "promote_finding":
        workspace_id = args["workspace_id"]
        agent_id = args["agent_id"]
        text = args["text"]
        embedding = (await get_ollama().embed([text]))[0]
        result = await promote_to_shared(
            workspace_id=workspace_id,
            source_agent_id=agent_id,
            text=text,
            embedding=embedding,
        )
        return str(result)

    if name == "search_knowledge":
        workspace_id = args["workspace_id"]
        agent_id = args["agent_id"]
        query = args["query"]
        agent_tags = args.get("agent_tags", [])
        limit = int(args.get("limit", 8))
        chunks = await recall_org_knowledge(
            workspace_id=workspace_id,
            agent_id=agent_id,
            agent_tags=agent_tags,
            query_text=query,
            top_k=limit,
        )
        return "\n---\n".join(c.text for c in chunks) or "(no results)"

    raise HTTPException(status_code=400, detail=f"Unknown tool: {name}")
