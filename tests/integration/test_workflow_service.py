"""Integration tests for WorkflowService."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import (
    AgentRunnerType,
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
    load_routine_from_path,
)
from orchestrator.db import (
    create_engine,
    create_session_factory,
    create_wired_event_store_v2,
    init_db,
)
from orchestrator.db import (
    ProjectionRegistry,
    RunStateProjector,
    SqliteEventStore,
    TaskStateProjector,
)
from orchestrator.state.errors import (
    ChecklistItemNotFoundError,
    RunNotFoundError,
    TaskNotFoundError,
)
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.service import WorkflowService
from orchestrator.workflow import (
    InvalidTransitionError,
    UpdateLatestAttemptCommand,
    deserialize_event,
    handle_update_latest_attempt,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def service(session: AsyncSession) -> WorkflowService:
    return WorkflowService(session)


def _make_simple_run() -> Run:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.DRAFT,
        routine_id="simple-routine",
        routine_source=RoutineSource.LOCAL,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.PENDING,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Complete the task",
                                priority=Priority.CRITICAL,
                            )
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


def _embedded_simple_routine() -> dict[str, object]:
    return {
        "id": "simple-routine",
        "name": "Simple Routine",
        "steps": [
            {
                "id": "S-01",
                "title": "Only Step",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Only Task",
                        "task_context": "Do something simple",
                        "requirements": [
                            {
                                "id": "R1",
                                "desc": "Complete the task",
                            }
                        ],
                    }
                ],
            }
        ],
    }


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


async def test_full_lifecycle(service: WorkflowService) -> None:
    """Full lifecycle: create -> start run -> start task -> submit -> verify -> complete."""
    run = _make_simple_run()
    await service.create_run(run)

    # Start run
    started = await service.apply_start_run("run-1")
    assert started.status == RunStatus.ACTIVE

    # Start task
    result = await service.start_task("run-1", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING

    # Update checklist to pass gate
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)

    # Submit for verification
    result = await service.submit_for_verification("run-1", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.VERIFYING

    # Set grade
    item = await service.set_grade("run-1", "task-1", "R1", "A")
    assert item.grade == "A"

    # Complete verification
    result = await service.complete_verification("run-1", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED


async def test_state_survives_restart(session: AsyncSession) -> None:
    """State persists across service instances (simulated restart)."""
    service1 = WorkflowService(session)

    run = _make_simple_run()
    await service1.create_run(run)
    await service1.apply_start_run("run-1")

    # Simulate restart by creating a new service with same session
    service2 = WorkflowService(session)
    loaded = await service2.get_run("run-1")
    assert loaded.status == RunStatus.ACTIVE
    assert loaded.started_at is not None


async def test_events_logged(service: WorkflowService, session: AsyncSession) -> None:
    """Events are persisted to the event store."""
    run = _make_simple_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    store = SqliteEventStore(session)
    events = await store.get_stream("run-1")
    assert len(events) >= 2
    event_types = [e.event_type for e in events]
    assert "run_status_changed" in event_types
    assert "task_status_changed" in event_types


async def test_start_task_projects_attempt_without_save_run(
    service: WorkflowService, session: AsyncSession
) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")

    result = await service.start_task("run-1", "task-1")

    assert result.success is True
    task = await service.get_task("run-1", "task-1")
    assert task.status == TaskStatus.BUILDING
    assert task.current_attempt == 1
    assert len(task.attempts) == 1
    assert task.attempts[0].attempt_num == 1
    assert task.attempts[0].started_at is not None

    events = await SqliteEventStore(session).get_stream("run-1")
    status_events = [event for event in events if event.event_type == "task_status_changed"]
    assert len(status_events) == 1
    payload = json.loads(status_events[0].payload)
    assert payload["new_status"] == "building"
    assert payload["current_attempt"] == 1
    assert [attempt["attempt_num"] for attempt in payload["attempt_snapshots"]] == [1]


async def test_submit_projects_verifying_without_save_run(
    service: WorkflowService, session: AsyncSession
) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)

    result = await service.submit_for_verification("run-1", "task-1")

    assert result.success is True
    task = await service.get_task("run-1", "task-1")
    assert task.status == TaskStatus.VERIFYING
    assert task.current_attempt == 1
    assert len(task.attempts) == 1

    events = await SqliteEventStore(session).get_stream("run-1")
    verifying_events = [
        json.loads(event.payload)
        for event in events
        if event.event_type == "task_status_changed"
        and json.loads(event.payload)["new_status"] == "verifying"
    ]
    assert len(verifying_events) == 1
    assert verifying_events[0]["current_attempt"] == 1


async def test_complete_verification_projects_pass_without_save_run(
    service: WorkflowService, session: AsyncSession
) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "A", "complete")

    result = await service.complete_verification("run-1", "task-1")

    assert result.success is True
    task = await service.get_task("run-1", "task-1")
    assert task.status == TaskStatus.COMPLETED
    assert task.attempts[0].outcome == "passed"
    assert task.attempts[0].completed_at is not None
    assert task.attempts[0].grade_snapshot[0].grade == "A"

    events = await SqliteEventStore(session).get_stream("run-1")
    completed_events = [
        json.loads(event.payload)
        for event in events
        if event.event_type == "task_status_changed"
        and json.loads(event.payload)["new_status"] == "completed"
    ]
    assert len(completed_events) == 1
    assert completed_events[0]["attempt_snapshots"][0]["outcome"] == "passed"


async def test_complete_verification_projects_revision_without_save_run(
    service: WorkflowService, session: AsyncSession
) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "D", "Needs work")

    result = await service.complete_verification("run-1", "task-1")

    assert result.success is True
    task = await service.get_task("run-1", "task-1")
    assert task.status == TaskStatus.BUILDING
    assert task.current_attempt == 2
    assert len(task.attempts) == 2
    assert task.attempts[0].outcome == "revision_needed"
    assert task.attempts[0].completed_at is not None
    assert task.attempts[1].started_at is not None

    events = await SqliteEventStore(session).get_stream("run-1")
    building_events = [
        json.loads(event.payload)
        for event in events
        if event.event_type == "task_status_changed"
        and json.loads(event.payload)["new_status"] == "building"
    ]
    assert len(building_events) == 2
    assert building_events[-1]["current_attempt"] == 2
    assert [attempt["attempt_num"] for attempt in building_events[-1]["attempt_snapshots"]] == [
        1,
        2,
    ]


async def test_attempt_replay_preserves_explicit_attempt_update_fields(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "tester@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "work.txt").write_text("initial\n")
    _git(repo, "add", "work.txt")
    _git(repo, "commit", "-m", "initial")
    start_commit = _git(repo, "rev-parse", "HEAD")

    service = WorkflowService(session)
    run = _make_simple_run()
    run.worktree_path = str(repo)
    run.agent_runner_type = AgentRunnerType.CLI_SUBPROCESS
    run.agent_runner_config = {
        "model": "gpt-5.3-codex",
        "temperature": 0.2,
        "api_key": "secret",
    }
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    task = await service.get_task("run-1", "task-1")
    attempt_id = task.attempts[0].id
    await handle_update_latest_attempt(
        UpdateLatestAttemptCommand(
            run_id="run-1",
            task_id="task-1",
            attempt_id=attempt_id,
            builder_prompt="builder prompt text",
            verifier_prompt="verifier prompt text",
        ),
        create_wired_event_store_v2(session),
        session,
    )
    await session.commit()

    (repo / "work.txt").write_text("builder changes\n")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    end_commit = _git(repo, "rev-parse", "HEAD")
    assert end_commit != start_commit

    await service.set_grade("run-1", "task-1", "R1", "D", "Needs more proof")
    await service.complete_verification("run-1", "task-1")

    live_task = await service.get_task("run-1", "task-1")
    live_attempt = live_task.attempts[0]
    live_grade_snapshot = [item.model_dump(mode="json") for item in live_attempt.grade_snapshot]
    assert live_attempt.builder_prompt == "builder prompt text"
    assert live_attempt.verifier_prompt == "verifier prompt text"
    assert live_attempt.verifier_comment is not None
    assert live_attempt.grade_snapshot[0].grade == "D"
    assert live_attempt.agent_runner_type == AgentRunnerType.CLI_SUBPROCESS
    assert live_attempt.agent_model == "gpt-5.3-codex"
    assert live_attempt.agent_settings == {
        "model": "gpt-5.3-codex",
        "temperature": 0.2,
    }
    assert live_attempt.start_commit == start_commit
    assert live_attempt.end_commit == end_commit

    stored_events = await SqliteEventStore(session).get_stream("run-1")
    attempt_updates = [
        json.loads(event.payload)
        for event in stored_events
        if event.event_type == "attempt_updated"
    ]
    assert any(
        payload.get("agent_settings") == live_attempt.agent_settings
        and payload.get("start_commit") == start_commit
        for payload in attempt_updates
    )
    assert any(payload.get("end_commit") == end_commit for payload in attempt_updates)
    assert any(
        payload.get("grade_snapshot") == live_grade_snapshot
        and payload.get("verifier_comment") == live_attempt.verifier_comment
        for payload in attempt_updates
    )

    await session.execute(text("DELETE FROM attempts"))
    await session.execute(text("DELETE FROM tasks"))
    await session.execute(text("DELETE FROM steps"))
    await session.execute(text("DELETE FROM runs"))
    await session.commit()

    workflow_events = [
        deserialize_event(event.event_type, event.payload) for event in stored_events
    ]
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.commit()

    replayed_task = await service.get_task("run-1", "task-1")
    replayed_attempt = replayed_task.attempts[0]
    assert replayed_attempt.builder_prompt == live_attempt.builder_prompt
    assert replayed_attempt.verifier_prompt == live_attempt.verifier_prompt
    assert replayed_attempt.verifier_comment == live_attempt.verifier_comment
    assert [item.model_dump(mode="json") for item in replayed_attempt.grade_snapshot] == (
        live_grade_snapshot
    )
    assert replayed_attempt.agent_runner_type == live_attempt.agent_runner_type
    assert replayed_attempt.agent_model == live_attempt.agent_model
    assert replayed_attempt.agent_settings == live_attempt.agent_settings
    assert replayed_attempt.start_commit == live_attempt.start_commit
    assert replayed_attempt.end_commit == live_attempt.end_commit


async def test_trigger_recovery_projects_pause_and_attempt_snapshot_without_save_run(
    service: WorkflowService,
    session: AsyncSession,
) -> None:
    run = _make_simple_run()
    run.routine_embedded = _embedded_simple_routine()
    failure_context = "validator crashed after exhausting retries"
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")

    await service.trigger_recovery("run-1", "task-1", failure_context)

    live_run = await service.get_run("run-1")
    live_task = await service.get_task("run-1", "task-1")
    assert live_run.status == RunStatus.PAUSED
    assert live_run.pause_reason == "recovery_triggered"
    assert live_task.status == TaskStatus.RECOVERING
    assert live_task.current_attempt == 1
    assert live_task.attempts[-1].verifier_comment == failure_context
    assert live_task.attempts[-1].builder_prompt is not None
    assert live_task.attempts[-1].builder_prompt.startswith("[RECOVERY PROMPT]")
    assert failure_context in live_task.attempts[-1].builder_prompt

    stored_events = await SqliteEventStore(session).get_stream("run-1")
    recovery_events = [
        json.loads(event.payload)
        for event in stored_events
        if event.event_type == "task_status_changed"
        and json.loads(event.payload)["new_status"] == "recovering"
    ]
    assert len(recovery_events) == 1
    assert recovery_events[0]["current_attempt"] == 1
    assert recovery_events[0]["attempt_snapshots"][-1]["verifier_comment"] == failure_context
    assert recovery_events[0]["attempt_snapshots"][-1]["builder_prompt"].startswith(
        "[RECOVERY PROMPT]"
    )
    pause_events = [
        json.loads(event.payload)
        for event in stored_events
        if event.event_type == "run_status_changed"
        and json.loads(event.payload)["new_status"] == "paused"
    ]
    assert pause_events[-1]["pause_reason"] == "recovery_triggered"

    await session.execute(text("DELETE FROM attempts"))
    await session.execute(text("DELETE FROM tasks"))
    await session.execute(text("DELETE FROM steps"))
    await session.execute(text("DELETE FROM runs"))
    await session.commit()

    workflow_events = [
        deserialize_event(event.event_type, event.payload) for event in stored_events
    ]
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.commit()

    replayed_run = await service.get_run("run-1")
    replayed_task = await service.get_task("run-1", "task-1")
    assert replayed_run.status == RunStatus.PAUSED
    assert replayed_run.pause_reason == "recovery_triggered"
    assert replayed_task.status == TaskStatus.RECOVERING
    assert replayed_task.current_attempt == 1
    assert replayed_task.attempts[-1].verifier_comment == failure_context
    assert replayed_task.attempts[-1].builder_prompt == live_task.attempts[-1].builder_prompt


async def test_trigger_recovery_does_not_emit_run_status_when_already_paused(
    service: WorkflowService,
    session: AsyncSession,
) -> None:
    run = _make_simple_run()
    run.routine_embedded = _embedded_simple_routine()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.apply_pause_run("run-1", reason="manual_pause")
    events_before = await SqliteEventStore(session).get_stream("run-1")
    run_status_count_before = sum(
        1 for event in events_before if event.event_type == "run_status_changed"
    )

    await service.trigger_recovery("run-1", "task-1", "crash while paused")

    paused_run = await service.get_run("run-1")
    assert paused_run.status == RunStatus.PAUSED
    assert paused_run.pause_reason == "manual_pause"
    recovering_task = await service.get_task("run-1", "task-1")
    assert recovering_task.status == TaskStatus.RECOVERING
    events_after = await SqliteEventStore(session).get_stream("run-1")
    run_status_count_after = sum(
        1 for event in events_after if event.event_type == "run_status_changed"
    )
    assert run_status_count_after == run_status_count_before


async def test_complete_recovery_retry_projects_attempts_and_resumes_without_save_run(
    service: WorkflowService,
    session: AsyncSession,
) -> None:
    run = _make_simple_run()
    run.routine_embedded = _embedded_simple_routine()
    run.agent_runner_type = AgentRunnerType.CLI_SUBPROCESS
    run.agent_runner_config = {
        "model": "gpt-5.3-codex",
        "temperature": 0.2,
        "api_key": "secret",
    }
    failure_context = "validator crashed before retry"
    recovery_notes = "Configuration repaired; retry the task."
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await session.execute(
        text("UPDATE attempts SET end_commit = 'prev-end' WHERE task_id = 'task-1'")
    )
    await session.commit()
    await service.trigger_recovery("run-1", "task-1", failure_context)

    result = await service.complete_recovery_retry("run-1", "task-1", recovery_notes)

    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING
    live_run = await service.get_run("run-1")
    live_task = await service.get_task("run-1", "task-1")
    assert live_run.status == RunStatus.ACTIVE
    assert live_run.pause_reason is None
    assert live_run.last_error is None
    assert live_task.status == TaskStatus.BUILDING
    assert live_task.current_attempt == 2
    assert [attempt.attempt_num for attempt in live_task.attempts] == [1, 2]
    assert live_task.attempts[0].verifier_comment == recovery_notes
    assert live_task.attempts[0].end_commit == "prev-end"
    assert live_task.attempts[1].agent_runner_type == AgentRunnerType.CLI_SUBPROCESS
    assert live_task.attempts[1].agent_model == "gpt-5.3-codex"
    assert live_task.attempts[1].agent_settings == {
        "model": "gpt-5.3-codex",
        "temperature": 0.2,
    }
    assert live_task.attempts[1].start_commit == "prev-end"

    stored_events = await SqliteEventStore(session).get_stream("run-1")
    retry_events = [
        json.loads(event.payload)
        for event in stored_events
        if event.event_type == "task_status_changed"
        and json.loads(event.payload)["new_status"] == "building"
        and len(json.loads(event.payload)["attempt_snapshots"]) == 2
    ]
    assert len(retry_events) == 1
    retry_payload = retry_events[0]
    assert retry_payload["current_attempt"] == 2
    assert retry_payload["attempt_snapshots"][0]["verifier_comment"] == recovery_notes
    assert retry_payload["attempt_snapshots"][1]["agent_runner_type"] == "cli_subprocess"
    assert retry_payload["attempt_snapshots"][1]["agent_model"] == "gpt-5.3-codex"
    assert retry_payload["attempt_snapshots"][1]["agent_settings"] == {
        "model": "gpt-5.3-codex",
        "temperature": 0.2,
    }
    assert retry_payload["attempt_snapshots"][1]["start_commit"] == "prev-end"
    active_events = [
        json.loads(event.payload)
        for event in stored_events
        if event.event_type == "run_status_changed"
        and json.loads(event.payload)["new_status"] == "active"
    ]
    assert active_events[-1]["old_status"] == "paused"
    assert active_events[-1]["pause_reason"] is None
    assert active_events[-1]["last_error"] is None

    await session.execute(text("DELETE FROM attempts"))
    await session.execute(text("DELETE FROM tasks"))
    await session.execute(text("DELETE FROM steps"))
    await session.execute(text("DELETE FROM runs"))
    await session.commit()

    workflow_events = [
        deserialize_event(event.event_type, event.payload) for event in stored_events
    ]
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.commit()

    replayed_run = await service.get_run("run-1")
    replayed_task = await service.get_task("run-1", "task-1")
    assert replayed_run.status == RunStatus.ACTIVE
    assert replayed_run.pause_reason is None
    assert replayed_run.last_error is None
    assert replayed_task.status == TaskStatus.BUILDING
    assert replayed_task.current_attempt == 2
    assert [attempt.attempt_num for attempt in replayed_task.attempts] == [1, 2]
    assert replayed_task.attempts[0].verifier_comment == recovery_notes
    assert replayed_task.attempts[0].end_commit == "prev-end"
    assert replayed_task.attempts[1].agent_runner_type == AgentRunnerType.CLI_SUBPROCESS
    assert replayed_task.attempts[1].agent_model == "gpt-5.3-codex"
    assert replayed_task.attempts[1].agent_settings == {
        "model": "gpt-5.3-codex",
        "temperature": 0.2,
    }
    assert replayed_task.attempts[1].start_commit == "prev-end"


async def test_complete_recovery_skip_projects_attempt_step_and_run_without_save_run(
    session: AsyncSession,
) -> None:
    completed_at = datetime(2025, 1, 15, 13, 30, 0, tzinfo=timezone.utc)
    service = WorkflowService(session, clock=_FixedClock(completed_at))
    run = _make_simple_run()
    run.routine_embedded = _embedded_simple_routine()
    failure_context = "validator crashed before skip"
    recovery_notes = "Task is non-critical; skip it."
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.trigger_recovery("run-1", "task-1", failure_context)

    result = await service.complete_recovery_skip("run-1", "task-1", recovery_notes)

    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED
    live_run = await service.get_run("run-1")
    live_task = await service.get_task("run-1", "task-1")
    assert live_run.status == RunStatus.COMPLETED
    assert live_run.pause_reason is None
    assert live_run.last_error is None
    assert live_run.current_step_index == 1
    assert live_run.steps[0].completed is True
    assert live_task.status == TaskStatus.COMPLETED
    assert live_task.current_attempt == 1
    assert live_task.attempts[-1].outcome == "skipped"
    assert live_task.attempts[-1].verifier_comment == recovery_notes
    assert live_task.attempts[-1].completed_at == completed_at

    stored_events = await SqliteEventStore(session).get_stream("run-1")
    skip_events = [
        json.loads(event.payload)
        for event in stored_events
        if event.event_type == "task_status_changed"
        and json.loads(event.payload)["new_status"] == "completed"
    ]
    assert len(skip_events) == 1
    skip_payload = skip_events[0]
    assert skip_payload["old_status"] == "recovering"
    assert skip_payload["current_attempt"] == 1
    assert skip_payload["attempt_snapshots"][-1]["outcome"] == "skipped"
    assert skip_payload["attempt_snapshots"][-1]["verifier_comment"] == recovery_notes
    assert skip_payload["attempt_snapshots"][-1]["completed_at"] == "2025-01-15T13:30:00Z"
    event_types = [event.event_type for event in stored_events]
    assert event_types.count("step_completed") == 1
    run_status_payloads = [
        json.loads(event.payload)
        for event in stored_events
        if event.event_type == "run_status_changed"
    ]
    assert any(
        payload["old_status"] == "paused"
        and payload["new_status"] == "active"
        and payload["pause_reason"] is None
        for payload in run_status_payloads
    )
    assert run_status_payloads[-1]["new_status"] == "completed"

    await session.execute(text("DELETE FROM attempts"))
    await session.execute(text("DELETE FROM tasks"))
    await session.execute(text("DELETE FROM steps"))
    await session.execute(text("DELETE FROM runs"))
    await session.commit()

    workflow_events = [
        deserialize_event(event.event_type, event.payload) for event in stored_events
    ]
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.commit()

    replayed_run = await service.get_run("run-1")
    replayed_task = await service.get_task("run-1", "task-1")
    assert replayed_run.status == RunStatus.COMPLETED
    assert replayed_run.pause_reason is None
    assert replayed_run.last_error is None
    assert replayed_run.current_step_index == 1
    assert replayed_run.steps[0].completed is True
    assert replayed_task.status == TaskStatus.COMPLETED
    assert replayed_task.current_attempt == 1
    assert replayed_task.attempts[-1].outcome == "skipped"
    assert replayed_task.attempts[-1].verifier_comment == recovery_notes
    assert replayed_task.attempts[-1].completed_at == completed_at


async def test_complete_recovery_abandon_projects_failed_attempt_without_save_run(
    session: AsyncSession,
) -> None:
    completed_at = datetime(2025, 1, 15, 12, 45, 0, tzinfo=timezone.utc)
    service = WorkflowService(session, clock=_FixedClock(completed_at))
    run = _make_simple_run()
    run.routine_embedded = _embedded_simple_routine()
    failure_context = "validator crashed before abandon"
    recovery_notes = "Cannot recover safely; abandon the task."
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.trigger_recovery("run-1", "task-1", failure_context)

    result = await service.complete_recovery_abandon("run-1", "task-1", recovery_notes)

    assert result.success is True
    assert result.new_status == TaskStatus.FAILED
    live_task = await service.get_task("run-1", "task-1")
    assert live_task.status == TaskStatus.FAILED
    assert live_task.current_attempt == 1
    assert live_task.attempts[-1].outcome == "failed"
    assert live_task.attempts[-1].verifier_comment == recovery_notes
    assert live_task.attempts[-1].completed_at == completed_at

    stored_events = await SqliteEventStore(session).get_stream("run-1")
    abandon_events = [
        json.loads(event.payload)
        for event in stored_events
        if event.event_type == "task_status_changed"
        and json.loads(event.payload)["new_status"] == "failed"
    ]
    assert len(abandon_events) == 1
    abandon_payload = abandon_events[0]
    assert abandon_payload["old_status"] == "recovering"
    assert abandon_payload["current_attempt"] == 1
    assert abandon_payload["attempt_snapshots"][-1]["outcome"] == "failed"
    assert abandon_payload["attempt_snapshots"][-1]["verifier_comment"] == recovery_notes
    assert abandon_payload["attempt_snapshots"][-1]["completed_at"] == "2025-01-15T12:45:00Z"

    await session.execute(text("DELETE FROM attempts"))
    await session.execute(text("DELETE FROM tasks"))
    await session.execute(text("DELETE FROM steps"))
    await session.execute(text("DELETE FROM runs"))
    await session.commit()

    workflow_events = [
        deserialize_event(event.event_type, event.payload) for event in stored_events
    ]
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.commit()

    replayed_task = await service.get_task("run-1", "task-1")
    assert replayed_task.status == TaskStatus.FAILED
    assert replayed_task.current_attempt == 1
    assert replayed_task.attempts[-1].outcome == "failed"
    assert replayed_task.attempts[-1].verifier_comment == recovery_notes
    assert replayed_task.attempts[-1].completed_at == completed_at


async def test_core_lifecycle_replays_from_events_v2(
    service: WorkflowService, session: AsyncSession
) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "A", "complete")
    await service.complete_verification("run-1", "task-1")

    await session.execute(text("DELETE FROM attempts"))
    await session.execute(text("DELETE FROM tasks"))
    await session.execute(text("DELETE FROM steps"))
    await session.execute(text("DELETE FROM runs"))
    await session.commit()

    stored_events = await SqliteEventStore(session).get_stream("run-1")
    workflow_events = [
        deserialize_event(event.event_type, event.payload) for event in stored_events
    ]
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.commit()

    replayed = await service.get_task("run-1", "task-1")
    assert replayed.status == TaskStatus.COMPLETED
    assert replayed.checklist[0].status == ChecklistStatus.DONE
    assert replayed.checklist[0].grade == "A"
    assert replayed.current_attempt == 1
    assert len(replayed.attempts) == 1
    assert replayed.attempts[0].outcome == "passed"


async def test_set_worktree_path_updates_projection_and_events_v2(
    service: WorkflowService, session: AsyncSession, tmp_path: Path
) -> None:
    run = _make_simple_run()
    await service.create_run(run)

    worktree_path = str(tmp_path / "run-1")
    updated = await service.set_worktree_path("run-1", worktree_path, "abc123")

    assert updated.worktree_path == worktree_path
    assert updated.source_branch_sha == "abc123"
    reloaded = await service.get_run("run-1")
    assert reloaded.worktree_path == worktree_path
    assert reloaded.source_branch_sha == "abc123"

    events = await SqliteEventStore(session).get_stream("run-1")
    worktree_events = [event for event in events if event.event_type == "run_worktree_updated"]
    assert len(worktree_events) == 1
    payload = json.loads(worktree_events[0].payload)
    assert payload["worktree_path"] == worktree_path
    assert payload["source_branch_sha"] == "abc123"


async def test_error_propagation(service: WorkflowService) -> None:
    """Domain errors propagate correctly."""
    with pytest.raises(RunNotFoundError):
        await service.get_run("nonexistent")

    with pytest.raises(RunNotFoundError):
        await service.apply_start_run("nonexistent")


async def test_task_not_found(service: WorkflowService) -> None:
    run = _make_simple_run()
    await service.create_run(run)

    with pytest.raises(TaskNotFoundError):
        await service.get_task("run-1", "nonexistent-task")


async def test_checklist_item_not_found(service: WorkflowService) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    with pytest.raises(ChecklistItemNotFoundError):
        await service.update_checklist_item(
            "run-1", "task-1", "nonexistent-req", ChecklistStatus.DONE
        )


async def test_update_checklist_item_updates_projection_and_events_v2(
    service: WorkflowService, session: AsyncSession
) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    item = await service.update_checklist_item(
        "run-1", "task-1", "R1", ChecklistStatus.DONE, "implemented"
    )

    assert item.req_id == "R1"
    assert item.status == ChecklistStatus.DONE
    assert item.note == "implemented"
    reloaded = await service.get_task("run-1", "task-1")
    assert reloaded.checklist[0].status == ChecklistStatus.DONE
    assert reloaded.checklist[0].note == "implemented"

    events = await SqliteEventStore(session).get_stream("run-1")
    checklist_events = [event for event in events if event.event_type == "checklist_item_updated"]
    assert len(checklist_events) == 1
    payload = json.loads(checklist_events[0].payload)
    assert payload["task_id"] == "task-1"
    assert payload["req_id"] == "R1"
    assert payload["status"] == "done"
    assert payload["note"] == "implemented"


async def test_set_grade_not_found(service: WorkflowService) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")

    with pytest.raises(ChecklistItemNotFoundError):
        await service.set_grade("run-1", "task-1", "nonexistent-req", "A")


async def test_set_grade_updates_projection_and_events_v2(
    service: WorkflowService, session: AsyncSession
) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")

    item = await service.set_grade("run-1", "task-1", "R1", "A", "complete")

    assert item.req_id == "R1"
    assert item.grade == "A"
    assert item.grade_reason == "complete"
    reloaded = await service.get_task("run-1", "task-1")
    assert reloaded.checklist[0].grade == "A"
    assert reloaded.checklist[0].grade_reason == "complete"

    events = await SqliteEventStore(session).get_stream("run-1")
    grade_events = [event for event in events if event.event_type == "checklist_item_graded"]
    assert len(grade_events) == 1
    payload = json.loads(grade_events[0].payload)
    assert payload["task_id"] == "task-1"
    assert payload["req_id"] == "R1"
    assert payload["grade"] == "A"
    assert payload["grade_reason"] == "complete"


async def test_flexible_numeric_req_id_formats(service: WorkflowService) -> None:
    """Numeric checklist IDs should accept R1/R-01/1 style inputs."""
    run = _make_simple_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    # Update using dashed format resolves to canonical checklist item R1.
    item = await service.update_checklist_item("run-1", "task-1", "R-01", ChecklistStatus.DONE)
    assert item.req_id == "R1"
    assert item.status == ChecklistStatus.DONE

    await service.submit_for_verification("run-1", "task-1")

    # Grade using numeric-only format resolves to the same item.
    graded = await service.set_grade("run-1", "task-1", "1", "A", "Flexible ID mapping works")
    assert graded.req_id == "R1"
    assert graded.grade == "A"


async def test_multi_step_routine(service: WorkflowService) -> None:
    """Test with a multi-step routine created from YAML."""
    routine = load_routine_from_path(FIXTURES / "valid_complete.yaml")
    run = create_run_from_routine(
        routine=routine,
        repo_name="proj-1",
        source_branch="main",
        config={"feature_name": "auth"},
        routine_source=RoutineSource.LOCAL,
    )

    created = await service.create_run(run)
    assert len(created.steps) == 2
    assert len(created.steps[0].tasks) == 1
    assert len(created.steps[1].tasks) == 2

    await service.apply_start_run(created.id)
    task_id = created.steps[0].tasks[0].id

    result = await service.start_task(created.id, task_id)
    assert result.success is True

    task = await service.get_task(created.id, task_id)
    assert task.status == TaskStatus.BUILDING


async def test_list_runs(service: WorkflowService) -> None:
    run = _make_simple_run()
    await service.create_run(run)

    runs = await service.list_runs()
    assert len(runs) == 1
    assert runs[0].id == "run-1"


async def test_list_runs_by_repo(service: WorkflowService) -> None:
    run = _make_simple_run()
    await service.create_run(run)

    runs = await service.list_runs_by_repo("proj-1")
    assert len(runs) == 1

    runs = await service.list_runs_by_repo("other-project")
    assert len(runs) == 0


async def test_delete_run(service: WorkflowService, session: AsyncSession) -> None:
    run = _make_simple_run()
    await service.create_run(run)
    await service.delete_run("run-1")

    with pytest.raises(RunNotFoundError):
        await service.get_run("run-1")

    store = SqliteEventStore(session)
    events = await store.get_stream("run-1")
    deleted_events = [event for event in events if event.event_type == "run_deleted"]
    assert len(deleted_events) == 1


async def test_delete_run_not_found(service: WorkflowService) -> None:
    with pytest.raises(RunNotFoundError):
        await service.delete_run("missing-run")


async def test_revision_cycle(service: WorkflowService) -> None:
    """Test revision: fail grades -> go back to BUILDING -> fix -> pass."""
    run = _make_simple_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    # Pass checklist gate
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")

    # Set failing grade
    await service.set_grade("run-1", "task-1", "R1", "D", "Needs improvement")

    # Complete verification -> should trigger revision
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.BUILDING  # Revision

    task = await service.get_task("run-1", "task-1")
    assert task.current_attempt == 2

    # Fix grade and retry
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")
    await service.set_grade("run-1", "task-1", "R1", "A")
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.COMPLETED


def _make_failed_run_with_downstream() -> Run:
    now = datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc)
    return Run(
        id="run-recover-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.FAILED,
        routine_id="recover-routine",
        routine_source=RoutineSource.LOCAL,
        current_step_index=0,
        completed_at=now,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                completed=True,
                tasks=[
                    TaskState(
                        id="task-1",
                        config_id="T-01",
                        status=TaskStatus.FAILED,
                        current_attempt=2,
                        max_attempts=2,
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Target task requirement",
                                priority=Priority.CRITICAL,
                                status=ChecklistStatus.DONE,
                            )
                        ],
                    ),
                    TaskState(
                        id="task-2",
                        config_id="T-02",
                        status=TaskStatus.COMPLETED,
                        current_attempt=1,
                        max_attempts=2,
                        checklist=[
                            ChecklistItem(
                                req_id="R2",
                                desc="Downstream requirement",
                                priority=Priority.EXPECTED,
                                status=ChecklistStatus.DONE,
                                note="kept note",
                            )
                        ],
                    ),
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


async def _rebuild_run_from_events(
    session: AsyncSession,
    service: WorkflowService,
    run_id: str,
) -> Run:
    stored_events = await SqliteEventStore(session).get_stream(run_id)
    await session.execute(text("DELETE FROM attempts"))
    await session.execute(text("DELETE FROM tasks"))
    await session.execute(text("DELETE FROM steps"))
    await session.execute(text("DELETE FROM runs"))
    await session.commit()

    workflow_events = [
        deserialize_event(event.event_type, event.payload) for event in stored_events
    ]
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    await registry.rebuild_all(workflow_events, session)
    await session.commit()
    return await service.get_run(run_id)


@pytest.mark.parametrize("status", [RunStatus.ACTIVE, RunStatus.COMPLETED])
async def test_recover_run_rejects_non_recoverable_statuses(
    service: WorkflowService, status: RunStatus
) -> None:
    """recover_run only accepts FAILED and PAUSED runs; ACTIVE and COMPLETED are rejected."""
    run = _make_simple_run()
    run.id = f"run-non-recoverable-{status.value}"
    run.status = status
    await service.create_run(run)

    with pytest.raises(InvalidTransitionError):
        await service.recover_run(run.id, "task-1")


async def test_recover_run_accepts_paused_run(service: WorkflowService) -> None:
    """A PAUSED run can be recovered — e.g. user pauses to jump back to a failed task."""
    run = _make_failed_run_with_downstream()
    run.id = "run-paused-recover"
    run.status = RunStatus.PAUSED
    run.pause_reason = "manual_pause"
    run.completed_at = None
    await service.create_run(run)

    result = await service.recover_run("run-paused-recover", "task-1")
    assert result.status == "paused"
    assert result.pause_reason == "recovered"


async def test_recover_run_resets_target_and_downstream(
    service: WorkflowService,
    session: AsyncSession,
) -> None:
    run = _make_failed_run_with_downstream()
    await service.create_run(run)

    result = await service.recover_run("run-recover-1", "task-1", additional_attempts=1)
    updated = await service.get_run("run-recover-1")

    assert result.status == "paused"
    assert result.pause_reason == "recovered"
    assert updated.status == RunStatus.PAUSED
    assert updated.pause_reason == "recovered"
    assert updated.completed_at is None

    target = updated.steps[0].tasks[0]
    assert target.status == TaskStatus.BUILDING
    assert target.max_attempts == 3
    assert target.current_attempt == 1
    assert len(target.attempts) == 1

    downstream = updated.steps[0].tasks[1]
    assert downstream.status == TaskStatus.PENDING
    assert downstream.current_attempt == 0
    assert downstream.attempts == []
    assert downstream.checklist[0].status == ChecklistStatus.OPEN
    assert downstream.checklist[0].note is None
    assert updated.steps[0].completed is False

    events = await SqliteEventStore(session).get_stream("run-recover-1")
    event_types = [event.event_type for event in events]
    assert "run_step_backward" in event_types
    assert event_types.count("task_reverted") == 2
    assert event_types[-1] == "run_status_changed"

    replayed = await _rebuild_run_from_events(session, service, "run-recover-1")
    assert replayed.status == RunStatus.PAUSED
    assert replayed.pause_reason == "recovered"
    assert replayed.completed_at is None
    assert replayed.current_step_index == 0

    replayed_target = replayed.steps[0].tasks[0]
    assert replayed_target.status == TaskStatus.BUILDING
    assert replayed_target.max_attempts == 3
    assert replayed_target.current_attempt == 1
    assert len(replayed_target.attempts) == 1

    replayed_downstream = replayed.steps[0].tasks[1]
    assert replayed_downstream.status == TaskStatus.PENDING
    assert replayed_downstream.current_attempt == 0
    assert replayed_downstream.attempts == []
    assert replayed_downstream.checklist[0].status == ChecklistStatus.OPEN
    assert replayed_downstream.checklist[0].note is None
    assert replayed.steps[0].completed is False


async def test_recover_run_preserves_downstream_checklist_when_requested(
    service: WorkflowService,
    session: AsyncSession,
) -> None:
    run = _make_failed_run_with_downstream()
    run.id = "run-recover-2"
    await service.create_run(run)

    await service.recover_run("run-recover-2", "task-1", preserve_checklist=True)
    updated = await service.get_run("run-recover-2")
    downstream = updated.steps[0].tasks[1]

    assert downstream.status == TaskStatus.PENDING
    assert downstream.checklist[0].status == ChecklistStatus.DONE
    assert downstream.checklist[0].note == "kept note"

    replayed = await _rebuild_run_from_events(session, service, "run-recover-2")
    replayed_downstream = replayed.steps[0].tasks[1]
    assert replayed_downstream.status == TaskStatus.PENDING
    assert replayed_downstream.checklist[0].status == ChecklistStatus.DONE
    assert replayed_downstream.checklist[0].note == "kept note"
