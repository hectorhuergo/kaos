"""`kaos subscribe|unsubscribe|subscriptions|run`: manage watched sources.

Subscriptions persist in the configured store (PostgreSQL when
`KAOS_DATABASE_URL` is set). `run` iterates the active subscriptions and
summarizes each, reusing the summary cache so unchanged conversations don't
hit the LLM again.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from kaos.bootstrap.factory import build_subscription_store
from kaos.cli.backfill import run_backfill, run_forum_backfill
from kaos.cli.github import run_github
from kaos.core.config import Settings
from kaos.domain.subscription import CHANNEL, FORUM, GITHUB, KINDS, Subscription

# A subscription runner turns one active subscription into a summarization run.
# Registering a kind here (instead of an ``if/elif`` chain) keeps the dispatch
# open for extension: a new source kind only needs its own runner, without
# touching ``run_subscriptions`` — the subscription loop stays agnostic of the
# concrete connector behind each kind.
SubscriptionRunner = Callable[..., Awaitable[int]]


async def _run_forum(
    sub: Subscription, *, dry_run: bool, consolidated: bool, force: bool, settings: Settings
) -> int:
    return await run_forum_backfill(
        sub.channel_id,
        guild_id=sub.guild_id,
        dry_run=dry_run,
        consolidated=consolidated,
        force=force,
        only_if_changed=True,
        settings=settings,
    )


async def _run_channel(
    sub: Subscription, *, dry_run: bool, consolidated: bool, force: bool, settings: Settings
) -> int:
    return await run_backfill(sub.channel_id, dry_run=dry_run, settings=settings)


async def _run_github(
    sub: Subscription, *, dry_run: bool, consolidated: bool, force: bool, settings: Settings
) -> int:
    return await run_github(sub.channel_id, dry_run=dry_run, settings=settings)


SUBSCRIPTION_RUNNERS: dict[str, SubscriptionRunner] = {
    FORUM: _run_forum,
    CHANNEL: _run_channel,
    GITHUB: _run_github,
}


async def _close(store: object) -> None:
    close = getattr(store, "close", None)
    if close is not None:
        await close()


async def add_subscription(
    channel_id: str,
    *,
    kind: str = FORUM,
    guild_id: str | None = None,
    resume_thread_id: str | None = None,
    interval_seconds: int | None = None,
    settings: Settings | None = None,
) -> int:
    """Persist a subscription to a forum/channel (Discord) or repo (GitHub).

    For ``kind == 'github'`` ``channel_id`` is the repository slug ``owner/name``.
    ``interval_seconds`` sets the execution plan (how often the scheduler runs
    it); ``None`` means it runs on every scheduler pass.
    """
    if kind not in KINDS:
        print(f"error: kind must be one of {KINDS}, got '{kind}'")
        return 1
    if kind == GITHUB and "/" not in channel_id:
        print(f"error: un repo de GitHub debe ser 'owner/name', got '{channel_id}'")
        return 1
    settings = settings if settings is not None else Settings.from_env()
    store = build_subscription_store(settings)
    subscription = Subscription(
        workspace=Subscription.workspace_for_kind(kind, channel_id),
        kind=kind,
        channel_id=channel_id,
        guild_id=guild_id or settings.discord_guild_id,
        resume_thread_id=resume_thread_id or settings.discord_resume_thread_id,
        interval_seconds=interval_seconds,
    )
    try:
        await store.add(subscription)
    finally:
        await _close(store)
    print(f"subscribed: {kind} {channel_id} -> {subscription.workspace}")
    return 0


async def remove_subscription(
    channel_id: str, *, settings: Settings | None = None
) -> int:
    """Deactivate a subscription."""
    settings = settings if settings is not None else Settings.from_env()
    store = build_subscription_store(settings)
    try:
        found = await store.deactivate(channel_id)
    finally:
        await _close(store)
    if found:
        print(f"unsubscribed: {channel_id}")
        return 0
    print(f"not found: {channel_id}")
    return 1


async def list_subscriptions(*, settings: Settings | None = None) -> int:
    """Print the active subscriptions."""
    settings = settings if settings is not None else Settings.from_env()
    store = build_subscription_store(settings)
    try:
        subscriptions = await store.list(active_only=True)
    finally:
        await _close(store)
    if not subscriptions:
        print("(sin suscripciones)")
        return 0
    print(f"{len(subscriptions)} suscripción(es) activa(s):")
    for sub in subscriptions:
        thread = sub.resume_thread_id or "-"
        print(f"  · {sub.kind:7} {sub.channel_id}  guild={sub.guild_id or '-'}  resume={thread}")
    return 0


async def run_subscriptions(
    *,
    dry_run: bool = False,
    consolidated: bool = False,
    force: bool = False,
    only: set[str] | None = None,
    settings: Settings | None = None,
) -> int:
    """Summarize the active subscriptions.

    ``only`` restricts the run to a set of ``channel_id``s (used by the scheduler
    to run just the subscriptions whose execution plan is due); by default every
    active subscription runs.
    """
    settings = settings if settings is not None else Settings.from_env()
    store = build_subscription_store(settings)
    try:
        subscriptions = await store.list(active_only=True)
    finally:
        await _close(store)

    if only is not None:
        subscriptions = [s for s in subscriptions if s.channel_id in only]

    if not subscriptions:
        print("(sin suscripciones activas)")
        return 0

    print(f"KAOS run — {len(subscriptions)} suscripción(es)\n")
    exit_code = 0
    for sub in subscriptions:
        # Publish to this subscription's resume thread, if it has one.
        sub_settings = settings.model_copy(
            update={
                "discord_resume_thread_id": (
                    sub.resume_thread_id or settings.discord_resume_thread_id
                )
            }
        )
        print(f"=== {sub.kind} {sub.channel_id} ===")
        runner = SUBSCRIPTION_RUNNERS.get(sub.kind, _run_channel)
        rc = await runner(
            sub,
            dry_run=dry_run,
            consolidated=consolidated,
            force=force,
            settings=sub_settings,
        )
        exit_code = exit_code or rc
    return exit_code

