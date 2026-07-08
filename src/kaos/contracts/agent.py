"""Agent contract: transforms context into knowledge.

Agents are the heart of KAOS. They consume an immutable Context (events plus
parameters) and produce Artifacts. Agents never mutate events and always
declare the source events of what they produce.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from kaos.contracts.artifact import Artifact
from kaos.contracts.context import Context


@runtime_checkable
class Agent(Protocol):
    """Transforms a Context into a sequence of Artifacts."""

    @property
    def name(self) -> str:
        """Unique, stable identifier of the agent."""
        ...

    def accepts(self, context: Context) -> bool:
        """Return whether the agent can handle the given context."""
        ...

    async def run(self, context: Context) -> Sequence[Artifact]:
        """Transform the context into zero or more Artifacts."""
        ...

