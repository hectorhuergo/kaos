"""ProviderCredential: a provider's secret + endpoint overrides, persisted.

Historically KAOS kept every secret in the environment (Config Split, ADR-0008).
To let an operator configure providers entirely from the web console, a
provider's credential (API key/token) and optional endpoint overrides can now be
persisted in PostgreSQL, keyed by provider id. The environment stays as the
**fallback**: if no credential is stored for the active provider, the value from
``.env`` is used.

The secret is write-only from the API's perspective: it is never returned by the
read routes — only whether a credential is stored.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from kaos.contracts.event import utcnow


class ProviderCredential(BaseModel):
    """A persisted credential for one LLM provider (secret + optional overrides)."""

    provider: str
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    updated_at: datetime = Field(default_factory=utcnow)

