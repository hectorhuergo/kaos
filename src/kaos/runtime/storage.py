"""In-memory implementation of the Storage contract.

Keeps events and artifacts in process memory. Useful for tests and for the
single-process Runtime; it can be swapped for PostgreSQL/MinIO backends without
touching the rest of the system.
"""

from __future__ import annotations

from uuid import UUID

from kaos.contracts.artifact import Artifact
from kaos.contracts.event import Event


class InMemoryStorage:
    """Non-durable Storage that keeps everything in memory."""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._artifacts: dict[UUID, Artifact] = {}

    async def save_event(self, event: Event) -> None:
        """Record an event."""
        self._events.append(event)

    async def save_artifact(self, artifact: Artifact) -> None:
        """Record an artifact."""
        self._artifacts[artifact.id] = artifact

    async def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        """Return an artifact by id, or ``None`` if it does not exist."""
        return self._artifacts.get(artifact_id)

    async def list_events(self, workspace: str) -> list[Event]:
        """Return all events recorded for a workspace."""
        return [e for e in self._events if e.workspace == workspace]

    async def list_artifacts(self, workspace: str) -> list[Artifact]:
        """Return all artifacts produced within a workspace."""
        return [a for a in self._artifacts.values() if a.workspace == workspace]

