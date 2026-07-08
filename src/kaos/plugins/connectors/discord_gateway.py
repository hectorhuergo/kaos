"""Real Discord message source backed by the discord.py gateway.

`discord.py` is imported lazily so this module can be imported (and the mapping
logic tested) without the dependency installed. Install it with the optional
extra: ``pip install -e .[discord]``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from typing import Any

from kaos.plugins.connectors.discord_connector import DiscordMessage


class DiscordGatewaySource:
    """A live `DiscordMessageSource` fed by the Discord gateway."""

    def __init__(
        self,
        token: str,
        guild_id: str | None = None,
        channel_ids: Iterable[str] | None = None,
    ) -> None:
        self._token = token
        self._guild_id = guild_id
        self._channels = {str(c) for c in (channel_ids or ())}
        self._queue: asyncio.Queue[DiscordMessage | None] = asyncio.Queue()
        self._client: Any = None
        self._task: asyncio.Task[Any] | None = None
        self._closed = False

    @staticmethod
    def to_discord_message(message: Any) -> DiscordMessage:
        """Map a discord.py Message (or a duck-typed equivalent) to our model."""
        guild = getattr(message, "guild", None)
        return DiscordMessage(
            message_id=str(message.id),
            channel_id=str(message.channel.id),
            guild_id=str(guild.id) if guild is not None else "dm",
            author=str(message.author),
            text=message.content,
        )

    def _accepts(self, message: Any) -> bool:
        if getattr(message.author, "bot", False):
            return False
        if self._channels and str(message.channel.id) not in self._channels:
            return False
        if self._guild_id is not None:
            guild = getattr(message, "guild", None)
            if guild is None or str(guild.id) != self._guild_id:
                return False
        return True

    def _build_client(self) -> Any:
        import discord  # lazy import: only required for the live gateway

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_message(message: Any) -> None:  # pragma: no cover - needs gateway
            if self._accepts(message):
                await self._queue.put(self.to_discord_message(message))

        return client

    async def messages(self) -> AsyncIterator[DiscordMessage]:
        """Yield messages as they arrive from the gateway until closed."""
        self._client = self._build_client()
        self._task = asyncio.create_task(self._client.start(self._token))
        while not self._closed:
            item = await self._queue.get()
            if item is None:
                break
            yield item

    async def close(self) -> None:
        """Stop the gateway client and end the message stream."""
        self._closed = True
        await self._queue.put(None)
        if self._client is not None:
            await self._client.close()
        if self._task is not None:
            self._task.cancel()

