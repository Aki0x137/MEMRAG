"""MEMRAG Memory API — unified HTTP service for all 4 memory layers.

Layers handled by this service:
  L1 — Session buffer   : GET/POST /api/v1/session/{id}/turns      (Redis)
  L2 — Agent memory     : POST /api/v1/memories[/search]           (Qdrant)
  L3 — Shared memory    : POST /api/v1/shared[/search]             (Qdrant)

Header contract (all stateful endpoints):
  X-Workspace-ID  — primary workspace/tenant identifier
  X-Tenant-ID     — legacy alias; accepted wherever X-Workspace-ID is accepted
  X-Agent-ID      — required on all stateful endpoints including L1
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from memrag_shared.infra.ollama_client import get_client as get_ollama
from memrag_shared.infra.qdrant_client import get_client as get_qdrant
from memrag_shared.infra.redis_client import get_client as get_redis
from memrag_shared.memory.mem0_client import extract_and_store
from memrag_shared.memory.shared import promote_to_shared
from memrag_shared.recall.layer2 import recall_agent_memory
from memrag_shared.recall.layer3 import recall_shared_memory
from memrag_shared.session.session import checkpoint_session, fetch_recent_session

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="MEMRAG Memory API", version="0.2.0")


@app.on_event("startup")
async def _ensure_qdrant_collections() -> None:  # pragma: no cover
    """Create agent_memories and shared_memories collections when app starts.

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

    for col in ("agent_memories", "shared_memories"):
        if col not in existing:
            qdrant.create_collection(
                collection_name=col,
                vectors_config={"dense": qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE)},
                sparse_vectors_config={"sparse": qmodels.SparseVectorParams()},
            )
            log.info("Created Qdrant collection '%s' (dim=%d)", col, dim)


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
    agent_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None


class SearchMemoriesRequest(BaseModel):
    query: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
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
    if request.agent_id != agent_id:
        raise HTTPException(
            status_code=400,
            detail="X-Agent-ID header must match the agent_id in the request body",
        )
    stored_ids = await extract_and_store(
        agent_id=request.agent_id,
        workspace_id=workspace_id,
        text=request.content,
    )
    if not stored_ids:
        return {"stored": False, "reason": "duplicate"}
    return {"stored": True, "stored_ids": stored_ids}


@app.post("/api/v1/memories/search", response_model=list[str])
async def search_memories(
    request: SearchMemoriesRequest,
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-ID"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_agent_id: str | None = Header(default=None, alias="X-Agent-ID"),
) -> list[str]:
    workspace_id = _resolve_workspace(x_workspace_id, x_tenant_id)
    agent_id = _require_agent_id(x_agent_id)
    if request.agent_id != agent_id:
        raise HTTPException(
            status_code=400,
            detail="X-Agent-ID header must match the agent_id in the request body",
        )
    chunks = await recall_agent_memory(
        workspace_id=workspace_id,
        agent_id=request.agent_id,
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
    from memrag_shared.infra.ollama_client import get_client as get_ollama

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