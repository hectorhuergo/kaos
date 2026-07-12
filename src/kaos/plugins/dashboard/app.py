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
- ``GET  /api/agents``               → the catalog of agents KAOS ships.
- ``PUT  /api/agents/{id}/instructions`` → persist an agent's extra prompt.
- ``GET  /api/providers``            → LLM provider catalog + persisted choice.
- ``PUT  /api/config/provider``      → persist the active provider + model.
- ``PUT  /api/providers/{id}/credential`` → persist a provider's secret.
- ``DELETE /api/providers/{id}/credential`` → clear a provider's secret.
- ``GET  /api/subscriptions``        → active subscriptions.
- ``POST /api/subscriptions``        → add/upsert a subscription.
- ``PATCH /api/subscriptions/{id}``  → edit a subscription (project/publish/relations).
- ``DELETE /api/subscriptions/{id}`` → deactivate a subscription.
- ``POST /api/preview/github``       → dry-run summary of a repo (no publish).
- ``POST /api/preview/subscription`` → dry-run summary of a subscription.
- ``POST /api/run/subscription``     → real run: persist + populate cache (optional publish).
- ``POST /api/run/all``              → real run of every active subscription.

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
from kaos.core.agents import agent_catalog
from kaos.core.config import LLM_PROVIDERS, Settings
from kaos.core.knowledge import relate_workspaces
from kaos.core.providers import provider_status, secret_field
from kaos.domain.provider_credential import ProviderCredential
from kaos.domain.runtime_config import RuntimeConfig
from kaos.domain.subscription import GITHUB, KINDS, Subscription
from kaos.plugins.agents.dev_agent import BASE_PROMPT as DEV_BASE_PROMPT
from kaos.plugins.agents.resume_agent import SYSTEM_PROMPT as RESUME_BASE_PROMPT
from kaos.plugins.dashboard import render_dashboard
from kaos.plugins.dashboard.console import render_console
from kaos.plugins.dashboard.directory import (
    resolve_header,
    resolve_labels,
)
from kaos.plugins.dashboard.execute import RunError, run_all, run_subscription
from kaos.plugins.dashboard.preview import (
    PreviewError,
    preview_github,
    preview_subscription,
)
from kaos.plugins.dashboard.service import (
    artifacts_to_dicts,
    load_knowledge,
    load_projects,
    load_relations,
)

# The base (fixed) prompt each augmentable agent uses, shown in the console so an
# operator can see what their extra instructions are appended to.
AGENT_BASE_PROMPTS: dict[str, str] = {
    "resume-agent": RESUME_BASE_PROMPT,
    "dev-agent": DEV_BASE_PROMPT,
}


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
    extra_instructions: str = ""


class SubscriptionPreviewInput(BaseModel):
    """Request body: a subscription to preview (dry-run, no publish)."""

    channel_id: str
    extra_instructions: str = ""


class SubscriptionRunInput(BaseModel):
    """Request body: a subscription to run for real (persist + cache)."""

    channel_id: str
    force: bool = False
    publish: bool = False
    extra_instructions: str = ""


class RunAllInput(BaseModel):
    """Request body: run every active subscription (persist + cache)."""

    force: bool = False
    publish: bool = False
    extra_instructions: str = ""


class SubscriptionInput(BaseModel):
    """Request body: a subscription to add/upsert."""

    channel_id: str
    kind: str = "forum"
    guild_id: str | None = None
    resume_thread_id: str | None = None
    interval_seconds: int | None = None
    project: str | None = None
    publish_default: bool = True
    related_to: list[str] = []


class SubscriptionPatch(BaseModel):
    """Request body: partial edit of an existing subscription.

    Only the provided fields are changed; the rest of the subscription is kept.
    """

    resume_thread_id: str | None = None
    interval_seconds: int | None = None
    project: str | None = None
    publish_default: bool | None = None
    related_to: list[str] | None = None


