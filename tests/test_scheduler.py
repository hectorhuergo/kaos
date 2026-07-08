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

