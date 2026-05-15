"""Unit tests for super-parent service mechanics."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.workflow import (
    InMemorySignalTransport,
    InvalidTransitionError,
    WorkflowService,
    WorkflowSignal,
)
from orchestrator.config import AgentRunnerType, RunStatus, TaskStatus
from orchestrator.db import RunRepository, create_engine, create_session_factory, init_db
from orchestrator.state import Attempt, Run, StepState, TaskState
from tests.unit.git_helpers import _commit_file, _git, _init_repo


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
        agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
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


async def test_collect_run_evidence_accepts_evidence_directory_with_slice_filename(
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    child_dir = tmp_path / "child-wt"
    child_dir.mkdir()
    _init_repo(child_dir)
    base_sha = _git(["rev-parse", "HEAD"], cwd=child_dir)

    evidence_dir = child_dir / "docs" / "super-parent" / "evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "slice-p6-python-hypothesis.json").write_text(
        json.dumps(_valid_evidence_bundle("behavior_already_correct")),
        encoding="utf-8",
    )
    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.COMPLETED,
        worktree_path=str(child_dir),
    )
    child.source_branch_sha = base_sha

    await service.create_run(child)

    evidence = await service.collect_run_evidence("child")

    assert [item["path"] for item in evidence] == [
        "docs/super-parent/evidence/slice-p6-python-hypothesis.json"
    ]
    assert evidence[0]["bundle"]["outcome"] == "behavior_already_correct"


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

    parent_after_review = await service.get_run("parent")
    review_states = parent_after_review.oversight_state["delegation_review_states"]
    assert review_states[-1]["work_id"] == "child"
    assert review_states[-1]["stable_state"] == "InvalidEvidence"


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


async def test_accept_child_run_rejects_mismatched_evidence_identity(
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    parent = _parent_run(parent_id="parent")
    parent.worktree_path = str(tmp_path / "parent-wt")
    (tmp_path / "parent-wt").mkdir()

    child_dir = tmp_path / "child-wt"
    evidence_dir = child_dir / "docs" / "run-evidence"
    evidence_dir.mkdir(parents=True)
    bundle = _valid_evidence_bundle("verified_fix")
    bundle["slice_id"] = "wrong-slice"
    bundle["routine_id"] = "wrong-routine"
    (evidence_dir / "slice-01-evidence.json").write_text(
        json.dumps(bundle),
        encoding="utf-8",
    )

    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.COMPLETED,
        worktree_path=str(child_dir),
    )
    child.routine_id = "child-routine"

    await service.create_run(parent)
    await service.create_run(child)

    with pytest.raises(
        InvalidTransitionError,
        match="slice_id: expected 'slice-01', got 'wrong-slice'",
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

    parent_after_review = await service.get_run("parent")
    review_states = parent_after_review.oversight_state["delegation_review_states"]
    assert review_states[-1]["work_id"] == "child"
    assert review_states[-1]["reason"] == "child_acceptance_evidence_missing"


async def test_accept_child_run_records_merge_conflict_review_state(
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _commit_file(repo, "shared.txt", "base\n", "Add shared file")

    _git(["checkout", "-b", "orchestrator/run-parent"], cwd=repo)
    _commit_file(repo, "shared.txt", "parent\n", "Parent edit")

    _git(["checkout", "main"], cwd=repo)
    _git(["checkout", "-b", "orchestrator/run-child"], cwd=repo)
    evidence_dir = repo / "docs" / "run-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "slice-01-evidence.json").write_text(
        json.dumps(_valid_evidence_bundle("verified_fix")),
        encoding="utf-8",
    )
    _commit_file(repo, "shared.txt", "child\n", "Child edit")
    _git(["add", "docs/run-evidence/slice-01-evidence.json"], cwd=repo)
    _git(["commit", "-m", "Add evidence"], cwd=repo)

    child_worktree = tmp_path / "child-wt"
    _git(["checkout", "orchestrator/run-parent"], cwd=repo)
    _git(["worktree", "add", str(child_worktree), "orchestrator/run-child"], cwd=repo)

    parent = _parent_run(parent_id="parent")
    parent.worktree_path = str(repo)
    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.COMPLETED,
        worktree_path=str(child_worktree),
    )
    child.routine_id = "child-routine"

    await service.create_run(parent)
    await service.create_run(child)

    result = await service.accept_child_run("parent", "child")

    assert result.status == "conflicts"
    parent_after_conflict = await service.get_run("parent")
    review_states = parent_after_conflict.oversight_state["delegation_review_states"]
    assert review_states[-1]["stable_state"] == "MergeConflict"
    assert review_states[-1]["payload"]["conflict_files"] == ["shared.txt"]
    assert parent_after_conflict.oversight_state["delegation_decisions"][-1]["kind"] == "conflict"
    assert parent_after_conflict.oversight_state["delegated_work"]["child"]["status"] == "review"


async def test_accept_child_run_records_integrate_command_and_generation(
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _commit_file(repo, "base.txt", "base\n", "Add base file")

    _git(["checkout", "-b", "orchestrator/run-parent"], cwd=repo)
    _commit_file(repo, "parent.txt", "parent\n", "Parent edit")

    _git(["checkout", "main"], cwd=repo)
    _git(["checkout", "-b", "orchestrator/run-child"], cwd=repo)
    evidence_dir = repo / "docs" / "run-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "slice-01-evidence.json").write_text(
        json.dumps(_valid_evidence_bundle("verified_fix")),
        encoding="utf-8",
    )
    _commit_file(repo, "child.txt", "child\n", "Child edit")
    _git(["add", "docs/run-evidence/slice-01-evidence.json"], cwd=repo)
    _git(["commit", "-m", "Add evidence"], cwd=repo)

    child_worktree = tmp_path / "child-wt"
    _git(["checkout", "orchestrator/run-parent"], cwd=repo)
    _git(["worktree", "add", str(child_worktree), "orchestrator/run-child"], cwd=repo)

    parent = _parent_run(parent_id="parent")
    parent.worktree_path = str(repo)
    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.COMPLETED,
        worktree_path=str(child_worktree),
    )
    child.routine_id = "child-routine"

    await service.create_run(parent)
    await service.create_run(child)

    result = await service.accept_child_run("parent", "child")

    assert result.status == "clean"
    parent_after_accept = await service.get_run("parent")
    delegated_child = parent_after_accept.oversight_state["delegated_work"]["child"]
    assert delegated_child["status"] == "integrated"
    integrate_decisions = [
        item
        for item in parent_after_accept.oversight_state["delegation_decisions"]
        if item.get("work_id") == "child" and item.get("kind") == "integrate"
    ]
    assert integrate_decisions
    assert (
        parent_after_accept.oversight_state["delegation_results"][-1]["generation"]
        == (delegated_child["generation"])
    )

    duplicate = await service.accept_child_run("parent", "child")

    assert duplicate.status == "clean"
    parent_after_duplicate = await service.get_run("parent")
    accepted_children = [
        item
        for item in parent_after_duplicate.oversight_state["accepted_children"]
        if item.get("child_run_id") == "child"
    ]
    assert len(accepted_children) == 1
    assert parent_after_duplicate.oversight_state["delegation_decisions"][-1]["kind"] == (
        "stale_command_ignored"
    )
    assert parent_after_duplicate.oversight_state["delegation_decisions"][-1]["reason"] == (
        "duplicate_command"
    )


async def test_accept_child_run_stale_generation_or_token_prevents_merge_side_effects(
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
        match="accept_child_run \\(stale delegation command\\)",
    ):
        await service.accept_child_run("parent", "child", expected_generation=0)

    parent_after_generation = await service.get_run("parent")
    assert parent_after_generation.oversight_state["delegation_decisions"][-1]["reason"] == (
        "generation_mismatch"
    )
    assert parent_after_generation.oversight_state.get("accepted_child_run_ids") in (None, [])

    with pytest.raises(
        InvalidTransitionError,
        match="accept_child_run \\(stale delegation command\\)",
    ):
        await service.accept_child_run("parent", "child", owner_token="wrong-owner")

    parent_after_token = await service.get_run("parent")
    assert parent_after_token.oversight_state["delegation_decisions"][-1]["reason"] == (
        "owner_token_mismatch"
    )
    assert parent_after_token.oversight_state.get("accepted_child_run_ids") in (None, [])


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


async def test_apply_pause_run_does_not_cascade_on_server_shutdown(
    service: WorkflowService,
) -> None:
    """Server-shutdown pauses must not cascade to children.

    System-wide pauses are caught by each run's own asyncio loop, so the
    cascade would clobber the correct ``server_shutdown`` reason with a
    ``parent_server_shutdown`` prefix that historically skipped auto-resume.
    """
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

    paused_parent = await service.apply_pause_run("parent", reason="server_shutdown")

    assert paused_parent.status == RunStatus.PAUSED
    assert paused_parent.pause_reason == "server_shutdown"

    untouched_child = await service.get_run("child")
    # The child's own runtime loop is responsible for self-pausing; the parent
    # cascade must leave it alone.
    assert untouched_child.status == RunStatus.ACTIVE
    assert untouched_child.pause_reason is None


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


async def test_safety_net_save_applies_terminal_guard(
    service: WorkflowService,
    session: AsyncSession,
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
    assert "terminal_guard" not in guarded.oversight_state
    raw_parent = await RunRepository(session).get("parent")
    for computed_key in (
        "child_count",
        "child_summaries",
        "terminal_guard",
        "next_parent_action",
        "attention_items",
    ):
        assert computed_key not in raw_parent.oversight_state
    projection = await service.get_parent_oversight("parent")
    assert "child: child_not_terminal:active" in projection["terminal_guard"]["blocking_reasons"]
    assert projection["delegation_decisions"][-1]["kind"] == "wait"
    assert projection["delegation_decisions"][-1]["stable_state"] == ("WaitingOnDelegate")


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
    parent_after_rejection = await service.get_run("parent")
    assert parent_after_rejection.oversight_state["delegation_decisions"][-1]["kind"] == ("review")
    assert parent_after_rejection.oversight_state["delegation_decisions"][-1]["reason"] == (
        "parent_not_active"
    )


async def test_create_child_run_enqueues_child_start(session: AsyncSession) -> None:
    transport = InMemorySignalTransport()
    service = WorkflowService(session, signal_transport=transport)
    parent = _parent_run(parent_id="parent")
    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.DRAFT,
        worktree_path="/tmp/child-worktree",
    )

    await service.create_run(parent)
    await service.create_child_run(
        "parent",
        child,
        parent_slice_id="slice-01",
        next_action_decision="continue",
    )

    signals = await transport.drain("child")
    assert [signal.signal_type for signal in signals] == [WorkflowSignal.RUN_START]
    parent_after_child = await service.get_run("parent")
    assert parent_after_child.oversight_state["child_count"] == 1
    assert parent_after_child.oversight_state["last_child_run_id"] == "child"
    assert (
        "no_child_runs"
        not in parent_after_child.oversight_state["terminal_guard"]["blocking_reasons"]
    )
    raw_parent = await RunRepository(session).get("parent")
    for computed_key in (
        "child_count",
        "child_summaries",
        "merge_queue",
        "terminal_guard",
        "next_parent_action",
        "attention_items",
    ):
        assert computed_key not in raw_parent.oversight_state
    assert raw_parent.oversight_state["last_child_run_id"] == "child"


async def test_concurrent_create_child_run_keeps_single_unresolved_child(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "coordination.sqlite")
    await init_db(engine)
    factory = create_session_factory(engine)
    parent = _parent_run(parent_id="parent")

    async with factory() as setup_session:
        await WorkflowService(setup_session).create_run(parent)

    async def create_child(child_id: str) -> object:
        async with factory() as child_session:
            service = WorkflowService(
                child_session,
                signal_transport=InMemorySignalTransport(),
            )
            child = _child_run(
                child_id=child_id,
                parent_id="parent",
                status=RunStatus.DRAFT,
                worktree_path=f"/tmp/{child_id}-worktree",
            )
            return await service.create_child_run(
                "parent",
                child,
                parent_slice_id=f"slice-{child_id}",
                next_action_decision="continue",
            )

    results = await asyncio.gather(
        create_child("child-a"),
        create_child("child-b"),
        return_exceptions=True,
    )

    successful = [result for result in results if isinstance(result, Run)]
    failures = [result for result in results if isinstance(result, InvalidTransitionError)]
    assert len(successful) == 1
    assert len(failures) == 1

    async with factory() as verify_session:
        verify_service = WorkflowService(verify_session)
        children = await verify_service.list_child_runs("parent")
        assert [child.id for child in children] == [successful[0].id]
        raw_parent = await RunRepository(verify_session).get("parent")
        assert len(raw_parent.oversight_state["slices"]) == 1
        assert list(raw_parent.oversight_state["delegated_work"]) == [successful[0].id]

    await engine.dispose()


async def test_locked_oversight_merge_uses_fresh_state_from_loaded_session(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "locked-merge.sqlite")
    await init_db(engine)
    factory = create_session_factory(engine)
    parent = _parent_run(parent_id="parent")

    async with factory() as setup_session:
        await WorkflowService(setup_session).create_run(parent)

    async with factory() as stale_session:
        stale_repo = RunRepository(stale_session)
        await stale_repo.get("parent")

        async with factory() as writer_session:
            writer_repo = RunRepository(writer_session)
            await writer_repo.update_parent_oversight_facts(
                "parent",
                {
                    "delegation_results": [
                        {
                            "work_id": "child-a",
                            "generation": 0,
                            "terminal_status": "completed",
                        }
                    ]
                },
            )
            await writer_session.commit()

        await stale_repo.update_parent_oversight_facts(
            "parent",
            {
                "delegation_decisions": [
                    {
                        "kind": "wait",
                        "work_id": "child-b",
                    }
                ]
            },
        )
        await stale_session.commit()

    async with factory() as verify_session:
        raw_parent = await RunRepository(verify_session).get("parent")
        assert raw_parent.oversight_state["delegation_results"] == [
            {
                "work_id": "child-a",
                "generation": 0,
                "terminal_status": "completed",
            }
        ]
        assert raw_parent.oversight_state["delegation_decisions"] == [
            {
                "kind": "wait",
                "work_id": "child-b",
            }
        ]

    await engine.dispose()


async def test_duplicate_create_child_run_is_typed_noop(
    session: AsyncSession,
) -> None:
    transport = InMemorySignalTransport()
    service = WorkflowService(session, signal_transport=transport)
    parent = _parent_run(parent_id="parent")
    first_child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.DRAFT,
        worktree_path="/tmp/child-worktree",
    )
    duplicate_child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.DRAFT,
        worktree_path="/tmp/child-worktree",
    )

    await service.create_run(parent)
    created = await service.create_child_run(
        "parent",
        first_child,
        parent_slice_id="slice-01",
        next_action_decision="continue",
    )
    duplicate = await service.create_child_run(
        "parent",
        duplicate_child,
        parent_slice_id="slice-01",
        next_action_decision="continue",
    )

    assert duplicate.id == created.id
    first_signals = await transport.drain("child")
    assert [signal.signal_type for signal in first_signals] == [WorkflowSignal.RUN_START]
    assert await transport.drain("child") == []
    children = await service.list_child_runs("parent")
    assert [child.id for child in children] == ["child"]
    parent_after_duplicate = await service.get_run("parent")
    assert parent_after_duplicate.oversight_state["delegation_decisions"][-1]["kind"] == (
        "stale_command_ignored"
    )
    assert parent_after_duplicate.oversight_state["delegation_decisions"][-1]["reason"] == (
        "duplicate_child_create"
    )


async def test_create_child_run_rejects_child_without_executor(
    service: WorkflowService,
) -> None:
    parent = _parent_run(parent_id="parent")
    child = _child_run(
        child_id="child",
        parent_id="parent",
        status=RunStatus.DRAFT,
        worktree_path="/tmp/child-worktree",
    )
    child.agent_runner_type = None

    await service.create_run(parent)

    with pytest.raises(
        InvalidTransitionError,
        match="create_child_run \\(requires managed agent runner\\)",
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


async def test_resolve_child_run_unblocks_replacement_child(
    session: AsyncSession,
) -> None:
    transport = InMemorySignalTransport()
    service = WorkflowService(session, signal_transport=transport)
    parent = _parent_run(parent_id="parent")
    failed_child = _child_run(
        child_id="failed-child",
        parent_id="parent",
        status=RunStatus.FAILED,
        worktree_path="/tmp/failed-child-worktree",
    )
    next_child = _child_run(
        child_id="next-child",
        parent_id="parent",
        status=RunStatus.DRAFT,
        worktree_path="/tmp/next-child-worktree",
    )

    await service.create_run(parent)
    await service.create_run(failed_child)

    result = await service.resolve_child_run(
        "parent",
        "failed-child",
        resolution="reject",
        reason="Attempt failed and replacement slice is required.",
    )

    assert result.resolution == "reject"
    parent_after_resolution = await service.get_run("parent")
    assert parent_after_resolution.oversight_state["rejected_child_run_ids"] == ["failed-child"]
    assert parent_after_resolution.oversight_state["next_parent_action"] == "launch_child"
    assert (
        "failed-child: failed_child_unresolved"
        not in parent_after_resolution.oversight_state["terminal_guard"]["blocking_reasons"]
    )
    assert parent_after_resolution.oversight_state["decisions"][-1]["action"] == "reject"

    await service.create_child_run(
        "parent",
        next_child,
        parent_slice_id="slice-02",
        next_action_decision="replan",
    )

    signals = await transport.drain("next-child")
    assert [signal.signal_type for signal in signals] == [WorkflowSignal.RUN_START]


async def test_resolve_retryable_runner_failure_keeps_existing_child(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    service = WorkflowService(session)
    worktree = tmp_path / "retryable-child"
    worktree.mkdir()
    _init_repo(worktree)
    parent = _parent_run(parent_id="parent")
    paused_child = _child_run(
        child_id="paused-child",
        parent_id="parent",
        status=RunStatus.PAUSED,
        worktree_path=str(worktree),
    )
    paused_child.pause_reason = "agent_execution_error"
    paused_child.last_error = "API Error: 529 Overloaded"

    await service.create_run(parent)
    await service.create_run(paused_child)

    with pytest.raises(
        InvalidTransitionError,
        match="resolve_child_run \\(retryable runner failure; resume existing child\\)",
    ):
        await service.resolve_child_run(
            "parent",
            "paused-child",
            resolution="reject",
            reason="Runner failed before the child could work.",
        )

    parent_after = await service.refresh_parent_oversight("parent")
    assert parent_after.oversight_state["rejected_child_run_ids"] == []
    assert parent_after.oversight_state["retryable_child_run_ids"] == ["paused-child"]
    assert parent_after.oversight_state["next_parent_action"] == "wait_for_child"


async def test_collect_evidence_synthesizes_turn_limit_partial_progress(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    service = WorkflowService(session)
    worktree = tmp_path / "turn-limit-child"
    worktree.mkdir()
    _init_repo(worktree)
    base_sha = _git(["rev-parse", "HEAD"], cwd=worktree)
    (worktree / "changed.py").write_text("print('partial')\n", encoding="utf-8")
    parent = _parent_run(parent_id="parent")
    child = _child_run(
        child_id="turn-limit-child",
        parent_id="parent",
        status=RunStatus.PAUSED,
        worktree_path=str(worktree),
    )
    child.routine_id = "child-slice-01"
    child.source_branch_sha = base_sha
    child.pause_reason = "agent_execution_error"
    child.last_error = "Agent hit the max-turns limit without completing (exit code 1)"

    await service.create_run(parent)
    await service.create_run(child)

    evidence = await service.collect_validated_run_evidence(
        "turn-limit-child",
        expected_slice_id="slice-01",
        expected_routine_id="child-slice-01",
    )

    assert evidence["invalid_evidence"] == []
    assert len(evidence["evidence"]) == 1
    bundle = evidence["evidence"][0]["bundle"]
    assert bundle["outcome"] == "partial_progress"
    assert bundle["next_recommendation"] == "replan"
    assert bundle["files_changed"] == ["changed.py"]
    assert "turn limit" in bundle["summary"]


async def test_duplicate_resolve_child_run_is_typed_noop(
    service: WorkflowService,
) -> None:
    parent = _parent_run(parent_id="parent")
    failed_child = _child_run(
        child_id="failed-child",
        parent_id="parent",
        status=RunStatus.FAILED,
        worktree_path="/tmp/failed-child-worktree",
    )

    await service.create_run(parent)
    await service.create_run(failed_child)

    first = await service.resolve_child_run(
        "parent",
        "failed-child",
        resolution="reject",
        reason="Attempt failed and replacement slice is required.",
    )
    second = await service.resolve_child_run(
        "parent",
        "failed-child",
        resolution="reject",
        reason="Duplicate callback for the same decision.",
    )

    assert first.resolution == second.resolution == "reject"
    parent_after_resolution = await service.get_run("parent")
    assert parent_after_resolution.oversight_state["rejected_child_run_ids"] == ["failed-child"]
    decisions = parent_after_resolution.oversight_state["decisions"]
    child_resolutions = [
        decision
        for decision in decisions
        if decision.get("kind") == "child_resolution"
        and decision.get("child_run_id") == "failed-child"
    ]
    assert len(child_resolutions) == 1
    assert parent_after_resolution.oversight_state["delegation_decisions"][-1]["kind"] == (
        "stale_command_ignored"
    )
    assert parent_after_resolution.oversight_state["delegation_decisions"][-1]["reason"] == (
        "duplicate_child_resolution"
    )


async def test_stale_child_wait_observation_is_recorded_without_wait(
    service: WorkflowService,
) -> None:
    parent = _parent_run(parent_id="parent")
    parent.oversight_state = {"delegation_owner_token": "owner-current"}
    active_child = _child_run(
        child_id="active-child",
        parent_id="parent",
        status=RunStatus.ACTIVE,
        worktree_path="/tmp/active-child-worktree",
    )

    await service.create_run(parent)
    await service.create_run(active_child)

    updated = await service.record_child_wait_observation(
        "parent",
        "active-child",
        observed_status=RunStatus.ACTIVE,
        phase="observed",
        timeout_seconds=1,
        owner_token="owner-previous",
        idempotency_key="old-wait-callback",
    )

    assert updated.oversight_state["child_waits"] == []
    assert updated.oversight_state["delegation_decisions"][-1]["kind"] == ("stale_command_ignored")
    assert updated.oversight_state["delegation_decisions"][-1]["reason"] == ("owner_token_mismatch")


async def test_observe_running_child_records_wait_observation(
    service: WorkflowService,
) -> None:
    parent = _parent_run(parent_id="parent")
    active_child = _child_run(
        child_id="active-child",
        parent_id="parent",
        status=RunStatus.ACTIVE,
        worktree_path="/tmp/active-child-worktree",
    )

    await service.create_run(parent)
    await service.create_run(active_child)

    updated = await service.record_child_wait_observation(
        "parent",
        "active-child",
        observed_status=RunStatus.ACTIVE,
        phase="observed",
        timeout_seconds=1,
        idempotency_key="wait-callback",
    )

    assert updated.oversight_state["child_waits"][-1]["child_run_id"] == "active-child"
    assert updated.oversight_state["delegation_decisions"][-1]["kind"] == "wait"
    assert updated.oversight_state["delegation_decisions"][-1]["stable_state"] == (
        "WaitingOnDelegate"
    )

    duplicate = await service.record_child_wait_observation(
        "parent",
        "active-child",
        observed_status=RunStatus.ACTIVE,
        phase="observed",
        timeout_seconds=1,
        idempotency_key="wait-callback",
    )

    assert len(duplicate.oversight_state["child_waits"]) == 1
    assert duplicate.oversight_state["delegation_decisions"][-1]["kind"] == (
        "stale_command_ignored"
    )
    assert duplicate.oversight_state["delegation_decisions"][-1]["reason"] == ("duplicate_command")


async def test_stale_child_wait_generation_is_recorded_without_wait(
    service: WorkflowService,
) -> None:
    parent = _parent_run(parent_id="parent")
    active_child = _child_run(
        child_id="active-child",
        parent_id="parent",
        status=RunStatus.ACTIVE,
        worktree_path="/tmp/active-child-worktree",
    )

    await service.create_run(parent)
    await service.create_run(active_child)

    updated = await service.record_child_wait_observation(
        "parent",
        "active-child",
        observed_status=RunStatus.ACTIVE,
        phase="observed",
        timeout_seconds=1,
        expected_generation=0,
        idempotency_key="old-generation-wait-callback",
    )

    assert updated.oversight_state["child_waits"] == []
    assert updated.oversight_state["delegation_decisions"][-1]["kind"] == ("stale_command_ignored")
    assert updated.oversight_state["delegation_decisions"][-1]["reason"] == ("generation_mismatch")


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
