"""Integration tests for AgentOutputEvent batching via OutputBatcher."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import (
    AgentRunnerType,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import EventV2Model
from orchestrator.runners import AttemptStore
from orchestrator.runners import EventBroadcaster
from orchestrator.runners import OutputBatcher
from orchestrator.runners import PhaseHandler
from orchestrator.runners.types import (
    AgentRunnerInfo,
    ExecutionContext,
    ExecutionMetrics,
    ExecutionResult,
    LogLineCallback,
)
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState


FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

LINE_COUNT = 60


class _LineEmittingAgent:
    """Agent that emits LINE_COUNT lines via on_output, then submits."""

    def __init__(self, line_count: int) -> None:
        self._line_count = line_count

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
            name="line-emitting-test",
            version="1.0.0",
        )

    def get_quota(self, fetcher: Any = None) -> None:
        return None

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: Any,
        on_submit: Any,
        on_output: LogLineCallback | None = None,
        on_grade: Any = None,
        on_agent_metadata: Any = None,
        on_escalation: Any = None,
    ) -> ExecutionResult:
        if on_output is not None:
            for i in range(self._line_count):
                await on_output([f"line {i}"])
        await on_submit()
        return ExecutionResult(
            success=True,
            metrics=ExecutionMetrics(),
        )

    async def cancel(self) -> None:
        pass


class _FakeConnectionManager:
    """Records broadcast AgentOutputEvents without a WebSocket server."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def broadcast_event(self, event: object) -> None:
        self.events.append(event)


class _CommitFailingSession(AsyncSession):
    """Session that flushes normally but fails before committing."""

    async def commit(self) -> None:
        raise RuntimeError("commit failed")


def _make_run() -> Run:
    now = datetime.now(timezone.utc)
    return Run(
        id="test-run-batching",
        repo_name="test-project",
        source_branch="main",
        status=RunStatus.ACTIVE,
        routine_id="test-routine",
        routine_source=RoutineSource.LOCAL,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[],
            )
        ],
        created_at=now,
        updated_at=now,
    )


def _make_task_state() -> TaskState:
    return TaskState(
        id="test-task-batching",
        config_id="T-01",
        status=TaskStatus.BUILDING,
        checklist=[
            ChecklistItem(
                req_id="R1",
                desc="Test requirement",
                priority=Priority.CRITICAL,
            )
        ],
        current_attempt=0,
        max_attempts=3,
    )


@pytest.fixture
async def session_factory_fixture() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    yield factory
    await engine.dispose()


