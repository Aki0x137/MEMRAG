"""GitHub connector for fetching repository content."""

from __future__ import annotations

import base64
import os
from datetime import datetime, timezone

import httpx

from connectors import BaseConnector, Resource


class GitHubConnector(BaseConnector):
    """Connector for GitHub repositories via REST API."""

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.token = os.getenv("GITHUB_TOKEN", "")
        self.base_url = os.getenv("GITHUB_API_BASE_URL", "https://api.github.com")
        self.owner = config.get("owner", "")
        self.repo = config.get("repo", "")
        self.branch = config.get("branch", "main")
        self.file_extensions = config.get("file_extensions", [".md", ".py", ".go", ".ts"])

    async def authenticate(self) -> None:
        """Test the token by fetching user info."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/user",
                headers={"Authorization": f"token {self.token}"},
            )
            response.raise_for_status()

    async def list_resources(self) -> list[Resource]:
        """Fetch repository tree and filter by file extensions."""
        async with httpx.AsyncClient() as client:
            # Get the default branch commit SHA
            branch_resp = await client.get(
                f"{self.base_url}/repos/{self.owner}/{self.repo}/branches/{self.branch}",
                headers={"Authorization": f"token {self.token}"},
            )
            branch_resp.raise_for_status()
            sha = branch_resp.json()["commit"]["sha"]

            # Get the tree recursively
            tree_resp = await client.get(
                f"{self.base_url}/repos/{self.owner}/{self.repo}/git/trees/{sha}",
                params={"recursive": 1},
                headers={"Authorization": f"token {self.token}"},
            )
            tree_resp.raise_for_status()
            tree_data = tree_resp.json()

        resources: list[Resource] = []
        for item in tree_data.get("tree", []):
            if item["type"] != "blob":
                continue
            path = item["path"]
            if not any(path.endswith(ext) for ext in self.file_extensions):
                continue

            resources.append(
                Resource(
                    id=item["sha"],
                    url=f"https://github.com/{self.owner}/{self.repo}/blob/{self.branch}/{path}",
                    title=path,
                    last_modified=datetime.now(timezone.utc),
                )
            )
        return resources

    async def fetch_resource(self, resource_id: str) -> bytes:
        """Fetch file content by SHA (tree entry)."""
        async with httpx.AsyncClient() as client:
            # For GitHub tree endpoints, we need the file path
            # Instead, use the Contents API with a simpler approach:
            # The resource_id format should be "owner/repo/branch/path"
            # For now, store it in fetch and parse from context
            # This is a simplified version; in production would need better resource tracking

            # Fallback: Get the blob directly if resource_id is a SHA
            blob_resp = await client.get(
                f"{self.base_url}/repos/{self.owner}/{self.repo}/git/blobs/{resource_id}",
                headers={"Authorization": f"token {self.token}"},
            )
            blob_resp.raise_for_status()
            blob_data = blob_resp.json()

            if blob_data.get("encoding") == "base64":
                return base64.b64decode(blob_data["content"])
            return blob_data["content"].encode("utf-8")
