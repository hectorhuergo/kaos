"""Tests for the Discord Connector."""

from __future__ import annotations

import asyncio

from kaos.contracts import Artifact, Event, EventBus
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.connectors import DiscordConnector, DiscordMessage, StaticDiscordSource
from kaos.runtime import InMemoryEventBus, InMemoryStorage, KaosRuntime
from kaos.sdk import EchoLLMProvider


def _msg(author: str, text: str, mid: str = "1") -> DiscordMessage:
    return DiscordMessage(
        message_id=mid,
        channel_id="100",
        guild_id="42",
        author=author,
        text=text,
    )


def test_connector_publishes_message_events() -> None:
    bus = InMemoryEventBus()
    seen: list[Event] = []

    async def handler(event: Event) -> None:
        seen.append(event)

    source = StaticDiscordSource([_msg("ana", "hola", "1"), _msg("juan", "listo", "2")])
    connector = DiscordConnector(source)

    async def scenario() -> None:
        bus.subscribe("*", handler)
        await connector.start(bus)
        await connector.stop()

    asyncio.run(scenario())

    assert [e.type for e in seen] == ["message.created", "message.created"]
    first = seen[0]
    assert first.source == "discord-connector"
    assert first.workspace == "discord:42"
    assert first.payload == {
        "author": "ana",
        "text": "hola",
        "channel_id": "100",
        "message_id": "1",
    }
    assert source.closed is True


def test_event_payload_includes_timestamp_when_present() -> None:
    bus = InMemoryEventBus()
    seen: list[Event] = []

    async def handler(event: Event) -> None:
        seen.append(event)

    dated = DiscordMessage(
        message_id="1",
        channel_id="100",
        guild_id="42",
        author="ana",
        text="hola",
        timestamp="2026-07-08T14:30:00+00:00",
    )
    connector = DiscordConnector(StaticDiscordSource([dated]))

    async def scenario() -> None:
        bus.subscribe("*", handler)
        await connector.start(bus)

    asyncio.run(scenario())

    assert seen[0].payload["timestamp"] == "2026-07-08T14:30:00+00:00"


class _CollectingPublisher:
    name = "collecting-publisher"

    def __init__(self) -> None:
        self.published: list[Artifact] = []

    async def publish(self, artifact: Artifact) -> None:
        self.published.append(artifact)


def test_discord_to_resume_pipeline_end_to_end() -> None:
    """Discord -> EventBus -> ResumeAgent -> Publisher, the MVP pipeline."""
    storage = InMemoryStorage()
    runtime = KaosRuntime(storage=storage)
    publisher = _CollectingPublisher()

    source = StaticDiscordSource([_msg("ana", "avanzamos con Odoo", "1")])
    runtime.register_connector(DiscordConnector(source, emit_completed=True))
    runtime.register_agent(ResumeAgent(EchoLLMProvider(response="# Resumen Ejecutivo")))
    runtime.register_publisher(publisher)

    asyncio.run(runtime.start())

    assert len(publisher.published) == 1
    artifact = publisher.published[0]
    assert artifact.kind == "conversation.summary"
    assert artifact.workspace == "discord:42"
    assert artifact.content["summary"] == "# Resumen Ejecutivo"

    events = asyncio.run(storage.list_events("discord:42"))
    # One message event plus the conversation.completed trigger.
    assert [e.type for e in events] == ["message.created", "conversation.completed"]


def test_connector_emits_completed_trigger() -> None:
    bus = InMemoryEventBus()
    seen: list[Event] = []

    async def handler(event: Event) -> None:
        seen.append(event)

    source = StaticDiscordSource([_msg("ana", "hola", "1"), _msg("juan", "listo", "2")])
    connector = DiscordConnector(source, emit_completed=True)

    async def scenario() -> None:
        bus.subscribe("*", handler)
        await connector.start(bus)

    asyncio.run(scenario())

    assert [e.type for e in seen] == [
        "message.created",
        "message.created",
        "conversation.completed",
    ]
    assert seen[-1].workspace == "discord:42"

