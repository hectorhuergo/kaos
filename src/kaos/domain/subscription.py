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
    # Whether an *automated* run (the scheduler / ``kaos run``) publishes this
    # subscription's summary to Discord. Defaults to ``True`` (the historical
    # behavior). Turn it off to keep a subscription "knowledge-only": it is still
    # summarized and persisted, but not posted. The interactive console run keeps
    # its own explicit publish toggle, independent of this default.
    publish_default: bool = True
    # Optional project grouping: workspaces that share the same ``project`` are
    # related in the knowledge graph (Cross-Workspace Relations, ADR-0019), even
    # when their names don't share a prefix — e.g. the ``kaos`` repo (the brain)
    # grouped under the ``proyecto-x`` project alongside its forum and repos.
    project: str | None = None
    # Explicit, ad-hoc relations to other subscriptions (by workspace id). Adds
    # ``related_to`` edges in the graph beyond project/name grouping, so an
    # operator can connect two workspaces that neither share a name nor a project.
    related_to: list[str] = Field(default_factory=list)
    # Execution plan: how often the scheduler should run this subscription, in
    # seconds. ``None`` means "every scheduler pass" (the global cadence). The
    # plan lives with the thing being watched — there is no separate plan store.
    interval_seconds: int | None = None
    # Per-subscription LLM override. When set, the scheduler, ``kaos run`` and the
    # console use this provider/model instead of the global default (empty means
    # "use the global default"). Persisted so every run path honors the choice.
    llm_provider: str | None = None
    llm_model: str | None = None
    # Which agent processes this subscription. ``None`` means the default
    # summarizer (``resume-agent``). The selected agent's persisted extra
    # instructions augment the summary and it is stamped on the produced
    # artifact's ``metadata["agent_id"]`` for traceability. A single agent for
    # now; kept nullable/forward-compatible for future multi-agent orchestration.
    agent_id: str | None = None
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

