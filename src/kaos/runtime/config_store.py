"""In-memory implementation of the ConfigStore contract.

Keeps the active :class:`RuntimeConfig` in process memory. Useful for tests and
single-process use; swap for PostgreSQL to persist across runs.
"""

from __future__ import annotations

from kaos.domain.runtime_config import RuntimeConfig


class InMemoryConfigStore:
    """Non-durable ConfigStore that keeps the config in memory."""

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self._config = config

    async def get(self) -> RuntimeConfig | None:
        return self._config

    async def set(self, config: RuntimeConfig) -> None:
        self._config = config

