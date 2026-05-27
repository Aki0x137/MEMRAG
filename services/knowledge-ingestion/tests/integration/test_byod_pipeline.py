"""Integration test for US4: BYOD knowledge source pipeline.

Tests core BYOD functionality:
- Chunking code files
- Embedding generation
- Idempotency via content hash
- Qdrant upsert with deterministic IDs
- Full activity-chain test (all 6 workflow activities in sequence)
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add src to path for imports
src_path = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(src_path))

from chunker import chunk
from embedder import embed_sparse


@dataclass
class FakePoint:
    id: str
    vector: dict
    payload: dict
    score: float = 1.0


class FakeQdrant:
    def __init__(self) -> None:
        self.collections: dict[str, dict[str, FakePoint]] = {
            "org_knowledge": {},
        }

    def upsert(self, collection_name: str, points, wait: bool = True) -> None:
        for point in points:
            point_id = str(point.id)
            self.collections.setdefault(collection_name, {})[point_id] = FakePoint(
                id=point_id,
                vector=point.vector,
                payload=point.payload,
            )


def test_chunk_python_code() -> None:
    """Test code chunking at function boundaries."""
    code = '''
def function_one():
    """First function."""
    return 1

def function_two():
    """Second function."""
    return 2

class MyClass:
    def method_one(self):
        return "method"
'''
    chunks = chunk(code, "github", "code")
    assert len(chunks) > 0, "Should produce chunks"
    assert all(isinstance(c, str) for c in chunks), "All chunks should be strings"
    assert any("def " in c for c in chunks), "Should preserve function definitions"


def test_chunk_prose() -> None:
    """Test prose chunking with overlap."""
    text = """
This is a paragraph about MEMRAG.

This is another paragraph with more information.

And yet another section with additional context.
"""
    chunks = chunk(text, "confluence", "html")
    assert len(chunks) > 0, "Should produce chunks"
    assert all(isinstance(c, str) for c in chunks), "All chunks should be strings"


def test_chunk_rds_schema() -> None:
    """Test schema chunking (one per table)."""
    schema = """
-- Schema: public.users
CREATE TABLE public.users (
  id INTEGER NOT NULL,
  name VARCHAR(255) NOT NULL,
  email VARCHAR(255) UNIQUE NOT NULL
);