async def test_output_batching_fewer_events_than_lines(
    session_factory_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """60 lines emitted one-at-a-time should produce fewer than 60 AgentOutputEvent rows."""
    session_factory = session_factory_fixture

    manager = _FakeConnectionManager()
    batcher = OutputBatcher(session_factory=session_factory, connection_manager=manager)
    attempt_store = AttemptStore(session_factory)
    broadcaster = EventBroadcaster(session_factory)
    phase_handler = PhaseHandler(
        attempt_store=attempt_store,
        event_broadcaster=broadcaster,
        output_batcher=batcher,
    )

    run = _make_run()
    task_state = _make_task_state()
    agent = _LineEmittingAgent(LINE_COUNT)
    context = ExecutionContext(
        run_id=run.id,
        task_id=task_state.id,
        working_dir="/tmp",
        prompt="Emit output lines for batching test",
        requirements=["R1"],
    )

    await phase_handler.execute_phase(
        phase="building",
        run=run,
        task_state=task_state,
        service=None,
        agent=agent,
        context=context,
        req_desc_to_id={},
    )

    async with session_factory() as session:
        result = await session.execute(
            select(EventV2Model)
            .where(EventV2Model.aggregate_id == run.id)
            .where(EventV2Model.event_type == "agent_output")
            .order_by(EventV2Model.position)
        )
        events = result.scalars().all()

    event_count = len(events)
    assert event_count > 0, "Expected at least one AgentOutputEvent"
    assert event_count < LINE_COUNT, (
        f"Expected fewer than {LINE_COUNT} events (batching), got {event_count}"
    )
    broadcast_lines: list[str] = []
    for event in manager.events:
        broadcast_lines.extend(event.lines)
    assert broadcast_lines == [f"line {i}" for i in range(LINE_COUNT)]


async def test_output_batching_line_offset_monotonic_no_gaps(
    session_factory_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """line_offset values in stored AgentOutputEvents are monotonically increasing with no gaps."""
    session_factory = session_factory_fixture

    batcher = OutputBatcher(session_factory=session_factory)
    attempt_store = AttemptStore(session_factory)
    broadcaster = EventBroadcaster(session_factory)
    phase_handler = PhaseHandler(
        attempt_store=attempt_store,
        event_broadcaster=broadcaster,
        output_batcher=batcher,
    )

    run = _make_run()
    task_state = _make_task_state()
    agent = _LineEmittingAgent(LINE_COUNT)
    context = ExecutionContext(
        run_id=run.id,
        task_id=task_state.id,
        working_dir="/tmp",
        prompt="Emit output lines for batching test",
        requirements=["R1"],
    )

    await phase_handler.execute_phase(
        phase="building",
        run=run,
        task_state=task_state,
        service=None,
        agent=agent,
        context=context,
        req_desc_to_id={},
    )

    async with session_factory() as session:
        result = await session.execute(
            select(EventV2Model)
            .where(EventV2Model.aggregate_id == run.id)
            .where(EventV2Model.event_type == "agent_output")
            .order_by(EventV2Model.position)
        )
        events = result.scalars().all()

    expected_offset = 0
    for event_model in events:
        payload = json.loads(event_model.payload)
        line_offset = payload["line_offset"]
        lines = payload["lines"]
        assert line_offset == expected_offset, (
            f"Expected line_offset={expected_offset}, got {line_offset}"
        )
        expected_offset += len(lines)

    assert expected_offset == LINE_COUNT, (
        f"Total lines in events ({expected_offset}) != expected ({LINE_COUNT})"
    )


async def test_output_batching_all_lines_in_order(
    session_factory_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """All 60 lines are present in the correct order across batched events."""
    session_factory = session_factory_fixture

    batcher = OutputBatcher(session_factory=session_factory)
    attempt_store = AttemptStore(session_factory)
    broadcaster = EventBroadcaster(session_factory)
    phase_handler = PhaseHandler(
        attempt_store=attempt_store,
        event_broadcaster=broadcaster,
        output_batcher=batcher,
    )

    run = _make_run()
    task_state = _make_task_state()
    agent = _LineEmittingAgent(LINE_COUNT)
    context = ExecutionContext(
        run_id=run.id,
        task_id=task_state.id,
        working_dir="/tmp",
        prompt="Emit output lines for batching test",
        requirements=["R1"],
    )

    await phase_handler.execute_phase(
        phase="building",
        run=run,
        task_state=task_state,
        service=None,
        agent=agent,
        context=context,
        req_desc_to_id={},
    )

    async with session_factory() as session:
        result = await session.execute(
            select(EventV2Model)
            .where(EventV2Model.aggregate_id == run.id)
            .where(EventV2Model.event_type == "agent_output")
            .order_by(EventV2Model.position)
        )
        events = result.scalars().all()

    all_lines: list[str] = []
    for event_model in events:
        payload = json.loads(event_model.payload)
        all_lines.extend(payload["lines"])

    expected_lines = [f"line {i}" for i in range(LINE_COUNT)]
    assert all_lines == expected_lines, (
        f"Lines out of order or missing. Got {len(all_lines)} lines, expected {LINE_COUNT}"
    )


async def test_output_batching_event_count_in_events_v2(
    session_factory_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """AgentOutputEvent row count in events_v2 is less than line count confirming batching."""
    session_factory = session_factory_fixture

    batcher = OutputBatcher(session_factory=session_factory)
    attempt_store = AttemptStore(session_factory)
    broadcaster = EventBroadcaster(session_factory)
    phase_handler = PhaseHandler(
        attempt_store=attempt_store,
        event_broadcaster=broadcaster,
        output_batcher=batcher,
    )

    run = _make_run()
    task_state = _make_task_state()
    agent = _LineEmittingAgent(LINE_COUNT)
    context = ExecutionContext(
        run_id=run.id,
        task_id=task_state.id,
        working_dir="/tmp",
        prompt="Emit output lines for batching test",
        requirements=["R1"],
    )

    await phase_handler.execute_phase(
        phase="building",
        run=run,
        task_state=task_state,
        service=None,
        agent=agent,
        context=context,
        req_desc_to_id={},
    )

    async with session_factory() as session:
        from sqlalchemy import func

        result = await session.execute(
            select(func.count(EventV2Model.position))
            .where(EventV2Model.aggregate_id == run.id)
            .where(EventV2Model.event_type == "agent_output")
        )
        row_count = result.scalar_one()

    assert row_count < LINE_COUNT, (
        f"AgentOutputEvent row count ({row_count}) should be less than "
        f"line count ({LINE_COUNT}) confirming batching occurred"
    )


async def test_output_batching_timer_persists_single_line(
    session_factory_fixture: async_sessionmaker[AsyncSession],
) -> None:
    """A single quiet output line is persisted by the autonomous timer."""
    session_factory = session_factory_fixture
    manager = _FakeConnectionManager()
    batcher = OutputBatcher(
        session_factory=session_factory,
        flush_interval_ms=10,
        connection_manager=manager,
    )

    try:
        await batcher.add_line("timer-run", "timer-task", 1, "line a")
        await asyncio.sleep(0.05)

        async with session_factory() as session:
            result = await session.execute(
                select(EventV2Model)
                .where(EventV2Model.aggregate_id == "timer-run")
                .where(EventV2Model.event_type == "agent_output")
                .order_by(EventV2Model.position)
            )
            events = result.scalars().all()

        assert len(events) == 1
        payload = json.loads(events[0].payload)
        assert payload["task_id"] == "timer-task"
        assert payload["lines"] == ["line a"]
        assert payload["line_offset"] == 0
        assert len(manager.events) == 1
        assert manager.events[0].lines == ["line a"]
    finally:
        await batcher.aclose()


async def test_output_batching_session_factory_writes_jsonl_outbox(tmp_path: Path) -> None:
    """Session-factory flushes use the wired event store and write JSONL outbox rows."""
    db_path = tmp_path / "orchestrator.db"
    engine = create_engine(db_path)
    await init_db(engine)
    session_factory = create_session_factory(engine)

    try:
        batcher = OutputBatcher(session_factory=session_factory)
        await batcher.add_line("jsonl-run", "jsonl-task", 1, "line a")
        await batcher.add_line("jsonl-run", "jsonl-task", 1, "line b")
        await batcher.flush_immediate()
    finally:
        await engine.dispose()

    journal_path = tmp_path / ".orchestrator" / "state" / "history.jsonl"
    records = [json.loads(line) for line in journal_path.read_text().splitlines()]
    output_records = [record for record in records if record["event_type"] == "agent_output"]
    assert len(output_records) == 1
    payload = output_records[0]["payload"]
    assert payload["run_id"] == "jsonl-run"
    assert payload["task_id"] == "jsonl-task"
    assert payload["lines"] == ["line a", "line b"]
    assert payload["line_offset"] == 0


async def test_output_batching_commit_failure_does_not_write_jsonl_outbox(
    tmp_path: Path,
) -> None:
    """Outbox rows are written only after the events_v2 transaction commits."""
    db_path = tmp_path / "orchestrator.db"
    engine = create_engine(db_path)
    await init_db(engine)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=_CommitFailingSession,
    )

    try:
        batcher = OutputBatcher(session_factory=session_factory)
        await batcher.add_line("rollback-run", "rollback-task", 1, "line a")
        with pytest.raises(RuntimeError, match="commit failed"):
            await batcher.flush_immediate()
    finally:
        await engine.dispose()

    journal_path = tmp_path / ".orchestrator" / "state" / "history.jsonl"
    assert not journal_path.exists()
