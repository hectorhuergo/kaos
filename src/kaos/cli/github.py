"""`kaos github`: summarize a repository's recent activity into knowledge.

Reads recent commits (and optionally issues/PRs) from the GitHub REST API,
maps them to events and runs the Resume Agent — KAOS dogfooding its own
development. With ``--dry-run`` the summary prints to the console instead of
being published.
"""

from __future__ import annotations

import httpx

from kaos.bootstrap.factory import build_llm, build_publisher, build_storage
from kaos.core.config import Settings
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.connectors import GitHubConnector, GitHubRestSource
from kaos.plugins.publishers import ConsolePublisher
from kaos.runtime import InMemoryStorage, KaosRuntime


async def run_github(
    repo: str | None = None,
    *,
    dry_run: bool = False,
    limit: int = 30,
    include_issues: bool = True,
    settings: Settings | None = None,
) -> int:
    """Summarize a repository's recent activity and publish (or print) it."""
    settings = settings if settings is not None else Settings.from_env()
    target = repo or settings.github_repo
    if not target:
        print("error: falta el repositorio (argumento <owner/repo> o KAOS_GITHUB_REPO)")
        return 1
    token = settings.github_token or settings.llm_api_key
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
    runtime.register_agent(ResumeAgent(llm))
    runtime.register_publisher(ConsolePublisher() if dry_run else build_publisher(settings))

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

