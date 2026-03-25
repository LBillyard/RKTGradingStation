"""Background task runner for CPU-heavy operations."""

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class TaskStatus:
    """Status of a background task."""
    task_id: str
    status: str = "pending"  # pending, running, completed, failed, cancelled
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class BackgroundTaskRunner:
    """Manages CPU-heavy tasks in a thread pool."""

    def __init__(self, max_workers: int = 4):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.tasks: dict[str, TaskStatus] = {}
        self._lock = threading.Lock()

    async def submit(self, task_id: str, fn: Callable, *args, **kwargs) -> TaskStatus:
        """Submit a task for background execution."""
        status = TaskStatus(task_id=task_id, status="pending")
        with self._lock:
            self.tasks[task_id] = status
            # P10: Prune completed/failed tasks older than 1 hour on each submit
            self._prune_completed_tasks()

        loop = asyncio.get_event_loop()

        def _run():
            with self._lock:
                status.status = "running"
                status.started_at = datetime.now(timezone.utc)
            try:
                result = fn(*args, **kwargs)
                with self._lock:
                    status.result = result
                    status.status = "completed"
                    status.progress = 1.0
            except Exception as e:
                with self._lock:
                    status.error = str(e)
                    status.status = "failed"
                logger.error(f"Background task {task_id} failed: {e}")
            finally:
                with self._lock:
                    status.completed_at = datetime.now(timezone.utc)

        loop.run_in_executor(self.executor, _run)
        return status

    def get_status(self, task_id: str) -> Optional[TaskStatus]:
        """Get the current status of a task."""
        with self._lock:
            return self.tasks.get(task_id)

    def update_progress(self, task_id: str, progress: float, message: str = "") -> None:
        """Update progress of a running task (called from within the task)."""
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id].progress = progress
                self.tasks[task_id].message = message

    def _prune_completed_tasks(self, max_age_seconds: int = 3600) -> None:
        """Remove completed/failed tasks older than max_age_seconds.

        Called internally under self._lock — do NOT acquire the lock again.
        """
        now = datetime.now(timezone.utc)
        stale = [
            tid for tid, s in self.tasks.items()
            if s.completed_at and (now - s.completed_at).total_seconds() > max_age_seconds
        ]
        for tid in stale:
            del self.tasks[tid]
        if stale:
            logger.debug("Pruned %d completed background tasks", len(stale))

    def cleanup_completed(self, max_age_seconds: int = 3600) -> int:
        """Remove completed tasks older than max_age_seconds."""
        with self._lock:
            now = datetime.now(timezone.utc)
            to_remove = []
            for task_id, status in self.tasks.items():
                if status.completed_at and (now - status.completed_at).total_seconds() > max_age_seconds:
                    to_remove.append(task_id)
            for task_id in to_remove:
                del self.tasks[task_id]
            return len(to_remove)


# Singleton task runner
task_runner = BackgroundTaskRunner()
