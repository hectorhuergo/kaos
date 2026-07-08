"""SubscriptionStore contract: durable persistence for subscriptions.

Keeps the set of sources KAOS watches. The Core stays agnostic of the concrete
backend (PostgreSQL, in-memory, ...), mirroring the ``Storage`` contract.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from kaos.domain.subscription import Subscription


@runtime_checkable
class SubscriptionStore(Protocol):
    """Persists and retrieves subscriptions."""

    async def add(self, subscription: Subscription) -> None:
        """Persist a subscription (upsert by ``channel_id``)."""
        ...

    async def get(self, channel_id: str) -> Subscription | None:
        """Return the subscription for a channel, or ``None``."""
        ...

    async def list(self, *, active_only: bool = True) -> Sequence[Subscription]:
        """Return subscriptions, by default only the active ones."""
        ...

    async def deactivate(self, channel_id: str) -> bool:
        """Mark a subscription inactive. Return ``True`` if one was found."""
        ...

