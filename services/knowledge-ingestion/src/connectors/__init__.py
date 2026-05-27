"""Abstract base class for knowledge connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Resource:
    """Metadata for a resource in an external system."""

    id: str  # Resource ID in external system
    url: str | None  # URL to resource
    title: str  # Display name
    last_modified: datetime  # Last modification timestamp


class BaseConnector(ABC):
    """Base class for all knowledge connectors (GitHub, Confluence, Slack, RDS)."""

    def __init__(self, config: dict) -> None:
        """Initialize with connector-specific configuration."""
        self.config = config

    @abstractmethod
    async def authenticate(self) -> None:
        """Authenticate with the external system. Raise on failure."""
        pass

    @abstractmethod
    async def list_resources(self) -> list[Resource]:
        """List all available resources matching the connector's scope.
        
        Returns:
            List of Resource metadata objects.
        """
        pass

    @abstractmethod
    async def fetch_resource(self, resource_id: str) -> bytes:
        """Fetch the full content of a single resource.
        
        Args:
            resource_id: The ID of the resource to fetch.
            
        Returns:
            Raw content as bytes.
        """
        pass
