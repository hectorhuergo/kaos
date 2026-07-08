"""Concrete Runtime that orchestrates the KAOS pipeline.

The Runtime wires everything around the EventBus:

    Connectors -> EventBus -> Agents -> Publishers

For every event it builds a Context, runs the Agents that accept it, and hands
the produced Artifacts to the Publishers. An optional Storage persists both the
events (evidence) and the artifacts (knowledge).
"""

from __future__ import annotations

from kaos.contracts.agent import Agent
from kaos.contracts.connector import Connector
from kaos.contracts.context import Context
from kaos.contracts.event import Event
from kaos.contracts.event_bus import EventBus
from kaos.contracts.publisher import Publisher
from kaos.contracts.storage import Storage
from kaos.runtime.event_bus import WILDCARD, InMemoryEventBus


class KaosRuntime:
    """Single-process orchestration of connectors, agents and publishers."""

    def __init__(self, bus: EventBus | None = None, storage: Storage | None = None) -> None:
        self._bus: EventBus = bus if bus is not None else InMemoryEventBus()
        self._storage = storage
        self._connectors: list[Connector] = []
        self._agents: list[Agent] = []
        self._publishers: list[Publisher] = []
        self._history: dict[str, list[Event]] = {}
        self._started = False

    @property
    def bus(self) -> EventBus:
        """The EventBus used to move events through the pipeline."""
        return self._bus

    def register_connector(self, connector: Connector) -> None:
        """Register a connector to produce events."""
        self._connectors.append(connector)

    def register_agent(self, agent: Agent) -> None:
        """Register an agent to transform context into knowledge."""
        self._agents.append(agent)

    def register_publisher(self, publisher: Publisher) -> None:
        """Register a publisher to expose knowledge."""
        self._publishers.append(publisher)

    async def start(self) -> None:
        """Subscribe the dispatcher and start every connector."""
        if self._started:
            return
        self._bus.subscribe(WILDCARD, self._on_event)
        self._started = True
        for connector in self._connectors:
            await connector.start(self._bus)

    async def stop(self) -> None:
        """Stop every connector and mark the runtime as stopped."""
        for connector in self._connectors:
            await connector.stop()
        self._started = False

    async def _on_event(self, event: Event) -> None:
        """Transform an event into knowledge and publish it.

        Events are accumulated per workspace so that conversation-level agents
        receive the whole conversation as context (a minimal Context Engine),
        not just the triggering event.
        """
        if self._storage is not None:
            await self._storage.save_event(event)
        history = self._history.setdefault(event.workspace, [])
        history.append(event)
        context = Context(workspace=event.workspace, events=tuple(history))
        for agent in self._agents:
            if not agent.accepts(context):
                continue
            for artifact in await agent.run(context):
                if self._storage is not None:
                    await self._storage.save_artifact(artifact)
                for publisher in self._publishers:
                    await publisher.publish(artifact)

