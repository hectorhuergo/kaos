"""`kaos github`: summarize a repository's recent activity into knowledge.

Reads recent commits (and optionally issues/PRs) from the GitHub REST API,
maps them to events and runs the Resume Agent — KAOS dogfooding its own
development. With ``--dry-run`` the summary prints to the console instead of
being published.
"""

from __future__ import annotations

import httpx

from kaos.bootstrap.factory import (
    build_credential_store,
    build_llm,
    build_publisher,
    build_storage,
    load_settings,
)
from kaos.contracts.publisher import Publisher
from kaos.core.config import Settings
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.connectors import GitHubConnector, GitHubRestSource
from kaos.plugins.dashboard.chat import load_contributions
from kaos.plugins.publishers import ConsolePublisher
from kaos.runtime import InMemoryStorage, KaosRuntime


async def _resolve_github_token(settings: Settings) -> str | None:
    """Resolve the GitHub token: credential store wins over env."""
    # Credential store (edited from console) takes precedence over env.
    if settings.database_url:
        store = build_credential_store(settings)
        try:
            cred = await store.get("github")
            if cred and cred.api_key:
                return cred.api_key
        finally:
            close = getattr(store, "close", None)
            if close:
                await close()
    # Fallback to env.
    return settings.github_token or settings.llm_api_key


async def run_github(
    repo: str | None = None,
    *,
    dry_run: bool = False,
    limit: int = 30,
    include_issues: bool = True,
    settings: Settings | None = None,
    publisher: Publisher | None = None,
    extra_instructions: str = "",
    llm_provider: str | None = None,
    llm_model: str | None = None,
    agent_id: str | None = None,
) -> int:
    """Summarize a repository's recent activity and publish (or print) it.

    When ``publisher`` is provided it is used instead of the configured one
    (e.g. a capturing publisher for a web-console dry-run preview), so nothing is
    sent to Discord regardless of the environment. ``extra_instructions`` augment
    the Resume Agent's prompt (focus/tone) without changing its structure.

    ``llm_provider``/``llm_model`` are an optional per-run override (from a
    subscription or a console run) that wins over the global default.
    """
    settings = await load_settings(settings, provider=llm_provider, model=llm_model)
    target = repo or settings.github_repo
    if not target:
        print("error: falta el repositorio (argumento <owner/repo> o KAOS_GITHUB_REPO)")
        return 1
    token = await _resolve_github_token(settings)
    if not token:
        print("error: KAOS_GITHUB_TOKEN es necesario para leer GitHub")
        return 1

    try:
        llm = build_llm(settings)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    source = GitHubRestSource(token=token, repo=target, limit=limit, include_issues=include_issues)
    storage = InMemoryStorage() if dry_run else build_storage(settings)
    runtime = KaosRuntime(storage=storage)
    runtime.register_connector(GitHubConnector(source, repo=target, emit_completed=True))
    runtime.register_agent(
        ResumeAgent(llm, extra_instructions=extra_instructions, agent_id=agent_id)
    )
    runtime.register_publisher(
        publisher or (ConsolePublisher() if dry_run else build_publisher(settings))
    )

    # Weigh human contributions made from the chat (any user message in this
    # workspace) when re-summarizing.
    workspace = f"github:{target}"
    runtime.prime_workspace(workspace, await load_contributions(storage, workspace))

    print(f"KAOS github — {target} (dry_run={dry_run})\n")
    try:
        await runtime.start()
        await runtime.stop()
    except httpx.HTTPStatusError as exc:
        print(f"error: GitHub respondió HTTP {exc.response.status_code}: {exc.response.text[:200]}")
        return 1
    finally:
        close = getattr(storage, "close", None)
        if close is not None:
            await close()
    print("Done.")
    return 0

