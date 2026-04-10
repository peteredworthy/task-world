"""Parity test: linear two-step workflow with three tasks.

Captures current orchestrator behaviour as a regression baseline.
Covers: run creation → start → build → submit → verify → complete for
each task across two steps, asserting run.status, run.current_step_index,
task.status, and attempt counts at every meaningful stage.

Also contains engine-level lifecycle tests (migrated from test_workflow_execution.py)
and MockAgent/WorkflowService tests (migrated from test_mock_agent_workflow.py).
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.app import create_app
from orchestrator.config import ChecklistStatus, Priority, RoutineSource, RunStatus, TaskStatus
from orchestrator.config import load_routine_from_path
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.runners import MockAgent, MockBehavior
from orchestrator.runners.types import ExecutionContext
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.state.session import SessionStateManager
from orchestrator.workflow import InMemorySignalTransport, RunStatusChanged, TaskStatusChanged, WorkflowEngine
from orchestrator.workflow.service import WorkflowService

from tests.conftest import CollectingEmitter, FakeClock
from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

# ---------------------------------------------------------------------------
# Embedded routine: 2 steps, 3 tasks
# ---------------------------------------------------------------------------

LINEAR_ROUTINE: dict[str, Any] = {
    "id": "parity-linear",
    "name": "Parity Linear Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Step One",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Task One",
                    "task_context": "Do task one",
                    "requirements": [{"id": "R1", "desc": "Requirement 1"}],
                }
            ],
        },
        {
            "id": "S-02",
            "title": "Step Two",
            "tasks": [
                {
                    "id": "T-02",
                    "title": "Task Two",
                    "task_context": "Do task two",
                    "requirements": [{"id": "R1", "desc": "Requirement 1"}],
                },
                {
                    "id": "T-03",
                    "title": "Task Three",
                    "task_context": "Do task three",
                    "requirements": [{"id": "R1", "desc": "Requirement 1"}],
                },
            ],
        },
    ],
}

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    transport = InMemorySignalTransport()
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    app.state.signal_transport = transport
    await init_db(app.state.engine)
    asgi = ASGITransport(app=app)  # type: ignore[arg-type]
    drain = make_drain_fn(app, transport)
    async with AsyncClient(transport=asgi, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_run(client: AsyncClient) -> dict[str, Any]:
    resp = await client.post(
        "/api/runs",
        json={
            "routine_embedded": LINEAR_ROUTINE,
            "repo_name": "parity-linear-repo",
            "branch": "main",
        },
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    return resp.json()


async def _start_run(
    client: AsyncClient, run_id: str, drain: DrainFn | None = None
) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202, f"Failed to start run: {resp.text}"
    if drain is not None:
        await drain(run_id)
    resp2 = await client.get(f"/api/runs/{run_id}")
    assert resp2.status_code == 200
    return resp2.json()


async def _get_run(client: AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    return resp.json()


async def _get_task(client: AsyncClient, run_id: str, task_id: str) -> dict[str, Any]:
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    return resp.json()


async def _complete_task(
    client: AsyncClient, run_id: str, task_id: str, drain: DrainFn, req_id: str = "R1"
) -> None:
    """Drive a task through the full build → verify → complete cycle."""
    # Start
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["new_status"] == "building"

    # Mark checklist done
    resp = await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}",
        json={"status": "done"},
    )
    assert resp.status_code == 200

    # Submit (now returns 200)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await drain(run_id)

    # Grade
    resp = await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/{req_id}/grade",
        json={"grade": "A", "grade_reason": "Looks good"},
    )
    assert resp.status_code == 200

    # Complete verification (now returns 200)
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    await drain(run_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_linear_run_structure(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Run created with 2 steps and 3 tasks in the expected layout."""
    client, _drain = client_and_drain
    run = await _create_run(client)

    assert run["status"] == "draft"
    assert len(run["steps"]) == 2, "Expected 2 steps"
    assert len(run["steps"][0]["tasks"]) == 1, "Step 1 should have 1 task"
    assert len(run["steps"][1]["tasks"]) == 2, "Step 2 should have 2 tasks"
    assert run["current_step_index"] == 0


