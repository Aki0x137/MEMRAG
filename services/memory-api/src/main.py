"""FastAPI compatibility service for MEMRAG Layer 2 memory operations."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


_ROOT = Path(__file__).resolve().parents[3]
_MEM0_CLIENT_PATH = _ROOT / "services" / "agent-workers" / "src" / "memory" / "mem0_client.py"
_LAYER2_PATH = _ROOT / "services" / "agent-workers" / "src" / "recall" / "layer2.py"


def _load_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {module_name} from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MEM0_CLIENT = _load_module("mem0_client", _MEM0_CLIENT_PATH)
_LAYER2 = _load_module("layer2", _LAYER2_PATH)

extract_and_store = _MEM0_CLIENT.extract_and_store
recall_agent_memory = _LAYER2.recall_agent_memory


class StoreMemoryRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None


class SearchMemoriesRequest(BaseModel):
    query: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=50)


app = FastAPI(title="MEMRAG Memory API", version="0.1.0")


def _validate_agent_headers(body_agent_id: str, x_agent_id: str) -> None:
    if body_agent_id != x_agent_id:
        raise HTTPException(
            status_code=400,
            detail="X-Agent-ID header must match the agent_id in the request body",
        )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/memories")
async def store_memory(
    request: StoreMemoryRequest,
    x_workspace_id: str = Header(alias="X-Workspace-ID"),
    x_agent_id: str = Header(alias="X-Agent-ID"),
) -> dict[str, Any]:
    _validate_agent_headers(request.agent_id, x_agent_id)
    stored_ids = await extract_and_store(
        agent_id=request.agent_id,
        workspace_id=x_workspace_id,
        text=request.content,
    )
    return {
        "status": "ok",
        "agent_id": request.agent_id,
        "stored_count": len(stored_ids),
        "stored_ids": stored_ids,
    }


@app.post("/api/v1/memories/search", response_model=list[str])
async def search_memories(
    request: SearchMemoriesRequest,
    x_workspace_id: str = Header(alias="X-Workspace-ID"),
    x_agent_id: str = Header(alias="X-Agent-ID"),
) -> list[str]:
    _validate_agent_headers(request.agent_id, x_agent_id)
    chunks = await recall_agent_memory(
        workspace_id=x_workspace_id,
        agent_id=request.agent_id,
        query_text=request.query,
        top_k=request.limit,
    )
    return [chunk.text for chunk in chunks]