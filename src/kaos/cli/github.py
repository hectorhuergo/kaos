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
from kaos.cli.backfill import consolidate_sections
from kaos.contracts.artifact import Artifact
from kaos.contracts.publisher import Publisher
from kaos.core.config import Settings
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.connectors import GitHubConnector, GitHubRestSource
from kaos.plugins.dashboard.chat import load_contributions
from kaos.plugins.publishers import CapturingPublisher, ConsolePublisher
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

    The **designated agent** (``agent_id``, from a subscription/console run) is
    honored dynamically: the resume-agent always produces a chunk-aware reduced
    summary of the activity (so it fits the model's context window); the default
    run publishes that summary, while a designated task/dev agent synthesizes the
    final report from that compact summary — never from the oversized raw
    activity. This mirrors the forum consolidation path (ADR-0024/0025).
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
    workspace = f"github:{target}"
    resume_agent = ResumeAgent(
        llm,
        extra_instructions=extra_instructions,
        agent_id=agent_id,
        context_tokens=settings.llm_num_ctx,
    )
    aid = (agent_id or "").strip() or resume_agent.name
    default_agent = aid == resume_agent.name

    real_storage = InMemoryStorage() if dry_run else build_storage(settings)
    out_publisher = publisher or (ConsolePublisher() if dry_run else build_publisher(settings))

    # The resume-agent always produces the chunk-aware reduced summary. For the
    # default agent that summary IS the report (persisted by the runtime, as
    # before). For a designated task/dev agent the summary is only the *compact
    # input* they synthesize into the final report, so we keep it out of the DB
    # (an in-memory storage) and persist just the one report per run.
    summary_storage = real_storage if default_agent else InMemoryStorage()

    # Weigh human contributions made from the chat (any user message in this
    # workspace) when re-summarizing.
    contributions = await load_contributions(real_storage, workspace)

    capturing = CapturingPublisher()
    runtime = KaosRuntime(storage=summary_storage)
    runtime.register_connector(GitHubConnector(source, repo=target, emit_completed=True))
    runtime.register_agent(resume_agent)
    runtime.register_publisher(capturing)
    runtime.prime_workspace(workspace, contributions)

    print(f"KAOS github — {target} (dry_run={dry_run})\n")
    try:
        await runtime.start()
        await runtime.stop()
        if not capturing.published:
            print("(sin actividad para resumir)")
            return 0
        summary = capturing.published[0]
        report = await _designated_report(
            summary,
            default_agent=default_agent,
            agent_id=agent_id,
            resume_agent=resume_agent,
            llm=llm,
            workspace=workspace,
            storage=real_storage,
        )
        await out_publisher.publish(report)
    except httpx.HTTPStatusError as exc:
        print(f"error: GitHub respondió HTTP {exc.response.status_code}: {exc.response.text[:200]}")
        return 1
    finally:
        close = getattr(real_storage, "close", None)
        if close is not None:
            await close()
    print("Done.")
    return 0


async def _designated_report(
    summary: Artifact,
    *,
    default_agent: bool,
    agent_id: str | None,
    resume_agent: ResumeAgent,
    llm: object,
    workspace: str,
    storage: object,
) -> Artifact:
    """The report to publish, produced by the designated agent.

    For the default (resume) agent the reduced ``summary`` is the report as-is.
    For a designated task/dev agent, that compact summary is synthesized into the
    final report via the shared :func:`consolidate_sections` dispatcher; the
    result is attributed to the designated agent and persisted (one report per
    run). The summary's embedded transcript and ``source_events`` travel with the
    report so the knowledge stays traceable (Everything is Traceable).
    """
    if default_agent:
        return summary
    section = str(summary.content.get("summary", ""))
    text, produced_by = await consolidate_sections(
        agent_id, resume_agent, llm, workspace=workspace, sections=[section]  # type: ignore[arg-type]
    )
    report = Artifact(
        kind=summary.kind,
        workspace=workspace,
        produced_by=produced_by,
        content={
            "summary": text.strip() or section,
            "format": "markdown",
            "message_count": summary.content.get("message_count", 0),
            "messages": summary.content.get("messages", []),
        },
        source_events=summary.source_events,
        metadata={**summary.metadata, "agent_id": produced_by},
    )
    save = getattr(storage, "save_artifact", None)
    if save is not None:
        await save(report)
    return report