async def test_linear_run_starts_active(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Run transitions to active and lands on step 0 after start."""
    client, _drain = client_and_drain
    run = await _create_run(client)
    run_id = run["id"]

    started = await _start_run(client, run_id, drain=_drain)
    assert started["status"] == "active"
    assert started["current_step_index"] == 0


async def test_linear_task_status_transitions(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Task status progresses: pending → building → verifying → completed."""
    client, drain = client_and_drain
    run = await _create_run(client)
    run_id = run["id"]
    task_id = run["steps"][0]["tasks"][0]["id"]

    await _start_run(client, run_id, drain=drain)

    # Initially pending
    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "pending"

    # After start: building, first attempt created
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert resp.status_code == 200
    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "building"
    assert task["current_attempt"] == 1
    assert len(task["attempts"]) == 1

    # After submit: verifying
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 200
    await drain(run_id)
    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "verifying"

    # After complete-verification with grade A: completed
    await client.put(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
        json={"grade": "A"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/complete-verification")
    assert resp.status_code == 200
    await drain(run_id)
    task = await _get_task(client, run_id, task_id)
    assert task["status"] == "completed"
    assert task["attempts"][0]["outcome"] == "passed"


async def test_linear_step_advances_after_step1_complete(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """current_step_index advances from 0 to 1 after step 1 completes."""
    client, drain = client_and_drain
    run = await _create_run(client)
    run_id = run["id"]
    task1_id = run["steps"][0]["tasks"][0]["id"]

    await _start_run(client, run_id, drain=drain)

    # Step 0 is current
    r = await _get_run(client, run_id)
    assert r["current_step_index"] == 0

    await _complete_task(client, run_id, task1_id, drain)

    # Step should have advanced
    r = await _get_run(client, run_id)
    assert r["current_step_index"] == 1, "Should advance to step index 1 after step 1 completes"
    assert r["steps"][0]["completed"] is True


async def test_linear_full_workflow_completes_run(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Full 3-task linear run: all tasks done, run status == completed."""
    client, drain = client_and_drain
    run = await _create_run(client)
    run_id = run["id"]
    task1_id = run["steps"][0]["tasks"][0]["id"]
    task2_id = run["steps"][1]["tasks"][0]["id"]
    task3_id = run["steps"][1]["tasks"][1]["id"]

    await _start_run(client, run_id, drain=drain)

    # Complete step 1
    await _complete_task(client, run_id, task1_id, drain)

    r = await _get_run(client, run_id)
    assert r["status"] == "active", "Run should remain active after step 1"
    assert r["current_step_index"] == 1

    # Complete step 2 task 1
    await _complete_task(client, run_id, task2_id, drain)

    r = await _get_run(client, run_id)
    assert r["status"] == "active", "Run still active with one step-2 task remaining"

    # Complete step 2 task 2 → run should complete
    await _complete_task(client, run_id, task3_id, drain)

    r = await _get_run(client, run_id)
    assert r["status"] == "completed"
    assert r["completed_at"] is not None
    assert r["steps"][0]["completed"] is True
    assert r["steps"][1]["completed"] is True

    # All tasks completed with one attempt each
    for task_id in (task1_id, task2_id, task3_id):
        t = await _get_task(client, run_id, task_id)
        assert t["status"] == "completed"
        assert t["current_attempt"] == 1
        assert len(t["attempts"]) == 1


# ---------------------------------------------------------------------------
# Engine-level lifecycle tests (migrated from test_workflow_execution.py)
# ---------------------------------------------------------------------------


def test_engine_full_lifecycle_event_sequence() -> None:
    """Engine-level: full build/verify lifecycle emits correct event sequence.

    Verifies RunStatusChanged + TaskStatusChanged x3 in order, FakeClock
    advancing between phases, and attempt outcome recorded on completion.
    Migrated from test_workflow_execution.py::test_full_lifecycle.
    """
    routine = load_routine_from_path(FIXTURES / "valid_simple.yaml")
    run = create_run_from_routine(
        routine=routine,
        repo_name="test-project",
        source_branch="main",
        config={"feature": "auth"},
    )

    manager = SessionStateManager()
    manager.add_run(run)
    clock = FakeClock()
    emitter = CollectingEmitter()
    engine = WorkflowEngine(manager, clock=clock, emitter=emitter)

    engine.start_run(run.id)
    assert run.status == RunStatus.ACTIVE

    task = run.steps[0].tasks[0]
    assert task.status == TaskStatus.PENDING

    result = engine.start_task(run.id, task.id)
    assert result.success is True
    assert task.status == TaskStatus.BUILDING

    for item in task.checklist:
        item.status = ChecklistStatus.DONE

    clock.advance(timedelta(minutes=10))
    result = engine.submit_for_verification(run.id, task.id)
    assert result.success is True
    assert result.gate_result is not None
    assert result.gate_result.passed is True
    assert task.status == TaskStatus.VERIFYING

    for item in task.checklist:
        item.grade = "A"

    clock.advance(timedelta(minutes=5))
    result = engine.complete_verification(run.id, task.id)
    assert result.success is True
    assert result.new_status == TaskStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED

    # Verify event sequence
    assert len(emitter.events) >= 4
    assert isinstance(emitter.events[0], RunStatusChanged)
    assert emitter.events[0].new_status == RunStatus.ACTIVE

    task_events = [e for e in emitter.events if isinstance(e, TaskStatusChanged)]
    assert len(task_events) == 3
    assert task_events[0].new_status == TaskStatus.BUILDING
    assert task_events[1].new_status == TaskStatus.VERIFYING
    assert task_events[2].new_status == TaskStatus.COMPLETED

    # Attempt tracking
    assert len(task.attempts) == 1
    assert task.attempts[0].outcome == "passed"
    assert task.attempts[0].completed_at is not None


def test_engine_revision_lifecycle() -> None:
    """Engine-level: fail → retry produces two attempts with correct outcomes.

    Migrated from test_workflow_execution.py::test_revision_lifecycle.
    """
    routine = load_routine_from_path(FIXTURES / "valid_simple.yaml")
    run = create_run_from_routine(routine=routine, repo_name="test-project", source_branch="main")

    manager = SessionStateManager()
    manager.add_run(run)
    clock = FakeClock()
    emitter = CollectingEmitter()
    engine = WorkflowEngine(manager, clock=clock, emitter=emitter)

    engine.start_run(run.id)
    task = run.steps[0].tasks[0]

    # Attempt 1: build, submit, fail verification (grade D)
    engine.start_task(run.id, task.id)
    for item in task.checklist:
        item.status = ChecklistStatus.DONE
        item.grade = "D"
        item.grade_reason = "Needs work"

    engine.submit_for_verification(run.id, task.id)
    result = engine.complete_verification(run.id, task.id)
    assert result.new_status == TaskStatus.BUILDING  # Revision started
    assert task.current_attempt == 2

    # Attempt 2: fix grades and pass
    for item in task.checklist:
        item.grade = "A"
        item.grade_reason = None

    engine.submit_for_verification(run.id, task.id)
    clock.advance(timedelta(minutes=5))
    result = engine.complete_verification(run.id, task.id)
    assert result.new_status == TaskStatus.COMPLETED
    assert len(task.attempts) == 2
    assert task.attempts[0].outcome == "revision_needed"
    assert task.attempts[1].outcome == "passed"


# ---------------------------------------------------------------------------
# MockAgent + WorkflowService tests (migrated from test_mock_agent_workflow.py)
# ---------------------------------------------------------------------------


def _make_run_with_requirements(req_ids: list[str]) -> Run:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-mock-1",
        repo_name="proj-1",
        source_branch="main",
        status=RunStatus.DRAFT,
        routine_id="test-routine",
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
                                req_id=req_id,
                                desc=f"Requirement {req_id}",
                                priority=Priority.CRITICAL,
                            )
                            for req_id in req_ids
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
async def mock_agent_service() -> AsyncGenerator[WorkflowService, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield WorkflowService(s)
    await engine.dispose()


async def test_mock_agent_completes_task(mock_agent_service: WorkflowService) -> None:
    """MockAgent completes requirements and submits, driving task to VERIFYING.

    Migrated from test_mock_agent_workflow.py::test_mock_agent_completes_task.
    """
    service = mock_agent_service
    run = _make_run_with_requirements(["R1", "R2"])
    await service.create_run(run)
    await service.apply_start_run("run-mock-1")
    await service.start_task("run-mock-1", "task-1")

    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        await service.update_checklist_item("run-mock-1", "task-1", req_id, status, note)

    async def on_submit() -> None:
        await service.submit_for_verification("run-mock-1", "task-1")

    behavior = MockBehavior(complete_requirements=["R1", "R2"], should_submit=True)
    agent = MockAgent(behavior)
    context = ExecutionContext(
        run_id="run-mock-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="Complete the requirements",
        requirements=["R1", "R2"],
    )

    result = await agent.execute(context, on_checklist_update, on_submit)
    assert result.success is True

    task = await service.get_task("run-mock-1", "task-1")
    assert task.status == TaskStatus.VERIFYING
    assert task.checklist[0].status == ChecklistStatus.DONE
    assert task.checklist[1].status == ChecklistStatus.DONE


async def test_mock_agent_partial_completion(mock_agent_service: WorkflowService) -> None:
    """MockAgent completes some requirements, blocks others, task stays BUILDING.

    Migrated from test_mock_agent_workflow.py::test_mock_agent_partial_completion.
    """
    service = mock_agent_service
    run = _make_run_with_requirements(["R1", "R2", "R3"])
    run.id = "run-mock-partial"
    await service.create_run(run)
    await service.apply_start_run("run-mock-partial")
    await service.start_task("run-mock-partial", "task-1")

    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        await service.update_checklist_item("run-mock-partial", "task-1", req_id, status, note)

    async def on_submit() -> None:
        await service.submit_for_verification("run-mock-partial", "task-1")

    behavior = MockBehavior(
        complete_requirements=["R1"],
        fail_requirements=["R2"],
        should_submit=False,
    )
    agent = MockAgent(behavior)
    context = ExecutionContext(
        run_id="run-mock-partial",
        task_id="task-1",
        working_dir="/tmp",
        prompt="Try the requirements",
        requirements=["R1", "R2", "R3"],
    )

    result = await agent.execute(context, on_checklist_update, on_submit)
    assert result.success is True

    task = await service.get_task("run-mock-partial", "task-1")
    assert task.status == TaskStatus.BUILDING  # Still building since no submit
    assert task.checklist[0].status == ChecklistStatus.DONE
    assert task.checklist[1].status == ChecklistStatus.BLOCKED
    assert task.checklist[2].status == ChecklistStatus.OPEN  # Untouched


async def test_mock_agent_full_lifecycle(mock_agent_service: WorkflowService) -> None:
    """Full lifecycle: mock agent builds, verifier grades A, task completes.

    Migrated from test_mock_agent_workflow.py::test_mock_agent_full_lifecycle.
    """
    service = mock_agent_service
    run = _make_run_with_requirements(["R1"])
    run.id = "run-mock-full"
    await service.create_run(run)
    await service.apply_start_run("run-mock-full")
    await service.start_task("run-mock-full", "task-1")

    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        await service.update_checklist_item("run-mock-full", "task-1", req_id, status, note)

    async def on_submit() -> None:
        await service.submit_for_verification("run-mock-full", "task-1")

    behavior = MockBehavior(complete_requirements=["R1"], should_submit=True)
    agent = MockAgent(behavior)
    context = ExecutionContext(
        run_id="run-mock-full",
        task_id="task-1",
        working_dir="/tmp",
        prompt="Build it",
        requirements=["R1"],
    )
    await agent.execute(context, on_checklist_update, on_submit)

    # Verifier phase - grade and complete
    await service.set_grade("run-mock-full", "task-1", "R1", "A")
    result = await service.complete_verification("run-mock-full", "task-1")
    assert result.new_status == TaskStatus.COMPLETED
