"""Confluence connector for fetching spaces and pages."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

from connectors import BaseConnector, Resource


class ConfluenceConnector(BaseConnector):
    """Connector for Confluence spaces via OAuth 2.0."""

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.base_url = os.getenv("CONFLUENCE_BASE_URL", config.get("base_url", "")).rstrip("/")
        self.space_keys = config.get("space_keys", [])
        self.access_token = ""
        self.last_sync: datetime | None = None

    async def authenticate(self) -> None:
        """Validate the access token by fetching user info."""
        if not self.access_token:
            raise RuntimeError("Access token not set")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/wiki/rest/api/user/current",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            response.raise_for_status()

    async def list_resources(self) -> list[Resource]:
        """Search for pages in configured spaces, updated since last_sync."""
        if not self.space_keys:
            return []

        resources: list[Resource] = []
        cql_filter = f"space IN ({','.join(self.space_keys)})"
        
        if self.last_sync:
            cql_filter += f" AND lastModified >= '{self.last_sync.isoformat()}'"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/wiki/rest/api/content/search",
                params={"cql": cql_filter, "limit": 100, "expand": "version"},
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            response.raise_for_status()
            data = response.json()

        for page in data.get("results", []):
            resources.append(
                Resource(
                    id=page["id"],
                    url=page.get("_links", {}).get("webui", ""),
                    title=page.get("title", ""),
                    last_modified=datetime.fromisoformat(page.get("version", {}).get("when", datetime.now(timezone.utc).isoformat())),
                )
            )
        return resources

    async def fetch_resource(self, resource_id: str) -> bytes:
        """Fetch page content as HTML."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/wiki/rest/api/content/{resource_id}",
                params={"expand": "body.storage"},
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            response.raise_for_status()
            data = response.json()

        html_content = data.get("body", {}).get("storage", {}).get("value", "")
        return html_content.encode("utf-8")

    def set_access_token(self, token: str) -> None:
        """Set the OAuth access token (called post-3LO flow)."""
        self.access_token = token

    def set_last_sync(self, dt: datetime) -> None:
        """Set the last sync timestamp for delta syncs."""
        self.last_sync = dt
