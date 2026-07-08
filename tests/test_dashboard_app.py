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
    monkeypatch.setattr("kaos.plugins.dashboard.service.build_storage", lambda _s: storage)
    return TestClient(create_app(Settings()))


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

