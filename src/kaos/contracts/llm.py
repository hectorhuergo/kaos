"""LLMProvider contract: AI Provider Agnostic access to language models.

The Core never depends on a concrete AI provider. Agents request completions
through this contract and any provider (OpenAI, Anthropic, local, ...) can be
plugged in behind it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


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

