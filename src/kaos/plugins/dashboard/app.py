"""Live dashboard + web console: a FastAPI app over the KAOS knowledge and config.

Unlike the static HTML export, this reads persistence on each request so the
view reflects the latest state. The stores are built once at startup and reused
across requests (a single PostgreSQL pool), then closed on shutdown. FastAPI is
imported lazily inside `create_app` so importing this module never requires the
web stack; `kaos serve` wires it to uvicorn.

Routes:
- ``GET  /``                         → the HTML dashboard (knowledge view).
- ``GET  /console``                  → the admin console (providers/subs/dash).
- ``GET  /api/workspaces``           → the workspaces KAOS manages.
- ``GET  /api/knowledge``            → the knowledge graph as JSON.
- ``GET  /api/artifacts``            → the stored artifacts (optionally by ws).
- ``GET  /api/providers``            → LLM provider catalog + persisted choice.
- ``PUT  /api/config/provider``      → persist the active provider + model.
- ``PUT  /api/providers/{id}/credential`` → persist a provider's secret.
- ``DELETE /api/providers/{id}/credential`` → clear a provider's secret.
- ``GET  /api/subscriptions``        → active subscriptions.
- ``POST /api/subscriptions``        → add/upsert a subscription.
- ``DELETE /api/subscriptions/{id}`` → deactivate a subscription.
- ``POST /api/preview/github``       → dry-run summary of a repo (no publish).
- ``POST /api/preview/subscription`` → dry-run summary of a subscription.

Mutating routes edit durable state: the runtime config, provider credentials and
the subscriptions. Provider secrets can be persisted in PostgreSQL (with the
environment as fallback); they are write-only over the API — never returned.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from kaos.bootstrap.factory import (
    build_config_store,
    build_credential_store,
    build_storage,
    build_subscription_store,
)
from kaos.core.config import LLM_PROVIDERS, Settings
from kaos.core.providers import provider_status, secret_field
from kaos.domain.provider_credential import ProviderCredential
from kaos.domain.runtime_config import RuntimeConfig
from kaos.domain.subscription import KINDS, Subscription
from kaos.plugins.dashboard import render_dashboard
from kaos.plugins.dashboard.console import render_console
from kaos.plugins.dashboard.preview import (
    PreviewError,
    preview_github,
    preview_subscription,
)
from kaos.plugins.dashboard.service import artifacts_to_dicts, load_knowledge


class ProviderChoice(BaseModel):
    """Request body: the LLM provider selection to persist."""

    provider: str
    model: str = ""


class CredentialInput(BaseModel):
    """Request body: a provider's credential (secret + optional overrides)."""

    api_key: str = ""
    model: str = ""
    base_url: str = ""


class GitHubPreviewInput(BaseModel):
    """Request body: a GitHub repo to preview (dry-run, no publish)."""

    repo: str
    limit: int = 30


class SubscriptionPreviewInput(BaseModel):
    """Request body: a subscription to preview (dry-run, no publish)."""

    channel_id: str


class SubscriptionInput(BaseModel):
    """Request body: a subscription to add/upsert."""

    channel_id: str
    kind: str = "forum"
    guild_id: str | None = None
    resume_thread_id: str | None = None


async def _close(obj: object) -> None:
    close = getattr(obj, "close", None)
    if close is not None:
        await close()


