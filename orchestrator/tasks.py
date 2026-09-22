"""Per-chat registry of the asyncio task that is currently running."""

from __future__ import annotations


class ActiveTasks:
    """Tracks which asyncio task owns a chat so /stop can cancel the right one."""

    def __init__(self, tasks: dict):
        self.tasks = tasks

    def track(self, chat_id: str, task) -> None:
        self.tasks[chat_id] = task

    def release(self, chat_id: str, task) -> None:
        if self.tasks.get(chat_id) == task:
            self.tasks.pop(chat_id, None)
