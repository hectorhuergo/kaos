"""CredentialStore contract: durable persistence for provider credentials.

Keeps a :class:`ProviderCredential` per provider (the secret + optional endpoint
overrides). The Core stays agnostic of the concrete backend (PostgreSQL,
in-memory, ...), mirroring the ``Storage``, ``SubscriptionStore`` and
``ConfigStore`` contracts.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from kaos.domain.provider_credential import ProviderCredential


@runtime_checkable
class CredentialStore(Protocol):
    """Persists and retrieves per-provider credentials."""

    async def get(self, provider: str) -> ProviderCredential | None:
        """Return the stored credential for ``provider``, or ``None``."""
        ...

    async def set(self, credential: ProviderCredential) -> None:
        """Persist ``credential`` (replacing any previous one for its provider)."""
        ...

    async def delete(self, provider: str) -> bool:
        """Remove ``provider``'s credential; return whether one existed."""
        ...

    async def list(self) -> list[ProviderCredential]:
        """Return every stored credential (secrets included — keep server-side)."""
        ...

