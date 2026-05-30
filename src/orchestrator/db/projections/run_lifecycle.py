"""RunLifecycleProjector: tracks active run_ids from RunStatusChanged events."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import RunStatus
from orchestrator.workflow import RunStatusChanged, WorkflowEvent

_ACTIVE_STATUSES: frozenset[RunStatus] = frozenset({RunStatus.ACTIVE, RunStatus.PAUSED})
_TERMINAL_STATUSES: frozenset[RunStatus] = frozenset({RunStatus.COMPLETED, RunStatus.FAILED})


class RunLifecycleProjector:
    """In-memory set of active run_ids derived from RunStatusChanged events.

    A run is considered active if its most recent status is ACTIVE or PAUSED.
    Terminal and pre-start statuses (DRAFT, STOPPING, COMPLETED, FAILED) are
    treated as inactive.
    """

    handled_events: frozenset[type] = frozenset({RunStatusChanged})

    def __init__(self) -> None:
        self._active: set[str] = set()
        self._terminal: set[str] = set()

    def is_active(self, run_id: str) -> bool:
        """Return True if run_id is currently in an active status."""
        return run_id in self._active

    def is_terminal(self, run_id: str) -> bool:
        """Return True if run_id is in a terminal status (COMPLETED or FAILED)."""
        return run_id in self._terminal

    async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None:
        if not isinstance(event, RunStatusChanged):
            return
        try:
            new_status = RunStatus(event.new_status)
        except ValueError:
            self._active.discard(event.run_id)
            self._terminal.discard(event.run_id)
            return
        if new_status in _ACTIVE_STATUSES:
            self._active.add(event.run_id)
            self._terminal.discard(event.run_id)
        elif new_status in _TERMINAL_STATUSES:
            self._active.discard(event.run_id)
            self._terminal.add(event.run_id)
        else:
            self._active.discard(event.run_id)
            self._terminal.discard(event.run_id)

    async def rebuild(self, events: Sequence[WorkflowEvent], session: AsyncSession) -> None:
        self._active.clear()
        self._terminal.clear()
        for event in events:
            if isinstance(event, RunStatusChanged):
                await self.handle(event, session)
