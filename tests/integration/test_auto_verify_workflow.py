"""Integration tests for auto-verify wired into the workflow service.

Tests use a real SQLite in-memory database, real subprocess execution via
LocalAutoVerifyRunner, and real temporary directories. No mocking.
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import (
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.db.event_store import EventStore
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
from orchestrator.workflow.prompts import generate_builder_prompt
from orchestrator.workflow.service import (
    WorkflowService,
    find_task_config,
    resolve_auto_verify_config,
)


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _embedded_routine_with_auto_verify(
    auto_verify_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a routine_embedded dict with auto_verify config on the task."""
    return {
        "id": "av-routine",
        "name": "Auto-Verify Test Routine",
        "steps": [
            {
                "id": "S-01",
                "title": "Step 1",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task with auto-verify",
                        "task_context": "Do the thing",
                        "requirements": [{"id": "R1", "desc": "It works"}],
                        "auto_verify": {
                            "items": auto_verify_items,
                            "tail_lines": 10,
                        },
                    }
                ],
            }
        ],
    }


def _make_run_with_auto_verify(
    project_path: str,
    auto_verify_items: list[dict[str, Any]],
) -> Run:
    """Create a run with an embedded routine containing auto_verify config."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-av",
        repo_name="test-repo",
        worktree_path=project_path,  # Set worktree_path for auto-verify to work
        status=RunStatus.DRAFT,
        routine_id="av-routine",
        routine_source=RoutineSource.EMBEDDED,
        routine_embedded=_embedded_routine_with_auto_verify(auto_verify_items),
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
                                desc="It works",
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


def _make_run_without_auto_verify(project_path: str) -> Run:
    """Create a run with no auto_verify config (routine_embedded with empty items)."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-no-av",
        repo_name="test-repo",
        worktree_path=project_path,
        status=RunStatus.DRAFT,
        routine_id="no-av-routine",
        routine_source=RoutineSource.EMBEDDED,
        routine_embedded={
            "id": "no-av-routine",
            "name": "No Auto-Verify Routine",
            "steps": [
                {
                    "id": "S-01",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "T-01",
                            "title": "Task without auto-verify",
                            "task_context": "Do the thing",
                            "requirements": [{"id": "R1", "desc": "It works"}],
                        }
                    ],
                }
            ],
        },
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
                                desc="It works",
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


# --- Pure function tests ---


class TestFindTaskConfig:
    def test_finds_existing_task(self) -> None:
        from orchestrator.config.models import RoutineConfig

        routine = RoutineConfig.model_validate(
            _embedded_routine_with_auto_verify([{"id": "check1", "cmd": "echo ok", "must": True}])
        )
        task_config = find_task_config(routine, "T-01")
        assert task_config is not None
        assert task_config.id == "T-01"
        assert len(task_config.auto_verify.items) == 1

    def test_returns_none_for_missing_task(self) -> None:
        from orchestrator.config.models import RoutineConfig

        routine = RoutineConfig.model_validate(_embedded_routine_with_auto_verify([]))
        assert find_task_config(routine, "nonexistent") is None

    def test_finds_correct_task_when_ids_reused_across_steps(self) -> None:
        from orchestrator.config.models import RoutineConfig

        # Create routine with two steps, each with a task "T-01" but different configs
        routine_dict = {
            "id": "multi-step-routine",
            "name": "Multi-Step Test Routine",
            "steps": [
                {
                    "id": "S-01",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "T-01",
                            "title": "Task in Step 1",
                            "task_context": "Do step 1 thing",
                            "requirements": [{"id": "R1", "desc": "Step 1 requirement"}],
                            "auto_verify": {
                                "items": [{"id": "check-s1", "cmd": "echo step1", "must": True}],
                                "tail_lines": 10,
                            },
                        }
                    ],
                },
                {
                    "id": "S-02",
                    "title": "Step 2",
                    "tasks": [
                        {
                            "id": "T-01",
                            "title": "Task in Step 2",
                            "task_context": "Do step 2 thing",
                            "requirements": [{"id": "R1", "desc": "Step 2 requirement"}],
                            "auto_verify": {
                                "items": [{"id": "check-s2", "cmd": "echo step2", "must": True}],
                                "tail_lines": 10,
                            },
                        }
                    ],
                },
            ],
        }
        routine = RoutineConfig.model_validate(routine_dict)

        # Find with step_config_id="S-01"
        task_s1 = find_task_config(routine, "T-01", step_config_id="S-01")
        assert task_s1 is not None
        assert task_s1.id == "T-01"
        assert task_s1.title == "Task in Step 1"
        assert len(task_s1.auto_verify.items) == 1
        assert task_s1.auto_verify.items[0].id == "check-s1"

        # Find with step_config_id="S-02"
        task_s2 = find_task_config(routine, "T-01", step_config_id="S-02")
        assert task_s2 is not None
        assert task_s2.id == "T-01"
        assert task_s2.title == "Task in Step 2"
        assert len(task_s2.auto_verify.items) == 1
        assert task_s2.auto_verify.items[0].id == "check-s2"

        # Verify they are different configs
        assert task_s1.title != task_s2.title
        assert task_s1.auto_verify.items[0].id != task_s2.auto_verify.items[0].id

        # Without step_config_id, returns first match (S-01)
        task_first = find_task_config(routine, "T-01")
        assert task_first is not None
        assert task_first.title == "Task in Step 1"


