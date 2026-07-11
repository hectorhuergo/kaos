"""`kaos schedule`: run subscriptions periodically honoring each one's plan.

Wraps `kaos run` (idempotent, ADR-0008) in a :class:`Scheduler` loop, so KAOS
keeps its published knowledge up to date without a human triggering each run.
Because `run` publishes only on change, a scheduled run over unchanged forums is
a no-op.

Execution plan (ADR-0016): the schedule lives *with the subscription* — each one
carries an optional ``interval_seconds``. The scheduler ticks at a base cadence
(``--interval`` / ``KAOS_SCHEDULER_INTERVAL``, the granularity) and, on each
tick, runs only the subscriptions whose own interval has elapsed since their last
run (a subscription without an interval runs every tick). There is no separate
plan store; ``--once`` performs a single pass over the due subscriptions.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence

from kaos.bootstrap.factory import build_subscription_store
from kaos.cli.subscriptions import run_subscriptions
from kaos.core.config import Settings
from kaos.domain.subscription import Subscription
from kaos.runtime import Scheduler


def due_subscriptions(
    subscriptions: Sequence[Subscription],
    *,
    now: float,
    last_run: dict[str, float],
    base_interval: float,
) -> set[str]:
    """Return the ``channel_id``s whose execution plan is due at ``now``.

    A subscription is due when it has never run, or when at least its
    ``interval_seconds`` (falling back to ``base_interval``) has elapsed since its
    last run. ``last_run`` maps ``channel_id`` → monotonic timestamp of the last
    run and is owned by the caller (the scheduler updates it after each pass).
    """
    due: set[str] = set()
    for sub in subscriptions:
        interval = sub.interval_seconds if sub.interval_seconds else base_interval
        previous = last_run.get(sub.channel_id)
        if previous is None or (now - previous) >= interval:
            due.add(sub.channel_id)
    return due


async def run_scheduler(
    *,
    interval: float | None = None,
    once: bool = False,
    dry_run: bool = False,
    consolidated: bool = False,
    force: bool = False,
    settings: Settings | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Run due subscriptions on a fixed base interval until stopped.

    ``clock`` is injectable so tests can drive the plan deterministically.
    """
    settings = settings if settings is not None else Settings.from_env()
    seconds = interval if interval is not None else settings.scheduler_interval
    last_run: dict[str, float] = {}

    async def job() -> int:
        store = build_subscription_store(settings)
        try:
            subs = await store.list(active_only=True)
        finally:
            close = getattr(store, "close", None)
            if close is not None:
                await close()
        now = clock()
        due = due_subscriptions(subs, now=now, last_run=last_run, base_interval=seconds)
        if not due:
            print("(sin suscripciones vencidas en esta pasada)")
            return 0
        rc = await run_subscriptions(
            dry_run=dry_run,
            consolidated=consolidated,
            force=force,
            only=due,
            settings=settings,
        )
        for channel_id in due:
            last_run[channel_id] = now
        return rc

    scheduler = Scheduler(job, interval=seconds, max_runs=1 if once else None)

    if once:
        print("KAOS scheduler — pasada única\n")
        await scheduler.run()
        return 0

    print(
        f"KAOS scheduler — tick cada {seconds:.0f}s, plan por suscripción "
        "(Ctrl-C para detener)\n"
    )
    try:
        await scheduler.run()
    except (KeyboardInterrupt, asyncio.CancelledError):  # pragma: no cover
        print(f"\nScheduler detenido tras {scheduler.runs} corrida(s).")
    return 0


