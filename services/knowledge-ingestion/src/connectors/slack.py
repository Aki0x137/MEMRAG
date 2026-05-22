"""Slack connector for fetching channel messages."""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

import httpx

from connectors import BaseConnector, Resource


class SlackConnector(BaseConnector):
    """Connector for Slack channels via Slack API."""

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.token = os.getenv("SLACK_TOKEN", "")
        self.base_url = "https://slack.com/api"
        self.channel_ids = config.get("channel_ids", [])
        # Hard constraint: never fetch messages < 7 days old (FR-015, A-009)
        self.min_age_seconds = 7 * 24 * 60 * 60  # 7 days

    async def authenticate(self) -> None:
        """Test the token by fetching workspace info."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/auth.test",
                data={"token": self.token},
            )
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                raise RuntimeError(f"Slack auth failed: {data.get('error')}")

    async def list_resources(self) -> list[Resource]:
        """List message threads from configured channels (7+ days old only)."""
        resources: list[Resource] = []
        now = datetime.now(timezone.utc).timestamp()

        for channel_id in self.channel_ids:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/conversations.history",
                    data={
                        "token": self.token,
                        "channel": channel_id,
                        "limit": 100,
                    },
                )
                response.raise_for_status()
                data = response.json()

                if not data.get("ok"):
                    continue

                for message in data.get("messages", []):
                    msg_ts = float(message.get("ts", 0))
                    msg_age = now - msg_ts
                    
                    # Hard filter: skip messages < 7 days old
                    if msg_age < self.min_age_seconds:
                        continue

                    msg_time = datetime.fromtimestamp(msg_ts, tz=timezone.utc)
                    resources.append(
                        Resource(
                            id=f"{channel_id}:{message.get('ts')}",
                            url=f"https://slack.com/archives/{channel_id}/p{int(msg_ts * 1000000)}",
                            title=f"Message in #{channel_id} at {msg_time.isoformat()}",
                            last_modified=msg_time,
                        )
                    )
        return resources

    async def fetch_resource(self, resource_id: str) -> bytes:
        """Fetch message thread content."""
        channel_id, msg_ts = resource_id.split(":", 1)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/conversations.replies",
                data={
                    "token": self.token,
                    "channel": channel_id,
                    "ts": msg_ts,
                    "limit": 100,
                },
            )
            response.raise_for_status()
            data = response.json()

        # Concatenate all messages in the thread
        content_parts: list[str] = []
        for msg in data.get("messages", []):
            text = msg.get("text", "")
            user = msg.get("user", "unknown")
            ts = msg.get("ts", "")
            content_parts.append(f"[{user} @ {ts}]: {text}")

        content = "\n".join(content_parts)
        return content.encode("utf-8")