class TestResolveAutoVerifyConfig:
    def test_returns_config_when_items_present(self) -> None:
        run = _make_run_with_auto_verify("/tmp", [{"id": "check1", "cmd": "echo ok", "must": True}])
        config = resolve_auto_verify_config(run, "T-01")
        assert config is not None
        assert len(config.items) == 1
        assert config.items[0].id == "check1"

    def test_returns_none_when_no_items(self) -> None:
        run = _make_run_with_auto_verify("/tmp", [])
        config = resolve_auto_verify_config(run, "T-01")
        assert config is None

    def test_returns_none_when_no_routine_embedded(self) -> None:
        now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        run = Run(
            id="run-1",
            repo_name="/tmp",
            status=RunStatus.DRAFT,
            routine_id="some-routine",
            routine_embedded=None,
            steps=[],
            created_at=now,
            updated_at=now,
        )
        config = resolve_auto_verify_config(run, "T-01")
        assert config is None

    def test_returns_none_when_task_not_found(self) -> None:
        run = _make_run_with_auto_verify("/tmp", [{"id": "check1", "cmd": "echo ok"}])
        config = resolve_auto_verify_config(run, "nonexistent-task")
        assert config is None

    def test_resolves_correct_config_with_duplicate_task_ids(self) -> None:
        # Create Run with routine_embedded having two steps with "T-01" but different auto_verify
        now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        run = Run(
            id="run-multi-step",
            repo_name="test-repo",
            worktree_path="/tmp",
            status=RunStatus.DRAFT,
            routine_id="multi-step-routine",
            routine_source=RoutineSource.EMBEDDED,
            routine_embedded={
                "id": "multi-step-routine",
                "name": "Multi-Step Test Routine",
                "steps": [
                    {
                        "id": "S-01",
                        "title": "Step 1",
                        "tasks": [
                            {
                                "id": "T-01",
                                "title": "Task in Step 1",
                                "task_context": "Do step 1 thing",
                                "requirements": [{"id": "R1", "desc": "Step 1 requirement"}],
                                "auto_verify": {
                                    "items": [
                                        {"id": "check-s1", "cmd": "echo step1", "must": True}
                                    ],
                                    "tail_lines": 10,
                                },
                            }
                        ],
                    },
                    {
                        "id": "S-02",
                        "title": "Step 2",
                        "tasks": [
                            {
                                "id": "T-01",
                                "title": "Task in Step 2",
                                "task_context": "Do step 2 thing",
                                "requirements": [{"id": "R1", "desc": "Step 2 requirement"}],
                                "auto_verify": {
                                    "items": [
                                        {"id": "check-s2", "cmd": "echo step2", "must": True}
                                    ],
                                    "tail_lines": 10,
                                },
                            }
                        ],
                    },
                ],
            },
            steps=[],
            created_at=now,
            updated_at=now,
        )

        # Resolve with step_config_id="S-01"
        config_s1 = resolve_auto_verify_config(run, "T-01", step_config_id="S-01")
        assert config_s1 is not None
        assert len(config_s1.items) == 1
        assert config_s1.items[0].id == "check-s1"

        # Resolve with step_config_id="S-02"
        config_s2 = resolve_auto_verify_config(run, "T-01", step_config_id="S-02")
        assert config_s2 is not None
        assert len(config_s2.items) == 1
        assert config_s2.items[0].id == "check-s2"


