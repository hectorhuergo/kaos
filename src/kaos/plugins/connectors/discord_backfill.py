"""Backfill Discord message source: reads a thread/channel history via REST.

Unlike the live gateway, this is a *bounded* source: it fetches the historical
messages of a channel (e.g. a forum thread) and yields them in chronological
order. That makes it a perfect fit for the ``conversation.completed`` trigger,
so the Resume Agent summarizes the whole thread once.

Uses the Discord REST API via httpx (no discord.py dependency).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from kaos.plugins.connectors.discord_connector import DiscordMessage

DISCORD_API = "https://discord.com/api/v10"
PAGE_SIZE = 100


async def list_forum_threads(
    token: str,
    guild_id: str,
    forum_channel_id: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[tuple[str, str]]:
    """Return ``(thread_id, name)`` for every thread of a forum channel.

    Combines active threads (guild-wide, filtered by parent) and archived
    public threads (channel-scoped). Requires a bot token with access.
    """
    owns = client is None
    http = client if client is not None else httpx.AsyncClient()
    headers = {"Authorization": f"Bot {token}"}
    found: dict[str, str] = {}
    try:
        active = await http.get(
            f"{DISCORD_API}/guilds/{guild_id}/threads/active", headers=headers
        )
        active.raise_for_status()
        for thread in active.json().get("threads", []):
            if str(thread.get("parent_id")) == str(forum_channel_id):
                found[str(thread["id"])] = thread.get("name", "(sin nombre)")

        archived = await http.get(
            f"{DISCORD_API}/channels/{forum_channel_id}/threads/archived/public",
            headers=headers,
        )
        archived.raise_for_status()
        for thread in archived.json().get("threads", []):
            found[str(thread["id"])] = thread.get("name", "(sin nombre)")
    finally:
        if owns:
            await http.aclose()
    return list(found.items())



class DiscordBackfillSource:
    """A bounded `DiscordMessageSource` over a channel's message history."""

    def __init__(
        self,
        token: str,
        channel_id: str,
        guild_id: str | None = None,
        *,
        limit: int = PAGE_SIZE,
        include_bots: bool = False,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._channel_id = str(channel_id)
        self._guild_id = guild_id
        self._limit = limit
        self._include_bots = include_bots
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def _fetch_all(self) -> list[dict[str, Any]]:
        client = self._get_client()
        collected: list[dict[str, Any]] = []
        before: str | None = None
        remaining = self._limit
        while remaining > 0:
            page = min(PAGE_SIZE, remaining)
            params: dict[str, Any] = {"limit": page}
            if before is not None:
                params["before"] = before
            response = await client.get(
                f"{DISCORD_API}/channels/{self._channel_id}/messages",
                params=params,
                headers={"Authorization": f"Bot {self._token}"},
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            collected.extend(batch)
            before = batch[-1]["id"]
            remaining -= len(batch)
            if len(batch) < page:
                break
        return collected

    async def messages(self) -> AsyncIterator[DiscordMessage]:
        # Discord returns newest-first; reverse to chronological order.
        for raw in reversed(await self._fetch_all()):
            author = raw.get("author", {})
            if not self._include_bots and author.get("bot"):
                continue
            yield self._to_message(raw)

    def _to_message(self, raw: dict[str, Any]) -> DiscordMessage:
        author = raw.get("author", {})
        name = author.get("global_name") or author.get("username") or "unknown"
        return DiscordMessage(
            message_id=str(raw["id"]),
            channel_id=str(raw.get("channel_id", self._channel_id)),
            guild_id=self._guild_id or "backfill",
            author=str(name),
            text=raw.get("content", ""),
        )

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

