"""Tests for the KAOS runtime (EventBus, Runtime, Storage)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from kaos.contracts import Artifact, Context, Event, EventBus
from kaos.runtime import InMemoryEventBus, InMemoryStorage, KaosRuntime


def test_event_bus_dispatches_by_type_and_wildcard() -> None:
    bus = InMemoryEventBus()
    seen: list[str] = []

    async def on_message(event: Event) -> None:
        seen.append(f"typed:{event.type}")

    async def on_any(event: Event) -> None:
        seen.append(f"any:{event.type}")

    bus.subscribe("message.created", on_message)
    bus.subscribe("*", on_any)

    event = Event(type="message.created", source="discord", workspace="w1")
    asyncio.run(bus.publish(event))

    assert seen == ["typed:message.created", "any:message.created"]


class _EchoAgent:
    """Turns every message event into a one-line summary artifact."""

    name = "echo-agent"

    def accepts(self, context: Context) -> bool:
        return any(e.type == "message.created" for e in context.events)

    async def run(self, context: Context) -> Sequence[Artifact]:
        return [
            Artifact(
                kind="summary",
                workspace=context.workspace,
                produced_by=self.name,
                content={"text": context.events[0].payload.get("text", "")},
                source_events=tuple(e.id for e in context.events),
            )
        ]


class _CollectingPublisher:
    name = "collecting-publisher"

    def __init__(self) -> None:
        self.published: list[Artifact] = []

    async def publish(self, artifact: Artifact) -> None:
        self.published.append(artifact)


class _OneShotConnector:
    """Emits a single message event when started."""

    name = "one-shot-connector"

    async def start(self, bus: EventBus) -> None:
        await bus.publish(
            Event(
                type="message.created",
                source=self.name,
                workspace="w1",
                payload={"text": "hello kaos"},
            )
        )

    async def stop(self) -> None:
        ...


def test_runtime_end_to_end_with_storage() -> None:
    storage = InMemoryStorage()
    runtime = KaosRuntime(storage=storage)
    publisher = _CollectingPublisher()

    runtime.register_connector(_OneShotConnector())
    runtime.register_agent(_EchoAgent())
    runtime.register_publisher(publisher)

    asyncio.run(runtime.start())

    # The connector emitted one event, the agent produced one artifact,
    # the publisher received it and storage recorded both.
    assert len(publisher.published) == 1
    artifact = publisher.published[0]
    assert artifact.produced_by == "echo-agent"
    assert artifact.content == {"text": "hello kaos"}
    assert len(artifact.source_events) == 1

    events = asyncio.run(storage.list_events("w1"))
    artifacts = asyncio.run(storage.list_artifacts("w1"))
    assert len(events) == 1
    assert len(artifacts) == 1
    # Traceability: the artifact references the stored event.
    assert artifact.source_events[0] == events[0].id


def test_runtime_start_is_idempotent() -> None:
    runtime = KaosRuntime()
    publisher = _CollectingPublisher()
    runtime.register_agent(_EchoAgent())
    runtime.register_publisher(publisher)

    async def scenario() -> None:
        await runtime.start()
        await runtime.start()  # second call must not double-subscribe
        await runtime.bus.publish(
            Event(type="message.created", source="t", workspace="w1", payload={"text": "x"})
        )

    asyncio.run(scenario())
    assert len(publisher.published) == 1

