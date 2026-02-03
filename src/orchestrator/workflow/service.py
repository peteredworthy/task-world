"""Async workflow service wiring WorkflowEngine to persistent storage."""

import asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import ChecklistStatus, RunStatus
from orchestrator.db.event_store import EventStore
from orchestrator.db.repositories import RunRepository
from orchestrator.state.models import ChecklistItem, Run, TaskState
from orchestrator.state.session import SessionStateManager
from orchestrator.workflow.engine import WorkflowEngine
from orchestrator.workflow.event_logger import PersistentEventEmitter
from orchestrator.workflow.events import BufferingEmitter
from orchestrator.workflow.transitions import TransitionResult


class SubmitEventRegistry:
    """Shared registry of asyncio.Events for submit notifications.

    This must be a singleton per application so that all WorkflowService
    instances (one per request) share the same events.  A UserManagedAgent
    registers an event here; when *any* WorkflowService instance calls
    ``submit_for_verification``, it notifies through this registry.
    """

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}

    def register(self, task_id: str) -> asyncio.Event:
        """Register and return an event for *task_id*."""
        event = asyncio.Event()
        self._events[task_id] = event
        return event

    def unregister(self, task_id: str) -> None:
        """Remove a previously registered event."""
        self._events.pop(task_id, None)

    def notify(self, task_id: str) -> None:
        """Set the event for *task_id*, if one is registered."""
        event = self._events.get(task_id)
        if event is not None:
            event.set()


