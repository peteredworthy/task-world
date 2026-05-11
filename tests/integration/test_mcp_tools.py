"""Integration tests for MCP ToolHandler with real WorkflowService."""

import os
import subprocess
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config import ChecklistStatus, Priority, RoutineSource, RunStatus, TaskStatus
from orchestrator.db import EventStore, create_engine, create_session_factory, init_db
from orchestrator.api import ToolHandler
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


@pytest.fixture
def handler(service: WorkflowService) -> ToolHandler:
    return ToolHandler(service)


def _make_run() -> Run:
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
                                req_id="R1",
                                desc="First requirement",
                                priority=Priority.CRITICAL,
                            ),
                            ChecklistItem(
                                req_id="R2",
                                desc="Second requirement",
                                priority=Priority.EXPECTED,
                            ),
                        ],
                        max_attempts=3,
                    )
                ],
            )
        ],
        created_at=now,
        updated_at=now,
    )


EMBEDDED_ROUTINE: dict[str, object] = {
    "id": "mcp-child-slice",
    "name": "MCP Child Slice",
    "steps": [
        {
            "id": "S-01",
            "title": "Slice",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Prove child orchestration",
                    "task_context": "Prove child orchestration.",
                    "requirements": [{"id": "R1", "desc": "Done"}],
                }
            ],
        }
    ],
}


async def test_get_requirements(handler: ToolHandler, service: WorkflowService) -> None:
    run = _make_run()
    await service.create_run(run)

    result = await handler.handle(
        "orchestrator_get_requirements",
        {"run_id": "run-1", "task_id": "task-1"},
    )

    assert "requirements" in result
    reqs = result["requirements"]
    assert len(reqs) == 2
    assert reqs[0]["req_id"] == "R1"
    assert reqs[0]["desc"] == "First requirement"
    assert reqs[0]["priority"] == "critical"
    assert reqs[0]["status"] == "open"
    assert reqs[1]["req_id"] == "R2"


async def test_update_checklist(handler: ToolHandler, service: WorkflowService) -> None:
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    result = await handler.handle(
        "orchestrator_update_checklist",
        {
            "run_id": "run-1",
            "task_id": "task-1",
            "req_id": "R1",
            "status": "done",
            "note": "Completed via MCP",
        },
    )

    assert result["req_id"] == "R1"
    assert result["status"] == "done"
    assert result["note"] == "Completed via MCP"

    # Verify in service
    task = await service.get_task("run-1", "task-1")
    assert task.checklist[0].status == ChecklistStatus.DONE


async def test_submit(handler: ToolHandler, service: WorkflowService) -> None:
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    # Complete all critical requirements first
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.update_checklist_item("run-1", "task-1", "R2", ChecklistStatus.DONE)

    result = await handler.handle(
        "orchestrator_submit",
        {"run_id": "run-1", "task_id": "task-1"},
    )

    assert result["success"] is True
    assert result["new_status"] == "verifying"


async def test_set_grade(handler: ToolHandler, service: WorkflowService) -> None:
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    # Complete and submit
    await service.update_checklist_item("run-1", "task-1", "R1", ChecklistStatus.DONE)
    await service.update_checklist_item("run-1", "task-1", "R2", ChecklistStatus.DONE)
    await service.submit_for_verification("run-1", "task-1")

    result = await handler.handle(
        "orchestrator_set_grade",
        {
            "run_id": "run-1",
            "task_id": "task-1",
            "req_id": "R1",
            "grade": "A",
            "grade_reason": "Well done",
        },
    )

    assert result["req_id"] == "R1"
    assert result["grade"] == "A"
    assert result["grade_reason"] == "Well done"


async def test_unknown_tool(handler: ToolHandler) -> None:
    with pytest.raises(ValueError, match="Unknown tool"):
        await handler.handle("nonexistent_tool", {})


async def test_request_clarification_rejects_free_text_finite_choice(
    handler: ToolHandler,
    service: WorkflowService,
) -> None:
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    with pytest.raises(ValueError, match="finite choice"):
        await handler.handle(
            "orchestrator_request_clarification",
            {
                "run_id": "run-1",
                "task_id": "task-1",
                "questions": [
                    {
                        "question": "Pick: (a) accept it; (b) retry it; or (c) abandon it.",
                        "context": (
                            "Parent needed: decide. Child did: stopped. Decision needed: choose."
                        ),
                        "question_type": "free_text",
                        "options": [],
                    }
                ],
            },
        )


