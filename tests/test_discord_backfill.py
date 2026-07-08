"""Tests for the Discord backfill source (REST, no network via MockTransport)."""

from __future__ import annotations

import asyncio

import httpx

from kaos.contracts import Artifact, Context
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.agents.resume_agent import CONVERSATION_COMPLETED
from kaos.plugins.connectors import DiscordBackfillSource, DiscordConnector
from kaos.runtime import InMemoryEventBus, InMemoryStorage, KaosRuntime
from kaos.sdk import EchoLLMProvider


def _msg(mid: str, text: str, *, bot: bool = False, name: str = "ana") -> dict:
    return {
        "id": mid,
        "channel_id": "1416219205216374795",
        "author": {"username": name, "global_name": name, "bot": bot},
        "content": text,
    }


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_backfill_reads_in_chronological_order_and_filters_bots() -> None:
    # Discord returns newest-first. Two humans + one bot.
    newest_first = [
        _msg("3", "tercero"),
        _msg("2", "segundo (bot)", bot=True, name="botty"),
        _msg("1", "primero"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bot tkn"
        assert request.url.params.get("limit") == "100"
        return httpx.Response(200, json=newest_first)

    source = DiscordBackfillSource(
        token="tkn", channel_id="1416219205216374795", guild_id="42", client=_client(handler)
    )

    async def collect() -> list[str]:
        out = []
        async for m in source.messages():
            out.append(m.text)
        await source.close()
        return out

    texts = asyncio.run(collect())
    # Chronological (oldest first) and the bot message filtered out.
    assert texts == ["primero", "tercero"]


def test_backfill_paginates_with_before() -> None:
    seen_params: list[str | None] = []
    page1 = [_msg(str(i), f"m{i}") for i in range(200, 100, -1)]  # 100 items, ids 200..101
    page2 = [_msg(str(i), f"m{i}") for i in range(100, 50, -1)]   # 50 items, ids 100..51

    def handler(request: httpx.Request) -> httpx.Response:
        before = request.url.params.get("before")
        seen_params.append(before)
        return httpx.Response(200, json=page1 if before is None else page2)

    source = DiscordBackfillSource(
        token="tkn", channel_id="c", limit=200, client=_client(handler)
    )

    async def count() -> int:
        n = 0
        async for _ in source.messages():
            n += 1
        await source.close()
        return n

    total = asyncio.run(count())
    assert total == 150
    # Second request paginated using the last id of page 1 (101).
    assert seen_params == [None, "101"]


class _CollectingPublisher:
    name = "collecting-publisher"

    def __init__(self) -> None:
        self.published: list[Artifact] = []

    async def publish(self, artifact: Artifact) -> None:
        self.published.append(artifact)


def test_backfill_to_resume_pipeline() -> None:
    newest_first = [_msg("2", "usaremos PostgreSQL"), _msg("1", "avanzamos con Odoo")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=newest_first)

    source = DiscordBackfillSource(
        token="tkn", channel_id="1416219205216374795", guild_id="1404788552444940380",
        client=_client(handler),
    )
    runtime = KaosRuntime(storage=InMemoryStorage())
    publisher = _CollectingPublisher()
    runtime.register_connector(DiscordConnector(source, emit_completed=True))
    runtime.register_agent(ResumeAgent(EchoLLMProvider()))  # echo -> transcript
    runtime.register_publisher(publisher)

    asyncio.run(runtime.start())

    assert len(publisher.published) == 1
    artifact = publisher.published[0]
    assert artifact.workspace == "discord:1404788552444940380"
    assert artifact.content["message_count"] == 2
    # Transcript is chronological.
    assert artifact.content["summary"] == "ana: avanzamos con Odoo\nana: usaremos PostgreSQL"