class AgentInstructionsInput(BaseModel):
    """Request body: the extra prompt instructions to persist for an agent."""

    instructions: str = ""


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
        workspaces, graph, sections = await load_knowledge(
            cfg,
            workspace=workspace,
            include_events=events,
            storage=_store(),
            subscription_store=_subs(),
        )
        # Friendly names for section titles, and a rich header when a single
        # Discord workspace is in view (best-effort; falls back to the raw id).
        labels = await resolve_labels(workspaces, cfg)
        graph.relabel(labels)  # show channel/forum names on the graph nodes
        projects = await load_projects(cfg, workspaces, subscription_store=_subs())
        relations = await load_relations(cfg, workspaces, subscription_store=_subs())
        graph.edges.extend(  # connect related projects (name + explicit grouping)
            relate_workspaces(labels, projects=projects, relations=relations)
        )
        header = None
        if len(workspaces) == 1:
            header = await resolve_header(workspaces[0], cfg)
        return render_dashboard(
            sections, graph, header=header, workspace_labels=labels
        )

    @app.get("/console", response_class=HTMLResponse)
    async def console() -> str:
        return render_console()

    @app.get("/api/workspaces")
    async def api_workspaces() -> dict[str, Any]:
        workspaces, _graph, _sections = await load_knowledge(
            cfg, storage=_store(), subscription_store=_subs()
        )
        return {"workspaces": workspaces, "labels": await resolve_labels(workspaces, cfg)}

    @app.get("/api/knowledge")
    async def api_knowledge(
        workspace: str | None = Query(default=None),
        events: bool = Query(default=False),
    ) -> dict[str, Any]:
        workspaces, graph, _sections = await load_knowledge(
            cfg,
            workspace=workspace,
            include_events=events,
            storage=_store(),
            subscription_store=_subs(),
        )
        # Relabel workspace nodes with friendly channel/forum names so the graph
        # doesn't expose the raw ``discord:<id>`` (best-effort; falls back to id),
        # and connect workspaces that belong to the same project.
        labels = await resolve_labels(workspaces, cfg)
        graph.relabel(labels)
        projects = await load_projects(cfg, workspaces, subscription_store=_subs())
        relations = await load_relations(cfg, workspaces, subscription_store=_subs())
        graph.edges.extend(
            relate_workspaces(labels, projects=projects, relations=relations)
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

    async def _current_config() -> RuntimeConfig:
        """Return the persisted config, or a default seeded from the environment."""
        persisted: RuntimeConfig | None = await _config().get()
        if persisted is not None:
            return persisted
        return RuntimeConfig(llm_provider=cfg.llm_provider, llm_model=cfg.llm_model)

    @app.get("/api/agents")
    async def api_agents() -> dict[str, Any]:
        instructions = (await _current_config()).agent_instructions
        return {
            "agents": [
                {
                    "id": a.id,
                    "label": a.label,
                    "description": a.description,
                    "produces": a.produces,
                    "trigger": a.trigger,
                    "augmentable": a.augmentable,
                    "base_prompt": AGENT_BASE_PROMPTS.get(a.id, ""),
                    "instructions": instructions.get(a.id, ""),
                }
                for a in agent_catalog()
            ]
        }

    @app.put("/api/agents/{agent_id}/instructions")
    async def api_set_agent_instructions(
        agent_id: str, body: AgentInstructionsInput = Body(...)
    ) -> dict[str, Any]:
        agent = next((a for a in agent_catalog() if a.id == agent_id), None)
        if agent is None:
            raise HTTPException(status_code=404, detail="agent not found")
        if not agent.augmentable:
            raise HTTPException(
                status_code=422, detail=f"agent '{agent_id}' takes no extra prompt"
            )
        # Read-modify-write so we keep the provider/model selection and any other
        # agents' instructions intact.
        current = await _current_config()
        merged = dict(current.agent_instructions)
        text = body.instructions.strip()
        if text:
            merged[agent_id] = text
        else:
            merged.pop(agent_id, None)  # empty clears the override
        await _config().set(
            RuntimeConfig(
                llm_provider=current.llm_provider,
                llm_model=current.llm_model,
                agent_instructions=merged,
            )
        )
        return {
            "agent": agent_id,
            "instructions": merged.get(agent_id, ""),
            "persistent": bool(cfg.database_url),
        }

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
                "ready": env_ready or info.id in stored_ids,
                # Whether the secret is available from the environment (.env). This
                # is independent of which provider is currently selected.
                "env_ready": env_ready,
                "stored": info.id in stored_ids,
                "needs_secret": secret_field(info.id) is not None,
                "selected": info.id == selected,
            }
            for info, env_ready, _active in provider_status(cfg)
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
        current = await _current_config()
        config = RuntimeConfig(
            llm_provider=choice.provider,
            llm_model=model,
            agent_instructions=current.agent_instructions,
        )
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
        # Resolve a friendly channel/forum/repo name per subscription (best-effort;
        # falls back to the raw id when there is no token or the lookup fails).
        labels = await resolve_labels([s.workspace for s in subs], cfg)
        return {
            "subscriptions": [
                {
                    "id": str(s.id),
                    "workspace": s.workspace,
                    "name": labels.get(s.workspace, s.workspace),
                    "kind": s.kind,
                    "channel_id": s.channel_id,
                    "guild_id": s.guild_id,
                    "resume_thread_id": s.resume_thread_id,
                    "interval_seconds": s.interval_seconds,
                    "project": s.project,
                    "publish_default": s.publish_default,
                    "related_to": list(s.related_to),
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
        if sub.kind == GITHUB and "/" not in sub.channel_id:
            raise HTTPException(
                status_code=422, detail="a GitHub repo must be 'owner/name'"
            )
        subscription = Subscription(
            workspace=Subscription.workspace_for_kind(sub.kind, sub.channel_id),
            kind=sub.kind,
            channel_id=sub.channel_id,
            guild_id=sub.guild_id or cfg.discord_guild_id,
            resume_thread_id=sub.resume_thread_id or cfg.discord_resume_thread_id,
            interval_seconds=sub.interval_seconds,
            project=(sub.project.strip() if sub.project and sub.project.strip() else None),
            publish_default=sub.publish_default,
            related_to=[w.strip() for w in sub.related_to if w.strip()],
        )
        await _subs().add(subscription)
        return {"channel_id": subscription.channel_id, "workspace": subscription.workspace}

    @app.patch("/api/subscriptions/{channel_id}")
    async def api_edit_subscription(
        channel_id: str, patch: SubscriptionPatch = Body(...)
    ) -> dict[str, Any]:
        current = await _subs().get(channel_id)
        if current is None:
            raise HTTPException(status_code=404, detail="subscription not found")
        updates: dict[str, Any] = {}
        fields = patch.model_dump(exclude_unset=True)
        if "resume_thread_id" in fields:
            value = patch.resume_thread_id
            updates["resume_thread_id"] = value.strip() if value and value.strip() else None
        if "interval_seconds" in fields:
            updates["interval_seconds"] = patch.interval_seconds
        if "project" in fields:
            value = patch.project
            updates["project"] = value.strip() if value and value.strip() else None
        if "publish_default" in fields and patch.publish_default is not None:
            updates["publish_default"] = patch.publish_default
        if "related_to" in fields and patch.related_to is not None:
            # Never relate a subscription to itself.
            updates["related_to"] = [
                w.strip()
                for w in patch.related_to
                if w.strip() and w.strip() != current.workspace
            ]
        updated = current.model_copy(update=updates)
        await _subs().add(updated)
        return {
            "channel_id": updated.channel_id,
            "project": updated.project,
            "publish_default": updated.publish_default,
            "related_to": list(updated.related_to),
        }

    @app.delete("/api/subscriptions/{channel_id}")
    async def api_remove_subscription(channel_id: str) -> dict[str, Any]:
        found = await _subs().deactivate(channel_id)
        if not found:
            raise HTTPException(status_code=404, detail="subscription not found")
        return {"channel_id": channel_id, "deactivated": True}

    # ---- Dry-run previews (summarize without publishing to Discord) ----

    async def _effective_instructions(provided: str) -> str:
        """Use the request's instructions, or fall back to the persisted ones.

        The summary pipeline augments the Resume Agent's prompt; when a caller
        does not pass instructions we apply the ones saved from the console so a
        stored preference also applies to scheduled/headless runs.
        """
        if provided.strip():
            return provided
        return (await _current_config()).agent_instructions.get("resume-agent", "")

    @app.post("/api/preview/github")
    async def api_preview_github(
        body: GitHubPreviewInput = Body(...),
    ) -> dict[str, Any]:
        try:
            artifacts = await preview_github(
                cfg, body.repo, limit=body.limit,
                extra_instructions=await _effective_instructions(body.extra_instructions),
            )
        except PreviewError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"published": False, "artifacts": artifacts_to_dicts(artifacts)}

    @app.post("/api/preview/subscription")
    async def api_preview_subscription(
        body: SubscriptionPreviewInput = Body(...),
    ) -> dict[str, Any]:
        try:
            artifacts = await preview_subscription(
                cfg, body.channel_id, subscription_store=_subs(),
                extra_instructions=await _effective_instructions(body.extra_instructions),
            )
        except PreviewError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"published": False, "artifacts": artifacts_to_dicts(artifacts)}

    # ---- Interactive run (persist + populate cache; does NOT publish) ----

    @app.post("/api/run/subscription")
    async def api_run_subscription(
        body: SubscriptionRunInput = Body(...),
    ) -> dict[str, Any]:
        try:
            artifacts = await run_subscription(
                cfg,
                body.channel_id,
                subscription_store=_subs(),
                force=body.force,
                publish=body.publish,
                extra_instructions=await _effective_instructions(body.extra_instructions),
            )
        except RunError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "persisted": True,
            "published": body.publish,
            "artifacts": artifacts_to_dicts(artifacts),
        }

    @app.post("/api/run/all")
    async def api_run_all(body: RunAllInput = Body(...)) -> dict[str, Any]:
        try:
            artifacts = await run_all(
                cfg,
                subscription_store=_subs(),
                force=body.force,
                publish=body.publish,
                extra_instructions=await _effective_instructions(body.extra_instructions),
            )
        except RunError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "persisted": True,
            "published": body.publish,
            "artifacts": artifacts_to_dicts(artifacts),
        }

    return app