async def test_oversight_child_run_tools(
    handler: ToolHandler,
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    parent = _make_run()
    parent.status = RunStatus.ACTIVE
    parent_worktree = tmp_path / "parent-worktree"
    parent_worktree.mkdir()
    _init_repo(parent_worktree)
    report_path = parent_worktree / "docs" / "super-parent" / "final-report.md"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("# Final validation\n", encoding="utf-8")
    parent.worktree_path = str(parent_worktree)
    parent_head = _git(["rev-parse", "HEAD"], cwd=parent_worktree)
    await service.create_run(parent)

    create_result = await handler.handle(
        "orchestrator_create_child_run",
        {
            "parent_run_id": "run-1",
            "parent_slice_id": "slice-01",
            "routine_embedded": EMBEDDED_ROUTINE,
            "next_action_decision": "continue",
        },
    )
    child_id = create_result["child_run_id"]
    assert create_result["parent_run_id"] == "run-1"
    assert create_result["parent_slice_id"] == "slice-01"
    assert create_result["start_enqueued"] is True

    list_result = await handler.handle(
        "orchestrator_list_child_runs",
        {"parent_run_id": "run-1"},
    )
    assert [child["id"] for child in list_result["children"]] == [child_id]

    wait_result = await handler.handle(
        "orchestrator_wait_for_run",
        {"run_id": child_id, "timeout_seconds": 0},
    )
    assert wait_result["run_id"] == child_id
    assert wait_result["terminal"] is False
    assert wait_result["meaningful_state"] is False

    parent_after_wait = await service.get_run("run-1")
    assert [item["phase"] for item in parent_after_wait.oversight_state["child_waits"]] == [
        "started",
        "observed",
    ]

    worktree = tmp_path / "worktree"
    evidence_dir = worktree / "docs" / "run-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "slice-01-evidence.json").write_text(
        """{
  "schema_version": "run.evidence.v1",
  "slice_id": "slice-01",
  "routine_id": "mcp-child-slice",
  "assumption_tested": "MCP can retrieve native child evidence.",
  "summary": "Evidence returned through ToolHandler.",
  "commands_run": [{"command": "printf ok", "exit_code": 0, "stdout_excerpt": "ok", "stderr_excerpt": ""}],
  "test_results": [{"name": "mcp evidence", "status": "passed", "details": "valid"}],
  "target_bug_reproduced": "not_targeted",
  "real_frontend_path_exercised": false,
  "real_execution_surface": "MCP ToolHandler",
  "files_changed": ["docs/run-evidence/slice-01-evidence.json"],
  "evidence_files": ["docs/run-evidence/slice-01-evidence.json"],
  "open_uncertainties": [],
  "next_recommendation": "proceed",
  "outcome": "verified_fix"
}""",
        encoding="utf-8",
    )
    await service.set_worktree_path(child_id, str(worktree))

    evidence_result = await handler.handle("orchestrator_get_run_evidence", {"run_id": child_id})
    assert evidence_result["evidence"][0]["bundle"]["outcome"] == "verified_fix"

    refresh_result = await handler.handle(
        "orchestrator_refresh_parent_oversight",
        {"run_id": "run-1"},
    )
    assert refresh_result["oversight_state"]["child_count"] == 1
    assert refresh_result["oversight_state"]["terminal_guard"]["can_complete"] is False

    get_result = await handler.handle(
        "orchestrator_get_parent_oversight",
        {"run_id": "run-1"},
    )
    assert get_result["oversight_state"]["child_summaries"][0]["run_id"] == child_id

    update_result = await handler.handle(
        "orchestrator_update_parent_oversight",
        {
            "run_id": "run-1",
            "current_understanding": {"summary": "MCP recorded durable facts"},
            "target_inventory": [{"id": "INV-001", "resolved": True}],
            "final_validation": {
                "passed": True,
                "integrated_commit_sha": parent_head,
                "report_path": "docs/super-parent/final-report.md",
                "commands_run": [
                    {
                        "command": "uv run pytest tests/integration/test_mcp_tools.py",
                        "exit_code": 0,
                    }
                ],
                "evidence_files": ["docs/super-parent/final-report.md"],
            },
            "decision": {"kind": "mcp_update"},
        },
    )
    updated_state = update_result["oversight_state"]
    assert updated_state["current_understanding"] == {"summary": "MCP recorded durable facts"}
    assert updated_state["target_inventory"][0]["id"] == "INV-001"
    assert updated_state["final_validation"]["passed"] is True
    assert updated_state["final_validation"]["service_verified"] is True
    assert updated_state["decisions"][0]["kind"] == "mcp_update"


