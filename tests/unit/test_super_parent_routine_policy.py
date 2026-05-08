"""Tests for the super-parent routine policy contract."""

from pathlib import Path

from orchestrator.config import load_routine_from_path

ROUTINE_PATH = Path(__file__).parent.parent.parent / "routines" / "super-parent" / "routine.yaml"


def _task_context(step_id: str, task_id: str) -> str:
    routine = load_routine_from_path(ROUTINE_PATH)
    step = next(step for step in routine.steps if step.id == step_id)
    task = next(task for task in step.tasks if task.id == task_id)
    return task.task_context


def test_evaluate_child_evidence_is_orchestration_only() -> None:
    routine = load_routine_from_path(ROUTINE_PATH)
    step = next(step for step in routine.steps if step.id == "SP-04")
    task = next(task for task in step.tasks if task.id == "T-01")
    normalized = " ".join(task.task_context.split())

    assert task.work_mode == "oversight"
    assert "orchestration-only" in normalized
    assert "do not edit source code, tests, dependency files, lockfiles" in normalized
    assert "orchestrator_refresh_parent_oversight" in normalized
    assert "orchestrator_resolve_child_run" in normalized
    assert "orchestrator_request_clarification" in normalized
    assert "orchestrator_escalate_requirement" in normalized
    assert "paused, failed without schema-valid evidence" in normalized


def test_accept_and_merge_child_refuses_unacceptable_children() -> None:
    routine = load_routine_from_path(ROUTINE_PATH)
    step = next(step for step in routine.steps if step.id == "SP-04")
    task = next(task for task in step.tasks if task.id == "T-02")
    normalized = " ".join(task.task_context.split())

    assert task.work_mode == "oversight"
    assert "Read the current parent oversight state first" in normalized
    assert "merge queue" in normalized
    assert "orchestrator_accept_child_run" in normalized
    assert "orchestrator_resolve_child_run" in normalized
    assert "Do not merge failed, paused, unsupported, or missing-evidence children" in (normalized)
    assert "Do not manually run `git merge`" in normalized
    assert "edit source/tests" in normalized
    assert "record the no-op merge decision" in normalized

    r2 = next(req for req in task.requirements if req.id == "R2")
    assert "paused" in r2.desc
    assert "missing-evidence" in r2.desc
