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


def test_load_settings_override_without_db_is_transient() -> None:
    base = Settings(llm_provider="echo", llm_model="x")
    got = asyncio.run(load_settings(base, provider="openai", model="gpt-4o-mini"))
    assert got.llm_provider == "openai"
    assert got.llm_model == "gpt-4o-mini"
    # A None override keeps the base selection.
    same = asyncio.run(load_settings(base))
    assert same.llm_provider == "echo"


def test_load_settings_override_wins_over_persisted(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import kaos.bootstrap.factory as factory

    config = InMemoryConfigStore()
    creds = InMemoryCredentialStore()

    async def setup() -> None:
        await config.set(RuntimeConfig(llm_provider="openai", llm_model="gpt-4o"))
        await creds.set(
            ProviderCredential(provider="anthropic", api_key="sk-ant", model="claude-x")
        )

    asyncio.run(setup())
    monkeypatch.setattr(factory, "build_config_store", lambda base: config)
    monkeypatch.setattr(factory, "build_credential_store", lambda base: creds)

    base = Settings(database_url="postgresql://x")
    got = asyncio.run(load_settings(base, provider="anthropic"))
    # The explicit override wins over the persisted 'openai' selection...
    assert got.llm_provider == "anthropic"
    # ...resolves the overridden provider's credential...
    assert got.anthropic_api_key == "sk-ant"
    # ...and the persisted model for 'openai' does not leak; the credential's does.
    assert got.llm_model == "claude-x"


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


def test_github_env_ready_when_token_in_env_though_not_selected() -> None:
    """GitHub Models must read as ready when its token is in .env (env_ready).

    Regression: the console pill used to key off the *selected* provider, so a
    GitHub token present in the environment showed as "sin credencial" whenever
    another provider (e.g. openai) was active.
    """
    app = create_app(
        Settings(github_token="ghp_env", llm_provider="openai"),
        storage=InMemoryStorage(),
        subscription_store=InMemorySubscriptionStore(),
        config_store=InMemoryConfigStore(),
        credential_store=InMemoryCredentialStore(),
    )
    client = TestClient(app)
    github = next(
        p for p in client.get("/api/providers").json()["providers"] if p["id"] == "github"
    )
    assert github["selected"] is False  # openai is active, not github
    assert github["env_ready"] is True  # …but the token is in .env
    assert github["ready"] is True
    assert github["stored"] is False


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


def test_subscription_llm_override_roundtrip(client: TestClient) -> None:
    resp = client.post(
        "/api/subscriptions",
        json={
            "channel_id": "123",
            "kind": "forum",
            "llm_provider": "anthropic",
            "llm_model": "claude-3-5-haiku-latest",
        },
    )
    assert resp.status_code == 201
    sub = client.get("/api/subscriptions").json()["subscriptions"][0]
    assert sub["llm_provider"] == "anthropic"
    assert sub["llm_model"] == "claude-3-5-haiku-latest"

    # A blank override clears it back to null (use the global default).
    resp = client.patch(
        "/api/subscriptions/123", json={"llm_provider": "  ", "llm_model": ""}
    )
    assert resp.status_code == 200
    assert resp.json()["llm_provider"] is None
    assert resp.json()["llm_model"] is None


def test_provider_models_endpoint_best_effort(client: TestClient) -> None:
    # echo has no catalog -> empty list, not an error.
    resp = client.get("/api/providers/echo/models")
    assert resp.status_code == 200
    assert resp.json()["models"] == []
    # unknown provider -> 404.
    assert client.get("/api/providers/nope/models").status_code == 404


def test_subscription_agent_roundtrip(client: TestClient) -> None:
    resp = client.post(
        "/api/subscriptions",
        json={"channel_id": "123", "kind": "forum", "agent_id": "resume-agent"},
    )
    assert resp.status_code == 201
    sub = client.get("/api/subscriptions").json()["subscriptions"][0]
    assert sub["agent_id"] == "resume-agent"

    # A blank agent clears it back to null (use the default summarizer).
    resp = client.patch("/api/subscriptions/123", json={"agent_id": "  "})
    assert resp.status_code == 200
    assert resp.json()["agent_id"] is None


def test_run_subscription_defaults_to_stored_agent(
    client: TestClient, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    from kaos.contracts.artifact import Artifact

    client.post(
        "/api/subscriptions",
        json={"channel_id": "123", "kind": "forum", "agent_id": "dev-agent"},
    )

    seen: dict[str, object] = {}

    async def fake_forum(  # type: ignore[no-untyped-def]
        channel_id, *, guild_id, dry_run, consolidated, force, only_if_changed,
        settings, publisher, extra_instructions="", llm_provider=None, llm_model=None,
        agent_id=None,
    ):
        seen["agent_id"] = agent_id
        await publisher.publish(
            Artifact(
                kind="project.status",
                workspace=f"discord:{channel_id}",
                produced_by="resume-agent",
                content={"summary": "ok"},
            )
        )
        return 0

    monkeypatch.setattr(
        "kaos.plugins.dashboard.execute.run_forum_backfill", fake_forum
    )
    # No override -> the subscription's stored agent is used.
    assert client.post("/api/run/subscription", json={"channel_id": "123"}).status_code == 200
    assert seen["agent_id"] == "dev-agent"
    # An explicit per-run agent wins over the stored one.
    client.post(
        "/api/run/subscription", json={"channel_id": "123", "agent_id": "resume-agent"}
    )
    assert seen["agent_id"] == "resume-agent"


def test_run_subscription_defaults_to_stored_override(
    client: TestClient, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    from kaos.contracts.artifact import Artifact

    client.post(
        "/api/subscriptions",
        json={
            "channel_id": "123",
            "kind": "forum",
            "llm_provider": "anthropic",
            "llm_model": "claude-x",
        },
    )

    seen: dict[str, object] = {}

    async def fake_forum(  # type: ignore[no-untyped-def]
        channel_id, *, guild_id, dry_run, consolidated, force, only_if_changed,
        settings, publisher, extra_instructions="", llm_provider=None, llm_model=None, agent_id=None,
    ):
        seen["llm_provider"] = llm_provider
        seen["llm_model"] = llm_model
        await publisher.publish(
            Artifact(
                kind="project.status",
                workspace=f"discord:{channel_id}",
                produced_by="resume-agent",
                content={"summary": "ok"},
            )
        )
        return 0

    monkeypatch.setattr(
        "kaos.plugins.dashboard.execute.run_forum_backfill", fake_forum
    )
    # No override in the request -> the subscription's stored values are used.
    resp = client.post("/api/run/subscription", json={"channel_id": "123"})
    assert resp.status_code == 200
    assert seen["llm_provider"] == "anthropic"
    assert seen["llm_model"] == "claude-x"


def test_subscription_project_roundtrip(client: TestClient) -> None:
    resp = client.post(
        "/api/subscriptions",
        json={"channel_id": "acme/kaos", "kind": "github", "project": "proyecto-x"},
    )
    assert resp.status_code == 201
    subs = client.get("/api/subscriptions").json()["subscriptions"]
    assert subs[0]["project"] == "proyecto-x"
    # A blank project is stored as null, not "".
    resp = client.post(
        "/api/subscriptions",
        json={"channel_id": "acme/other", "kind": "github", "project": "  "},
    )
    assert resp.status_code == 201
    other = next(
        s
        for s in client.get("/api/subscriptions").json()["subscriptions"]
        if s["channel_id"] == "acme/other"
    )
    assert other["project"] is None


def test_subscription_publish_default_and_relations_roundtrip(client: TestClient) -> None:
    resp = client.post(
        "/api/subscriptions",
        json={
            "channel_id": "acme/kaos",
            "kind": "github",
            "publish_default": False,
            "related_to": ["discord:1"],
        },
    )
    assert resp.status_code == 201
    sub = client.get("/api/subscriptions").json()["subscriptions"][0]
    assert sub["publish_default"] is False
    assert sub["related_to"] == ["discord:1"]


def test_subscription_defaults_publish_true(client: TestClient) -> None:
    client.post("/api/subscriptions", json={"channel_id": "1", "kind": "forum"})
    sub = client.get("/api/subscriptions").json()["subscriptions"][0]
    assert sub["publish_default"] is True  # historical behavior preserved
    assert sub["related_to"] == []


def test_subscription_patch_edits_fields(client: TestClient) -> None:
    client.post("/api/subscriptions", json={"channel_id": "1", "kind": "forum"})
    resp = client.patch(
        "/api/subscriptions/1",
        json={"project": "proyecto-x", "publish_default": False, "related_to": ["discord:9"]},
    )
    assert resp.status_code == 200
    sub = client.get("/api/subscriptions").json()["subscriptions"][0]
    assert sub["project"] == "proyecto-x"
    assert sub["publish_default"] is False
    assert sub["related_to"] == ["discord:9"]
    # A subscription is never related to itself.
    client.patch("/api/subscriptions/1", json={"related_to": ["discord:1", "discord:9"]})
    sub = client.get("/api/subscriptions").json()["subscriptions"][0]
    assert sub["related_to"] == ["discord:9"]


def test_subscription_patch_missing_is_404(client: TestClient) -> None:
    assert client.patch("/api/subscriptions/nope", json={"project": "x"}).status_code == 404


def test_subscription_patch_and_delete_with_slash_id(client: TestClient) -> None:
    # GitHub subscriptions use an ``owner/repo`` channel_id, so the encoded
    # ``%2F`` in the path must still route (regression: was 404).
    client.post("/api/subscriptions", json={"channel_id": "owner/repo", "kind": "github"})
    resp = client.patch("/api/subscriptions/owner%2Frepo", json={"project": "px"})
    assert resp.status_code == 200
    sub = client.get("/api/subscriptions").json()["subscriptions"][0]
    assert sub["project"] == "px"
    assert client.delete("/api/subscriptions/owner%2Frepo").status_code == 200


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

    async def fake_run_github(repo, *, dry_run, limit, settings, publisher, extra_instructions="", llm_provider=None, llm_model=None, agent_id=None):  # type: ignore[no-untyped-def]
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

    async def boom(repo, *, dry_run, limit, settings, publisher, extra_instructions="", llm_provider=None, llm_model=None, agent_id=None):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("kaos.plugins.dashboard.preview.run_github", boom)
    resp = client.post("/api/preview/github", json={"repo": "o/r"})
    # A transport error must not surface as a 500.
    assert resp.status_code == 422
    assert "red" in resp.json()["detail"].lower()


def test_preview_github_timeout_is_422_retriable(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import httpx

    async def slow(repo, *, dry_run, limit, settings, publisher, extra_instructions="", llm_provider=None, llm_model=None, agent_id=None):  # type: ignore[no-untyped-def]
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

    async def fake_forum(channel_id, *, guild_id, dry_run, consolidated, settings, publisher, extra_instructions="", llm_provider=None, llm_model=None, agent_id=None):  # type: ignore[no-untyped-def]
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


def test_agents_route_lists_catalog(client: TestClient) -> None:
    resp = client.get("/api/agents")
    assert resp.status_code == 200
    ids = {a["id"] for a in resp.json()["agents"]}
    assert {"resume-agent", "dev-agent"} <= ids


def test_agents_route_exposes_base_prompt(client: TestClient) -> None:
    agents = client.get("/api/agents").json()["agents"]
    resume = next(a for a in agents if a["id"] == "resume-agent")
    # The base prompt is shown so the operator sees what extra instructions augment.
    assert "Resumen Ejecutivo" in resume["base_prompt"]
    assert resume["instructions"] == ""  # nothing saved yet


def test_agent_instructions_persist_and_reflect(client: TestClient) -> None:
    resp = client.put(
        "/api/agents/resume-agent/instructions",
        json={"instructions": "  enfocate en riesgos y montos  "},
    )
    assert resp.status_code == 200
    assert resp.json()["instructions"] == "enfocate en riesgos y montos"  # trimmed

    # Persisted: a later GET returns the saved value.
    agents = client.get("/api/agents").json()["agents"]
    resume = next(a for a in agents if a["id"] == "resume-agent")
    assert resume["instructions"] == "enfocate en riesgos y montos"


def test_agent_instructions_survive_provider_change(client: TestClient) -> None:
    client.put(
        "/api/agents/resume-agent/instructions", json={"instructions": "tono formal"}
    )
    # Changing the provider must not wipe the saved agent instructions.
    client.put("/api/config/provider", json={"provider": "openai", "model": "gpt-4o"})
    agents = client.get("/api/agents").json()["agents"]
    resume = next(a for a in agents if a["id"] == "resume-agent")
    assert resume["instructions"] == "tono formal"


def test_agent_instructions_empty_clears(client: TestClient) -> None:
    client.put("/api/agents/resume-agent/instructions", json={"instructions": "algo"})
    client.put("/api/agents/resume-agent/instructions", json={"instructions": "   "})
    agents = client.get("/api/agents").json()["agents"]
    resume = next(a for a in agents if a["id"] == "resume-agent")
    assert resume["instructions"] == ""


def test_agent_instructions_unknown_agent_is_404(client: TestClient) -> None:
    resp = client.put("/api/agents/nope/instructions", json={"instructions": "x"})
    assert resp.status_code == 404


def test_preview_subscription_uses_saved_instructions(
    client: TestClient, monkeypatch  # type: ignore[no-untyped-def]
) -> None:
    from kaos.contracts.artifact import Artifact

    client.post("/api/subscriptions", json={"channel_id": "123", "kind": "forum"})
    client.put(
        "/api/agents/resume-agent/instructions",
        json={"instructions": "enfocate en decisiones"},
    )
    seen: dict[str, object] = {}

    async def fake_forum(channel_id, *, guild_id, dry_run, consolidated, settings, publisher, extra_instructions="", llm_provider=None, llm_model=None, agent_id=None):  # type: ignore[no-untyped-def]
        seen["extra"] = extra_instructions
        await publisher.publish(
            Artifact(
                kind="project.status",
                workspace=f"discord:{channel_id}",
                produced_by="resume-agent",
                content={"summary": "# ok"},
            )
        )
        return 0

    monkeypatch.setattr("kaos.plugins.dashboard.preview.run_forum_backfill", fake_forum)
    # No extra_instructions in the request -> the saved ones are applied.
    resp = client.post("/api/preview/subscription", json={"channel_id": "123"})
    assert resp.status_code == 200
    assert seen["extra"] == "enfocate en decisiones"


def test_run_subscription_missing_is_422(client: TestClient) -> None:
    resp = client.post("/api/run/subscription", json={"channel_id": "nope"})
    assert resp.status_code == 422


def test_run_subscription_route_persists(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from kaos.contracts.artifact import Artifact

    client.post("/api/subscriptions", json={"channel_id": "123", "kind": "forum"})

    seen: dict[str, object] = {}

    async def fake_forum(channel_id, *, guild_id, dry_run, consolidated, force, only_if_changed, settings, publisher, extra_instructions="", llm_provider=None, llm_model=None, agent_id=None):  # type: ignore[no-untyped-def]
        # A real run persists (not a dry-run) and captures instead of publishing.
        seen["dry_run"] = dry_run
        seen["force"] = force
        await publisher.publish(
            Artifact(
                kind="project.status",
                workspace=f"discord:{channel_id}",
                produced_by="resume-agent",
                content={"summary": "# Estado del Proyecto"},
            )
        )
        return 0

    monkeypatch.setattr("kaos.plugins.dashboard.execute.run_forum_backfill", fake_forum)
    resp = client.post("/api/run/subscription", json={"channel_id": "123", "force": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["persisted"] is True
    assert body["published"] is False
    assert body["artifacts"][0]["content"]["summary"] == "# Estado del Proyecto"
    assert seen["dry_run"] is False  # persists to real storage + cache
    assert seen["force"] is True


def test_run_all_route_runs_every_subscription(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from kaos.contracts.artifact import Artifact

    client.post("/api/subscriptions", json={"channel_id": "a", "kind": "forum"})
    client.post("/api/subscriptions", json={"channel_id": "b", "kind": "forum"})

    ran: list[str] = []

    async def fake_forum(channel_id, *, guild_id, dry_run, consolidated, force, only_if_changed, settings, publisher, extra_instructions="", llm_provider=None, llm_model=None, agent_id=None):  # type: ignore[no-untyped-def]
        ran.append(channel_id)
        await publisher.publish(
            Artifact(
                kind="project.status",
                workspace=f"discord:{channel_id}",
                produced_by="resume-agent",
                content={"summary": f"# {channel_id}"},
            )
        )
        return 0

    monkeypatch.setattr("kaos.plugins.dashboard.execute.run_forum_backfill", fake_forum)
    resp = client.post("/api/run/all", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["persisted"] is True
    assert sorted(ran) == ["a", "b"]
    assert len(body["artifacts"]) == 2


def test_run_subscription_resume_thread_overrides_global(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A subscription's resume thread wins over KAOS_DISCORD_RESUME_THREAD_ID."""
    from kaos.domain.subscription import FORUM, Subscription
    from kaos.plugins.dashboard.execute import run_subscription

    # Global default from the environment/.env.
    settings = Settings(discord_token="t", discord_resume_thread_id="GLOBAL")
    store = InMemorySubscriptionStore()

    seen: dict[str, object] = {}

    async def fake_forum(channel_id, *, guild_id, dry_run, consolidated, force, only_if_changed, settings, publisher, extra_instructions="", llm_provider=None, llm_model=None, agent_id=None):  # type: ignore[no-untyped-def]
        seen["thread_id"] = settings.discord_resume_thread_id
        return 0

    async def scenario() -> None:
        await store.add(
            Subscription(
                workspace=Subscription.workspace_for_kind(FORUM, "123"),
                kind=FORUM,
                channel_id="123",
                resume_thread_id="SUB",  # per-subscription target
            )
        )
        await run_subscription(settings, "123", subscription_store=store)

    monkeypatch.setattr("kaos.plugins.dashboard.execute.run_forum_backfill", fake_forum)
    asyncio.run(scenario())
    assert seen["thread_id"] == "SUB"  # subscription value wins over the global


def test_run_subscription_falls_back_to_global_resume_thread(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Without a per-subscription thread, the global default is used."""
    from kaos.domain.subscription import FORUM, Subscription
    from kaos.plugins.dashboard.execute import run_subscription

    settings = Settings(discord_token="t", discord_resume_thread_id="GLOBAL")
    store = InMemorySubscriptionStore()
    seen: dict[str, object] = {}

    async def fake_forum(channel_id, *, guild_id, dry_run, consolidated, force, only_if_changed, settings, publisher, extra_instructions="", llm_provider=None, llm_model=None, agent_id=None):  # type: ignore[no-untyped-def]
        seen["thread_id"] = settings.discord_resume_thread_id
        return 0

    async def scenario() -> None:
        await store.add(
            Subscription(
                workspace=Subscription.workspace_for_kind(FORUM, "123"),
                kind=FORUM,
                channel_id="123",
                resume_thread_id=None,  # no per-subscription target
            )
        )
        await run_subscription(settings, "123", subscription_store=store)

    monkeypatch.setattr("kaos.plugins.dashboard.execute.run_forum_backfill", fake_forum)
    asyncio.run(scenario())
    assert seen["thread_id"] == "GLOBAL"


