"""Storage contract: durable persistence for events and artifacts.

Storage keeps the immutable record of everything that happens (events) and
everything that is known (artifacts). The Core stays agnostic of the concrete
backend (PostgreSQL, MinIO, in-memory, ...).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from kaos.contracts.artifact import Artifact
from kaos.contracts.event import Event


@runtime_checkable
class Storage(Protocol):
    """Persists and retrieves events and artifacts."""

    async def save_event(self, event: Event) -> None:
        """Persist an event immutably."""
        ...

    async def save_artifact(self, artifact: Artifact) -> None:
        """Persist an artifact immutably."""
        ...

    async def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        """Retrieve an artifact by id, or ``None`` if it does not exist."""
        ...

    async def list_events(self, workspace: str) -> Sequence[Event]:
        """Return all events recorded for a workspace."""
        ...

    async def list_artifacts(self, workspace: str) -> Sequence[Artifact]:
        """Return all artifacts produced within a workspace."""
        ...

