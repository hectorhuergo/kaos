"""Runtime contract: orchestrates the execution of the platform.

The Runtime wires Connectors, Agents and Publishers together around the
EventBus. Plugins register themselves through this contract but never modify
the Runtime itself.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from kaos.contracts.agent import Agent
from kaos.contracts.connector import Connector
from kaos.contracts.publisher import Publisher


@runtime_checkable
class Runtime(Protocol):
    """Orchestrates connectors, agents and publishers."""

    def register_connector(self, connector: Connector) -> None:
        """Register a connector to produce events."""
        ...

    def register_agent(self, agent: Agent) -> None:
        """Register an agent to transform context into knowledge."""
        ...

    def register_publisher(self, publisher: Publisher) -> None:
        """Register a publisher to expose knowledge."""
        ...

    async def start(self) -> None:
        """Start the runtime and all registered components."""
        ...

    async def stop(self) -> None:
        """Stop the runtime and release all resources."""
        ...

