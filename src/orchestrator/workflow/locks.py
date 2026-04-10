"""Task-level pessimistic locking."""

from datetime import datetime, timedelta
from typing import Protocol


class TaskLockedError(Exception):
    """Raised when a task is already locked by another agent."""

    def __init__(self, task_id: str, locked_by: str) -> None:
        self.task_id = task_id
        self.locked_by = locked_by
        super().__init__(f"Task {task_id} is locked by agent {locked_by}")


class LockTimeoutError(Exception):
    """Raised when a lock has expired."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        super().__init__(f"Lock on task {task_id} has expired")


class LockManager(Protocol):
    """Protocol for task lock management."""

    def acquire(self, task_id: str, agent_id: str, now: datetime) -> bool: ...
    def release(self, task_id: str, agent_id: str) -> bool: ...
    def is_locked(self, task_id: str, now: datetime) -> bool: ...


class InMemoryLockManager:
    """In-memory lock manager with configurable timeout."""

    def __init__(self, timeout: timedelta = timedelta(minutes=5)) -> None:
        self._locks: dict[str, tuple[str, datetime]] = {}  # task_id -> (agent_id, locked_at)
        self._timeout = timeout

    def acquire(self, task_id: str, agent_id: str, now: datetime) -> bool:
        """Acquire a lock. Returns False if locked by another non-expired agent."""
        if task_id in self._locks:
            existing_agent, locked_at = self._locks[task_id]
            if existing_agent != agent_id and (now - locked_at) < self._timeout:
                return False
        self._locks[task_id] = (agent_id, now)
        return True

    def release(self, task_id: str, agent_id: str) -> bool:
        """Release a lock. Returns False if not locked by this agent."""
        if task_id not in self._locks:
            return False
        existing_agent, _ = self._locks[task_id]
        if existing_agent != agent_id:
            return False
        del self._locks[task_id]
        return True

    def is_locked(self, task_id: str, now: datetime) -> bool:
        """Check if a task is currently locked (non-expired)."""
        if task_id not in self._locks:
            return False
        _, locked_at = self._locks[task_id]
        return (now - locked_at) < self._timeout
