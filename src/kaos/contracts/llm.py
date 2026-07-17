"""LLMProvider contract: AI Provider Agnostic access to language models.

The Core never depends on a concrete AI provider. Agents request completions
through this contract and any provider (OpenAI, Anthropic, local, ...) can be
plugged in behind it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class LLMError(RuntimeError):
    """A provider-side failure while requesting a completion.

    Carries a human-readable ``message`` (safe to surface in the UI) plus optional
    context: the provider ``name``, the ``model`` and the upstream HTTP
    ``status_code``. This keeps the Core AI-Provider-Agnostic while letting
    callers show a meaningful error (e.g. "unknown model", "rate limited",
    "request too large") instead of a raw transport/HTTP exception.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.status_code = status_code


class Message(BaseModel):
    """A single chat message exchanged with a language model."""

    role: str
    content: str


@runtime_checkable
class LLMProvider(Protocol):
    """Provider-agnostic access to a language model."""

    @property
    def name(self) -> str:
        """Unique, stable identifier of the provider."""
        ...

    async def complete(self, messages: Sequence[Message], **options: object) -> str:
        """Return the model completion for the given conversation."""
        ...

