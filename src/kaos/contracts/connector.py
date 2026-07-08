"""Connector contract: the sources that produce events.

A Connector adapts an external system (Discord, GitHub, Odoo, ...) into KAOS
events. Discord is simply the first Connector of the platform.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from kaos.contracts.event_bus import EventBus


@runtime_checkable
class Connector(Protocol):
    """Produces events from an external system onto the EventBus."""

    @property
    def name(self) -> str:
        """Unique, stable identifier of the connector."""
        ...

    async def start(self, bus: EventBus) -> None:
        """Begin producing events onto the given bus."""
        ...

    async def stop(self) -> None:
        """Stop producing events and release resources."""
        ...

