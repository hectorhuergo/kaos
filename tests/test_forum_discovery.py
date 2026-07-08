"""Tests for forum thread discovery."""

from __future__ import annotations

import asyncio

import httpx

from kaos.plugins.connectors import list_forum_threads


def test_list_forum_threads_merges_active_and_archived() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bot tkn"
        if request.url.path.endswith("/threads/active"):
            return httpx.Response(
                200,
                json={
                    "threads": [
                        {"id": "1", "name": "Implementación", "parent_id": "FORUM"},
                        {"id": "2", "name": "Otro canal", "parent_id": "OTHER"},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"threads": [{"id": "3", "name": "Demo (archivado)"}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    threads = asyncio.run(
        list_forum_threads("tkn", "GUILD", "FORUM", client=client)
    )
    asyncio.run(client.aclose())

    ids = {tid for tid, _ in threads}
    names = {name for _, name in threads}
    # Active thread of another parent is filtered out; archived is included.
    assert ids == {"1", "3"}
    assert names == {"Implementación", "Demo (archivado)"}