def create_app(
    settings: Settings | None = None,
    *,
    storage: Any = None,
    subscription_store: Any = None,
    config_store: Any = None,
    credential_store: Any = None,
) -> Any:
    """Build the FastAPI dashboard + console app.

    ``settings`` defaults to the environment. The stores can be injected (the
    caller then owns their lifecycle) — useful for tests and to share instances;
    otherwise they are built from ``settings`` at startup and closed on
    shutdown.
    """
    from collections.abc import AsyncIterator
    from contextlib import asynccontextmanager

    from fastapi import Body, FastAPI, HTTPException, Query
    from fastapi.responses import HTMLResponse

    cfg = settings if settings is not None else Settings.from_env()

    # Build shared stores once; remember which ones we own so we close only those.
    owned: list[object] = []

    @asynccontextmanager
    async def lifespan(_app: Any) -> AsyncIterator[None]:
        try:
            yield
        finally:
            for obj in owned:
                await _close(obj)

    app = FastAPI(title="KAOS Dashboard", version="1.0.0-beta.1", lifespan=lifespan)

    def _store() -> Any:
        nonlocal storage
        if storage is None:
            storage = build_storage(cfg)
            owned.append(storage)
        return storage

    def _subs() -> Any:
        nonlocal subscription_store
        if subscription_store is None:
            subscription_store = build_subscription_store(cfg)
            owned.append(subscription_store)
        return subscription_store

    def _config() -> Any:
        nonlocal config_store
        if config_store is None:
            config_store = build_config_store(cfg)
            owned.append(config_store)
        return config_store

    def _creds() -> Any:
        nonlocal credential_store
        if credential_store is None:
            credential_store = build_credential_store(cfg)
            owned.append(credential_store)
        return credential_store


    # ---- Dashboard (knowledge view) ----

    @app.get("/", response_class=HTMLResponse)
    async def index(
        workspace: str | None = Query(default=None),
        events: bool = Query(default=False),
    ) -> str:
        _ws, graph, sections = await load_knowledge(
            cfg,
            workspace=workspace,
            include_events=events,
            storage=_store(),
            subscription_store=_subs(),
        )
        return render_dashboard(sections, graph)

    @app.get("/console", response_class=HTMLResponse)
    async def console() -> str:
        return render_console()

    @app.get("/api/workspaces")
    async def api_workspaces() -> dict[str, list[str]]:
        workspaces, _graph, _sections = await load_knowledge(
            cfg, storage=_store(), subscription_store=_subs()
        )
        return {"workspaces": workspaces}

    @app.get("/api/knowledge")
    async def api_knowledge(
        workspace: str | None = Query(default=None),
        events: bool = Query(default=False),
    ) -> dict[str, Any]:
        _ws, graph, _sections = await load_knowledge(
            cfg,
            workspace=workspace,
            include_events=events,
            storage=_store(),
            subscription_store=_subs(),
        )
        return graph.to_dict()

    @app.get("/api/artifacts")
    async def api_artifacts(
        workspace: str | None = Query(default=None),
    ) -> dict[str, Any]:
        _ws, _graph, sections = await load_knowledge(
            cfg,
            workspace=workspace,
            storage=_store(),
            subscription_store=_subs(),
        )
        return {
            "artifacts": [
                {"workspace": ws, "items": artifacts_to_dicts(arts)}
                for ws, arts in sections
            ]
        }

    # ---- Providers (persisted runtime config) ----

    @app.get("/api/providers")
    async def api_providers() -> dict[str, Any]:
        persisted = await _config().get()
        selected = persisted.llm_provider if persisted else cfg.llm_provider
        selected_model = persisted.llm_model if persisted else cfg.llm_model
        # Which providers have a credential persisted in the store (secrets stay
        # server-side; we only expose the boolean).
        stored_ids = {c.provider for c in await _creds().list() if c.api_key}
        providers = [
            {
                "id": info.id,
                "label": info.label,
                "default_model": info.default_model,
                "base_url": info.base_url,
                "notes": info.notes,
                # Ready if the env has the secret OR one is persisted in Postgres.
                "ready": ready or info.id in stored_ids,
                "active_env": active_env,
                "stored": info.id in stored_ids,
                "needs_secret": secret_field(info.id) is not None,
                "selected": info.id == selected,
            }
            for info, ready, active_env in provider_status(cfg)
        ]
        return {
            "providers": providers,
            "selected_provider": selected,
            "selected_model": selected_model,
            "persistent": bool(cfg.database_url),
        }

    @app.put("/api/config/provider")
    async def api_set_provider(choice: ProviderChoice = Body(...)) -> dict[str, Any]:
        if choice.provider not in LLM_PROVIDERS:
            raise HTTPException(
                status_code=422,
                detail=f"provider must be one of {LLM_PROVIDERS}",
            )
        model = choice.model.strip() or cfg.llm_model
        config = RuntimeConfig(llm_provider=choice.provider, llm_model=model)
        await _config().set(config)
        return {
            "provider": config.llm_provider,
            "model": config.llm_model,
            "updated_at": config.updated_at.isoformat(),
            "persistent": bool(cfg.database_url),
        }

    @app.put("/api/providers/{provider}/credential")
    async def api_set_credential(
        provider: str, body: CredentialInput = Body(...)
    ) -> dict[str, Any]:
        if provider not in LLM_PROVIDERS:
            raise HTTPException(
                status_code=422, detail=f"provider must be one of {LLM_PROVIDERS}"
            )
        if secret_field(provider) is None:
            raise HTTPException(
                status_code=422, detail=f"provider '{provider}' takes no credential"
            )
        if not body.api_key.strip():
            raise HTTPException(status_code=422, detail="api_key is required")
        credential = ProviderCredential(
            provider=provider,
            api_key=body.api_key.strip(),
            model=body.model.strip(),
            base_url=body.base_url.strip(),
        )
        await _creds().set(credential)
        # Never echo the secret back.
        return {"provider": provider, "stored": True}

    @app.delete("/api/providers/{provider}/credential")
    async def api_delete_credential(provider: str) -> dict[str, Any]:
        removed = await _creds().delete(provider)
        if not removed:
            raise HTTPException(status_code=404, detail="credential not found")
        return {"provider": provider, "stored": False}

    # ---- Subscriptions ----

    @app.get("/api/subscriptions")
    async def api_subscriptions() -> dict[str, Any]:
        subs = await _subs().list(active_only=True)
        return {
            "subscriptions": [
                {
                    "id": str(s.id),
                    "workspace": s.workspace,
                    "kind": s.kind,
                    "channel_id": s.channel_id,
                    "guild_id": s.guild_id,
                    "resume_thread_id": s.resume_thread_id,
                    "active": s.active,
                    "created_at": s.created_at.isoformat(),
                }
                for s in subs
            ]
        }

    @app.post("/api/subscriptions", status_code=201)
    async def api_add_subscription(sub: SubscriptionInput = Body(...)) -> dict[str, Any]:
        if sub.kind not in KINDS:
            raise HTTPException(status_code=422, detail=f"kind must be one of {KINDS}")
        if not sub.channel_id.strip():
            raise HTTPException(status_code=422, detail="channel_id is required")
        subscription = Subscription(
            workspace=Subscription.workspace_for(sub.channel_id),
            kind=sub.kind,
            channel_id=sub.channel_id,
            guild_id=sub.guild_id or cfg.discord_guild_id,
            resume_thread_id=sub.resume_thread_id or cfg.discord_resume_thread_id,
        )
        await _subs().add(subscription)
        return {"channel_id": subscription.channel_id, "workspace": subscription.workspace}

    @app.delete("/api/subscriptions/{channel_id}")
    async def api_remove_subscription(channel_id: str) -> dict[str, Any]:
        found = await _subs().deactivate(channel_id)
        if not found:
            raise HTTPException(status_code=404, detail="subscription not found")
        return {"channel_id": channel_id, "deactivated": True}

    # ---- Dry-run previews (summarize without publishing to Discord) ----

    @app.post("/api/preview/github")
    async def api_preview_github(
        body: GitHubPreviewInput = Body(...),
    ) -> dict[str, Any]:
        try:
            artifacts = await preview_github(cfg, body.repo, limit=body.limit)
        except PreviewError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"published": False, "artifacts": artifacts_to_dicts(artifacts)}

    @app.post("/api/preview/subscription")
    async def api_preview_subscription(
        body: SubscriptionPreviewInput = Body(...),
    ) -> dict[str, Any]:
        try:
            artifacts = await preview_subscription(
                cfg, body.channel_id, subscription_store=_subs()
            )
        except PreviewError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"published": False, "artifacts": artifacts_to_dicts(artifacts)}

    return app



