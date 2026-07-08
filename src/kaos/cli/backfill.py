"""`kaos backfill`: read a Discord channel/thread history and summarize it.

Reads configuration from the environment (`.env`). With ``--dry-run`` the
summary is printed to the console instead of published.
"""

from __future__ import annotations

import httpx

from kaos.bootstrap.factory import build_llm, build_publisher, build_storage
from kaos.contracts.artifact import Artifact
from kaos.contracts.context import Context
from kaos.contracts.event import Event
from kaos.core.cache import (
    CONTENT_HASH,
    THREAD_ID,
    SummaryCache,
    content_fingerprint,
)
from kaos.core.config import Settings
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.connectors import (
    DiscordBackfillSource,
    DiscordConnector,
    list_forum_threads,
)
from kaos.plugins.publishers import ConsolePublisher
from kaos.runtime import InMemoryStorage, KaosRuntime


async def run_backfill(
    channel_id: str,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    settings: Settings | None = None,
) -> int:
    """Read a channel's history, summarize it, and publish (or print) the result."""
    settings = settings if settings is not None else Settings.from_env()
    if not settings.discord_token:
        print("error: KAOS_DISCORD_TOKEN is not set (needed to read Discord)")
        return 1

    source = DiscordBackfillSource(
        token=settings.discord_token,
        channel_id=channel_id,
        guild_id=settings.discord_guild_id,
        limit=limit if limit is not None else settings.discord_message_limit,
    )
    try:
        llm = build_llm(settings)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    storage = InMemoryStorage() if dry_run else build_storage(settings)
    runtime = KaosRuntime(storage=storage)
    runtime.register_connector(DiscordConnector(source, emit_completed=True))
    runtime.register_agent(ResumeAgent(llm))
    runtime.register_publisher(ConsolePublisher() if dry_run else build_publisher(settings))

    print(f"KAOS backfill — channel {channel_id} (dry_run={dry_run})\n")
    await runtime.start()
    await runtime.stop()
    print("Done.")
    return 0


def _should_publish(changed: int, only_if_changed: bool) -> bool:
    """Whether to publish given how many items changed.

    The scheduler rule: with ``only_if_changed`` we publish only when something
    actually changed, making re-runs idempotent. Otherwise we always publish.
    """
    return changed > 0 or not only_if_changed


