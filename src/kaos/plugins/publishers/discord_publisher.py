"""Discord Publisher: exposes summaries in a Discord "📋 Resume" thread.

The publisher depends on a `DiscordPoster` abstraction, so it is testable
without network access. `DiscordRestPoster` is a concrete poster over the
Discord REST API (via httpx).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from kaos.contracts.artifact import Artifact

DISCORD_API = "https://discord.com/api/v10"
PUBLIC_THREAD_TYPE = 11
MAX_MESSAGE_LEN = 2000


def chunk_message(content: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    """Split ``content`` into chunks within Discord's message length limit.

    Splits on line boundaries when possible; hard-splits any single line that
    exceeds the limit.
    """
    if len(content) <= limit:
        return [content]
    chunks: list[str] = []
    current = ""
    for line in content.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        addition = line if not current else "\n" + line
        if len(current) + len(addition) > limit:
            chunks.append(current)
            current = line
        else:
            current += addition
    if current:
        chunks.append(current)
    return chunks


@runtime_checkable
class DiscordPoster(Protocol):
    """Posts content to Discord threads/channels."""

    async def post_to_thread(self, channel_id: str, thread_name: str, content: str) -> None:
        """Create/reuse a thread named ``thread_name`` and post ``content``."""
        ...

    async def post_to_channel(self, channel_id: str, content: str) -> None:
        """Post ``content`` into an existing channel/thread by id."""
        ...


class DiscordRestPoster:
    """A `DiscordPoster` backed by the Discord REST API."""

    def __init__(
        self,
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._token = token
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bot {self._token}", "Content-Type": "application/json"}

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def post_to_channel(self, channel_id: str, content: str) -> None:
        """Post ``content`` (chunked) into an existing channel/thread by id.

        A Discord thread is itself a channel, so this posts into a forum thread
        such as "PMO" by its id.
        """
        client = self._get_client()
        for chunk in chunk_message(content):
            message = await client.post(
                f"{DISCORD_API}/channels/{channel_id}/messages",
                json={"content": chunk},
                headers=self._headers(),
            )
            message.raise_for_status()

    async def post_to_thread(self, channel_id: str, thread_name: str, content: str) -> None:
        client = self._get_client()
        created = await client.post(
            f"{DISCORD_API}/channels/{channel_id}/threads",
            json={
                "name": thread_name,
                "type": PUBLIC_THREAD_TYPE,
                "auto_archive_duration": 1440,
            },
            headers=self._headers(),
        )
        created.raise_for_status()
        thread_id = created.json()["id"]
        await self.post_to_channel(thread_id, content)

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None


class DiscordPublisher:
    """Publishes conversation summaries to a Discord thread.

    With ``thread_id`` set, posts directly into that existing thread/channel
    (e.g. the "PMO" forum thread). Otherwise it creates/reuses a thread named
    ``thread_name`` inside the artifact's originating channel.
    """

    name = "discord-publisher"

    def __init__(
        self,
        poster: DiscordPoster,
        *,
        thread_id: str | None = None,
        thread_name: str = "📋 Resume",
    ) -> None:
        self._poster = poster
        self._thread_id = thread_id
        self._thread_name = thread_name

    async def publish(self, artifact: Artifact) -> None:
        """Post the artifact's summary to Discord."""
        summary = artifact.content.get("summary")
        if not summary:
            return
        if self._thread_id:
            await self._poster.post_to_channel(str(self._thread_id), str(summary))
            return
        channel_id = artifact.metadata.get("channel_id")
        if not channel_id:
            return  # not a Discord-originated summary
        await self._poster.post_to_thread(str(channel_id), self._thread_name, str(summary))


class DiscordWebhookPublisher:
    """Publishes summaries through a Discord webhook (write-only, no bot token).

    Posts the artifact's summary to the webhook. When ``thread_id`` is set, the
    message is delivered into that specific thread (``?thread_id=...``), which is
    how you publish into a forum thread such as "PMO".
    """

    name = "discord-webhook-publisher"

    def __init__(
        self,
        webhook_url: str,
        *,
        thread_id: str | None = None,
        username: str | None = "KAOS",
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._webhook_url = webhook_url
        self._thread_id = thread_id
        self._username = username
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def publish(self, artifact: Artifact) -> None:
        """Post the artifact's summary to the configured webhook/thread.

        Long summaries are split into several messages within Discord's limit.
        """
        summary = artifact.content.get("summary")
        if not summary:
            return
        params = {"wait": "true"}
        if self._thread_id:
            params["thread_id"] = str(self._thread_id)
        client = self._get_client()
        for chunk in chunk_message(str(summary)):
            payload: dict[str, str] = {"content": chunk}
            if self._username:
                payload["username"] = self._username
            response = await client.post(self._webhook_url, params=params, json=payload)
            response.raise_for_status()

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None


