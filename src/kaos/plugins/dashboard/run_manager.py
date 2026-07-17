"""Manager for tracking and controlling Preview/Run tasks."""

from __future__ import annotations

import asyncio
from typing import Any


class RunTaskManager:
    """Manages active preview/run tasks, allowing cancellation.

    Each task is keyed by ``run_id`` (a client-generated UUID) so concurrent
    runs on different subscriptions can be tracked independently.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def register_task(self, run_id: str, task: asyncio.Task[Any]) -> None:
        """Register a task as active for the given run_id."""
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._cleanup(run_id))

    def cancel_task(self, run_id: str) -> bool:
        """Cancel the active task for the given run_id. Returns True if cancelled."""
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def _cleanup(self, run_id: str) -> None:
        """Remove a completed task from tracking."""
        self._tasks.pop(run_id, None)


# Global instance
_manager = RunTaskManager()


def get_run_manager() -> RunTaskManager:
    """Get the global run task manager."""
    return _manager