class _ServiceClock:
    """Clock for WorkflowService that returns UTC now."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class WorkflowService:
    """Async service that bridges WorkflowEngine (sync) with persistent storage.

    Pattern for each mutation:
    1. Load Run from RunRepository into a temporary SessionStateManager
    2. Create BufferingEmitter, create WorkflowEngine(state, clock, emitter)
    3. Call engine method (sync)
    4. repo.save() (flushes state)
    5. event_emitter.emit_batch(buffered_events) (flushes events)
    6. session.commit() (atomic)
    """

    def __init__(
        self,
        session: AsyncSession,
        repo: RunRepository | None = None,
        event_store: EventStore | None = None,
        event_emitter: PersistentEventEmitter | None = None,
        submit_event_registry: SubmitEventRegistry | None = None,
    ) -> None:
        self._session = session
        self._repo = repo or RunRepository(session)
        self._event_store = event_store or EventStore(session)
        self._event_emitter = event_emitter or PersistentEventEmitter(self._event_store)
        self._clock = _ServiceClock()
        self._submit_registry = submit_event_registry or SubmitEventRegistry()

    def _build_engine(
        self, run: Run
    ) -> tuple[WorkflowEngine, SessionStateManager, BufferingEmitter]:
        """Create an engine with a temporary in-memory state manager and buffering emitter."""
        state = SessionStateManager()
        state.add_run(run)
        buffer = BufferingEmitter()
        engine = WorkflowEngine(state, clock=self._clock, emitter=buffer)
        return engine, state, buffer

    async def _persist(
        self, state: SessionStateManager, run_id: str, buffer: BufferingEmitter
    ) -> Run:
        """Save state and events, then commit."""
        run = state.get_run(run_id)
        await self._repo.save(run)
        events = buffer.drain()
        await self._event_emitter.emit_batch(events)
        await self._session.commit()
        return run

    # --- Delegating to WorkflowEngine ---

    async def start_run(self, run_id: str) -> Run:
        """Start a run (DRAFT/QUEUED -> ACTIVE)."""
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)
        engine.start_run(run_id)
        return await self._persist(state, run_id, buffer)

    async def pause_run(self, run_id: str) -> Run:
        """Pause a run (ACTIVE -> PAUSED)."""
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)
        engine.pause_run(run_id)
        return await self._persist(state, run_id, buffer)

    async def resume_run(self, run_id: str) -> Run:
        """Resume a run (PAUSED -> ACTIVE)."""
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)
        engine.resume_run(run_id)
        return await self._persist(state, run_id, buffer)

    async def start_task(self, run_id: str, task_id: str) -> TransitionResult:
        """Start building a task (PENDING -> BUILDING)."""
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)
        result = engine.start_task(run_id, task_id)
        await self._persist(state, run_id, buffer)
        return result

    async def submit_for_verification(self, run_id: str, task_id: str) -> TransitionResult:
        """Submit task for verification (BUILDING -> VERIFYING)."""
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)
        result = engine.submit_for_verification(run_id, task_id)
        await self._persist(state, run_id, buffer)
        self._notify_submit(task_id)
        return result

    async def complete_verification(self, run_id: str, task_id: str) -> TransitionResult:
        """Complete verification phase."""
        run = await self._repo.get(run_id)
        engine, state, buffer = self._build_engine(run)
        result = engine.complete_verification(run_id, task_id)
        await self._persist(state, run_id, buffer)
        return result

    # --- Direct state operations ---

    async def get_run(self, run_id: str) -> Run:
        """Get a run by ID."""
        return await self._repo.get(run_id)

    async def list_runs(self) -> list[Run]:
        """List all runs."""
        return await self._repo.list_all()

    async def list_runs_by_project(self, project_id: str) -> list[Run]:
        """List runs for a project."""
        return await self._repo.list_by_project(project_id)

    async def list_runs_by_status(self, status: RunStatus) -> list[Run]:
        """List runs filtered by status."""
        return await self._repo.list_by_status(status)

    async def list_runs_by_project_and_status(
        self, project_id: str, status: RunStatus
    ) -> list[Run]:
        """List runs filtered by both project and status."""
        return await self._repo.list_by_project_and_status(project_id, status)

    async def get_task(self, run_id: str, task_id: str) -> TaskState:
        """Get a task by run ID and task ID."""
        run = await self._repo.get(run_id)
        state = SessionStateManager()
        state.add_run(run)
        return state.get_task(run_id, task_id)

    async def create_run(self, run: Run) -> Run:
        """Persist a new run."""
        await self._repo.save(run)
        await self._session.commit()
        return await self._repo.get(run.id)

    async def delete_run(self, run_id: str) -> None:
        """Delete a run."""
        await self._repo.delete(run_id)
        await self._session.commit()

    async def update_checklist_item(
        self,
        run_id: str,
        task_id: str,
        req_id: str,
        status: ChecklistStatus,
        note: str | None = None,
    ) -> ChecklistItem:
        """Update a checklist item status."""
        run = await self._repo.get(run_id)
        state = SessionStateManager()
        state.add_run(run)
        item = state.update_checklist_item(run_id, task_id, req_id, status, note)
        await self._repo.save(state.get_run(run_id))
        await self._session.commit()
        return item

    async def set_grade(
        self,
        run_id: str,
        task_id: str,
        req_id: str,
        grade: str,
        grade_reason: str | None = None,
    ) -> ChecklistItem:
        """Set a grade on a checklist item."""
        run = await self._repo.get(run_id)
        state = SessionStateManager()
        state.add_run(run)
        task = state.get_task(run_id, task_id)

        from orchestrator.state.errors import ChecklistItemNotFoundError

        for item in task.checklist:
            if item.req_id == req_id:
                item.grade = grade
                if grade_reason is not None:
                    item.grade_reason = grade_reason
                await self._repo.save(state.get_run(run_id))
                await self._session.commit()
                return item

        raise ChecklistItemNotFoundError(run_id, task_id, req_id)

    # --- Submit notification bridge ---

    def register_submit_event(self, task_id: str) -> asyncio.Event:
        """Register an asyncio.Event that fires when submit_for_verification is called for this task.

        Used by UserManagedAgent to wait for external submission via REST/MCP.
        Delegates to the shared :class:`SubmitEventRegistry`.
        """
        return self._submit_registry.register(task_id)

    def unregister_submit_event(self, task_id: str) -> None:
        """Remove a previously registered submit event."""
        self._submit_registry.unregister(task_id)

    def _notify_submit(self, task_id: str) -> None:
        """Signal any registered submit event for this task."""
        self._submit_registry.notify(task_id)
