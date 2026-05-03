"""Unit tests for super-parent service mechanics."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import RunStatus, TaskStatus
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.state import Attempt, Run, StepState, TaskState
from orchestrator.workflow import InvalidTransitionError, WorkflowService
from tests.unit.git_helpers import _git, _init_repo


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


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _parent_run(*, parent_id: str = "parent", status: RunStatus = RunStatus.ACTIVE) -> Run:
    return Run(
        id=parent_id,
        repo_name="proj-1",
        status=status,
        source_branch="main",
        created_at=_now(),
        updated_at=_now(),
    )


def _child_run(
    *,
    child_id: str,
    parent_id: str,
    status: RunStatus,
    worktree_path: str,
    include_open_attempt: bool = False,
) -> Run:
    tasks = []
    if include_open_attempt:
        tasks = [
            TaskState(
                id="child-task-1",
                config_id="T-01",
                status=TaskStatus.BUILDING,
                attempts=[
                    Attempt(
                        id="attempt-1",
                        attempt_num=1,
                        started_at=_now(),
                    )
                ],
                current_attempt=1,
            )
        ]

    return Run(
        id=child_id,
        repo_name="proj-1",
        status=status,
        parent_run_id=parent_id,
        parent_slice_id="slice-01",
        source_branch="main",
        steps=[
            StepState(
                id="child-step-1",
                config_id="S-01",
                tasks=tasks,
            )
        ],
        worktree_path=worktree_path,
        created_at=_now(),
        updated_at=_now(),
    )


def _valid_evidence_bundle(outcome: str) -> dict[str, object]:
    return {
        "schema_version": "run.evidence.v1",
        "slice_id": "slice-01",
        "routine_id": "child-routine",
        "assumption_tested": "The slice was exercised.",
        "summary": f"Outcome: {outcome}",
        "commands_run": [],
        "test_results": [],
        "target_bug_reproduced": "not_targeted",
        "real_frontend_path_exercised": False,
        "real_execution_surface": "unit",
        "files_changed": [],
        "evidence_files": [],
        "open_uncertainties": [],
        "next_recommendation": "proceed",
        "outcome": outcome,
    }


def _final_validation_marker(
    *,
    commit_sha: str,
    passed: bool = True,
) -> dict[str, object]:
    return {
        "passed": passed,
        "integrated_commit_sha": commit_sha,
        "report_path": "docs/super-parent/final-report.md",
        "commands_run": [
            {
                "command": "uv run pytest tests/unit/test_super_parent_service_mechanics.py",
                "exit_code": 0 if passed else 1,
                "stdout_excerpt": "",
                "stderr_excerpt": "",
            }
        ],
        "evidence_files": ["docs/super-parent/final-report.md"],
    }


def _prepare_final_validation_worktree(tmp_path: Path) -> tuple[Path, str]:
    worktree = tmp_path / "parent-wt"
    worktree.mkdir()
    _init_repo(worktree)
    report_path = worktree / "docs" / "super-parent" / "final-report.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("# Final validation\n", encoding="utf-8")
    return worktree, _git(["rev-parse", "HEAD"], cwd=worktree)


async def test_accept_child_run_rejects_malformed_verified_fix_evidence(
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    parent = _parent_run(parent_id="parent")
    parent.worktree_path = str(tmp_path / "parent-wt")
    (tmp_path / "parent-wt").mkdir()

    child_dir = tmp_path / "child-wt"
    evidence_dir = child_dir / "docs" / "run-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "slice-01-evidence.json").write_text(
        '{"schema_version": "run.evidence.v1", "outcome": "verified_fix"}',
        encoding="utf-8",
    )

    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.COMPLETED,
        worktree_path=str(child_dir),
    )

    await service.create_run(parent)
    await service.create_run(child)

    with pytest.raises(
        InvalidTransitionError,
        match="accept_child_run \\(invalid run.evidence.v1 bundle\\)",
    ):
        await service.accept_child_run("parent", "child")


async def test_accept_child_run_rejects_contradictory_evidence(
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    parent = _parent_run(parent_id="parent")
    parent.worktree_path = str(tmp_path / "parent-wt")
    (tmp_path / "parent-wt").mkdir()

    child_dir = tmp_path / "child-wt"
    evidence_dir = child_dir / "docs" / "run-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "slice-01-evidence.json").write_text(
        json.dumps(_valid_evidence_bundle("verified_fix")),
        encoding="utf-8",
    )
    (evidence_dir / "slice-01-revision-evidence.json").write_text(
        json.dumps(_valid_evidence_bundle("needs_revision")),
        encoding="utf-8",
    )

    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.COMPLETED,
        worktree_path=str(child_dir),
    )

    await service.create_run(parent)
    await service.create_run(child)

    with pytest.raises(
        InvalidTransitionError,
        match="accept_child_run \\(evidence contains non-acceptance outcome\\)",
    ):
        await service.accept_child_run("parent", "child")


async def test_accept_child_run_rejects_missing_evidence(
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    parent = _parent_run(parent_id="parent")
    parent.worktree_path = str(tmp_path / "parent-wt")
    (tmp_path / "parent-wt").mkdir()

    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.COMPLETED,
        worktree_path=str(tmp_path / "child-wt"),
    )
    (tmp_path / "child-wt").mkdir()

    await service.create_run(parent)
    await service.create_run(child)

    with pytest.raises(
        InvalidTransitionError,
        match="accept_child_run \\(requires verified_fix or behavior_already_correct evidence\\)",
    ):
        await service.accept_child_run("parent", "child")


async def test_apply_pause_run_pauses_active_child_and_marks_open_attempts(
    service: WorkflowService,
) -> None:
    parent = _parent_run(parent_id="parent")
    parent.worktree_path = "/tmp/parent-worktree"

    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.ACTIVE,
        worktree_path="/tmp/child-worktree",
        include_open_attempt=True,
    )

    await service.create_run(parent)
    await service.create_run(child)

    paused_parent = await service.apply_pause_run("parent")

    assert paused_parent.status == RunStatus.PAUSED
    assert paused_parent.pause_reason == "manual_pause"

    paused_child = await service.get_run("child")
    assert paused_child.status == RunStatus.PAUSED
    assert paused_child.pause_reason == "parent_manual_pause"
    attempt = paused_child.steps[0].tasks[0].attempts[0]
    assert attempt.paused_at is not None
    assert attempt.outcome == "paused"


async def test_update_parent_oversight_can_satisfy_terminal_guard(
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    worktree, head_commit = _prepare_final_validation_worktree(tmp_path)
    parent = _parent_run(parent_id="parent")
    parent.worktree_path = str(worktree)
    parent.oversight_state = {"accepted_child_run_ids": ["child"]}
    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.COMPLETED,
        worktree_path="/tmp/child-worktree",
    )

    await service.create_run(parent)
    await service.create_run(child)

    updated = await service.update_parent_oversight(
        "parent",
        target_inventory=[{"id": "INV-001", "resolved": True}],
        final_validation=_final_validation_marker(commit_sha=head_commit),
        decisions=[{"kind": "final_validation", "outcome": "passed"}],
    )

    assert updated.oversight_state["target_inventory"] == [
        {
            "schema_version": "super_parent.target_inventory.v1",
            "id": "INV-001",
            "in_scope": True,
            "resolved": True,
        }
    ]
    assert updated.oversight_state["final_validation"]["passed"] is True
    assert updated.oversight_state["final_validation"]["service_verified"] is True
    assert updated.oversight_state["terminal_guard"]["can_complete"] is True
    assert updated.oversight_state["next_parent_action"] == "complete_parent"


async def test_update_parent_oversight_rejects_mismatched_final_validation_commit(
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    worktree, _ = _prepare_final_validation_worktree(tmp_path)
    parent = _parent_run(parent_id="parent")
    parent.worktree_path = str(worktree)

    await service.create_run(parent)

    with pytest.raises(
        InvalidTransitionError,
        match="update_parent_oversight \\(final validation commit does not match parent HEAD\\)",
    ):
        await service.update_parent_oversight(
            "parent",
            target_inventory=[{"id": "INV-001", "resolved": True}],
            final_validation=_final_validation_marker(commit_sha="abc1234"),
        )


async def test_refresh_parent_oversight_invalidates_stale_final_validation(
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    worktree, head_commit = _prepare_final_validation_worktree(tmp_path)
    marker = _final_validation_marker(commit_sha=head_commit)
    marker["service_verified"] = True
    parent = _parent_run(parent_id="parent")
    parent.worktree_path = str(worktree)
    parent.oversight_state = {
        "accepted_child_run_ids": ["child"],
        "target_inventory": [{"id": "INV-001", "resolved": True}],
        "final_validation": marker,
    }
    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.COMPLETED,
        worktree_path="/tmp/child-worktree",
    )

    await service.create_run(parent)
    await service.create_run(child)

    (worktree / "later.txt").write_text("new parent work\n", encoding="utf-8")
    _git(["add", "later.txt"], cwd=worktree)
    _git(["commit", "-m", "Change parent head"], cwd=worktree)
    assert _git(["rev-parse", "HEAD"], cwd=worktree) != head_commit

    refreshed = await service.refresh_parent_oversight("parent")

    assert refreshed.oversight_state["final_validation"] is None
    assert (
        "final_validation_marker_missing"
        in refreshed.oversight_state["terminal_guard"]["blocking_reasons"]
    )


async def test_safety_net_save_applies_oversight_guard(
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    parent = _parent_run(parent_id="parent", status=RunStatus.COMPLETED)
    parent.completed_at = _now()
    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.ACTIVE,
        worktree_path=str(tmp_path / "child-worktree"),
    )

    await service.create_run(parent)
    await service.create_run(child)

    guarded = await service.save_run_with_oversight_terminal_guard(parent)

    assert guarded.status == RunStatus.PAUSED
    assert guarded.pause_reason == "oversight_children_unresolved"
    assert guarded.completed_at is None
    assert (
        "child: child_not_terminal:active"
        in guarded.oversight_state["terminal_guard"]["blocking_reasons"]
    )


async def test_create_child_run_rejects_paused_parent(service: WorkflowService) -> None:
    parent = _parent_run(parent_id="parent", status=RunStatus.PAUSED)
    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.DRAFT,
        worktree_path="/tmp/child-worktree",
    )

    await service.create_run(parent)

    with pytest.raises(
        InvalidTransitionError,
        match="create_child_run \\(requires active parent\\)",
    ):
        await service.create_child_run(
            "parent",
            child,
            parent_slice_id="slice-01",
            next_action_decision="continue",
        )


async def test_create_child_run_rejects_second_active_child(
    service: WorkflowService,
) -> None:
    parent = _parent_run(parent_id="parent")
    active_child = _child_run(
        child_id="active-child",
        parent_id="parent",
        status=RunStatus.ACTIVE,
        worktree_path="/tmp/active-child-worktree",
    )
    next_child = _child_run(
        child_id="next-child",
        parent_id="parent",
        status=RunStatus.DRAFT,
        worktree_path="/tmp/next-child-worktree",
    )

    await service.create_run(parent)
    await service.create_run(active_child)

    with pytest.raises(
        InvalidTransitionError,
        match="create_child_run \\(unresolved child already exists\\)",
    ):
        await service.create_child_run(
            "parent",
            next_child,
            parent_slice_id="slice-02",
            next_action_decision="continue",
        )


async def test_create_child_run_rejects_unresolved_paused_child(
    service: WorkflowService,
) -> None:
    parent = _parent_run(parent_id="parent")
    paused_child = _child_run(
        child_id="paused-child",
        parent_id="parent",
        status=RunStatus.PAUSED,
        worktree_path="/tmp/paused-child-worktree",
    )
    next_child = _child_run(
        child_id="next-child",
        parent_id="parent",
        status=RunStatus.DRAFT,
        worktree_path="/tmp/next-child-worktree",
    )

    await service.create_run(parent)
    await service.create_run(paused_child)

    with pytest.raises(
        InvalidTransitionError,
        match="create_child_run \\(unresolved child already exists\\)",
    ):
        await service.create_child_run(
            "parent",
            next_child,
            parent_slice_id="slice-02",
            next_action_decision="continue",
        )


async def test_create_child_run_enforces_configured_child_limit(
    service: WorkflowService,
) -> None:
    parent = _parent_run(parent_id="parent")
    parent.config = {"max_child_runs": 1}
    parent.oversight_state = {"accepted_child_run_ids": ["existing-child"]}
    existing_child = _child_run(
        child_id="existing-child",
        parent_id="parent",
        status=RunStatus.COMPLETED,
        worktree_path="/tmp/existing-child-worktree",
    )
    next_child = _child_run(
        child_id="next-child",
        parent_id="parent",
        status=RunStatus.DRAFT,
        worktree_path="/tmp/next-child-worktree",
    )

    await service.create_run(parent)
    await service.create_run(existing_child)

    with pytest.raises(
        InvalidTransitionError,
        match="create_child_run \\(max child run limit reached\\)",
    ):
        await service.create_child_run(
            "parent",
            next_child,
            parent_slice_id="slice-02",
            next_action_decision="continue",
        )
