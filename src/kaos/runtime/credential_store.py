"""In-memory implementation of the CredentialStore contract.

Keeps provider credentials in process memory. Useful for tests and single-process
use; swap for PostgreSQL to persist across runs.
"""

from __future__ import annotations

from kaos.domain.provider_credential import ProviderCredential


class InMemoryCredentialStore:
    """Non-durable CredentialStore that keeps credentials in memory."""

    def __init__(self) -> None:
        self._creds: dict[str, ProviderCredential] = {}

    async def get(self, provider: str) -> ProviderCredential | None:
        return self._creds.get(provider)

    async def set(self, credential: ProviderCredential) -> None:
        self._creds[credential.provider] = credential

    async def delete(self, provider: str) -> bool:
        return self._creds.pop(provider, None) is not None

    async def list(self) -> list[ProviderCredential]:
        return list(self._creds.values())

