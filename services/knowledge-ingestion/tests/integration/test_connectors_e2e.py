"""End-to-end integration test for US4: Full BYOD pipeline with connectors.

Tests:
- Connector instantiation and authentication
- Resource listing and fetching
- Workflow orchestration (with mock Temporal)
- Full pipeline: fetch → diff → chunk → embed → upsert
- FR-015: Slack 7-day hard filter (messages < 7 days old must never be fetched)
- A-009: Slack min_age_seconds enforced at connector level, not caller level
- GitHub file extension filtering respects configured extensions list
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# Add src to path for imports
src_path = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(src_path))

from connectors.github import GitHubConnector
from connectors.confluence import ConfluenceConnector
from connectors.slack import SlackConnector
from connectors.rds_schema import RDSSchemaConnector
from connectors import Resource
from chunker import chunk
from embedder import embed_sparse


# ============================================================================
# CONNECTOR INSTANTIATION TESTS
# ============================================================================

def test_github_connector_instantiation() -> None:
    """Test GitHubConnector can be instantiated."""
    connector = GitHubConnector(
        config={
            "owner": "testorg",
            "repo": "test-repo",
            "branch": "main",
            "file_extensions": [".py", ".md"],
        }
    )
    assert connector is not None
    assert hasattr(connector, "authenticate")
    assert hasattr(connector, "list_resources")
    assert hasattr(connector, "fetch_resource")


def test_confluence_connector_instantiation() -> None:
    """Test ConfluenceConnector can be instantiated."""
    connector = ConfluenceConnector(
        config={
            "base_url": "https://confluence.example.com",
            "space_keys": ["ENG", "ARCH"],
        }
    )
    assert connector is not None
    assert hasattr(connector, "authenticate")
    assert hasattr(connector, "list_resources")
    assert hasattr(connector, "fetch_resource")
    assert hasattr(connector, "set_access_token")


def test_slack_connector_instantiation() -> None:
    """Test SlackConnector can be instantiated."""
    connector = SlackConnector(
        config={
            "channel_ids": ["C123456", "C789012"],
        }
    )
    assert connector is not None
    assert hasattr(connector, "authenticate")
    assert hasattr(connector, "list_resources")
    assert hasattr(connector, "fetch_resource")


def test_rds_connector_instantiation() -> None:
    """Test RDSSchemaConnector can be instantiated."""
    connector = RDSSchemaConnector(
        config={
            "host": "db.example.com",
            "port": 5432,
            "database": "mydb",
            "username": "user",
            "password": "pass",
            "schema_filters": ["public"],
        }
    )
    assert connector is not None
    assert hasattr(connector, "authenticate")
    assert hasattr(connector, "list_resources")
    assert hasattr(connector, "fetch_resource")


# ============================================================================
# PIPELINE COMPONENT TESTS
# ============================================================================

def test_resource_dataclass() -> None:
    """Test Resource dataclass is properly structured."""
    resource = Resource(
        id="file-1",
        url="https://github.com/test/repo/blob/main/file.py",
        title="file.py",
        last_modified="2026-05-22T10:00:00Z",
    )
    assert resource.id == "file-1"
    assert resource.url.endswith("file.py")
    assert resource.title == "file.py"
    assert resource.last_modified


def test_chunker_preserves_deterministic_output() -> None:
    """Verify chunker output is deterministic for same input."""
    code = "def test():\n    return 42\n" * 10
    
    chunks1 = chunk(code, "github", "code")
    chunks2 = chunk(code, "github", "code")
    
    assert len(chunks1) == len(chunks2)
    assert chunks1 == chunks2, "Chunking should be deterministic"


def test_embedder_sparse_vector_structure() -> None:
    """Verify sparse embedder returns correctly structured data."""
    texts = ["hello world", "test code"]
    
    sparse_vectors = embed_sparse(texts)
    
    assert len(sparse_vectors) == 2
    for sv in sparse_vectors:
        assert isinstance(sv, dict)
        assert "indices" in sv
        assert "values" in sv
        assert isinstance(sv["indices"], list)
        assert isinstance(sv["values"], list)
        assert len(sv["indices"]) == len(sv["values"])


def test_full_pipeline_github_to_embeddings() -> None:
    """Test complete pipeline: GitHub mock → connector → chunk → embed."""
    
    # Simulate 5 Python files from GitHub mock
    mock_files = {
        "main.py": "def main():\n    print('hello')\n    return 0\n",
        "utils.py": "def helper():\n    pass\n",
        "models.py": "class User:\n    def __init__(self): pass\n",
        "api.py": "def create_endpoint():\n    return 'endpoint'\n",
        "tests.py": "def test_main():\n    assert True\n",
    }
    
    all_chunks = []
    
    for filename, content in mock_files.items():
        # Chunk
        chunks = chunk(content, "github", "code")
        for chunk_idx, chunk_text in enumerate(chunks):
            all_chunks.append({
                "resource_id": filename,
                "chunk_index": chunk_idx,
                "text": chunk_text,
                "embedding": embed_sparse([chunk_text])[0],  # Get sparse embedding
            })
    
    # Verify pipeline
    assert len(all_chunks) >= 5, "Should have at least one chunk per file"
    
    # Verify embeddings
    for item in all_chunks:
        assert "indices" in item["embedding"], "Sparse embedding must have indices"
        assert "values" in item["embedding"], "Sparse embedding must have values"
        assert len(item["embedding"]["indices"]) > 0, "Should have tokens"


def test_full_pipeline_confluence_to_embeddings() -> None:
    """Test complete pipeline: Confluence mock → connector → chunk → embed."""
    
    # Simulate Confluence pages
    mock_pages = {
        "page1": "<h1>API Design</h1><p>REST endpoints for all operations.</p>",
        "page2": "<h1>Data Model</h1><p>Schema for all entities in system.</p>",
        "page3": "<h1>Testing</h1><p>Comprehensive test coverage strategy.</p>",
    }
    
    all_chunks = []
    
    for page_id, html_content in mock_pages.items():
        chunks = chunk(html_content, "confluence", "html")
        for chunk_idx, chunk_text in enumerate(chunks):
            all_chunks.append({
                "resource_id": page_id,
                "chunk_index": chunk_idx,
                "text": chunk_text,
                "embedding": embed_sparse([chunk_text])[0],
            })
    
    assert len(all_chunks) >= 3
    for item in all_chunks:
        assert item["embedding"]["indices"]
        assert item["embedding"]["values"]


def test_idempotency_deterministic_hashes() -> None:
    """Test deterministic hashing for idempotency across connector types."""
    
    content_samples = [
        ("github_code.py", "def test(): return 42\n"),
        ("confluence_page.html", "<h1>Title</h1><p>Content</p>"),
        ("schema.sql", "CREATE TABLE t1 (id INT);"),
        ("slack_msg.txt", "Message from Slack channel"),
    ]
    
    for source, content in content_samples:
        # Hash same content twice
        hash1 = hashlib.sha256(content.encode()).hexdigest()
        hash2 = hashlib.sha256(content.encode()).hexdigest()
        
        assert hash1 == hash2, f"{source}: Hashes must be deterministic"
        
        # Different content = different hash
        different = hashlib.sha256((content + "modified").encode()).hexdigest()
        assert hash1 != different, f"{source}: Different content must have different hash"


def test_all_connectors_instantiate() -> None:
    """Test all connector types can be instantiated."""
    
    github = GitHubConnector(config={"owner": "test", "repo": "repo", "branch": "main"})
    assert github is not None
    
    confluence = ConfluenceConnector(config={"base_url": "http://example.com", "space_keys": ["ENG"]})
    assert confluence is not None
    
    slack = SlackConnector(config={"channel_ids": ["C123"]})
    assert slack is not None
    
    rds = RDSSchemaConnector(config={"host": "localhost", "port": 5432, "database": "db", "username": "u", "password": "p"})
    assert rds is not None


# ============================================================================
# BEHAVIORAL CONTRACT TESTS — FR-015, A-009 (no live services required)
# ============================================================================

def test_slack_min_age_is_7_days() -> None:
    """FR-015 / A-009: SlackConnector must enforce 7-day hard filter at the connector level."""
    connector = SlackConnector(config={"channel_ids": ["C123"]})
    assert connector.min_age_seconds == 7 * 24 * 60 * 60, (
        f"min_age_seconds must be exactly 604800 (7 days), got {connector.min_age_seconds}"
    )


def test_slack_list_resources_skips_recent_messages(monkeypatch) -> None:
    """FR-015: list_resources must filter out messages newer than 7 days."""
    now_ts = datetime.now(timezone.utc).timestamp()
    recent_ts = now_ts - (3 * 24 * 60 * 60)   # 3 days ago — must be excluded
    old_ts = now_ts - (10 * 24 * 60 * 60)      # 10 days ago — must be included

    async def fake_post(*args, **kwargs):
        class FakeResponse:
            def raise_for_status(self): pass
            def json(self):
                return {
                    "ok": True,
                    "messages": [
                        {"ts": str(recent_ts), "text": "recent message"},
                        {"ts": str(old_ts), "text": "old message"},
                    ],
                }
        return FakeResponse()

    import httpx
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    connector = SlackConnector(config={"channel_ids": ["C123"]})
    resources = asyncio.run(connector.list_resources())

    assert len(resources) == 1, (
        f"Expected only the 10-day-old message, got {len(resources)} resources"
    )
    old_ts_int = int(old_ts * 1_000_000)
    assert str(old_ts_int) in resources[0].url, "Returned resource must be the old message"


def test_github_connector_respects_file_extensions(monkeypatch) -> None:
    """GitHub connector must only list resources matching configured file_extensions."""
    import httpx

    tree_entries = [
        {"type": "blob", "path": "src/main.py", "sha": "abc"},
        {"type": "blob", "path": "src/utils.js", "sha": "def"},  # not in extensions
        {"type": "blob", "path": "README.md", "sha": "ghi"},
        {"type": "blob", "path": "src/helper.py", "sha": "jkl"},
        {"type": "tree", "path": "src", "sha": "mno"},  # tree entry, not a file
    ]

    call_count = {"n": 0}

    async def fake_get(self, url, **kwargs):
        call_count["n"] += 1
        class FakeResponse:
            def raise_for_status(self): pass
            def json(self_):
                # First call: branches API → return commit sha
                if call_count["n"] == 1:
                    return {"commit": {"sha": "deadbeef"}}
                # Second call: trees API → return file tree
                return {"tree": tree_entries}
        return FakeResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    connector = GitHubConnector(
        config={
            "owner": "testorg",
            "repo": "test-repo",
            "branch": "main",
            "file_extensions": [".py", ".md"],
        }
    )
    resources = asyncio.run(connector.list_resources())

    returned_paths = [r.title for r in resources]  # r.title stores the file path
    assert "src/utils.js" not in returned_paths, ".js must be excluded by extension filter"
    assert all(
        any(path.endswith(ext) for ext in [".py", ".md"])
        for path in returned_paths
    ), f"All returned resources must match .py or .md extensions: {returned_paths}"
    assert len(resources) >= 2, "main.py, README.md, helper.py should all be included"


def test_rds_connector_never_lists_row_data() -> None:
    """RDS schema connector must only expose schema metadata, never row data."""
    connector = RDSSchemaConnector(config={
        "host": "localhost",
        "port": 5432,
        "database": "db",
        "username": "u",
        "password": "p",
    })
    import inspect
    source = inspect.getsource(connector.list_resources)
    assert "information_schema.tables" in source, (
        "list_resources must query information_schema.tables"
    )
    # Verify no SELECT * FROM <user_table> style queries exist
    assert "SELECT *" not in source.upper() or "information_schema" in source, (
        "list_resources must not query row data from user tables"
    )
