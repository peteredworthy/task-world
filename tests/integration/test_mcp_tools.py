"""Integration tests for MCP ToolHandler with real WorkflowService."""

import subprocess
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

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
from orchestrator.mcp.tools import ToolHandler
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
    await service.start_run("run-1")
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
    await service.start_run("run-1")
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
    await service.start_run("run-1")
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


async def test_full_workflow_via_tools(handler: ToolHandler, service: WorkflowService) -> None:
    """Full workflow: get requirements -> update -> submit -> grade -> verify."""
    run = _make_run()
    await service.create_run(run)
    await service.start_run("run-1")
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


def _init_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit."""
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "branch", "-M", "main"], cwd=path, check=True, capture_output=True)


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
    subprocess.run(
        ["git", "checkout", "-b", "feature/auth"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)

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
        subprocess.run(
            ["git", "checkout", "-b", name],
            cwd=repo,
            check=True,
            capture_output=True,
        )
    subprocess.run(["git", "checkout", "main"], cwd=repo, check=True, capture_output=True)

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