# --- Integration tests with real DB and subprocess ---


async def test_submit_without_auto_verify_unchanged(session: AsyncSession, tmp_path: Path) -> None:
    """When no auto_verify config, submit_for_verification works as before."""
    runner = LocalAutoVerifyRunner()
    service = WorkflowService(session, auto_verify_runner=runner)

    run = _make_run_without_auto_verify(str(tmp_path))
    await service.create_run(run)
    await service.start_run("run-no-av")
    await service.start_task("run-no-av", "task-1")
    await service.update_checklist_item("run-no-av", "task-1", "R1", ChecklistStatus.DONE)

    result = await service.submit_for_verification("run-no-av", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.VERIFYING

    # Verify task is in VERIFYING state
    task = await service.get_task("run-no-av", "task-1")
    assert task.status == TaskStatus.VERIFYING


async def test_submit_with_passing_auto_verify(session: AsyncSession, tmp_path: Path) -> None:
    """When auto_verify items all pass, task stays in VERIFYING."""
    runner = LocalAutoVerifyRunner()
    service = WorkflowService(session, auto_verify_runner=runner)

    run = _make_run_with_auto_verify(
        str(tmp_path),
        [
            {"id": "check1", "cmd": "echo ok", "must": True},
            {"id": "check2", "cmd": "echo also_ok", "must": False},
        ],
    )
    await service.create_run(run)
    await service.start_run("run-av")
    await service.start_task("run-av", "task-1")
    await service.update_checklist_item("run-av", "task-1", "R1", ChecklistStatus.DONE)

    result = await service.submit_for_verification("run-av", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.VERIFYING

    # Verify task is in VERIFYING and results are stored
    task = await service.get_task("run-av", "task-1")
    assert task.status == TaskStatus.VERIFYING
    assert len(task.attempts) == 1
    assert len(task.attempts[0].auto_verify_results) == 2
    assert task.attempts[0].auto_verify_results[0]["passed"] is True
    assert task.attempts[0].auto_verify_results[1]["passed"] is True


async def test_submit_with_failing_must_auto_verify(session: AsyncSession, tmp_path: Path) -> None:
    """When auto_verify must-items fail, task transitions back to BUILDING."""
    runner = LocalAutoVerifyRunner()
    service = WorkflowService(session, auto_verify_runner=runner)

    run = _make_run_with_auto_verify(
        str(tmp_path),
        [
            {"id": "check1", "cmd": "false", "must": True},
            {"id": "check2", "cmd": "echo ok", "must": False},
        ],
    )
    await service.create_run(run)
    await service.start_run("run-av")
    await service.start_task("run-av", "task-1")
    await service.update_checklist_item("run-av", "task-1", "R1", ChecklistStatus.DONE)

    result = await service.submit_for_verification("run-av", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.BUILDING
    assert result.error == "Auto-verify must-items failed"

    # Verify task went back to BUILDING with a new attempt
    task = await service.get_task("run-av", "task-1")
    assert task.status == TaskStatus.BUILDING
    assert task.current_attempt == 2
    assert len(task.attempts) == 2

    # First attempt should have auto_verify_results stored
    assert len(task.attempts[0].auto_verify_results) == 2
    assert task.attempts[0].auto_verify_results[0]["passed"] is False
    assert task.attempts[0].auto_verify_results[0]["item_id"] == "check1"
    assert task.attempts[0].verifier_comment is not None
    assert "Auto-verify failed" in task.attempts[0].verifier_comment
    assert "command `false` failed" in task.attempts[0].verifier_comment

    # Revision prompt should include previous feedback even though a new attempt exists.
    from orchestrator.config.models import RoutineConfig

    routine = RoutineConfig.model_validate(run.routine_embedded)
    task_config = find_task_config(routine, "T-01")
    assert task_config is not None
    prompt = generate_builder_prompt(task_config, task, run.config)
    assert "Previous Feedback (Revision Required)" in prompt.user
    assert "command `false` failed" in prompt.user


async def test_submit_with_failing_non_must_still_verifying(
    session: AsyncSession, tmp_path: Path
) -> None:
    """When only non-must auto_verify items fail, task stays in VERIFYING."""
    runner = LocalAutoVerifyRunner()
    service = WorkflowService(session, auto_verify_runner=runner)

    run = _make_run_with_auto_verify(
        str(tmp_path),
        [
            {"id": "check1", "cmd": "echo ok", "must": True},
            {"id": "check2", "cmd": "false", "must": False},
        ],
    )
    await service.create_run(run)
    await service.start_run("run-av")
    await service.start_task("run-av", "task-1")
    await service.update_checklist_item("run-av", "task-1", "R1", ChecklistStatus.DONE)

    result = await service.submit_for_verification("run-av", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.VERIFYING

    # Results should still be stored even though must items passed
    task = await service.get_task("run-av", "task-1")
    assert task.status == TaskStatus.VERIFYING
    assert len(task.attempts[0].auto_verify_results) == 2
    assert task.attempts[0].auto_verify_results[1]["passed"] is False


async def test_auto_verify_events_emitted(session: AsyncSession, tmp_path: Path) -> None:
    """Auto-verify emits an AutoVerifyCompleted event."""
    runner = LocalAutoVerifyRunner()
    service = WorkflowService(session, auto_verify_runner=runner)

    run = _make_run_with_auto_verify(
        str(tmp_path),
        [{"id": "check1", "cmd": "echo ok", "must": True}],
    )
    await service.create_run(run)
    await service.start_run("run-av")
    await service.start_task("run-av", "task-1")
    await service.update_checklist_item("run-av", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-av", "task-1")

    # Query persisted events
    store = EventStore(session)
    events = await store.get_events_for_run("run-av")
    event_types = [e["type"] for e in events]
    assert "auto_verify_completed" in event_types

    # Find the auto_verify event and check its payload
    av_event = next(e for e in events if e["type"] == "auto_verify_completed")
    assert av_event["payload"]["passed"] is True
    assert av_event["payload"]["task_id"] == "task-1"


async def test_auto_verify_failure_events(session: AsyncSession, tmp_path: Path) -> None:
    """When auto-verify fails, both AutoVerifyCompleted and TaskStatusChanged events are emitted."""
    runner = LocalAutoVerifyRunner()
    service = WorkflowService(session, auto_verify_runner=runner)

    run = _make_run_with_auto_verify(
        str(tmp_path),
        [{"id": "check1", "cmd": "false", "must": True}],
    )
    await service.create_run(run)
    await service.start_run("run-av")
    await service.start_task("run-av", "task-1")
    await service.update_checklist_item("run-av", "task-1", "R1", ChecklistStatus.DONE)
    await service.submit_for_verification("run-av", "task-1")

    store = EventStore(session)
    events = await store.get_events_for_run("run-av")
    event_types = [e["type"] for e in events]

    assert "auto_verify_completed" in event_types

    # There should be a task_status_changed for BUILDING -> VERIFYING,
    # then auto_verify_completed (failed), then task_status_changed VERIFYING -> BUILDING
    task_status_events = [e for e in events if e["type"] == "task_status_changed"]
    # First: PENDING -> BUILDING (start_task)
    # Second: BUILDING -> VERIFYING (submit)
    # Third: VERIFYING -> BUILDING (auto-verify revision)
    assert len(task_status_events) >= 3

    av_event = next(e for e in events if e["type"] == "auto_verify_completed")
    assert av_event["payload"]["passed"] is False
    assert av_event["payload"]["failing_must_items"] == ["check1"]


async def test_no_runner_skips_auto_verify(session: AsyncSession, tmp_path: Path) -> None:
    """When no auto_verify_runner is set, auto-verify is skipped even with config."""
    # Create service WITHOUT a runner
    service = WorkflowService(session)

    run = _make_run_with_auto_verify(
        str(tmp_path),
        [{"id": "check1", "cmd": "false", "must": True}],
    )
    await service.create_run(run)
    await service.start_run("run-av")
    await service.start_task("run-av", "task-1")
    await service.update_checklist_item("run-av", "task-1", "R1", ChecklistStatus.DONE)

    # Even though the command would fail, it should not run since no runner
    result = await service.submit_for_verification("run-av", "task-1")
    assert result.success is True
    assert result.new_status == TaskStatus.VERIFYING


async def test_auto_verify_revision_then_pass(session: AsyncSession, tmp_path: Path) -> None:
    """Full cycle: auto-verify fails, revision, fix, auto-verify passes, complete."""
    from orchestrator.config.enums import AgentType

    # Create a script that fails the first time and passes the second
    script = tmp_path / "check.sh"
    script.write_text(
        "#!/bin/bash\n"
        "COUNT=$(cat attempt_count 2>/dev/null || echo 0)\n"
        "echo $((COUNT + 1)) > attempt_count\n"
        'if [ "$COUNT" -ge "1" ]; then exit 0; else exit 1; fi\n'
    )
    script.chmod(0o755)

    runner = LocalAutoVerifyRunner()
    service = WorkflowService(session, auto_verify_runner=runner)

    run = _make_run_with_auto_verify(
        str(tmp_path),
        [{"id": "check1", "cmd": f"bash {script}", "must": True}],
    )
    # Set agent config
    run.agent_type = AgentType.CLI_SUBPROCESS
    run.agent_config = {
        "model": "claude-sonnet-4-5-20250514",
        "temperature": 0.7,
        "api_key": "secret-key",
    }

    await service.create_run(run)
    await service.start_run("run-av")
    await service.start_task("run-av", "task-1")
    await service.update_checklist_item("run-av", "task-1", "R1", ChecklistStatus.DONE)

    # First submit: auto-verify fails -> revision
    result1 = await service.submit_for_verification("run-av", "task-1")
    assert result1.new_status == TaskStatus.BUILDING
    assert result1.error == "Auto-verify must-items failed"

    # Second submit: auto-verify passes now
    await service.update_checklist_item("run-av", "task-1", "R1", ChecklistStatus.DONE)
    result2 = await service.submit_for_verification("run-av", "task-1")
    assert result2.new_status == TaskStatus.VERIFYING
    assert result2.success is True

    # Complete verification
    await service.set_grade("run-av", "task-1", "R1", "A")
    result3 = await service.complete_verification("run-av", "task-1")
    assert result3.new_status == TaskStatus.COMPLETED

    # Verify final state
    task = await service.get_task("run-av", "task-1")
    assert task.status == TaskStatus.COMPLETED
    assert task.current_attempt == 2
    assert len(task.attempts) == 2
    # First attempt had failing auto-verify
    assert task.attempts[0].auto_verify_results[0]["passed"] is False
    # Second attempt had passing auto-verify
    assert task.attempts[1].auto_verify_results[0]["passed"] is True

    # Verify agent snapshot was populated on both attempts
    assert task.attempts[0].agent_type == AgentType.CLI_SUBPROCESS
    assert task.attempts[0].agent_model == "claude-sonnet-4-5-20250514"
    assert task.attempts[0].agent_settings["model"] == "claude-sonnet-4-5-20250514"
    assert task.attempts[0].agent_settings["temperature"] == 0.7
    assert "api_key" not in task.attempts[0].agent_settings

    assert task.attempts[1].agent_type == AgentType.CLI_SUBPROCESS
    assert task.attempts[1].agent_model == "claude-sonnet-4-5-20250514"
    assert task.attempts[1].agent_settings["model"] == "claude-sonnet-4-5-20250514"
    assert task.attempts[1].agent_settings["temperature"] == 0.7
    assert "api_key" not in task.attempts[1].agent_settings


async def test_auto_verify_results_persist_across_sessions(
    tmp_path: Path,
) -> None:
    """Auto-verify results survive across separate database sessions."""
    db_path = tmp_path / "test_av.db"

    # Session 1: Create and run auto-verify
    engine1 = create_engine(str(db_path))
    await init_db(engine1)
    factory1 = create_session_factory(engine1)

    async with factory1() as session1:
        runner = LocalAutoVerifyRunner()
        service1 = WorkflowService(session1, auto_verify_runner=runner)

        run = _make_run_with_auto_verify(
            str(tmp_path),
            [{"id": "check1", "cmd": "echo hello", "must": True}],
        )
        await service1.create_run(run)
        await service1.start_run("run-av")
        await service1.start_task("run-av", "task-1")
        await service1.update_checklist_item("run-av", "task-1", "R1", ChecklistStatus.DONE)
        await service1.submit_for_verification("run-av", "task-1")

    await engine1.dispose()

    # Session 2: Verify results survived
    engine2 = create_engine(str(db_path))
    factory2 = create_session_factory(engine2)

    async with factory2() as session2:
        service2 = WorkflowService(session2)
        task = await service2.get_task("run-av", "task-1")
        assert task.status == TaskStatus.VERIFYING
        assert len(task.attempts[0].auto_verify_results) == 1
        assert task.attempts[0].auto_verify_results[0]["passed"] is True
        assert "hello" in task.attempts[0].auto_verify_results[0]["output"]

    await engine2.dispose()
