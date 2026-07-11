"""Subscription: what KAOS watches and where it publishes.

A Subscription is domain state (not a secret): it records which source KAOS
should summarize (a Discord forum/channel or a GitHub repository) and the thread
where the summary is published. It persists in the Storage layer so the set of
things KAOS manages survives restarts and evolves at runtime
(subscribe/unsubscribe) without redeploying. Secrets (tokens, DSNs) stay in the
environment.

For a Discord subscription ``channel_id`` holds the forum/channel id; for a
GitHub subscription it holds the repository slug (``owner/name``). The
``workspace`` field is the canonical, provider-namespaced id the rest of the
system reasons about.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from kaos.contracts.event import utcnow

FORUM = "forum"
CHANNEL = "channel"
GITHUB = "github"
KINDS = (FORUM, CHANNEL, GITHUB)


class Subscription(BaseModel):
    """A source KAOS watches and the thread it publishes summaries to."""

    id: UUID = Field(default_factory=uuid4)
    workspace: str
    kind: str = FORUM
    channel_id: str
    guild_id: str | None = None
    resume_thread_id: str | None = None
    active: bool = True
    # Execution plan: how often the scheduler should run this subscription, in
    # seconds. ``None`` means "every scheduler pass" (the global cadence). The
    # plan lives with the thing being watched — there is no separate plan store.
    interval_seconds: int | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @staticmethod
    def workspace_for(channel_id: str) -> str:
        """Return the canonical workspace id for a Discord channel/forum."""
        return f"discord:{channel_id}"

    @staticmethod
    def workspace_for_github(repo: str) -> str:
        """Return the canonical workspace id for a GitHub repository."""
        return f"github:{repo}"

    @classmethod
    def workspace_for_kind(cls, kind: str, channel_id: str) -> str:
        """Return the canonical workspace id for ``channel_id`` given its kind."""
        if kind == GITHUB:
            return cls.workspace_for_github(channel_id)
        return cls.workspace_for(channel_id)

