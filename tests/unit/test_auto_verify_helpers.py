"""Unit tests for pure helper functions in the auto-verify workflow service.

Tests ``find_task_config`` and ``resolve_auto_verify_config`` directly,
without any database or subprocess execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from orchestrator.config import Priority, RoutineSource, RunStatus, TaskStatus
from orchestrator.state.models import ChecklistItem, Run, StepState, TaskState
from orchestrator.workflow.service import (
    find_task_config,
    resolve_auto_verify_config,
)


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
        worktree_path=project_path,
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
