"""Tests for the GitHub connector (REST source, connector, pipeline)."""

from __future__ import annotations

import asyncio

import httpx

from kaos.contracts import Artifact, Event
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.connectors import (
    GitHubConnector,
    GitHubItem,
    GitHubRestSource,
    StaticGitHubSource,
)
from kaos.plugins.connectors.github_connector import COMMIT, ISSUE, PULL_REQUEST
from kaos.runtime import InMemoryEventBus, InMemoryStorage, KaosRuntime
from kaos.sdk import EchoLLMProvider

REPO = "hectorhuergo/kaos"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _commit(sha: str, msg: str, login: str, date: str) -> dict:
    return {
        "sha": sha,
        "html_url": f"https://github.com/{REPO}/commit/{sha}",
        "commit": {"message": msg, "author": {"name": login.title(), "date": date}},
        "author": {"login": login},
    }


def _issue(number: int, title: str, login: str, created: str, *, pr: bool = False) -> dict:
    raw = {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "created_at": created,
        "user": {"login": login},
    }
    if pr:
        raw["pull_request"] = {"url": "..."}
    return raw


def test_rest_source_maps_commits_and_issues_chronologically() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tkn"
        if request.url.path.endswith("/commits"):
            return httpx.Response(200, json=[_commit("a1", "feat: x\n\nbody", "ana", "2026-07-01T10:00:00Z")])
        if request.url.path.endswith("/issues"):
            return httpx.Response(
                200,
                json=[
                    _issue(8, "Add feature", "ana", "2026-07-03T10:00:00Z", pr=True),
                    _issue(7, "Bug", "beto", "2026-07-02T10:00:00Z"),
                ],
            )
        return httpx.Response(404, json={})

    source = GitHubRestSource(token="tkn", repo=REPO, client=_client(handler))

    async def collect() -> list[GitHubItem]:
        out = [item async for item in source.items()]
        await source.close()
        return out

    items = asyncio.run(collect())
    assert [i.kind for i in items] == [COMMIT, ISSUE, PULL_REQUEST]  # chronological
    assert items[0].text == "feat: x"  # first line only
    assert items[0].author == "ana"
    assert items[2].text == "#8 Add feature"


def test_connector_publishes_events_and_completed() -> None:
    bus = InMemoryEventBus()
    seen: list[Event] = []

    async def handler(event: Event) -> None:
        seen.append(event)

    source = StaticGitHubSource(
        [
            GitHubItem(item_id="a1", kind=COMMIT, author="ana", text="feat: x", timestamp="2026-07-01T10:00:00Z"),
            GitHubItem(item_id="issue-7", kind=ISSUE, author="beto", text="#7 Bug"),
        ]
    )
    connector = GitHubConnector(source, repo=REPO, emit_completed=True)

    async def scenario() -> None:
        bus.subscribe("*", handler)
        await connector.start(bus)
        await connector.stop()

    asyncio.run(scenario())

    assert [e.type for e in seen] == ["message.created", "message.created", "conversation.completed"]
    assert seen[0].workspace == f"github:{REPO}"
    assert seen[0].payload["text"] == "[commit] feat: x"
    assert seen[0].payload["timestamp"] == "2026-07-01T10:00:00Z"
    assert source.closed is True


class _CollectingPublisher:
    name = "collecting-publisher"

    def __init__(self) -> None:
        self.published: list[Artifact] = []

    async def publish(self, artifact: Artifact) -> None:
        self.published.append(artifact)


def test_github_to_resume_pipeline() -> None:
    source = StaticGitHubSource(
        [GitHubItem(item_id="a1", kind=COMMIT, author="ana", text="feat: knowledge graph")]
    )
    runtime = KaosRuntime(storage=InMemoryStorage())
    publisher = _CollectingPublisher()
    runtime.register_connector(GitHubConnector(source, repo=REPO, emit_completed=True))
    runtime.register_agent(ResumeAgent(EchoLLMProvider()))  # echo -> transcript
    runtime.register_publisher(publisher)

    asyncio.run(runtime.start())

    assert len(publisher.published) == 1
    artifact = publisher.published[0]
    assert artifact.workspace == f"github:{REPO}"
    assert "[commit] feat: knowledge graph" in artifact.content["summary"]

