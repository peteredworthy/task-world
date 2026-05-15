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
    assert "failed before child work began" in normalized
    assert "do not reject or abandon it and do not launch a replacement child" in normalized
    assert "service-provided synthetic evidence as `partial_progress`" in normalized
    assert "what the parent needed from the child" in normalized
    assert "what the child did" in normalized
    assert "what the parent needs the human to decide" in normalized
    assert "tool schema is canonical" in normalized
    assert "schema-supported select question with explicit options" in normalized
    assert "do not encode choices inside a free-text question" in normalized

    r5 = next(req for req in task.requirements if req.id == "R5")
    assert "Human clarification requests are concise" in r5.desc
    assert "select options for finite decisions" in r5.desc


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


def test_super_parent_declares_model_profiles() -> None:
    routine = load_routine_from_path(ROUTINE_PATH)
    profiles = {
        f"{step.id}/{task.id}": task.profile.value if task.profile else None
        for step in routine.steps
        for task in step.tasks
    }

    assert profiles == {
        "SP-01/T-01": "architect",
        "SP-02/T-01": "architect",
        "SP-03/T-01": "coder",
        "SP-04/T-01": "summarizer",
        "SP-04/T-02": "summarizer",
        "SP-05/T-01": "coder",
        "SP-05/T-02": "summarizer",
    }


def test_launch_child_run_declares_sequential_child_guard() -> None:
    normalized = " ".join(_task_context("SP-03", "T-01").split())

    assert "Before creating a child, enforce the sequential-child invariant" in normalized
    assert "terminal_guard.blocking_child_run_ids" in normalized
    assert "next_parent_action" in normalized
    assert "do not call `orchestrator_create_child_from_template`" in normalized
    assert "Never try to work around the invariant by creating a parallel child" in normalized