async def test_create_child_from_template_tool(
    handler: ToolHandler,
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    parent = _make_run()
    parent.status = RunStatus.ACTIVE
    parent_worktree = tmp_path / "parent-worktree"
    parent_worktree.mkdir()
    _init_repo(parent_worktree)
    parent.worktree_path = str(parent_worktree)
    await service.create_run(parent)

    result = await handler.handle(
        "orchestrator_create_child_from_template",
        {
            "parent_run_id": "run-1",
            "slice_spec": {
                "template_id": "test_coverage_gap",
                "slice_id": "slice-template",
                "goal": "Add missing coverage for child template compilation.",
                "verification_commands": [
                    "uv run pytest tests/unit/test_child_workflow_templates.py -q"
                ],
            },
        },
    )

    child = await service.get_run(cast(str, result["child_run_id"]))
    assert result["template_id"] == "test_coverage_gap"
    assert result["routine_id"] == "child-slice-template"
    assert child.parent_slice_id == "slice-template"
    assert child.routine_id == "child-slice-template"
    routine = cast(dict[str, Any], child.routine_embedded)
    steps = cast(list[dict[str, Any]], routine["steps"])
    task = cast(dict[str, Any], steps[0]["tasks"][0])
    assert task["artifacts"] == [
        {"path": "docs/run-evidence/slice-template-evidence.json", "required": True}
    ]


async def test_resolve_child_run_tool_records_parent_decision(
    handler: ToolHandler,
    service: WorkflowService,
) -> None:
    parent = _make_run()
    parent.status = RunStatus.ACTIVE
    await service.create_run(parent)
    child = Run(
        id="child-1",
        repo_name=parent.repo_name,
        status=RunStatus.FAILED,
        parent_run_id=parent.id,
        parent_slice_id="slice-01",
        source_branch="main",
        created_at=parent.created_at,
        updated_at=parent.updated_at,
    )
    await service.create_run(child)

    result = await handler.handle(
        "orchestrator_resolve_child_run",
        {
            "parent_run_id": parent.id,
            "child_run_id": child.id,
            "resolution": "abandon",
            "reason": "Environment setup failed; launch replacement slice.",
        },
    )

    assert result["resolution"] == "abandon"
    oversight_state = result["oversight_state"]
    assert oversight_state["abandoned_child_run_ids"] == ["child-1"]
    assert oversight_state["decisions"][-1]["action"] == "abandon"
    assert oversight_state["next_parent_action"] == "launch_child"


async def test_get_run_evidence_tool_returns_validation_errors(
    handler: ToolHandler,
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    run = _make_run()
    worktree = tmp_path / "worktree"
    evidence_dir = worktree / "docs" / "run-evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "slice-01-evidence.json").write_text(
        """{
  "schema_version": "run.evidence.v1",
  "slice_id": "slice-01",
  "routine_id": "test-routine",
  "assumption_tested": "Invalid evidence is reported.",
  "summary": "Bad status should not be hidden.",
  "commands_run": ["uv run pytest"],
  "test_results": [{"name": "bad status", "status": "partial", "details": "invalid"}],
  "target_bug_reproduced": true,
  "real_frontend_path_exercised": false,
  "real_execution_surface": "MCP ToolHandler",
  "files_changed": [],
  "evidence_files": [],
  "open_uncertainties": [],
  "next_recommendation": "waiver_requested",
  "outcome": "verified_fix"
}""",
        encoding="utf-8",
    )
    run.worktree_path = str(worktree)
    await service.create_run(run)

    result = await handler.handle("orchestrator_get_run_evidence", {"run_id": run.id})

    assert result["evidence"] == []
    invalid = result["invalid_evidence"][0]
    assert invalid["path"] == "docs/run-evidence/slice-01-evidence.json"
    assert {error["field"] for error in invalid["errors"]} >= {
        "commands_run.0",
        "test_results.0.status",
        "target_bug_reproduced",
        "next_recommendation",
    }


async def test_parent_terminal_guard_pauses_unresolved_child(
    service: WorkflowService,
    session: AsyncSession,
) -> None:
    parent = _make_run()
    parent.status = RunStatus.ACTIVE
    task = parent.steps[0].tasks[0]
    task.status = TaskStatus.VERIFYING
    for item in task.checklist:
        item.status = ChecklistStatus.DONE
        item.grade = "A"
    await service.create_run(parent)

    child = Run(
        id="child-1",
        repo_name=parent.repo_name,
        status=RunStatus.ACTIVE,
        parent_run_id=parent.id,
        parent_slice_id="slice-01",
        source_branch="main",
        created_at=parent.created_at,
        updated_at=parent.updated_at,
    )
    await service.create_child_run(
        parent.id,
        child,
        parent_slice_id="slice-01",
        next_action_decision="continue",
    )

    result = await service.complete_verification(parent.id, task.id)

    assert result.success
    updated_parent = await service.get_run(parent.id)
    assert updated_parent.status == RunStatus.PAUSED
    assert updated_parent.pause_reason == "oversight_children_unresolved"
    assert updated_parent.oversight_state["terminal_guard"]["can_complete"] is False
    assert updated_parent.oversight_state["active_child_run_ids"] == ["child-1"]
    store = EventStore(session)
    events = await store.get_events_for_run(parent.id)
    status_events = [event["payload"] for event in events if event["type"] == "run_status_changed"]
    assert any(event["new_status"] == "paused" for event in status_events)
    assert not any(event["new_status"] == "completed" for event in status_events)
    pending_actions = await service.get_pending_actions(parent.id)
    assert pending_actions[0]["action_type"] == "oversight"
    assert pending_actions[0]["details"]["active_child_run_ids"] == ["child-1"]


async def test_collect_run_evidence_uses_files_changed_since_source_commit(
    service: WorkflowService,
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "repo"
    worktree.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )
    committed_dir = worktree / "docs" / "old"
    committed_dir.mkdir(parents=True)
    (committed_dir / "old-evidence.json").write_text(
        '{"schema_version":"run.evidence.v1","outcome":"environment_blocked"}',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=worktree, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=worktree, check=True, capture_output=True)
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    evidence_dir = worktree / "docs" / "new"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "new-evidence.json").write_text(
        """{
  "schema_version": "run.evidence.v1",
  "slice_id": "slice-new",
  "routine_id": "evidence-filter",
  "assumption_tested": "Only changed evidence is collected.",
  "summary": "New evidence was produced by this run.",
  "commands_run": [],
  "test_results": [],
  "target_bug_reproduced": "not_targeted",
  "real_frontend_path_exercised": false,
  "real_execution_surface": "git worktree",
  "files_changed": ["docs/new/new-evidence.json"],
  "evidence_files": ["docs/new/new-evidence.json"],
  "open_uncertainties": [],
  "next_recommendation": "proceed",
  "outcome": "verified_fix"
}""",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=worktree, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add new evidence"],
        cwd=worktree,
        check=True,
        capture_output=True,
    )

    run = _make_run()
    run.worktree_path = str(worktree)
    run.source_branch_sha = base_sha
    await service.create_run(run)

    evidence = await service.collect_run_evidence(run.id)

    assert [item["path"] for item in evidence] == ["docs/new/new-evidence.json"]


