"""Scheduler: run an idempotent job on a fixed interval (Beta).

The Scheduler turns `kaos run` into a recurring operation. Because `run` is
idempotent (ADR-0008) — it publishes only when a watched conversation actually
changed — running it periodically is safe: unchanged forums produce no new
publication and unchanged conversations are served from the summary cache
(ADR-0007) without hitting the LLM.

The Scheduler is Core-agnostic: it takes any async job returning an exit code
and knows nothing about Discord, the LLM or Storage. Time is injectable
(``sleep``) so it is fully testable without real delays.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

Job = Callable[[], Awaitable[int]]
Sleep = Callable[[float], Awaitable[None]]


class Scheduler:
    """Runs an async job repeatedly, sleeping ``interval`` seconds between runs."""

    def __init__(
        self,
        job: Job,
        *,
        interval: float,
        max_runs: int | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be > 0")
        if max_runs is not None and max_runs <= 0:
            raise ValueError("max_runs must be > 0 when set")
        self._job = job
        self._interval = interval
        self._max_runs = max_runs
        self._sleep = sleep
        self.runs = 0

    async def run(self) -> int:
        """Run the job in a loop; return the number of completed runs.

        Stops after ``max_runs`` runs when set; otherwise loops until cancelled
        (e.g. Ctrl-C). Sleeps ``interval`` seconds *between* runs — never after
        the final run — so a single-pass scheduler (``max_runs=1``) returns
        immediately without waiting.
        """
        while True:
            await self._job()
            self.runs += 1
            if self._max_runs is not None and self.runs >= self._max_runs:
                return self.runs
            await self._sleep(self._interval)

