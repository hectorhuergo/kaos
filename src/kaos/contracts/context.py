"""Execution context handed to an Agent.

A Context bundles the events an Agent must transform together with the
parameters that scope its execution. It is immutable so that Agent runs are
reproducible and traceable.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kaos.contracts.event import Event


class Context(BaseModel):
    """The immutable input an Agent transforms into Artifacts."""

    model_config = ConfigDict(frozen=True)

    workspace: str
    events: tuple[Event, ...] = ()
    params: dict[str, Any] = Field(default_factory=dict)

