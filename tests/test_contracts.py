"""Tests for the KAOS public contracts."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError

from kaos.contracts import (
    Agent,
    Artifact,
    Connector,
    Context,
    Event,
    EventBus,
    LLMProvider,
    Publisher,
    Runtime,
    Storage,
)


def test_event_defaults_and_immutability() -> None:
    event = Event(type="message.created", source="discord", workspace="w1")
    assert event.id is not None
    assert event.timestamp.tzinfo is not None
    assert event.payload == {}
    with pytest.raises(ValidationError):
        event.type = "changed"  # type: ignore[misc]


def test_artifact_tracks_source_events() -> None:
    e1, e2 = uuid4(), uuid4()
    artifact = Artifact(
        kind="summary",
        workspace="w1",
        produced_by="resume-agent",
        source_events=(e1, e2),
    )
    assert artifact.source_events == (e1, e2)
    with pytest.raises(ValidationError):
        artifact.kind = "other"  # type: ignore[misc]


def test_context_is_immutable() -> None:
    event = Event(type="message.created", source="discord", workspace="w1")
    context = Context(workspace="w1", events=(event,))
    assert context.events == (event,)
    with pytest.raises(ValidationError):
        context.workspace = "w2"  # type: ignore[misc]


class _FakeAgent:
    name = "fake-agent"

    def accepts(self, context: Context) -> bool:
        return True

    async def run(self, context: Context):  # type: ignore[no-untyped-def]
        return [
            Artifact(kind="summary", workspace=context.workspace, produced_by=self.name)
        ]


class _FakeConnector:
    name = "fake-connector"

    async def start(self, bus: EventBus) -> None:  # noqa: D102
        ...

    async def stop(self) -> None:  # noqa: D102
        ...


class _FakePublisher:
    name = "fake-publisher"

    async def publish(self, artifact: Artifact) -> None:  # noqa: D102
        ...


@pytest.mark.parametrize(
    ("instance", "protocol"),
    [
        (_FakeAgent(), Agent),
        (_FakeConnector(), Connector),
        (_FakePublisher(), Publisher),
    ],
)
def test_concrete_implementations_satisfy_protocols(instance: object, protocol: type) -> None:
    assert isinstance(instance, protocol)


def test_runtime_storage_llm_are_runtime_checkable() -> None:
    # Empty objects must NOT satisfy the behavioural protocols.
    assert not isinstance(object(), Runtime)
    assert not isinstance(object(), Storage)
    assert not isinstance(object(), LLMProvider)


def test_fake_agent_produces_traceable_artifact() -> None:
    agent = _FakeAgent()
    event = Event(type="message.created", source="discord", workspace="w1")
    context = Context(workspace="w1", events=(event,))
    assert agent.accepts(context)
    artifacts = asyncio.run(agent.run(context))
    assert artifacts[0].produced_by == "fake-agent"
    assert artifacts[0].workspace == "w1"
