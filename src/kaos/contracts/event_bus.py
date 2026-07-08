"""EventBus contract: the transport that decouples Connectors from the Runtime.

Connectors publish events onto the bus and the Runtime dispatches them to the
appropriate Agents. The bus keeps the Core agnostic of any concrete transport
(in-memory, Redis, etc.).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from kaos.contracts.event import Event

EventHandler = Callable[[Event], Awaitable[None]]
"""An async callable that reacts to a published Event."""


@runtime_checkable
class EventBus(Protocol):
    """Publish/subscribe transport for events."""

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers of its type."""
        ...

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for events of the given type (``*`` for all)."""
        ...

