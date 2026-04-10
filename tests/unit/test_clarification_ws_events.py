"""Unit tests for WebSocket events emitted on clarification create/respond.

These tests verify that the WorkflowService emits ClarificationRequested and
ClarificationResponded events that reach the ConnectionManager — without
booting a full HTTP app, without StaticPool, and without SignalQueue plumbing.

The ConnectionManager is not mocked: a real subclass (RecordingConnectionManager)
is used to capture broadcast_event calls with no behaviour changes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.websocket import ConnectionManager
from orchestrator.config.enums import ChecklistStatus, Priority, RunStatus, TaskStatus
from orchestrator.db import (
    EventStore,
    RunRepository,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.state.models import Attempt, ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow import (
    ClarificationAnswer,
    ClarificationQuestion,
    ClarificationRequested,
    ClarificationResponded,
    LocalAutoVerifyRunner,
    PersistentEventEmitter,
)
from orchestrator.workflow import WorkflowEvent
from orchestrator.workflow.service import WorkflowService


# ---------------------------------------------------------------------------
# Real observing ConnectionManager — no mocking, just a spy subclass
# ---------------------------------------------------------------------------


class RecordingConnectionManager(ConnectionManager):
    """ConnectionManager subclass that records all broadcast_event calls."""

    def __init__(self) -> None:
        super().__init__()
        self.recorded: list[Any] = []

    async def broadcast_event(self, event: object) -> None:  # type: ignore[override]
        self.recorded.append(event)
        await super().broadcast_event(event)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _make_run() -> Run:
    """Build a minimal run with one task in BUILDING state."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-test",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.BUILDING,
                        current_attempt=1,
                        attempts=[
                            Attempt(
                                attempt_num=1,
                                started_at=now,
                            )
                        ],
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Do it",
                                priority=Priority.CRITICAL,
                                status=ChecklistStatus.OPEN,
                            ),
                        ],
                    )
                ],
            )
        ],
    )


def _make_service(
    session: AsyncSession,
    recording_manager: RecordingConnectionManager,
) -> WorkflowService:
    """Build a WorkflowService wired to the recording ConnectionManager."""
    repo = RunRepository(session)
    event_store = EventStore(session)
    emitter = PersistentEventEmitter(event_store)

    manager = recording_manager

    def _on_event(event: WorkflowEvent) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast_event(event))
        except RuntimeError:
            pass

    emitter.add_listener(_on_event)

    return WorkflowService(
        session=session,
        repo=repo,
        event_store=event_store,
        event_emitter=emitter,
        auto_verify_runner=LocalAutoVerifyRunner(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_clarification_requested(session: AsyncSession) -> None:
    """WorkflowService emits ClarificationRequested that reaches ConnectionManager."""
    run = _make_run()
    recording_manager = RecordingConnectionManager()
    svc = _make_service(session, recording_manager)

    await svc.create_run(run)

    questions = [
        ClarificationQuestion(
            id="q1",
            question="Need confirmation?",
            context="Quick check",
            options=["Yes", "No"],
        )
    ]
    await svc.request_clarification("run-test", "task-1", questions)

    # Allow the event loop to flush any pending broadcast_event tasks
    await asyncio.sleep(0)

    clarification_events = [
        e for e in recording_manager.recorded if isinstance(e, ClarificationRequested)
    ]
    assert len(clarification_events) == 1, (
        f"Expected 1 ClarificationRequested event, got {len(clarification_events)}. "
        f"All recorded events: {[type(e).__name__ for e in recording_manager.recorded]}"
    )
    event = clarification_events[0]
    assert event.run_id == "run-test"
    assert event.task_id == "task-1"
    assert event.question_count == 1


@pytest.mark.asyncio
async def test_ws_clarification_responded(session: AsyncSession) -> None:
    """WorkflowService emits ClarificationResponded that reaches ConnectionManager."""
    run = _make_run()
    recording_manager = RecordingConnectionManager()
    svc = _make_service(session, recording_manager)

    await svc.create_run(run)

    questions = [
        ClarificationQuestion(
            id="q1",
            question="Choose one",
            context="Selection",
            options=["A", "B"],
        )
    ]
    clarification = await svc.request_clarification("run-test", "task-1", questions)

    # Clear recorded events from the request step
    recording_manager.recorded.clear()

    answers = [
        ClarificationAnswer(
            question_id="q1",
            selected_option="A",
            answered_by="user",
            answered_at=datetime.now(timezone.utc),
        )
    ]
    await svc.respond_to_clarification("run-test", "task-1", clarification.id, answers, "user")

    # Allow the event loop to flush any pending broadcast_event tasks
    await asyncio.sleep(0)

    responded_events = [
        e for e in recording_manager.recorded if isinstance(e, ClarificationResponded)
    ]
    assert len(responded_events) == 1, (
        f"Expected 1 ClarificationResponded event, got {len(responded_events)}. "
        f"All recorded events: {[type(e).__name__ for e in recording_manager.recorded]}"
    )
    event = responded_events[0]
    assert event.run_id == "run-test"
    assert event.task_id == "task-1"
    assert event.request_id == clarification.id
