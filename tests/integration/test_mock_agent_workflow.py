"""Integration test: MockAgent with real WorkflowService."""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.runners import MockAgent, MockBehavior
from orchestrator.runners.types import ExecutionContext
from orchestrator.config.enums import (
    ChecklistStatus,
    Priority,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.service import WorkflowService


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


def _make_run_with_requirements(req_ids: list[str]) -> Run:
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-1",
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


async def test_mock_agent_completes_task(service: WorkflowService) -> None:
    """MockAgent completes requirements and submits, driving task to VERIFYING."""
    run = _make_run_with_requirements(["R1", "R2"])
    await service.create_run(run)
    await service.start_run("run-1")
    await service.start_task("run-1", "task-1")

    # Build callbacks that call into WorkflowService
    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        await service.update_checklist_item("run-1", "task-1", req_id, status, note)

    async def on_submit() -> None:
        await service.submit_for_verification("run-1", "task-1")

    behavior = MockBehavior(
        complete_requirements=["R1", "R2"],
        should_submit=True,
    )
    agent = MockAgent(behavior)
    context = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="Complete the requirements",
        requirements=["R1", "R2"],
    )

    result = await agent.execute(context, on_checklist_update, on_submit)

    assert result.success is True

    # Verify state in service
    task = await service.get_task("run-1", "task-1")
    assert task.status == TaskStatus.VERIFYING
    assert task.checklist[0].status == ChecklistStatus.DONE
    assert task.checklist[1].status == ChecklistStatus.DONE


async def test_mock_agent_partial_completion(service: WorkflowService) -> None:
    """MockAgent completes some requirements, blocks others, doesn't submit."""
    run = _make_run_with_requirements(["R1", "R2", "R3"])
    await service.create_run(run)
    await service.start_run("run-1")
    await service.start_task("run-1", "task-1")

    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        await service.update_checklist_item("run-1", "task-1", req_id, status, note)

    async def on_submit() -> None:
        await service.submit_for_verification("run-1", "task-1")

    behavior = MockBehavior(
        complete_requirements=["R1"],
        fail_requirements=["R2"],
        should_submit=False,  # Don't submit — task stays BUILDING
    )
    agent = MockAgent(behavior)
    context = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="Try the requirements",
        requirements=["R1", "R2", "R3"],
    )

    result = await agent.execute(context, on_checklist_update, on_submit)
    assert result.success is True

    task = await service.get_task("run-1", "task-1")
    assert task.status == TaskStatus.BUILDING  # Still building since no submit
    assert task.checklist[0].status == ChecklistStatus.DONE
    assert task.checklist[1].status == ChecklistStatus.BLOCKED
    assert task.checklist[2].status == ChecklistStatus.OPEN  # Untouched


async def test_mock_agent_full_lifecycle(service: WorkflowService) -> None:
    """Full lifecycle: mock agent builds, verifier grades, task completes."""
    run = _make_run_with_requirements(["R1"])
    await service.create_run(run)
    await service.start_run("run-1")
    await service.start_task("run-1", "task-1")

    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:
        await service.update_checklist_item("run-1", "task-1", req_id, status, note)

    async def on_submit() -> None:
        await service.submit_for_verification("run-1", "task-1")

    # Builder phase
    behavior = MockBehavior(complete_requirements=["R1"], should_submit=True)
    agent = MockAgent(behavior)
    context = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir="/tmp",
        prompt="Build it",
        requirements=["R1"],
    )
    await agent.execute(context, on_checklist_update, on_submit)

    # Verifier phase - grade and complete
    await service.set_grade("run-1", "task-1", "R1", "A")
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.COMPLETED
