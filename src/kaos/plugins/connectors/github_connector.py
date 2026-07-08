"""GitHub Connector: adapts GitHub repo activity into KAOS events.

Like the Discord connector, it depends on a `GitHubActivitySource` abstraction
instead of a concrete client, so it can be tested without the network and backed
by the real REST API in production. Each activity item (a commit, issue or pull
request) becomes a ``message.created`` event, so the existing Resume Agent can
summarize a repository's recent activity into knowledge — KAOS dogfooding its
own development.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from kaos.contracts.event import Event
from kaos.contracts.event_bus import EventBus

EVENT_TYPE = "message.created"
CONVERSATION_COMPLETED = "conversation.completed"

COMMIT = "commit"
ISSUE = "issue"
PULL_REQUEST = "pull_request"


class GitHubItem(BaseModel):
    """A normalized unit of GitHub activity (commit, issue or pull request)."""

    item_id: str
    kind: str
    author: str
    text: str
    url: str = ""
    timestamp: str | None = None


@runtime_checkable
class GitHubActivitySource(Protocol):
    """Yields normalized GitHub activity items (e.g. a REST reader)."""

    def items(self) -> AsyncIterator[GitHubItem]:
        """Return an async iterator of activity items."""
        ...

    async def close(self) -> None:
        """Release any resources held by the source."""
        ...


class StaticGitHubSource:
    """A finite `GitHubActivitySource` over a fixed list, for tests and demos."""

    def __init__(self, items: list[GitHubItem]) -> None:
        self._items = items
        self.closed = False

    async def items(self) -> AsyncIterator[GitHubItem]:
        for item in self._items:
            yield item

    async def close(self) -> None:
        self.closed = True


class GitHubConnector:
    """Produces `message.created` events from a GitHub activity source."""

    name = "github-connector"

    def __init__(
        self,
        source: GitHubActivitySource,
        repo: str,
        emit_completed: bool = False,
    ) -> None:
        self._source = source
        self._repo = repo
        self._emit_completed = emit_completed

    @property
    def workspace(self) -> str:
        return f"github:{self._repo}"

    async def start(self, bus: EventBus) -> None:
        """Drain the source, publishing an event per activity item.

        When ``emit_completed`` is set, a ``conversation.completed`` trigger is
        published after the batch so the Resume Agent runs once over the whole
        activity window.
        """
        seen = False
        async for item in self._source.items():
            seen = True
            await bus.publish(self._to_event(item))
        if self._emit_completed and seen:
            await bus.publish(
                Event(
                    type=CONVERSATION_COMPLETED,
                    source=self.name,
                    workspace=self.workspace,
                    payload={},
                )
            )

    async def stop(self) -> None:
        """Close the underlying source."""
        await self._source.close()

    def _to_event(self, item: GitHubItem) -> Event:
        payload = {
            "author": item.author,
            "text": f"[{item.kind}] {item.text}",
            "message_id": item.item_id,
            "kind": item.kind,
        }
        if item.url:
            payload["url"] = item.url
        if item.timestamp:
            payload["timestamp"] = item.timestamp
        return Event(
            type=EVENT_TYPE,
            source=self.name,
            workspace=self.workspace,
            payload=payload,
        )