async def test_full_workflow_via_tools(handler: ToolHandler, service: WorkflowService) -> None:
    """Full workflow: get requirements -> update -> submit -> grade -> verify."""
    run = _make_run()
    await service.create_run(run)
    await service.apply_start_run("run-1")
    await service.start_task("run-1", "task-1")

    # 1. Get requirements
    reqs = await handler.handle(
        "orchestrator_get_requirements",
        {"run_id": "run-1", "task_id": "task-1"},
    )
    assert len(reqs["requirements"]) == 2

    # 2. Update checklist items
    await handler.handle(
        "orchestrator_update_checklist",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R1", "status": "done"},
    )
    await handler.handle(
        "orchestrator_update_checklist",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R2", "status": "done"},
    )

    # 3. Submit
    submit_result = await handler.handle(
        "orchestrator_submit",
        {"run_id": "run-1", "task_id": "task-1"},
    )
    assert submit_result["success"] is True

    # 4. Grade
    await handler.handle(
        "orchestrator_set_grade",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R1", "grade": "A"},
    )
    await handler.handle(
        "orchestrator_set_grade",
        {"run_id": "run-1", "task_id": "task-1", "req_id": "R2", "grade": "A"},
    )

    # 5. Complete verification
    result = await service.complete_verification("run-1", "task-1")
    assert result.new_status == TaskStatus.COMPLETED


