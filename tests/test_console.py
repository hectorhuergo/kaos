"""Tests for the web console: providers, subscriptions and persisted config.

The FastAPI routes are exercised with injected in-memory stores so state is
shared across requests without a database. The ``load_settings`` overlay and the
in-memory ``ConfigStore`` are covered directly.
"""

from __future__ import annotations

import asyncio

import pytest

from kaos.bootstrap.factory import load_settings
from kaos.core.config import Settings
from kaos.domain.provider_credential import ProviderCredential
from kaos.domain.runtime_config import RuntimeConfig
from kaos.runtime import (
    InMemoryConfigStore,
    InMemoryCredentialStore,
    InMemoryStorage,
    InMemorySubscriptionStore,
)


def test_in_memory_config_store_roundtrip() -> None:
    store = InMemoryConfigStore()

    async def scenario() -> RuntimeConfig | None:
        assert await store.get() is None
        await store.set(RuntimeConfig(llm_provider="openai", llm_model="gpt-4o"))
        return await store.get()

    got = asyncio.run(scenario())
    assert got is not None
    assert got.llm_provider == "openai"
    assert got.llm_model == "gpt-4o"


def test_in_memory_credential_store_roundtrip() -> None:
    store = InMemoryCredentialStore()

    async def scenario() -> list[object]:
        assert await store.get("openai") is None
        assert await store.list() == []
        await store.set(ProviderCredential(provider="openai", api_key="sk-test"))
        got = await store.get("openai")
        listed = await store.list()
        removed = await store.delete("openai")
        missing = await store.delete("openai")
        return [got, listed, removed, missing]

    got, listed, removed, missing = asyncio.run(scenario())
    assert got is not None and got.api_key == "sk-test"  # type: ignore[union-attr]
    assert len(listed) == 1  # type: ignore[arg-type]
    assert removed is True
    assert missing is False


def test_load_settings_without_db_is_noop() -> None:
    base = Settings(llm_provider="echo", llm_model="x")
    got = asyncio.run(load_settings(base))
    assert got.llm_provider == "echo"
    assert got.llm_model == "x"


# ---- API tests (require FastAPI's TestClient) ----

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from kaos.plugins.dashboard.app import create_app  # noqa: E402


@pytest.fixture()
def stores() -> tuple[
    InMemoryStorage,
    InMemorySubscriptionStore,
    InMemoryConfigStore,
    InMemoryCredentialStore,
]:
    return (
        InMemoryStorage(),
        InMemorySubscriptionStore(),
        InMemoryConfigStore(),
        InMemoryCredentialStore(),
    )


@pytest.fixture()
def client(
    stores: tuple[
        InMemoryStorage,
        InMemorySubscriptionStore,
        InMemoryConfigStore,
        InMemoryCredentialStore,
    ],
) -> TestClient:
    storage, subs, config, creds = stores
    app = create_app(
        Settings(),
        storage=storage,
        subscription_store=subs,
        config_store=config,
        credential_store=creds,
    )
    return TestClient(app)


def test_console_page_is_html(client: TestClient) -> None:
    resp = client.get("/console")
    assert resp.status_code == 200
    assert "<!doctype html>" in resp.text
    assert "Providers" in resp.text and "Subscriptions" in resp.text


def test_providers_lists_catalog(client: TestClient) -> None:
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    data = resp.json()
    ids = {p["id"] for p in data["providers"]}
    assert {"echo", "openai", "github", "anthropic"} <= ids
    # echo is ready without credentials and selected by default.
    echo = next(p for p in data["providers"] if p["id"] == "echo")
    assert echo["ready"] is True
    assert data["selected_provider"] == "echo"


def test_set_provider_persists_and_reflects(client: TestClient) -> None:
    resp = client.put("/api/config/provider", json={"provider": "openai", "model": "gpt-4o"})
    assert resp.status_code == 200
    assert resp.json()["provider"] == "openai"

    data = client.get("/api/providers").json()
    assert data["selected_provider"] == "openai"
    assert data["selected_model"] == "gpt-4o"
    assert next(p for p in data["providers"] if p["id"] == "openai")["selected"] is True


def test_set_provider_rejects_unknown(client: TestClient) -> None:
    resp = client.put("/api/config/provider", json={"provider": "nope"})
    assert resp.status_code == 422


