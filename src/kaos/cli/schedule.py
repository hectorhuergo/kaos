"""`kaos schedule`: run subscriptions periodically (the Beta scheduler).

Wraps `kaos run` (idempotent, ADR-0008) in a :class:`Scheduler` loop, so KAOS
keeps its published knowledge up to date without a human triggering each run.
Because `run` publishes only on change, a scheduled run over unchanged forums is
a no-op. ``--once`` performs a single pass (useful behind an external cron).
"""

from __future__ import annotations

import asyncio

from kaos.cli.subscriptions import run_subscriptions
from kaos.core.config import Settings
from kaos.runtime import Scheduler


async def run_scheduler(
    *,
    interval: float | None = None,
    once: bool = False,
    dry_run: bool = False,
    consolidated: bool = False,
    force: bool = False,
    settings: Settings | None = None,
) -> int:
    """Run active subscriptions on a fixed interval until stopped."""
    settings = settings if settings is not None else Settings.from_env()
    seconds = interval if interval is not None else settings.scheduler_interval

    async def job() -> int:
        return await run_subscriptions(
            dry_run=dry_run,
            consolidated=consolidated,
            force=force,
            settings=settings,
        )

    scheduler = Scheduler(job, interval=seconds, max_runs=1 if once else None)

    if once:
        print("KAOS scheduler — pasada única\n")
        await scheduler.run()
        return 0

    print(f"KAOS scheduler — cada {seconds:.0f}s (Ctrl-C para detener)\n")
    try:
        await scheduler.run()
    except (KeyboardInterrupt, asyncio.CancelledError):  # pragma: no cover
        print(f"\nScheduler detenido tras {scheduler.runs} corrida(s).")
    return 0


