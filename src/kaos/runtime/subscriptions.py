"""In-memory implementation of the SubscriptionStore contract.

Keeps subscriptions in process memory. Useful for tests and single-process use;
swap for PostgreSQL to persist across runs.
"""

from __future__ import annotations

from kaos.domain.subscription import Subscription


class InMemorySubscriptionStore:
    """Non-durable SubscriptionStore that keeps everything in memory."""

    def __init__(self) -> None:
        self._by_channel: dict[str, Subscription] = {}

    async def add(self, subscription: Subscription) -> None:
        self._by_channel[subscription.channel_id] = subscription

    async def get(self, channel_id: str) -> Subscription | None:
        return self._by_channel.get(channel_id)

    async def list(self, *, active_only: bool = True) -> list[Subscription]:
        subs = list(self._by_channel.values())
        return [s for s in subs if s.active] if active_only else subs

    async def deactivate(self, channel_id: str) -> bool:
        current = self._by_channel.get(channel_id)
        if current is None:
            return False
        self._by_channel[channel_id] = current.model_copy(update={"active": False})
        return True