def test_credential_persists_and_marks_stored(client: TestClient) -> None:
    # Without a credential and without env secrets, openai is not ready.
    before = next(
        p for p in client.get("/api/providers").json()["providers"] if p["id"] == "openai"
    )
    assert before["ready"] is False
    assert before["stored"] is False

    resp = client.put("/api/providers/openai/credential", json={"api_key": "sk-xyz"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"provider": "openai", "stored": True}
    # The secret is never echoed back.
    assert "api_key" not in body

    after = next(
        p for p in client.get("/api/providers").json()["providers"] if p["id"] == "openai"
    )
    assert after["stored"] is True
    assert after["ready"] is True  # a stored credential makes it ready


def test_credential_clear_reverts_to_env(client: TestClient) -> None:
    client.put("/api/providers/github/credential", json={"api_key": "ghp_x"})
    resp = client.delete("/api/providers/github/credential")
    assert resp.status_code == 200
    assert resp.json()["stored"] is False
    after = next(
        p for p in client.get("/api/providers").json()["providers"] if p["id"] == "github"
    )
    assert after["stored"] is False


def test_credential_rejects_echo(client: TestClient) -> None:
    # echo needs no secret.
    resp = client.put("/api/providers/echo/credential", json={"api_key": "x"})
    assert resp.status_code == 422


def test_credential_requires_api_key(client: TestClient) -> None:
    resp = client.put("/api/providers/openai/credential", json={"api_key": "  "})
    assert resp.status_code == 422


def test_credential_rejects_unknown_provider(client: TestClient) -> None:
    resp = client.put("/api/providers/nope/credential", json={"api_key": "x"})
    assert resp.status_code == 422


def test_delete_missing_credential_is_404(client: TestClient) -> None:
    assert client.delete("/api/providers/anthropic/credential").status_code == 404


def test_subscription_crud_roundtrip(client: TestClient) -> None:
    assert client.get("/api/subscriptions").json()["subscriptions"] == []

    resp = client.post(
        "/api/subscriptions",
        json={"channel_id": "123", "kind": "forum", "resume_thread_id": "PMO"},
    )
    assert resp.status_code == 201
    assert resp.json()["workspace"] == "discord:123"

    subs = client.get("/api/subscriptions").json()["subscriptions"]
    assert len(subs) == 1
    assert subs[0]["channel_id"] == "123"
    assert subs[0]["resume_thread_id"] == "PMO"

    resp = client.delete("/api/subscriptions/123")
    assert resp.status_code == 200
    assert client.get("/api/subscriptions").json()["subscriptions"] == []


def test_subscription_rejects_bad_kind(client: TestClient) -> None:
    resp = client.post("/api/subscriptions", json={"channel_id": "1", "kind": "bogus"})
    assert resp.status_code == 422


def test_delete_missing_subscription_is_404(client: TestClient) -> None:
    assert client.delete("/api/subscriptions/nope").status_code == 404


# ---- Dry-run previews ----


def test_capturing_publisher_collects() -> None:
    from kaos.contracts.artifact import Artifact
    from kaos.plugins.publishers import CapturingPublisher

    pub = CapturingPublisher()
    art = Artifact(
        kind="conversation.summary",
        workspace="discord:1",
        produced_by="resume-agent",
        content={"summary": "hola"},
    )
    asyncio.run(pub.publish(art))
    assert pub.published == [art]
    assert pub.name == "capturing-publisher"


def test_preview_github_route_captures(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from kaos.contracts.artifact import Artifact

    async def fake_run_github(repo, *, dry_run, limit, settings, publisher):  # type: ignore[no-untyped-def]
        assert dry_run is True  # never publishes for real
        await publisher.publish(
            Artifact(
                kind="project.status",
                workspace=f"github:{repo}",
                produced_by="resume-agent",
                content={"summary": "# Preview"},
            )
        )
        return 0

    monkeypatch.setattr("kaos.plugins.dashboard.preview.run_github", fake_run_github)
    resp = client.post("/api/preview/github", json={"repo": "o/r", "limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["published"] is False
    assert body["artifacts"][0]["content"]["summary"] == "# Preview"


def test_preview_github_rejects_empty_repo(client: TestClient) -> None:
    resp = client.post("/api/preview/github", json={"repo": "  "})
    assert resp.status_code == 422


def test_preview_github_network_error_is_422(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import httpx

    async def boom(repo, *, dry_run, limit, settings, publisher):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("kaos.plugins.dashboard.preview.run_github", boom)
    resp = client.post("/api/preview/github", json={"repo": "o/r"})
    # A transport error must not surface as a 500.
    assert resp.status_code == 422
    assert "red" in resp.json()["detail"].lower()


def test_preview_github_timeout_is_422_retriable(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import httpx

    async def slow(repo, *, dry_run, limit, settings, publisher):  # type: ignore[no-untyped-def]
        raise httpx.ReadTimeout("too slow")

    monkeypatch.setattr("kaos.plugins.dashboard.preview.run_github", slow)
    resp = client.post("/api/preview/github", json={"repo": "o/r"})
    assert resp.status_code == 422
    assert "reintent" in resp.json()["detail"].lower()


def test_preview_subscription_missing_is_422(client: TestClient) -> None:
    resp = client.post("/api/preview/subscription", json={"channel_id": "nope"})
    assert resp.status_code == 422


def test_preview_subscription_route_captures(
    client: TestClient, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    from kaos.contracts.artifact import Artifact

    client.post("/api/subscriptions", json={"channel_id": "123", "kind": "forum"})

    async def fake_forum(channel_id, *, guild_id, dry_run, consolidated, settings, publisher):  # type: ignore[no-untyped-def]
        assert dry_run is True and consolidated is True
        await publisher.publish(
            Artifact(
                kind="project.status",
                workspace=f"discord:{channel_id}",
                produced_by="resume-agent",
                content={"summary": "# Estado del Proyecto"},
            )
        )
        return 0

    monkeypatch.setattr("kaos.plugins.dashboard.preview.run_forum_backfill", fake_forum)
    resp = client.post("/api/preview/subscription", json={"channel_id": "123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["published"] is False
    assert body["artifacts"][0]["content"]["summary"] == "# Estado del Proyecto"


