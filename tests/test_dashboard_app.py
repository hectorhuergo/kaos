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


def test_api_chat_send_persists_turns_and_sessions() -> None:
    storage = InMemoryStorage()
    client = TestClient(create_app(Settings(), storage=storage))
    payload = {
        "workspace": WS,
        "user_id": "ana",
        "agent_id": "resume-agent",
        "message": "Hola, necesitamos un resumen ejecutivo.",
        "project": "proyecto-x",
        "kind": "support",
    }

    resp = client.post("/api/chat/send", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["session"]["workspace"] == WS
    assert data["session"]["user_id"] == "ana"
    assert data["session"]["agent_id"] == "resume-agent"
    assert data["response"]

    sessions = client.get("/api/chat/sessions", params={"workspace": WS}).json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["project"] == "proyecto-x"
    assert sessions[0]["message_count"] == 1
    assert sessions[0]["agent_id"] == "resume-agent"


def test_api_chat_thread_and_aggregated_sessions() -> None:
    from kaos.domain.subscription import Subscription
    from kaos.runtime import InMemorySubscriptionStore

    storage = InMemoryStorage()
    subs = InMemorySubscriptionStore()
    asyncio.run(
        subs.add(Subscription(workspace=WS, kind="forum", channel_id="demo"))
    )
    client = TestClient(
        create_app(Settings(), storage=storage, subscription_store=subs)
    )
    payload = {
        "workspace": WS,
        "user_id": "ana",
        "agent_id": "resume-agent",
        "message": "primera pregunta",
    }
    session_id = client.post("/api/chat/send", json=payload).json()["session"]["session_id"]

    # The thread returns the ordered user/assistant turns for the session.
    thread = client.get(
        "/api/chat/thread", params={"workspace": WS, "session_id": session_id}
    ).json()
    roles = [m["role"] for m in thread["messages"]]
    assert roles == ["user", "assistant"]
    assert thread["messages"][0]["text"] == "primera pregunta"

    # Without a workspace the sessions endpoint aggregates across workspaces.
    agg = client.get("/api/chat/sessions").json()["sessions"]
    assert any(s["session_id"] == session_id and s["workspace"] == WS for s in agg)


def test_api_knowledge_relates_same_project_workspaces() -> None:
    """Workspaces of one project are connected; an unrelated repo stays apart."""
    from kaos.domain.subscription import GITHUB, Subscription
    from kaos.runtime import InMemorySubscriptionStore

    subs = InMemorySubscriptionStore()

    async def seed() -> None:
        for channel in ("acme/proyecto-x-grid", "acme/proyecto-x-api", "acme/kaos"):
            await subs.add(
                Subscription(
                    workspace=Subscription.workspace_for_kind(GITHUB, channel),
                    kind=GITHUB,
                    channel_id=channel,
                )
            )

    asyncio.run(seed())
    # No Discord token → labels fall back to the readable ``owner/repo``.
    client = TestClient(
        create_app(Settings(), storage=InMemoryStorage(), subscription_store=subs)
    )
    data = client.get("/api/knowledge").json()
    related = [e for e in data["edges"] if e["kind"] == "related_to"]
    pairs = {tuple(sorted((e["source"], e["target"]))) for e in related}
    assert (
        "github:acme/proyecto-x-api",
        "github:acme/proyecto-x-grid",
    ) in pairs
    # kaos is on its own island.
    assert not any("github:acme/kaos" in pair for pair in pairs)


def test_api_knowledge_relates_by_explicit_project() -> None:
    """A workspace grouped by explicit project joins it despite an unrelated name."""
    from kaos.domain.subscription import GITHUB, Subscription
    from kaos.runtime import InMemorySubscriptionStore

    subs = InMemorySubscriptionStore()

    async def seed() -> None:
        # 'kaos' shares no name prefix with the forum, but it's the brain of
        # proyecto-x → grouped by explicit project.
        await subs.add(
            Subscription(
                workspace="discord:1",  # forum (no token → raw id label)
                kind="forum",
                channel_id="1",
                project="proyecto-x",
            )
        )
        await subs.add(
            Subscription(
                workspace=Subscription.workspace_for_kind(GITHUB, "acme/kaos"),
                kind=GITHUB,
                channel_id="acme/kaos",
                project="proyecto-x",
            )
        )

    asyncio.run(seed())
    client = TestClient(
        create_app(Settings(), storage=InMemoryStorage(), subscription_store=subs)
    )
    data = client.get("/api/knowledge").json()
    related = [e for e in data["edges"] if e["kind"] == "related_to"]
    pairs = {tuple(sorted((e["source"], e["target"]))) for e in related}
    assert ("discord:1", "github:acme/kaos") in pairs


def test_api_knowledge_relates_by_explicit_relation() -> None:
    """An operator-set ``related_to`` connects two otherwise-unrelated workspaces."""
    from kaos.domain.subscription import GITHUB, Subscription
    from kaos.runtime import InMemorySubscriptionStore

    subs = InMemorySubscriptionStore()

    async def seed() -> None:
        await subs.add(
            Subscription(
                workspace="discord:7",  # 'soporte' forum, unrelated name
                kind="forum",
                channel_id="7",
                related_to=["github:acme/kaos"],
            )
        )
        await subs.add(
            Subscription(
                workspace=Subscription.workspace_for_kind(GITHUB, "acme/kaos"),
                kind=GITHUB,
                channel_id="acme/kaos",
            )
        )

    asyncio.run(seed())
    client = TestClient(
        create_app(Settings(), storage=InMemoryStorage(), subscription_store=subs)
    )
    data = client.get("/api/knowledge").json()
    pairs = {
        tuple(sorted((e["source"], e["target"])))
        for e in data["edges"]
        if e["kind"] == "related_to"
    }
    assert ("discord:7", "github:acme/kaos") in pairs


def _later(ts: object) -> object:
    from datetime import timedelta

    return ts + timedelta(seconds=1)  # type: ignore[operator]