async def run_forum_backfill(
    forum_channel_id: str,
    *,
    guild_id: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    consolidated: bool = False,
    force: bool = False,
    only_if_changed: bool = False,
    settings: Settings | None = None,
) -> int:
    """Summarize every thread of a Discord forum channel.

    The forum is the workspace; each thread is read and summarized. By default
    each thread summary is published separately (labeled with the thread name).
    With ``consolidated=True`` all thread summaries are merged into a single
    "Estado del Proyecto" report and published as one artifact (Knowledge before
    Reports). With ``--dry-run`` results print to console.

    Summaries are cached in Storage keyed by thread + content fingerprint: a
    thread whose messages have not changed is not re-sent to the LLM. Use
    ``force=True`` to recompute every thread regardless of the cache.

    With ``only_if_changed=True`` nothing is published when every thread was a
    cache hit (no changes). This makes a run idempotent: re-running without any
    new messages produces no new publication — the rule the scheduler follows.
    """
    settings = settings if settings is not None else Settings.from_env()
    if not settings.discord_token:
        print("error: KAOS_DISCORD_TOKEN is not set (needed to read Discord)")
        return 1
    guild = guild_id or settings.discord_guild_id
    if not guild:
        print("error: guild id required (--guild or KAOS_DISCORD_GUILD_ID)")
        return 1
    try:
        llm = build_llm(settings)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    agent = ResumeAgent(llm)
    publisher = ConsolePublisher() if dry_run else build_publisher(settings)
    storage = build_storage(settings)
    cache = SummaryCache(storage)
    workspace = f"discord:{forum_channel_id}"
    msg_limit = limit if limit is not None else settings.discord_message_limit

    # Collected per-thread summaries for the consolidated report.
    summaries: list[tuple[str, str, Artifact]] = []
    changed = 0  # threads that were (re)summarized this run

    try:
        async with httpx.AsyncClient() as client:
            threads = await list_forum_threads(
                settings.discord_token, guild, forum_channel_id, client=client
            )
            print(f"KAOS forum backfill — {len(threads)} hilos en el foro {forum_channel_id}\n")

            for thread_id, name in threads:
                source = DiscordBackfillSource(
                    token=settings.discord_token,
                    channel_id=thread_id,
                    guild_id=guild,
                    limit=msg_limit,
                    client=client,
                )
                try:
                    events = [
                        Event(
                            type="message.created",
                            source="discord-backfill",
                            workspace=workspace,
                            payload={
                                "author": m.author,
                                "text": m.text,
                                "channel_id": m.channel_id,
                                "message_id": m.message_id,
                            },
                        )
                        async for m in source.messages()
                    ]
                except httpx.HTTPStatusError as exc:
                    print(f"· {name}: no se pudo leer (HTTP {exc.response.status_code})")
                    continue

                if not events:
                    print(f"· {name}: (sin mensajes)")
                    continue

                if not any(e.payload.get("text") for e in events):
                    print(
                        f"· {name}: {len(events)} mensajes pero sin contenido "
                        "(¿falta el Message Content Intent del bot?)"
                    )
                    continue

                fingerprint = content_fingerprint(
                    [str(e.payload.get("message_id", "")) for e in events]
                )

                base: Artifact | None = None
                if not force:
                    cached = await cache.get(workspace, thread_id, fingerprint)
                    if cached is not None:
                        print(f"· {name}: sin cambios — reutilizando resumen cacheado")
                        base = cached

                thread_changed = base is None
                if base is None:
                    try:
                        artifacts = await agent.run(
                            Context(workspace=workspace, events=tuple(events))
                        )
                    except httpx.HTTPStatusError as exc:
                        print(
                            f"\nError del LLM (HTTP {exc.response.status_code}): "
                            f"{exc.response.text[:300]}"
                        )
                        print(
                            "Revisa KAOS_GITHUB_TOKEN (necesita permiso 'Models'), o usa "
                            "KAOS_LLM_PROVIDER=openai / echo."
                        )
                        return 1

                    if not artifacts:
                        continue
                    # Persist evidence and the summary, tagged for the cache.
                    base = Artifact(
                        kind=artifacts[0].kind,
                        workspace=workspace,
                        produced_by=artifacts[0].produced_by,
                        content=dict(artifacts[0].content),
                        source_events=artifacts[0].source_events,
                        metadata={
                            **artifacts[0].metadata,
                            THREAD_ID: thread_id,
                            CONTENT_HASH: fingerprint,
                            "thread_name": name,
                        },
                    )
                    for event in events:
                        await storage.save_event(event)
                    await storage.save_artifact(base)

                if thread_changed:
                    changed += 1

                if consolidated:
                    summaries.append((thread_id, name, base))
                else:
                    # Idempotency: publish a thread only when it changed.
                    if not _should_publish(1 if thread_changed else 0, only_if_changed):
                        continue
                    labeled = Artifact(
                        kind=base.kind,
                        workspace=workspace,
                        produced_by=base.produced_by,
                        content={
                            **base.content,
                            "summary": f"# 🧵 {name}\n\n{base.content.get('summary', '')}",
                            "thread": name,
                        },
                        source_events=base.source_events,
                        metadata={**base.metadata, THREAD_ID: thread_id, "thread_name": name},
                    )
                    await publisher.publish(labeled)

            if consolidated:
                if not summaries:
                    print("(sin hilos para consolidar)")
                elif not _should_publish(changed, only_if_changed):
                    # Idempotent: nothing changed, so the conclusion is the same.
                    print("\nSin cambios en ningún hilo — no se publica (idempotente).")
                else:
                    report = _build_consolidated_report(
                        forum_channel_id, workspace, summaries
                    )
                    await publisher.publish(report)
    finally:
        close = getattr(storage, "close", None)
        if close is not None:
            await close()

    print("\nDone.")
    return 0


def _build_consolidated_report(
    forum_channel_id: str,
    workspace: str,
    summaries: list[tuple[str, str, Artifact]],
) -> Artifact:
    """Merge per-thread summaries into a single "Estado del Proyecto" report.

    The report references every source event across all threads, so the
    consolidated knowledge stays fully traceable.
    """
    header = (
        f"# 📊 Estado del Proyecto\n\n"
        f"_Consolidado de {len(summaries)} hilos · generado por KAOS_\n"
    )
    sections = [header]
    all_source_events: list[str] = []
    total_messages = 0
    for _thread_id, name, base in summaries:
        body = base.content.get("summary", "")
        sections.append(f"\n---\n\n# 🧵 {name}\n\n{body}")
        all_source_events.extend(base.source_events)
        total_messages += int(base.content.get("message_count", 0))

    return Artifact(
        kind="project.status",
        workspace=workspace,
        produced_by="resume-agent",
        content={
            "summary": "\n".join(sections),
            "format": "markdown",
            "message_count": total_messages,
            "thread_count": len(summaries),
        },
        source_events=tuple(all_source_events),
        metadata={"forum_channel_id": forum_channel_id},
    )


