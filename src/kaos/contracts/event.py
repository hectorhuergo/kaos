"""Immutable fact produced by a Connector.

Embodies the *Event First* and *Immutable Evidence* principles: every piece of
knowledge in KAOS originates from an event, and events are never mutated once
recorded.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


class Event(BaseModel):
    """An immutable fact emitted by a Connector.

    Events are the single source of truth in KAOS. Runtime orchestrates their
    flow and Agents transform them into knowledge (Artifacts).
    """

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    type: str
    source: str
    workspace: str
    timestamp: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: UUID | None = None