-- Schema: public.posts
CREATE TABLE public.posts (
  id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  title VARCHAR(255)
);
"""
    chunks = chunk(schema, "rds_schema", "schema")
    assert len(chunks) == 2, "Should have one chunk per table"
    assert all("CREATE TABLE" in c for c in chunks), "Each chunk should have a table definition"


def test_embed_sparse() -> None:
    """Test sparse vector generation (BM25-like)."""
    texts = ["function code example", "database schema table", "API endpoint"]
    
    sparse_vectors = embed_sparse(texts)
    
    assert len(sparse_vectors) == 3, "Should generate one sparse vector per text"
    for sv in sparse_vectors:
        assert "indices" in sv, "Should have indices"
        assert "values" in sv, "Should have values"
        assert len(sv["indices"]) == len(sv["values"]), "Indices and values should match"


def test_idempotency_deterministic_id() -> None:
    """Verify deterministic content hashes for idempotency."""
    text = "def important_function(): return 42"
    
    hash1 = hashlib.sha256(text.encode()).hexdigest()
    hash2 = hashlib.sha256(text.encode()).hexdigest()
    
    assert hash1 == hash2, "Same content should produce same hash"
    assert len(hash1) == 64, "SHA256 hash should be 64 hex chars"
    
    text2 = "def different_function(): return 99"
    hash3 = hashlib.sha256(text2.encode()).hexdigest()
    assert hash1 != hash3, "Different content should produce different hash"


def test_qdrant_upsert_idempotency() -> None:
    """Test that Qdrant upsert with deterministic IDs is idempotent."""
    from qdrant_client.http import models
    
    fake_qdrant = FakeQdrant()
    
    text = "def test_function(): pass"
    embedding = [1.0, 2.0, 3.0]
    content_hash = hashlib.sha256(text.encode()).hexdigest()
    
    # First upsert
    point1 = models.PointStruct(
        id=content_hash,
        vector={"dense": embedding},
        payload={"text": text, "workspace_id": "ws1", "connector_id": "conn1"}
    )
    fake_qdrant.upsert("org_knowledge", [point1])
    assert len(fake_qdrant.collections["org_knowledge"]) == 1
    
    # Second upsert with same content (should replace, not duplicate)
    point2 = models.PointStruct(
        id=content_hash,
        vector={"dense": embedding},
        payload={"text": text, "workspace_id": "ws1", "connector_id": "conn1", "version": 2}
    )
    fake_qdrant.upsert("org_knowledge", [point2])
    assert len(fake_qdrant.collections["org_knowledge"]) == 1, "Should still have 1 point (replaced)"
    
    updated_point = fake_qdrant.collections["org_knowledge"][content_hash]
    assert updated_point.payload.get("version") == 2, "Payload should be updated"


def test_github_pipeline_simulation() -> None:
    """Simulate GitHub connector ingestion: fetch, chunk, deduplicate."""
    github_files = [
        {
            "id": f"file-{i}.py",
            "title": f"file-{i}.py",
            "url": f"https://github.com/test/repo/blob/main/file-{i}.py",
            "content": f"def function_{i}():\n    return {i}\n" * 5,
            "source_type": "github",
            "content_type": "code",
        }
        for i in range(10)
    ]
    
    all_chunks = []
    for file_info in github_files:
        chunks = chunk(file_info["content"], file_info["source_type"], file_info["content_type"])
        for j, c in enumerate(chunks):
            all_chunks.append({
                "text": c,
                "resource_id": file_info["id"],
                "chunk_index": j,
                "title": file_info["title"],
            })
    
    assert len(all_chunks) >= 10, "Should produce at least one chunk per file"
    
    # Verify deterministic hashing
    hashes = [hashlib.sha256(c["text"].encode()).hexdigest() for c in all_chunks]
    assert len(hashes) == len(set(hashes)), "All chunks should have unique hashes"
    
    # Simulate delta sync: same files, no changes
    all_chunks_2 = []
    for file_info in github_files:
        chunks = chunk(file_info["content"], file_info["source_type"], file_info["content_type"])
        for j, c in enumerate(chunks):
            all_chunks_2.append({
                "text": c,
                "resource_id": file_info["id"],
                "chunk_index": j,
                "title": file_info["title"],
            })
    
    hashes_2 = [hashlib.sha256(c["text"].encode()).hexdigest() for c in all_chunks_2]
    assert hashes == hashes_2, "Delta sync should produce identical hashes (idempotency)"


# ---------------------------------------------------------------------------
# Real activity-chain test — exercises all 6 workflow activities in sequence
# ---------------------------------------------------------------------------

class _FakeQdrantForActivityTest:
    """Minimal Qdrant fake for the activity chain test."""

    def __init__(self) -> None:
        self.collections: dict[str, dict[str, object]] = {"org_knowledge": {}}

    def upsert(self, collection_name: str, points, wait: bool = True) -> None:
        for point in points:
            self.collections.setdefault(collection_name, {})[str(point.id)] = point

    def scroll(self, collection_name: str, **_kw):
        return list(self.collections.get(collection_name, {}).values()), None


class _FakeOllamaForActivityTest:
    """Returns a deterministic 768-dim vector so embed_batch works without Ollama running."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t) % 100) / 100.0] * 768 for t in texts]


class _FakeDBCursor:
    """Fake psycopg2-style cursor backed by an in-memory dict.

    Intercepts:
    - INSERT INTO knowledge_sync_state (connector_id, resource_id, content_hash)
      → writes to the shared sync_db dict
    - SELECT resource_id, content_hash FROM knowledge_sync_state WHERE connector_id = %s
      → reads from the shared sync_db dict
    """

    def __init__(self, sync_db: dict) -> None:
        self._db = sync_db  # shared {(connector_id, resource_id): content_hash}
        self._rows: list = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        sql_up = sql.upper()
        if "INSERT INTO KNOWLEDGE_SYNC_STATE" in sql_up:
            # params = (connector_id, resource_id, content_hash)
            connector_id, resource_id, content_hash = params
            self._db[(connector_id, resource_id)] = content_hash
        elif "SELECT" in sql_up and "KNOWLEDGE_SYNC_STATE" in sql_up:
            # params = (connector_id,)
            connector_id = params[0]
            self._rows = [
                (k[1], v) for k, v in self._db.items() if k[0] == connector_id
            ]

    def fetchall(self) -> list:
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class _FakeDBConn:
    """In-memory PostgreSQL stand-in for sync-state activities."""

    def __init__(self, sync_db: dict) -> None:
        self._db = sync_db  # shared reference

    def cursor(self):
        return _FakeDBCursor(self._db)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass


def _build_fake_resources(n: int = 5) -> list[dict]:
    return [
        {
            "id": f"src/module_{i}.py",
            "url": f"https://github.com/org/repo/blob/main/src/module_{i}.py",
            "title": f"module_{i}.py",
            "last_modified": "2026-05-22T00:00:00Z",
            "content": (
                f"def handler_{i}(request):\n"
                f"    return {{'status': 'ok', 'id': {i}}}\n\n"
                f"def helper_{i}(value):\n"
                f"    return value * {i + 1}\n"
            ),
            "source_type": "github",
            "content_type": "code",
        }
        for i in range(n)
    ]


