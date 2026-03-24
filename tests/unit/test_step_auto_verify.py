"""Tests for step_auto_verify field on StepConfig and service integration."""

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
from orchestrator.config.models import AutoVerifyItemConfig, RoutineConfig, StepConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
from orchestrator.workflow.service import WorkflowService, find_step_config


# --- Unit tests for StepConfig schema ---


class TestStepAutoVerifyField:
    def test_step_config_accepts_step_auto_verify(self) -> None:
        step = StepConfig(
            id="S-01",
            title="Step 1",
            tasks=[{"id": "T-01", "title": "Task", "task_context": "ctx"}],
            step_auto_verify=[{"id": "check1", "cmd": "echo ok", "must": True}],
        )
        assert len(step.step_auto_verify) == 1
        assert step.step_auto_verify[0].id == "check1"
        assert step.step_auto_verify[0].must is True

    def test_step_auto_verify_defaults_to_empty(self) -> None:
        step = StepConfig(
            id="S-01",
            title="Step 1",
            tasks=[{"id": "T-01", "title": "Task", "task_context": "ctx"}],
        )
        assert step.step_auto_verify == []

    def test_step_auto_verify_items_are_auto_verify_item_configs(self) -> None:
        step = StepConfig(
            id="S-01",
            title="Step 1",
            tasks=[{"id": "T-01", "title": "Task", "task_context": "ctx"}],
            step_auto_verify=[
                {"id": "av1", "cmd": "true", "must": True},
                {"id": "av2", "cmd": "echo done", "must": False},
            ],
        )
        assert all(isinstance(item, AutoVerifyItemConfig) for item in step.step_auto_verify)
        assert step.step_auto_verify[1].must is False

    def test_step_auto_verify_in_routine_config(self) -> None:
        routine = RoutineConfig.model_validate(
            {
                "id": "r1",
                "name": "Routine",
                "steps": [
                    {
                        "id": "S-01",
                        "title": "Step 1",
                        "tasks": [{"id": "T-01", "title": "Task", "task_context": "ctx"}],
                        "step_auto_verify": [{"id": "sav1", "cmd": "echo step ok"}],
                    }
                ],
            }
        )
        assert len(routine.steps[0].step_auto_verify) == 1
        assert routine.steps[0].step_auto_verify[0].id == "sav1"


class TestFindStepConfig:
    def test_finds_step_by_id(self) -> None:
        routine = RoutineConfig.model_validate(
            {
                "id": "r1",
                "name": "Routine",
                "steps": [
                    {
                        "id": "S-01",
                        "title": "Step 1",
                        "tasks": [{"id": "T-01", "title": "T", "task_context": "ctx"}],
                    },
                    {
                        "id": "S-02",
                        "title": "Step 2",
                        "tasks": [{"id": "T-02", "title": "T2", "task_context": "ctx2"}],
                    },
                ],
            }
        )
        step = find_step_config(routine, "S-02")
        assert step is not None
        assert step.id == "S-02"

    def test_returns_none_for_missing_step(self) -> None:
        routine = RoutineConfig.model_validate(
            {
                "id": "r1",
                "name": "Routine",
                "steps": [
                    {
                        "id": "S-01",
                        "title": "Step 1",
                        "tasks": [{"id": "T-01", "title": "T", "task_context": "ctx"}],
                    }
                ],
            }
        )
        assert find_step_config(routine, "MISSING") is None


# --- Integration tests for step_auto_verify in the workflow service ---


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _make_run_with_step_auto_verify(
    tmp_path: Path,
    step_auto_verify_items: list[dict[str, Any]],
) -> Run:
    """Build a run whose step has step_auto_verify configured."""
    now = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    return Run(
        id="run-sav",
        repo_name="test-repo",
        worktree_path=str(tmp_path),
        status=RunStatus.DRAFT,
        routine_id="sav-routine",
        routine_source=RoutineSource.EMBEDDED,
        routine_embedded={
            "id": "sav-routine",
            "name": "Step Auto-Verify Test",
            "steps": [
                {
                    "id": "S-01",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "T-01",
                            "title": "Task",
                            "task_context": "ctx",
                            "requirements": [{"id": "R1", "desc": "works"}],
                            "verifier": {
                                "rubric": [{"id": "Q1", "text": "Did it work?"}],
                            },
                        }
                    ],
                    "step_auto_verify": step_auto_verify_items,
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
                                desc="works",
                                priority=Priority.CRITICAL,
                            )
                        ],
                        max_attempts=3,
                        has_verification=True,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


async def _run_task_to_verified(svc: WorkflowService, run_id: str, task_id: str) -> None:
    """Bring a task from PENDING through to complete_verification with passing grade."""
    await svc.start_run(run_id)
    await svc.start_task(run_id, task_id)
    await svc.update_checklist_item(run_id, task_id, "R1", ChecklistStatus.DONE)
    await svc.submit_for_verification(run_id, task_id)
    await svc.set_grade(run_id, task_id, "R1", "A")
    await svc.complete_verification(run_id, task_id)


@pytest.mark.asyncio
async def test_step_auto_verify_passing_completes_run(
    session: AsyncSession, tmp_path: Path
) -> None:
    """When step_auto_verify passes (exit 0), run completes normally."""
    run = _make_run_with_step_auto_verify(
        tmp_path,
        step_auto_verify_items=[{"id": "sav1", "cmd": "true", "must": True}],
    )
    svc = WorkflowService(session, auto_verify_runner=LocalAutoVerifyRunner())
    await svc.create_run(run)
    await _run_task_to_verified(svc, run.id, "task-1")

    updated = await svc.get_run(run.id)
    assert updated.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_step_auto_verify_failing_halts_run(session: AsyncSession, tmp_path: Path) -> None:
    """When step_auto_verify fails (exit non-0), run is halted as FAILED."""
    run = _make_run_with_step_auto_verify(
        tmp_path,
        step_auto_verify_items=[{"id": "sav1", "cmd": "false", "must": True}],
    )
    svc = WorkflowService(session, auto_verify_runner=LocalAutoVerifyRunner())
    await svc.create_run(run)
    await _run_task_to_verified(svc, run.id, "task-1")

    updated = await svc.get_run(run.id)
    assert updated.status == RunStatus.FAILED
    assert updated.last_error is not None
    assert "auto-verify" in updated.last_error.lower()


@pytest.mark.asyncio
async def test_step_auto_verify_skipped_without_runner(
    session: AsyncSession, tmp_path: Path
) -> None:
    """When no auto_verify_runner is configured, step_auto_verify is skipped (run completes)."""
    run = _make_run_with_step_auto_verify(
        tmp_path,
        step_auto_verify_items=[{"id": "sav1", "cmd": "false", "must": True}],
    )
    svc = WorkflowService(session, auto_verify_runner=None)
    await svc.create_run(run)
    await _run_task_to_verified(svc, run.id, "task-1")

    updated = await svc.get_run(run.id)
    assert updated.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_step_without_step_auto_verify_unaffected(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Steps without step_auto_verify complete normally (existing behavior unchanged)."""
    run = _make_run_with_step_auto_verify(
        tmp_path,
        step_auto_verify_items=[],
    )
    svc = WorkflowService(session, auto_verify_runner=LocalAutoVerifyRunner())
    await svc.create_run(run)
    await _run_task_to_verified(svc, run.id, "task-1")

    updated = await svc.get_run(run.id)
    assert updated.status == RunStatus.COMPLETED
