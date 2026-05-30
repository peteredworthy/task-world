"""Integration tests: projection rebuild restores read-model state from events."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import AgentRunnerType, RunStatus, TaskStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.db import SqliteEventStore
from orchestrator.db import RunModel, StepModel
from orchestrator.db import ProjectionRegistry, RunStateProjector, TaskStateProjector
from orchestrator.workflow import (
    AgentChangedEvent,
    AgentErrorEvent,
    AgentOutputEvent,
    CreateRunCommand,
    DeleteRunCommand,
    FanOutCompleted,
    HealthCheckEvent,
    RunCreated,
    StepCompleted,
    StepCreated,
    StepSkipped,
    TaskCreated,
    TaskStatusChanged,
    deserialize_event,
    handle_create_run,
    handle_delete_run,
)
from orchestrator.workflow import RunStatusChanged, StepHumanApprovalRecorded

NOW = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _make_run(run_id: str = "run-1", status: str = "queued") -> RunModel:
    return RunModel(
        id=run_id,
        repo_name="proj-1",
        status=status,
        runner_config={},
        config={},
        created_at=NOW,
        updated_at=NOW,
    )


async def _store_and_project(
    session: AsyncSession,
    run_id: str,
    new_status: RunStatus,
) -> None:
    """Append a RunStatusChanged event to events_v2 with projection wired."""
    store = SqliteEventStore(session)
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    store.add_projection_listener(registry)

    event = RunStatusChanged(
        run_id=run_id,
        event_type="run_status_changed",
        old_status=RunStatus.DRAFT,
        new_status=new_status,
        timestamp=NOW,
    )
    await store.append(event)


async def test_full_lifecycle_rebuild(session: AsyncSession) -> None:
    """Create a run, emit status events, corrupt state, rebuild, assert restored.

    Simulates the full lifecycle:
    1. Run created with initial status.
    2. Status events stored in events_v2.
    3. RunModel.status corrupted directly in DB.
    4. Rebuild from events_v2.
    5. Status restored to last event's value.
    """
    session.add(_make_run("run-1", "draft"))
    await session.flush()

    # Emit status transitions stored in events_v2
    await _store_and_project(session, "run-1", RunStatus.PAUSED)
    await _store_and_project(session, "run-1", RunStatus.ACTIVE)
    await session.flush()

    # Verify the projector updated the status
    result = await session.execute(text("SELECT status FROM runs WHERE id = 'run-1'"))
    assert result.fetchone()[0] == "active"

    # Corrupt the read model
    await session.execute(text("UPDATE runs SET status = 'corrupted' WHERE id = 'run-1'"))
    await session.flush()
    result = await session.execute(text("SELECT status FROM runs WHERE id = 'run-1'"))
    assert result.fetchone()[0] == "corrupted"

    # Rebuild from events_v2
    read_store = SqliteEventStore(session)
    stored = await read_store.get_all()
    workflow_events = []
    for se in stored:
        try:
            workflow_events.append(deserialize_event(se.event_type, se.payload))
        except ValueError:
            pass

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.flush()

    # Status must be restored to the last RunStatusChanged value
    result = await session.execute(text("SELECT status FROM runs WHERE id = 'run-1'"))
    assert result.fetchone()[0] == "active"


async def test_step_skipped_rebuild_restores_completed_and_current_step_index(
    session: AsyncSession,
) -> None:
    """Rebuilding from events_v2 restores manual skip read-model state."""
    store = SqliteEventStore(session)
    await store.append(
        [
            RunCreated(
                run_id="skip-run",
                timestamp=NOW,
                routine_id="routine-1",
                repo_name="skip-repo",
                status=RunStatus.PAUSED,
                pause_reason="manual_gate",
                current_step_index=1,
            ),
            StepCreated(
                run_id="skip-run",
                timestamp=NOW,
                step_id="step-1",
                config_id="S-01",
                title="Done Step",
                order_index=0,
                completed=True,
            ),
            StepCreated(
                run_id="skip-run",
                timestamp=NOW,
                step_id="step-2",
                config_id="S-02",
                title="Manual Step",
                order_index=1,
            ),
            StepSkipped(
                run_id="skip-run",
                timestamp=NOW,
                step_id="step-2",
                step_index=1,
                skip_reason="manual_skip",
                completed=True,
                current_step_index_after=2,
            ),
        ]
    )

    stored = await store.get_all()
    workflow_events = [
        deserialize_event(stored_event.event_type, stored_event.payload) for stored_event in stored
    ]

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.flush()

    step_result = await session.execute(
        text("SELECT skipped, skip_reason, completed FROM steps WHERE id = 'step-2'")
    )
    step_row = step_result.fetchone()
    assert step_row is not None
    assert step_row[0] == 1
    assert step_row[1] == "manual_skip"
    assert step_row[2] == 1

    run_result = await session.execute(
        text("SELECT current_step_index FROM runs WHERE id = 'skip-run'")
    )
    run_row = run_result.fetchone()
    assert run_row is not None
    assert run_row[0] == 2


async def test_fan_out_parent_verifying_rebuild_leaves_step_incomplete(
    session: AsyncSession,
) -> None:
    """Fan-out parent VERIFYING replay does not mark its step completed."""
    store = SqliteEventStore(session)
    await store.append(
        [
            RunCreated(
                run_id="fanout-run",
                timestamp=NOW,
                routine_id="routine-1",
                repo_name="fanout-repo",
                status=RunStatus.ACTIVE,
                current_step_index=0,
            ),
            StepCreated(
                run_id="fanout-run",
                timestamp=NOW,
                step_id="fanout-step",
                config_id="S-01",
                title="Fan-out Step",
                order_index=0,
                completed=False,
            ),
            TaskCreated(
                run_id="fanout-run",
                timestamp=NOW,
                task_id="fanout-parent",
                step_id="fanout-step",
                step_index=0,
                config_id="T-01",
                title="Fan-out Parent",
                order_index=0,
                status=TaskStatus.FAN_OUT_RUNNING,
            ),
            TaskStatusChanged(
                run_id="fanout-run",
                timestamp=NOW,
                event_type="task_status_changed",
                task_id="fanout-parent",
                old_status=TaskStatus.FAN_OUT_RUNNING,
                new_status=TaskStatus.VERIFYING,
            ),
            FanOutCompleted(
                run_id="fanout-run",
                timestamp=NOW,
                event_type="fan_out_completed",
                parent_task_id="fanout-parent",
                all_passed=True,
                completed_count=1,
                failed_count=0,
            ),
        ]
    )

    stored = await store.get_all()
    workflow_events = [
        deserialize_event(stored_event.event_type, stored_event.payload) for stored_event in stored
    ]

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.flush()

    step_result = await session.execute(
        text("SELECT completed FROM steps WHERE id = 'fanout-step'")
    )
    step_row = step_result.fetchone()
    assert step_row is not None
    assert step_row[0] == 0

    task_result = await session.execute(text("SELECT status FROM tasks WHERE id = 'fanout-parent'"))
    task_row = task_result.fetchone()
    assert task_row is not None
    assert task_row[0] == "verifying"


async def test_fan_out_parent_failed_rebuild_preserves_pause_reason(
    session: AsyncSession,
) -> None:
    """Failed fan-out replay pauses run with fan_out_child_failed reason."""
    store = SqliteEventStore(session)
    await store.append(
        [
            RunCreated(
                run_id="fanout-failed-run",
                timestamp=NOW,
                routine_id="routine-1",
                repo_name="fanout-repo",
                status=RunStatus.ACTIVE,
                current_step_index=0,
            ),
            StepCreated(
                run_id="fanout-failed-run",
                timestamp=NOW,
                step_id="fanout-failed-step",
                config_id="S-01",
                title="Fan-out Step",
                order_index=0,
                completed=False,
            ),
            TaskCreated(
                run_id="fanout-failed-run",
                timestamp=NOW,
                task_id="fanout-failed-parent",
                step_id="fanout-failed-step",
                step_index=0,
                config_id="T-01",
                title="Fan-out Parent",
                order_index=0,
                status=TaskStatus.FAN_OUT_RUNNING,
            ),
            TaskStatusChanged(
                run_id="fanout-failed-run",
                timestamp=NOW,
                event_type="task_status_changed",
                task_id="fanout-failed-parent",
                old_status=TaskStatus.FAN_OUT_RUNNING,
                new_status=TaskStatus.FAILED,
            ),
            FanOutCompleted(
                run_id="fanout-failed-run",
                timestamp=NOW,
                event_type="fan_out_completed",
                parent_task_id="fanout-failed-parent",
                all_passed=False,
                completed_count=0,
                failed_count=1,
            ),
            StepCompleted(
                run_id="fanout-failed-run",
                timestamp=NOW,
                event_type="step_completed",
                step_id="fanout-failed-step",
                step_index=0,
            ),
            RunStatusChanged(
                run_id="fanout-failed-run",
                timestamp=NOW,
                event_type="run_status_changed",
                old_status=RunStatus.ACTIVE,
                new_status=RunStatus.PAUSED,
                pause_reason="fan_out_child_failed",
            ),
        ]
    )

    workflow_events = [
        deserialize_event(stored_event.event_type, stored_event.payload)
        for stored_event in await store.get_all()
    ]

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.flush()

    run_result = await session.execute(
        text("SELECT status, pause_reason FROM runs WHERE id = 'fanout-failed-run'")
    )
    run_row = run_result.fetchone()
    assert run_row is not None
    assert run_row[0] == "paused"
    assert run_row[1] == "fan_out_child_failed"

    step_result = await session.execute(
        text("SELECT completed FROM steps WHERE id = 'fanout-failed-step'")
    )
    step_row = step_result.fetchone()
    assert step_row is not None
    assert step_row[0] == 1

    task_result = await session.execute(
        text("SELECT status FROM tasks WHERE id = 'fanout-failed-parent'")
    )
    task_row = task_result.fetchone()
    assert task_row is not None
    assert task_row[0] == "failed"


async def test_rebuild_is_idempotent(session: AsyncSession) -> None:
    """Running rebuild twice produces the same final read-model state."""
    session.add(_make_run("run-2", "draft"))
    await session.flush()

    await _store_and_project(session, "run-2", RunStatus.ACTIVE)
    await session.flush()

    read_store = SqliteEventStore(session)
    stored = await read_store.get_all()
    workflow_events = []
    for se in stored:
        try:
            workflow_events.append(deserialize_event(se.event_type, se.payload))
        except ValueError:
            pass

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())

    # First rebuild
    await registry.rebuild_all(workflow_events, session)
    await session.flush()
    result = await session.execute(text("SELECT status FROM runs WHERE id = 'run-2'"))
    status_after_first = result.fetchone()[0]

    # Second rebuild
    await registry.rebuild_all(workflow_events, session)
    await session.flush()
    result = await session.execute(text("SELECT status FROM runs WHERE id = 'run-2'"))
    status_after_second = result.fetchone()[0]

    assert status_after_first == status_after_second == "active"


async def test_rebuild_restores_step_human_approval(session: AsyncSession) -> None:
    """Step approval is reconstructed from events_v2."""
    session.add(_make_run("run-approval", "active"))
    session.add(
        StepModel(id="step-approval", run_id="run-approval", config_id="S-01", order_index=0)
    )
    await session.flush()

    store = SqliteEventStore(session)
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    store.add_projection_listener(registry)

    await store.append(
        StepHumanApprovalRecorded(
            run_id="run-approval",
            step_id="step-approval",
            approved_by="reviewer@example.com",
            approved_at=NOW,
            comment="Approved",
            timestamp=NOW,
        )
    )
    await session.flush()

    await session.execute(text("UPDATE steps SET human_approval = NULL WHERE id = 'step-approval'"))
    await session.flush()

    read_store = SqliteEventStore(session)
    stored = await read_store.get_all()
    workflow_events = []
    for se in stored:
        try:
            workflow_events.append(deserialize_event(se.event_type, se.payload))
        except ValueError:
            pass

    rebuild_registry = ProjectionRegistry()
    rebuild_registry.register(RunStateProjector())
    await rebuild_registry.rebuild_all(workflow_events, session)
    await session.flush()

    result = await session.execute(
        text("SELECT human_approval FROM steps WHERE id = 'step-approval'")
    )
    approval = json.loads(result.scalar_one())
    assert approval == {
        "approved_by": "reviewer@example.com",
        "approved_at": "2025-01-15T10:30:00Z",
        "comment": "Approved",
    }


async def test_rebuild_with_multiple_runs(session: AsyncSession) -> None:
    """Rebuild correctly restores status for multiple runs."""
    session.add(_make_run("run-a", "draft"))
    session.add(_make_run("run-b", "draft"))
    await session.flush()

    # Emit different status events for each run
    store = SqliteEventStore(session)
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    store.add_projection_listener(registry)

    await store.append(
        RunStatusChanged(
            run_id="run-a",
            event_type="run_status_changed",
            new_status=RunStatus.ACTIVE,
            timestamp=NOW,
        )
    )
    await store.append(
        RunStatusChanged(
            run_id="run-b",
            event_type="run_status_changed",
            new_status=RunStatus.PAUSED,
            timestamp=NOW,
        )
    )
    await session.flush()

    # Corrupt both
    await session.execute(text("UPDATE runs SET status = 'corrupted'"))
    await session.flush()

    stored = await store.get_all()
    workflow_events = [
        deserialize_event(se.event_type, se.payload)
        for se in stored
        if se.event_type in ("run_status_changed",)
    ]

    rebuild_registry = ProjectionRegistry()
    rebuild_registry.register(RunStateProjector())
    await rebuild_registry.rebuild_all(workflow_events, session)
    await session.flush()

    result_a = await session.execute(text("SELECT status FROM runs WHERE id = 'run-a'"))
    result_b = await session.execute(text("SELECT status FROM runs WHERE id = 'run-b'"))
    assert result_a.fetchone()[0] == "active"
    assert result_b.fetchone()[0] == "paused"


async def test_rebuild_with_run_deleted_tombstone_keeps_only_surviving_runs(
    session: AsyncSession,
) -> None:
    store = SqliteEventStore(session)
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    store.add_projection_listener(registry)

    await handle_create_run(
        CreateRunCommand(
            run_id="run-delete-a",
            routine_id="routine-1",
            project_path="",
            repo_name="repo-a",
            status=RunStatus.DRAFT,
        ),
        store,
        session,
    )
    await handle_create_run(
        CreateRunCommand(
            run_id="run-keep-b",
            routine_id="routine-1",
            project_path="",
            repo_name="repo-b",
            status=RunStatus.DRAFT,
        ),
        store,
        session,
    )
    await handle_delete_run(
        DeleteRunCommand(run_id="run-delete-a"),
        store,
        session,
    )
    await session.flush()

    deleted_result = await session.execute(text("SELECT id FROM runs WHERE id = 'run-delete-a'"))
    kept_result = await session.execute(text("SELECT id FROM runs WHERE id = 'run-keep-b'"))
    assert deleted_result.fetchone() is None
    assert kept_result.fetchone()[0] == "run-keep-b"

    stored = await store.get_all()
    workflow_events = [deserialize_event(se.event_type, se.payload) for se in stored]

    await session.execute(text("DELETE FROM runs"))
    await session.flush()

    rebuild_registry = ProjectionRegistry()
    rebuild_registry.register(RunStateProjector())
    rebuild_registry.register(TaskStateProjector())
    await rebuild_registry.rebuild_all(workflow_events, session)
    await session.flush()

    deleted_result = await session.execute(text("SELECT id FROM runs WHERE id = 'run-delete-a'"))
    kept_result = await session.execute(text("SELECT id FROM runs WHERE id = 'run-keep-b'"))
    assert deleted_result.fetchone() is None
    assert kept_result.fetchone()[0] == "run-keep-b"


async def test_deserialize_event_roundtrips_run_status_changed(session: AsyncSession) -> None:
    """StoredEvent payloads can be deserialized back to WorkflowEvent objects."""
    session.add(_make_run("run-rt", "draft"))
    await session.flush()

    store = SqliteEventStore(session)
    event = RunStatusChanged(
        run_id="run-rt",
        event_type="run_status_changed",
        new_status=RunStatus.ACTIVE,
        timestamp=NOW,
    )
    await store.append(event)
    await session.flush()

    stored = await store.get_all()
    assert len(stored) == 1

    deserialized = deserialize_event(stored[0].event_type, stored[0].payload)
    assert isinstance(deserialized, RunStatusChanged)
    assert deserialized.run_id == "run-rt"
    assert getattr(deserialized.new_status, "value", deserialized.new_status) == "active"


@pytest.mark.parametrize(
    ("event_type", "event", "expected_cls"),
    [
        (
            "agent_output",
            AgentOutputEvent(
                run_id="run-runtime",
                timestamp=NOW,
                task_id="task-1",
                attempt_num=1,
                lines=["hello"],
            ),
            AgentOutputEvent,
        ),
        (
            "agent_output_event",
            AgentOutputEvent(
                run_id="run-runtime",
                timestamp=NOW,
                task_id="task-1",
                attempt_num=1,
                lines=["hello"],
            ),
            AgentOutputEvent,
        ),
        (
            "agent_error",
            AgentErrorEvent(
                run_id="run-runtime",
                timestamp=NOW,
                task_id="task-1",
                attempt_num=1,
                error_type="AgentExecutionError",
                error_message="failed",
            ),
            AgentErrorEvent,
        ),
        (
            "agent_error_event",
            AgentErrorEvent(
                run_id="run-runtime",
                timestamp=NOW,
                task_id="task-1",
                attempt_num=1,
                error_type="AgentExecutionError",
                error_message="failed",
            ),
            AgentErrorEvent,
        ),
        (
            "health_check",
            HealthCheckEvent(
                run_id="run-runtime",
                timestamp=NOW,
                phase="completed",
                message="ok",
            ),
            HealthCheckEvent,
        ),
        (
            "health_check_event",
            HealthCheckEvent(
                run_id="run-runtime",
                timestamp=NOW,
                phase="completed",
                message="ok",
            ),
            HealthCheckEvent,
        ),
    ],
)
async def test_deserialize_event_accepts_runtime_canonical_and_legacy_aliases(
    event_type: str,
    event: AgentOutputEvent | AgentErrorEvent | HealthCheckEvent,
    expected_cls: type[AgentOutputEvent] | type[AgentErrorEvent] | type[HealthCheckEvent],
) -> None:
    deserialized = deserialize_event(event_type, event.model_dump_json())
    assert isinstance(deserialized, expected_cls)


async def test_projection_rebuild_accepts_runtime_events(session: AsyncSession) -> None:
    session.add(_make_run("run-runtime", "draft"))
    await session.flush()

    store = SqliteEventStore(session)
    await store.append(
        [
            AgentOutputEvent(
                run_id="run-runtime",
                timestamp=NOW,
                task_id="task-1",
                attempt_num=1,
                lines=["line"],
            ),
            AgentErrorEvent(
                run_id="run-runtime",
                timestamp=NOW,
                task_id="task-1",
                attempt_num=1,
                error_type="AgentExecutionError",
                error_message="failed",
            ),
            HealthCheckEvent(
                run_id="run-runtime",
                timestamp=NOW,
                phase="completed",
                message="ok",
            ),
        ]
    )
    await session.flush()

    stored = await store.get_all()
    assert [event.event_type for event in stored] == [
        "agent_output",
        "agent_error",
        "health_check",
    ]
    workflow_events = [deserialize_event(se.event_type, se.payload) for se in stored]

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)


async def test_rebuild_projects_agent_changed_event(session: AsyncSession) -> None:
    session.add(_make_run("run-agent", "active"))
    await session.flush()

    store = SqliteEventStore(session)
    await store.append(
        AgentChangedEvent(
            run_id="run-agent",
            timestamp=NOW,
            old_agent=AgentRunnerType.CLI_SUBPROCESS,
            new_agent=AgentRunnerType.CLAUDE_SDK,
            old_agent_runner_config={"model": "gpt-5.3-codex"},
            new_agent_runner_config={"model": "claude-sonnet-4-6"},
        )
    )
    await session.flush()

    await session.execute(
        text(
            "UPDATE runs SET runner_type = 'cli_subprocess', runner_config = '{}'"
            " WHERE id = 'run-agent'"
        )
    )
    await session.flush()

    stored = await store.get_all()
    workflow_events = [deserialize_event(se.event_type, se.payload) for se in stored]

    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.flush()

    result = await session.execute(
        text("SELECT runner_type, runner_config FROM runs WHERE id = 'run-agent'")
    )
    row = result.fetchone()
    assert row is not None
    assert row[0] == "claude_sdk"
    assert json.loads(row[1]) == {"model": "claude-sonnet-4-6"}


async def test_deserialize_event_accepts_agent_changed_aliases(session: AsyncSession) -> None:
    event = AgentChangedEvent(
        run_id="run-agent-alias",
        timestamp=NOW,
        old_agent=AgentRunnerType.CLI_SUBPROCESS,
        new_agent=AgentRunnerType.CLAUDE_SDK,
        new_agent_runner_config={"model": "claude-sonnet-4-6"},
    )
    payload = event.model_dump_json()

    current = deserialize_event("agent_changed", payload)
    legacy = deserialize_event("agent_changed_event", payload)

    assert isinstance(current, AgentChangedEvent)
    assert isinstance(legacy, AgentChangedEvent)
    assert current.event_type == "agent_changed"
    assert legacy.event_type == "agent_changed"