# --- Repo tool tests ---

_GIT_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(args: list[str], cwd: Path) -> str:
    """Run a git command, stripping GIT_* env vars to prevent test contamination."""
    result = subprocess.run(
        ["git"] + args, cwd=cwd, check=True, capture_output=True, text=True, env=_GIT_ENV
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit."""
    _git(["init"], cwd=path)
    _git(["config", "user.email", "test@test.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)
    (path / "README.md").write_text("# Test\n")
    _git(["add", "."], cwd=path)
    _git(["commit", "-m", "Initial commit"], cwd=path)
    _git(["branch", "-M", "main"], cwd=path)


@pytest.fixture
def repos_dir(tmp_path: Path) -> Path:
    """Create a repos directory with sample repos."""
    repos = tmp_path / "repos"
    repos.mkdir()
    return repos


@pytest.fixture
def handler_with_repos(service: WorkflowService, repos_dir: Path) -> ToolHandler:
    """Create a ToolHandler with repos_dir configured."""
    return ToolHandler(service, repos_dir=repos_dir)


async def test_list_repos_empty(handler_with_repos: ToolHandler) -> None:
    """List repos returns empty list when no repos exist."""
    result = await handler_with_repos.handle("orchestrator_list_repos", {})
    assert result["repos"] == []


async def test_list_repos_with_repos(handler_with_repos: ToolHandler, repos_dir: Path) -> None:
    """List repos returns repos in the repos directory."""
    # Create two repos
    repo1 = repos_dir / "alpha"
    repo1.mkdir()
    _init_repo(repo1)

    repo2 = repos_dir / "beta"
    repo2.mkdir()
    _init_repo(repo2)

    result = await handler_with_repos.handle("orchestrator_list_repos", {})
    repos = result["repos"]
    assert len(repos) == 2
    names = {r["name"] for r in repos}
    assert names == {"alpha", "beta"}
    for r in repos:
        assert "path" in r
        assert "default_branch" in r


async def test_list_repos_no_repos_dir(handler: ToolHandler) -> None:
    """List repos returns error when repos_dir is not configured."""
    result = await handler.handle("orchestrator_list_repos", {})
    assert "error" in result
    assert result["repos"] == []


async def test_list_branches(handler_with_repos: ToolHandler, repos_dir: Path) -> None:
    """List branches returns branches in a repo."""
    repo = repos_dir / "myrepo"
    repo.mkdir()
    _init_repo(repo)

    # Create additional branches
    _git(["checkout", "-b", "feature/auth"], cwd=repo)
    _git(["checkout", "main"], cwd=repo)

    result = await handler_with_repos.handle(
        "orchestrator_list_branches",
        {"repo_name": "myrepo"},
    )
    branches = result["branches"]
    assert len(branches) == 2
    names = {b["name"] for b in branches}
    assert "main" in names
    assert "feature/auth" in names


async def test_list_branches_with_pattern(handler_with_repos: ToolHandler, repos_dir: Path) -> None:
    """List branches filters by pattern."""
    repo = repos_dir / "myrepo"
    repo.mkdir()
    _init_repo(repo)

    # Create multiple branches
    for name in ["feature/auth", "feature/api", "bugfix/login"]:
        _git(["checkout", "-b", name], cwd=repo)
    _git(["checkout", "main"], cwd=repo)

    result = await handler_with_repos.handle(
        "orchestrator_list_branches",
        {"repo_name": "myrepo", "pattern": "feature/*"},
    )
    branches = result["branches"]
    assert len(branches) == 2
    names = {b["name"] for b in branches}
    assert names == {"feature/auth", "feature/api"}


async def test_list_branches_repo_not_found(
    handler_with_repos: ToolHandler,
) -> None:
    """List branches returns error for non-existent repo."""
    result = await handler_with_repos.handle(
        "orchestrator_list_branches",
        {"repo_name": "nonexistent"},
    )
    assert "error" in result
    assert result["branches"] == []
