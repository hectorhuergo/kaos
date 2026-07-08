"""Subscription: what KAOS watches and where it publishes.

A Subscription is domain state (not a secret): it records which Discord
forum/channel KAOS should summarize and the thread where the summary is
published. It persists in the Storage layer so the set of things KAOS manages
survives restarts and evolves at runtime (subscribe/unsubscribe) without
redeploying. Secrets (tokens, DSNs) stay in the environment.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from kaos.contracts.event import utcnow

FORUM = "forum"
CHANNEL = "channel"
KINDS = (FORUM, CHANNEL)


class Subscription(BaseModel):
    """A source KAOS watches and the thread it publishes summaries to."""

    id: UUID = Field(default_factory=uuid4)
    workspace: str
    kind: str = FORUM
    channel_id: str
    guild_id: str | None = None
    resume_thread_id: str | None = None
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)

    @staticmethod
    def workspace_for(channel_id: str) -> str:
        """Return the canonical workspace id for a Discord channel/forum."""
        return f"discord:{channel_id}"

