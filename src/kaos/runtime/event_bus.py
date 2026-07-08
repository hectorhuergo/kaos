"""In-memory implementation of the EventBus contract.

A simple publish/subscribe bus suitable for a single-process Runtime and for
tests. It keeps the Core agnostic: it can be swapped for a Redis-backed bus
without touching Connectors, Agents or Publishers.
"""

from __future__ import annotations

from collections import defaultdict

from kaos.contracts.event import Event
from kaos.contracts.event_bus import EventHandler

WILDCARD = "*"
"""Subscribe with this event type to receive every event."""


class InMemoryEventBus:
    """Dispatches events to subscribers within the current process."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for ``event_type`` (use ``*`` for all events)."""
        self._handlers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        """Dispatch an event to handlers of its type and to wildcard handlers."""
        for handler in (*self._handlers.get(event.type, ()), *self._handlers.get(WILDCARD, ())):
            await handler(event)

