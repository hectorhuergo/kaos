"""Discord Connector: adapts Discord messages into KAOS events.

The connector depends on a `DiscordMessageSource` abstraction instead of a
concrete Discord client, so it can be tested without a network connection and
backed later by a real discord.py gateway without changing the connector.

Discord is simply the first Connector of the platform.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from kaos.contracts.event import Event
from kaos.contracts.event_bus import EventBus

EVENT_TYPE = "message.created"
CONVERSATION_COMPLETED = "conversation.completed"


class DiscordMessage(BaseModel):
    """A normalized incoming Discord message."""

    message_id: str
    channel_id: str
    guild_id: str
    author: str
    text: str


@runtime_checkable
class DiscordMessageSource(Protocol):
    """Yields normalized Discord messages (e.g. a gateway or a backfill)."""

    def messages(self) -> AsyncIterator[DiscordMessage]:
        """Return an async iterator of incoming messages."""
        ...

    async def close(self) -> None:
        """Release any resources held by the source."""
        ...


class StaticDiscordSource:
    """A finite `DiscordMessageSource` over a fixed list, for tests and demos."""

    def __init__(self, messages: list[DiscordMessage]) -> None:
        self._messages = messages
        self.closed = False

    async def messages(self) -> AsyncIterator[DiscordMessage]:
        for message in self._messages:
            yield message

    async def close(self) -> None:
        self.closed = True


class DiscordConnector:
    """Produces `message.created` events from a Discord message source."""

    name = "discord-connector"

    def __init__(
        self,
        source: DiscordMessageSource,
        workspace_prefix: str = "discord",
        emit_completed: bool = False,
    ) -> None:
        self._source = source
        self._prefix = workspace_prefix
        self._emit_completed = emit_completed

    async def start(self, bus: EventBus) -> None:
        """Drain the source, publishing an event per Discord message.

        When ``emit_completed`` is set, a ``conversation.completed`` trigger is
        published for each workspace after the batch is drained, so
        conversation-level agents (e.g. the Resume Agent) run once.
        """
        workspaces: list[str] = []
        async for message in self._source.messages():
            event = self._to_event(message)
            if event.workspace not in workspaces:
                workspaces.append(event.workspace)
            await bus.publish(event)
        if self._emit_completed:
            for workspace in workspaces:
                await bus.publish(
                    Event(
                        type=CONVERSATION_COMPLETED,
                        source=self.name,
                        workspace=workspace,
                        payload={},
                    )
                )

    async def stop(self) -> None:
        """Close the underlying message source."""
        await self._source.close()

    def _to_event(self, message: DiscordMessage) -> Event:
        return Event(
            type=EVENT_TYPE,
            source=self.name,
            workspace=f"{self._prefix}:{message.guild_id}",
            payload={
                "author": message.author,
                "text": message.text,
                "channel_id": message.channel_id,
                "message_id": message.message_id,
            },
        )

