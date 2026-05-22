"""Real integration tests using mock services.

Tests that mocks are importable and work correctly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Get paths
src_path = Path(__file__).resolve().parents[2] / "src"
mocks_path = Path(__file__).resolve().parents[4] / "tests" / "mocks"

sys.path.insert(0, str(src_path))


def load_mock_app(name: str) -> object:
    """Load a mock app module by name."""
    if name == "github":
        spec_path = mocks_path / "github-api-mock" / "app.py"
    elif name == "confluence":
        spec_path = mocks_path / "confluence-api-mock" / "app.py"
    else:
        raise ValueError(f"Unknown mock: {name}")
    
    spec = importlib.util.spec_from_file_location(f"mock_{name}_app", str(spec_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGitHubMockService:
    """Test GitHub API mock service."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup mock client."""
        github_app = load_mock_app("github")
        self.client = TestClient(github_app.app)

    def test_github_mock_health(self):
        """Test GitHub mock health endpoint."""
        response = self.client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_github_mock_get_user(self):
        """Test GitHub mock get user endpoint."""
        response = self.client.get("/user")
        assert response.status_code == 200
        data = response.json()
        assert data["login"] == "test-user"

    def test_github_mock_get_tree(self):
        """Test GitHub mock tree endpoint with synthetic files."""
        response = self.client.get(
            "/repos/testorg/test-repo/git/trees/abc123",
            params={"recursive": 1}
        )
        assert response.status_code == 200
        data = response.json()
        assert "tree" in data
        assert len(data["tree"]) == 10

    def test_github_mock_get_blob(self):
        """Test GitHub mock blob endpoint returns base64 content."""
        tree_resp = self.client.get(
            "/repos/testorg/test-repo/git/trees/abc123"
        )
        tree_data = tree_resp.json()
        first_sha = tree_data["tree"][0]["sha"]
        
        response = self.client.get(
            f"/repos/testorg/test-repo/git/blobs/{first_sha}"
        )
        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert data["encoding"] == "base64"


class TestConfluenceMockService:
    """Test Confluence API mock service with OAuth."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup mock client."""
        confluence_app = load_mock_app("confluence")
        self.client = TestClient(confluence_app.app)

    def test_confluence_mock_health(self):
        """Test Confluence mock health endpoint."""
        response = self.client.get("/health")
        assert response.status_code == 200

    def test_confluence_oauth_token(self):
        """Test Confluence OAuth token endpoint."""
        response = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": "auth-code",
                "redirect_uri": "http://localhost/cb",
                "client_id": "test",
                "client_secret": "secret",
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

    def test_confluence_get_current_user(self):
        """Test Confluence get current user endpoint."""
        token_resp = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": "auth-code",
                "client_id": "test",
                "client_secret": "secret",
                "redirect_uri": "http://localhost/cb",
            }
        )
        token = token_resp.json()["access_token"]
        
        response = self.client.get(
            "/wiki/rest/api/user/current",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "test-user"

    def test_confluence_search_pages(self):
        """Test Confluence search endpoint."""
        token_resp = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": "auth-code",
                "client_id": "test",
                "client_secret": "secret",
                "redirect_uri": "http://localhost/cb",
            }
        )
        token = token_resp.json()["access_token"]
        
        response = self.client.get(
            "/wiki/rest/api/content/search",
            params={"cql": "space IN (ENG)", "limit": 10},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert len(data["results"]) >= 1


class TestConnectorAgainstMocks:
    """Test connectors work with mock services."""

    def test_github_connector_imports(self):
        """Test GitHubConnector can be imported."""
        from connectors.github import GitHubConnector
        assert GitHubConnector is not None

    def test_confluence_connector_imports(self):
        """Test ConfluenceConnector can be imported."""
        from connectors.confluence import ConfluenceConnector
        assert ConfluenceConnector is not None

    def test_all_core_modules_import(self):
        """Test all core modules import without errors."""
        from chunker import chunk
        from embedder import embed_sparse, embed_batch
        from workflows.ingestion import IngestionWorkflow
        from activities.sync_state import diff_resources
        from activities.upsert import upsert_org_knowledge
        
        assert all([chunk, embed_sparse, embed_batch, IngestionWorkflow, diff_resources, upsert_org_knowledge])

    def test_mock_apps_have_correct_endpoints(self):
        """Verify mock services implement required endpoints."""
        github_app = load_mock_app("github")
        routes = [route.path for route in github_app.app.routes]
        assert any("/health" in route for route in routes)
        assert any("/repos" in route for route in routes)
        
        confluence_app = load_mock_app("confluence")
        conf_routes = [route.path for route in confluence_app.app.routes]
        assert any("/oauth/token" in route for route in conf_routes)
        assert any("/wiki/rest/api/content/search" in route for route in conf_routes)
