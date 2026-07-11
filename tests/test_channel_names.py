"""Tests for friendly channel/forum names and the dashboard header.

Covers the Discord REST helpers (mocked httpx transport, no network), the
best-effort label/header resolver (fallbacks without a token) and the dashboard
rendering of labels + header indicators. The knowledge-graph CSS is checked so
the sizing fix (percentage max-width, thinner lines) does not regress.
"""

from __future__ import annotations

import asyncio

import httpx

from kaos.core.config import Settings
from kaos.core.knowledge import KnowledgeGraph, KnowledgeNode
from kaos.plugins.connectors.discord_rest import (
    count_admin_roles,
    fetch_channel,
    fetch_guild,
)
from kaos.plugins.dashboard import directory, render_dashboard


def _client(handler) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_fetch_channel_normalizes_forum() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/channels/999")
        return httpx.Response(
            200,
            json={
                "id": "999",
                "name": "pmo-general",
                "topic": "coordinación PMO",
                "type": 15,
                "guild_id": "42",
            },
        )

    async def scenario() -> dict[str, object]:
        async with _client(handler) as client:
            return await fetch_channel("tok", "999", client=client)

    ch = asyncio.run(scenario())
    assert ch["name"] == "pmo-general"
    assert ch["type_label"] == "foro"
    assert ch["guild_id"] == "42"


def test_fetch_guild_reads_counts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["with_counts"] == "true"
        return httpx.Response(
            200,
            json={
                "id": "42",
                "name": "KAOS HQ",
                "approximate_member_count": 1200,
                "approximate_presence_count": 87,
                "premium_subscription_count": 3,
                "owner_id": "7",
            },
        )

    async def scenario() -> dict[str, object]:
        async with _client(handler) as client:
            return await fetch_guild("tok", "42", client=client)

    g = asyncio.run(scenario())
    assert g["name"] == "KAOS HQ"
    assert g["members"] == 1200 and g["online"] == 87 and g["boosts"] == 3


def test_count_admin_roles_counts_administrator_bit() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"name": "everyone", "permissions": "0"},
                {"name": "admin", "permissions": "8"},  # ADMINISTRATOR
                {"name": "owner", "permissions": "8"},
                {"name": "mod", "permissions": "4"},  # not admin
            ],
        )

    async def scenario() -> int:
        async with _client(handler) as client:
            return await count_admin_roles("tok", "42", client=client)

    assert asyncio.run(scenario()) == 2


def test_fallback_label_without_token() -> None:
    directory.clear_cache()
    settings = Settings()  # no discord token
    assert asyncio.run(directory.resolve_label("discord:123", settings)) == "discord:123"
    # GitHub reads well without any lookup.
    assert asyncio.run(directory.resolve_label("github:o/r", settings)) == "o/r"


def test_resolve_label_uses_channel_name_with_token() -> None:
    directory.clear_cache()
    settings = Settings(discord_token="tok")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "123", "name": "innova-cfi"})

    async def scenario() -> str:
        async with _client(handler) as client:
            return await directory.resolve_label("discord:123", settings, client=client)

    assert asyncio.run(scenario()) == "innova-cfi"


def test_resolve_header_none_without_token() -> None:
    directory.clear_cache()
    assert asyncio.run(directory.resolve_header("discord:123", Settings())) is None


def test_dashboard_renders_label_and_header() -> None:
    graph = KnowledgeGraph()
    graph.add_node(KnowledgeNode(id="discord:123", kind="workspace", label="discord:123"))
    header = {
        "workspace": "discord:123",
        "channel": {"name": "pmo-general", "topic": "coordinación", "type_label": "foro"},
        "guild": {"name": "KAOS HQ", "members": 1200, "online": 87, "admin_roles": 2},
    }
    html_doc = render_dashboard(
        [("discord:123", [])],
        graph,
        header=header,
        workspace_labels={"discord:123": "pmo-general"},
    )
    # The section heading shows the friendly name (id kept as secondary).
    assert "pmo-general" in html_doc
    assert "ws-id" in html_doc
    # The header shows guild details and indicators.
    assert "KAOS HQ" in html_doc
    assert "1200" in html_doc and "roles admin" in html_doc


def test_graph_css_is_responsive_and_thin() -> None:
    html_doc = render_dashboard([("w", [])], KnowledgeGraph())
    # Percentage max-width (not the previous max-width:none) and thinner strokes.
    assert "max-width:100% !important" in html_doc
    assert "stroke-width:1px" in html_doc
    assert "useMaxWidth: true" in html_doc

