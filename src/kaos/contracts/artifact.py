"""Unit of structured knowledge produced by an Agent.

Artifacts are the durable output of KAOS. They are immutable and always trace
back to the events that produced them, supporting the *Structured Knowledge*,
*Immutable Evidence* and *Everything is Traceable* principles.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from kaos.contracts.event import utcnow


class Artifact(BaseModel):
    """An immutable unit of knowledge produced by an Agent.

    Reports, summaries and dashboards are merely views over Artifacts; the
    Artifact itself is the asset.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    kind: str
    workspace: str
    produced_by: str
    content: dict[str, Any] = Field(default_factory=dict)
    source_events: tuple[UUID, ...] = ()
    timestamp: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

