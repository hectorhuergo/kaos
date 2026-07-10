"""ConfigStore contract: durable persistence for the runtime configuration.

Keeps the single active :class:`RuntimeConfig` (the selected LLM provider and
model). The Core stays agnostic of the concrete backend (PostgreSQL,
in-memory, ...), mirroring the ``Storage`` and ``SubscriptionStore`` contracts.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from kaos.domain.runtime_config import RuntimeConfig


@runtime_checkable
class ConfigStore(Protocol):
    """Persists and retrieves the active runtime configuration."""

    async def get(self) -> RuntimeConfig | None:
        """Return the persisted configuration, or ``None`` if unset."""
        ...

    async def set(self, config: RuntimeConfig) -> None:
        """Persist the configuration (replacing the previous one)."""
        ...

