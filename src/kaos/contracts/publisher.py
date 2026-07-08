"""Publisher contract: exposes knowledge as views.

Publishers take Artifacts and expose them through some medium (a Discord
message, a dashboard, an API response, ...). They render knowledge but never
create it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from kaos.contracts.artifact import Artifact


@runtime_checkable
class Publisher(Protocol):
    """Exposes Artifacts through an output medium."""

    @property
    def name(self) -> str:
        """Unique, stable identifier of the publisher."""
        ...

    async def publish(self, artifact: Artifact) -> None:
        """Expose the given artifact through the publisher's medium."""
        ...

