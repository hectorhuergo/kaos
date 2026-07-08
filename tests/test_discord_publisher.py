"""Tests for the Discord Publisher and REST poster."""

from __future__ import annotations

import asyncio

import httpx

from kaos.contracts import Artifact
from kaos.plugins.publishers import DiscordPublisher, DiscordRestPoster, DiscordWebhookPublisher
from kaos.plugins.publishers.discord_publisher import chunk_message


def test_chunk_message_splits_on_lines_within_limit() -> None:
    text = "\n".join(f"line {i}" for i in range(100))
    chunks = chunk_message(text, limit=50)
    assert all(len(c) <= 50 for c in chunks)
    # Rejoining reproduces the original content.
    assert "\n".join(chunks) == text


def test_chunk_message_hard_splits_long_line() -> None:
    chunks = chunk_message("x" * 120, limit=50)
    assert [len(c) for c in chunks] == [50, 50, 20]


def test_chunk_message_short_content_single_chunk() -> None:
    assert chunk_message("hola") == ["hola"]


class _FakePoster:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.channel_calls: list[tuple[str, str]] = []

    async def post_to_thread(self, channel_id: str, thread_name: str, content: str) -> None:
        self.calls.append((channel_id, thread_name, content))

    async def post_to_channel(self, channel_id: str, content: str) -> None:
        self.channel_calls.append((channel_id, content))


def _summary_artifact(channel_id: str | None) -> Artifact:
    return Artifact(
        kind="conversation.summary",
        workspace="discord:42",
        produced_by="resume-agent",
        content={"summary": "# Resumen Ejecutivo"},
        metadata={"channel_id": channel_id} if channel_id else {},
    )


def test_publisher_posts_summary_to_thread() -> None:
    poster = _FakePoster()
    publisher = DiscordPublisher(poster, thread_name="📋 Resume")
    asyncio.run(publisher.publish(_summary_artifact("100")))
    assert poster.calls == [("100", "📋 Resume", "# Resumen Ejecutivo")]


def test_publisher_skips_without_channel() -> None:
    poster = _FakePoster()
    publisher = DiscordPublisher(poster)
    asyncio.run(publisher.publish(_summary_artifact(None)))
    assert poster.calls == []


def test_publisher_posts_to_fixed_thread_id() -> None:
    # With a thread_id (e.g. "PMO"), the bot posts directly into that thread,
    # regardless of the artifact's originating channel.
    poster = _FakePoster()
    publisher = DiscordPublisher(poster, thread_id="1415760589195575356")
    asyncio.run(publisher.publish(_summary_artifact(None)))
    assert poster.channel_calls == [("1415760589195575356", "# Resumen Ejecutivo")]
    assert poster.calls == []


def test_rest_poster_posts_to_channel_by_id() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["Authorization"] == "Bot tkn"
        return httpx.Response(200, json={"id": "msg-1"})

    poster = DiscordRestPoster("tkn", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def scenario() -> None:
        await poster.post_to_channel("1415760589195575356", "hola")
        await poster.aclose()

    asyncio.run(scenario())

    assert calls == ["https://discord.com/api/v10/channels/1415760589195575356/messages"]


def test_rest_poster_creates_thread_and_message() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/threads"):
            assert request.headers["Authorization"] == "Bot tkn"
            return httpx.Response(201, json={"id": "thread-1"})
        return httpx.Response(200, json={"id": "msg-1"})

    poster = DiscordRestPoster("tkn", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    async def scenario() -> None:
        await poster.post_to_thread("100", "📋 Resume", "hola")
        await poster.aclose()

    asyncio.run(scenario())

    assert calls == [
        "https://discord.com/api/v10/channels/100/threads",
        "https://discord.com/api/v10/channels/thread-1/messages",
    ]


def test_webhook_publisher_posts_to_thread() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["thread_id"] = request.url.params.get("thread_id")
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "posted"})

    publisher = DiscordWebhookPublisher(
        "https://discord.com/api/webhooks/1/abc",
        thread_id="1415760589195575356",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    artifact = Artifact(
        kind="conversation.summary",
        workspace="discord:42",
        produced_by="resume-agent",
        content={"summary": "# Resumen Ejecutivo"},
    )

    async def scenario() -> None:
        await publisher.publish(artifact)
        await publisher.aclose()

    asyncio.run(scenario())

    assert captured["thread_id"] == "1415760589195575356"
    assert captured["body"]["content"] == "# Resumen Ejecutivo"
    assert captured["body"]["username"] == "KAOS"


def test_webhook_publisher_splits_long_summary() -> None:
    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        posts.append(json.loads(request.content)["content"])
        return httpx.Response(200, json={"id": "x"})

    long_summary = "\n".join(f"linea {i} " + "y" * 100 for i in range(60))
    publisher = DiscordWebhookPublisher(
        "https://discord.com/api/webhooks/1/abc",
        thread_id="999",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    artifact = Artifact(
        kind="conversation.summary",
        workspace="w",
        produced_by="resume-agent",
        content={"summary": long_summary},
    )
    asyncio.run(publisher.publish(artifact))

    assert len(posts) > 1  # split into several messages
    assert all(len(p) <= 2000 for p in posts)


def test_webhook_publisher_skips_without_summary() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200)

    publisher = DiscordWebhookPublisher(
        "https://discord.com/api/webhooks/1/abc",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    artifact = Artifact(kind="x", workspace="w", produced_by="p", content={})
    asyncio.run(publisher.publish(artifact))
    assert calls == []


