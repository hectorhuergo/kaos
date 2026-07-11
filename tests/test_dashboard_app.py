"""Tests for the live FastAPI dashboard app.

Skipped when FastAPI/starlette's TestClient stack is not installed, so the base
test run stays dependency-light. The knowledge projection itself is covered by
``test_knowledge.py``; here we check the app wiring and routes.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from kaos.contracts.artifact import Artifact  # noqa: E402
from kaos.core.config import Settings  # noqa: E402
from kaos.plugins.dashboard.app import create_app  # noqa: E402
from kaos.runtime import InMemoryStorage  # noqa: E402

WS = "discord:demo"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # A shared in-memory storage seeded with one summary; the app resolves the
    # workspace explicitly via the query string, so no subscriptions are needed.
    storage = InMemoryStorage()

    async def seed() -> None:
        await storage.save_artifact(
            Artifact(
                kind="conversation.summary",
                workspace=WS,
                produced_by="resume-agent",
                content={"summary": "# Resumen\n- ok", "message_count": 1},
                metadata={"thread_name": "PMO", "model": "gpt-4o"},
            )
        )

    asyncio.run(seed())
    return TestClient(create_app(Settings(), storage=storage))


def test_index_returns_html(client: TestClient) -> None:
    resp = client.get("/", params={"workspace": WS})
    assert resp.status_code == 200
    assert "<!doctype html>" in resp.text
    assert "PMO" in resp.text


def test_api_knowledge_returns_graph(client: TestClient) -> None:
    resp = client.get("/api/knowledge", params={"workspace": WS})
    assert resp.status_code == 200
    data = resp.json()
    assert {"nodes", "edges"} == set(data)
    kinds = {n["kind"] for n in data["nodes"]}
    assert "workspace" in kinds and "artifact" in kinds


def test_api_artifacts_returns_items(client: TestClient) -> None:
    resp = client.get("/api/artifacts", params={"workspace": WS})
    assert resp.status_code == 200
    payload = resp.json()["artifacts"]
    assert payload[0]["workspace"] == WS
    assert payload[0]["items"][0]["metadata"]["thread_name"] == "PMO"


def test_api_artifacts_returns_all_versions_of_a_thread() -> None:
    # The same thread summarized by two models is kept as two versions (the graph
    # is deduped to one node, but the view groups the versions into one card).
    storage = InMemoryStorage()

    async def seed() -> None:
        older = Artifact(
            kind="conversation.summary",
            workspace=WS,
            produced_by="resume-agent",
            content={"summary": "v1", "message_count": 1},
            metadata={"thread_name": "Innova CFI", "model": "llama3.2:3b"},
        )
        await storage.save_artifact(older)
        newer = Artifact(  # a distinct artifact (new id) for the same thread
            kind="conversation.summary",
            workspace=WS,
            produced_by="resume-agent",
            content={"summary": "v2", "message_count": 1},
            metadata={"thread_name": "Innova CFI", "model": "qwen2.5:3b"},
            timestamp=_later(older.timestamp),  # type: ignore[arg-type]
        )
        await storage.save_artifact(newer)

    asyncio.run(seed())
    client = TestClient(create_app(Settings(), storage=storage))
    # The API returns every version…
    items = client.get("/api/artifacts", params={"workspace": WS}).json()["artifacts"][0][
        "items"
    ]
    assert len(items) == 2
    # …and the dashboard groups them into a single navigable card (one card
    # title, two versions, a version navigator).
    html_doc = client.get("/", params={"workspace": WS}).text
    assert html_doc.count("<h3>Innova CFI</h3>") == 1
    assert html_doc.count("class='version'") == 2
    assert "ver-nav" in html_doc
    assert "llama3.2:3b" in html_doc and "qwen2.5:3b" in html_doc


def _later(ts: object) -> object:
    from datetime import timedelta

    return ts + timedelta(seconds=1)  # type: ignore[operator]