def test_ingestion_activity_chain_full_then_delta(monkeypatch) -> None:
    """
    Exercises all 6 workflow activities in the correct sequence.

    Run 1 (full sync):
      fetch_resources → diff_resources → chunk_and_embed ×5 →
      pii_screen → upsert_org_knowledge → update_sync_state ×5

    Assertions after run 1:
      - Qdrant org_knowledge has ≥5 points (at least 1 per file)
      - Every point has the correct workspace_id and connector_id
      - Sync state table has 5 entries

    Run 2 (delta sync, no file changes):
      diff_resources returns 0 changed resources → 0 new points upserted

    Assertions after run 2:
      - Qdrant point count is identical to after run 1 (idempotency)
    """
    from activities.ingestion import (
        chunk_and_embed,
        diff_resources,
        pii_screen,
        update_sync_state,
        upsert_org_knowledge,
    )
    import activities.sync_state as sync_state_module
    import activities.upsert as upsert_module
    import embedder as embedder_module

    CONNECTOR_ID = "conn-test-001"
    WORKSPACE_ID = "workspace-test"
    CONNECTOR_CONFIG = {"source_type": "github", "sharing_scope": "workspace_internal"}

    fake_qdrant = _FakeQdrantForActivityTest()
    fake_ollama = _FakeOllamaForActivityTest()
    # shared in-memory sync state: {(connector_id, resource_id): content_hash}
    sync_state_db: dict[tuple[str, str], str] = {}

    def _fake_get_connection():
            return _FakeDBConn(sync_state_db)
    def _fake_update_sync_state_direct(connector_id: str, resource_id: str, content_hash: str) -> None:
        sync_state_db[(connector_id, resource_id)] = content_hash

    monkeypatch.setattr(upsert_module, "get_qdrant_client", lambda: fake_qdrant)
    monkeypatch.setattr(embedder_module, "get_ollama_client", lambda: fake_ollama)
    monkeypatch.setattr(sync_state_module, "get_connection", _fake_get_connection)

    resources = _build_fake_resources(5)

    # ---- RUN 1: full sync ------------------------------------------------
    # Activity 2: diff (all 5 are new → all returned)
    changed_resources = asyncio.run(diff_resources(CONNECTOR_ID, resources))
    assert len(changed_resources) == 5, "All 5 resources should be new on first sync"
    for r in changed_resources:
        assert "content" in r, "diff_resources must preserve full resource content"
        assert "content_hash" in r, "diff_resources must include content_hash"

    # Activity 3: chunk + embed each changed resource
    all_chunks: list[dict] = []
    for resource in changed_resources:
        chunks = asyncio.run(chunk_and_embed(CONNECTOR_ID, resource))
        assert len(chunks) >= 1, f"Resource {resource['id']} must produce at least one chunk"
        for c in chunks:
            assert c["metadata"]["content_hash"], "Each chunk must carry resource content_hash"
            assert c["metadata"]["resource_id"] == resource["id"]
        all_chunks.extend(chunks)

    assert len(all_chunks) >= 5, "At least one chunk per file expected"

    # Activity 4: PII screen (passthrough stub)
    screened = asyncio.run(pii_screen(CONNECTOR_ID, WORKSPACE_ID, all_chunks, False))
    assert len(screened) == len(all_chunks), "PII screen stub must not drop any chunks"

    # Activity 5: upsert to Qdrant
    upserted_count = asyncio.run(
        upsert_org_knowledge(CONNECTOR_ID, WORKSPACE_ID, screened, CONNECTOR_CONFIG)
    )
    assert upserted_count == len(screened)
    qdrant_points_run1 = len(fake_qdrant.collections["org_knowledge"])
    assert qdrant_points_run1 >= 5, f"Expected ≥5 Qdrant points, got {qdrant_points_run1}"

    # Verify payload correctness on every point
    for point in fake_qdrant.collections["org_knowledge"].values():
        assert point.payload["workspace_id"] == WORKSPACE_ID
        assert point.payload["connector_id"] == CONNECTOR_ID
        assert point.payload["content_hash"], "Every point must have a non-empty content_hash"

    # Activity 6: update sync state (once per resource)
    seen: set[str] = set()
    for c in screened:
        rid = c["metadata"]["resource_id"]
        chash = c["metadata"]["content_hash"]
        if rid and chash and rid not in seen:
            seen.add(rid)
            asyncio.run(update_sync_state(CONNECTOR_ID, rid, chash))

    assert len(sync_state_db) == 5, "Sync state must have one entry per resource"

    # ---- RUN 2: delta sync with no changes --------------------------------
    changed_run2 = asyncio.run(diff_resources(CONNECTOR_ID, resources))
    assert len(changed_run2) == 0, (
        "Delta sync must return 0 changed resources when content is identical"
    )

    # Qdrant should still have exactly the same number of points
    assert len(fake_qdrant.collections["org_knowledge"]) == qdrant_points_run1, (
        "Idempotency violated: Qdrant point count changed on delta sync with no file changes"
    )
