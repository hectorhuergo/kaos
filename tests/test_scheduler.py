"""Tests for the Beta scheduler (Core-agnostic, injectable time)."""

from __future__ import annotations

import asyncio

import pytest

from kaos.runtime import Scheduler


def test_runs_a_fixed_number_of_times() -> None:
    calls = 0

    async def job() -> int:
        nonlocal calls
        calls += 1
        return 0

    async def scenario() -> None:
        sched = Scheduler(job, interval=10, max_runs=3, sleep=_no_sleep)
        runs = await sched.run()
        assert runs == 3
        assert calls == 3

    asyncio.run(scenario())


def test_sleeps_between_runs_but_not_after_last() -> None:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    async def job() -> int:
        return 0

    async def scenario() -> None:
        sched = Scheduler(job, interval=42, max_runs=3, sleep=sleep)
        await sched.run()
        # 3 runs => 2 gaps between them, no trailing sleep.
        assert slept == [42, 42]

    asyncio.run(scenario())


def test_single_pass_does_not_sleep() -> None:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    async def job() -> int:
        return 0

    async def scenario() -> None:
        sched = Scheduler(job, interval=10, max_runs=1, sleep=sleep)
        runs = await sched.run()
        assert runs == 1
        assert slept == []

    asyncio.run(scenario())


def test_stops_when_cancelled_from_sleep() -> None:
    calls = 0

    async def job() -> int:
        nonlocal calls
        calls += 1
        return 0

    async def sleep(_seconds: float) -> None:
        raise asyncio.CancelledError

    async def scenario() -> None:
        sched = Scheduler(job, interval=10, sleep=sleep)  # no max_runs: infinite
        with pytest.raises(asyncio.CancelledError):
            await sched.run()
        assert calls == 1  # ran once, then cancelled during the sleep

    asyncio.run(scenario())


def test_rejects_invalid_arguments() -> None:
    async def job() -> int:
        return 0

    with pytest.raises(ValueError):
        Scheduler(job, interval=0)
    with pytest.raises(ValueError):
        Scheduler(job, interval=10, max_runs=0)


async def _no_sleep(_seconds: float) -> None:
    return None


def _sub(channel_id: str, interval_seconds: int | None = None):  # type: ignore[no-untyped-def]
    from kaos.domain.subscription import Subscription

    return Subscription(
        workspace=f"discord:{channel_id}",
        channel_id=channel_id,
        interval_seconds=interval_seconds,
    )


def test_due_runs_everything_on_first_pass() -> None:
    from kaos.cli.schedule import due_subscriptions

    subs = [_sub("a", 3600), _sub("b", None)]
    due = due_subscriptions(subs, now=1000.0, last_run={}, base_interval=900.0)
    assert due == {"a", "b"}  # never run yet → all due


def test_due_respects_per_subscription_interval() -> None:
    from kaos.cli.schedule import due_subscriptions

    subs = [_sub("fast", 300), _sub("slow", 3600)]
    last_run = {"fast": 1000.0, "slow": 1000.0}
    # 400s later: only the 300s one is due; the 3600s one is not.
    due = due_subscriptions(subs, now=1400.0, last_run=last_run, base_interval=900.0)
    assert due == {"fast"}


def test_due_falls_back_to_base_interval_when_unset() -> None:
    from kaos.cli.schedule import due_subscriptions

    subs = [_sub("x", None)]
    last_run = {"x": 1000.0}
    assert due_subscriptions(subs, now=1500.0, last_run=last_run, base_interval=900.0) == set()
    assert due_subscriptions(subs, now=1950.0, last_run=last_run, base_interval=900.0) == {"x"}


