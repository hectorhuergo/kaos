"""`kaos subscribe|unsubscribe|subscriptions|run`: manage watched sources.

Subscriptions persist in the configured store (PostgreSQL when
`KAOS_DATABASE_URL` is set). `run` iterates the active subscriptions and
summarizes each, reusing the summary cache so unchanged conversations don't
hit the LLM again.
"""

from __future__ import annotations

from kaos.bootstrap.factory import build_subscription_store
from kaos.cli.backfill import run_backfill, run_forum_backfill
from kaos.core.config import Settings
from kaos.domain.subscription import FORUM, KINDS, Subscription


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
    settings: Settings | None = None,
) -> int:
    """Persist a subscription to a forum/channel."""
    if kind not in KINDS:
        print(f"error: kind must be one of {KINDS}, got '{kind}'")
        return 1
    settings = settings if settings is not None else Settings.from_env()
    store = build_subscription_store(settings)
    subscription = Subscription(
        workspace=Subscription.workspace_for(channel_id),
        kind=kind,
        channel_id=channel_id,
        guild_id=guild_id or settings.discord_guild_id,
        resume_thread_id=resume_thread_id or settings.discord_resume_thread_id,
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
    settings: Settings | None = None,
) -> int:
    """Summarize every active subscription."""
    settings = settings if settings is not None else Settings.from_env()
    store = build_subscription_store(settings)
    try:
        subscriptions = await store.list(active_only=True)
    finally:
        await _close(store)

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
        if sub.kind == FORUM:
            rc = await run_forum_backfill(
                sub.channel_id,
                guild_id=sub.guild_id,
                dry_run=dry_run,
                consolidated=consolidated,
                force=force,
                only_if_changed=True,
                settings=sub_settings,
            )
        else:
            rc = await run_backfill(
                sub.channel_id, dry_run=dry_run, settings=sub_settings
            )
        exit_code = exit_code or rc
    return exit_code

