"""Manager for tracking and controlling chat message generation tasks."""

from __future__ import annotations

import asyncio
from typing import Any


class ChatSessionManager:
    """Manages active chat message generation tasks, allowing cancellation."""

    def __init__(self) -> None:
        # Maps (workspace, session_id) to the running task
        self._tasks: dict[tuple[str, str], asyncio.Task[Any]] = {}

    def register_task(
        self, workspace: str, session_id: str, task: asyncio.Task[Any]
    ) -> None:
        """Register a task as active for the given session."""
        key = (workspace, session_id)
        self._tasks[key] = task
        task.add_done_callback(lambda _: self._cleanup(key))

    async def cancel_task(self, workspace: str, session_id: str) -> bool:
        """Cancel the active task for the given session, if any. Returns True if cancelled."""
        key = (workspace, session_id)
        task = self._tasks.get(key)
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return True
        return False

    def _cleanup(self, key: tuple[str, str]) -> None:
        """Remove a completed task from tracking."""
        self._tasks.pop(key, None)


# Global instance
_manager = ChatSessionManager()


def get_chat_manager() -> ChatSessionManager:
    """Get the global chat session manager."""
    return _manager

