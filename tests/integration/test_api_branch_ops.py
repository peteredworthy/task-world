"""Integration tests for branch status and merge API endpoints."""

import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


def _git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
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


def _commit_file(path: Path, filename: str, content: str, message: str) -> str:
    """Create/modify a file and commit it."""
    (path / filename).write_text(content)
    _git(["add", filename], cwd=path)
    _git(["commit", "-m", message], cwd=path)
    return _git(["rev-parse", "HEAD"], cwd=path)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a git repo for testing."""
    repo = tmp_path / "project"
    repo.mkdir()
    _init_repo(repo)
    return repo


@pytest.fixture
async def client_with_repo(
    git_repo: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, DrainFn], None]:
    """Create test client with a real git repo as project."""
    from orchestrator.config.global_config import GlobalConfig, PathsConfig

    # Configure global config with proper repos/worktrees directories
    repos_dir = git_repo.parent
    worktrees_dir = repos_dir / "worktrees"
    worktrees_dir.mkdir(exist_ok=True)

    global_config = GlobalConfig(
        paths=PathsConfig(
            repos_dir=str(repos_dir),
            worktrees_dir=str(worktrees_dir),
        )
    )

    signal_transport = InMemorySignalTransport()
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
        global_config=global_config,
    )
    app.state.signal_transport = signal_transport
    await init_db(app.state.engine)
    drain = make_drain_fn(app, signal_transport)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, git_repo, drain
    await app.state.engine.dispose()


async def _create_and_start_run(
    client: AsyncClient, project_path: Path, drain: DrainFn
) -> dict[str, Any]:
    """Helper: create and start a run pointing at a real git repo."""
    resp = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": project_path.name,  # Use just the repo name, not the full path
            "branch": "main",
        },
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "active"
    assert data["worktree_path"] is not None
    return data


async def test_branch_status_no_divergence(
    client_with_repo: tuple[AsyncClient, Path, DrainFn],
) -> None:
    client, repo, drain = client_with_repo
    run_data = await _create_and_start_run(client, repo, drain)
    run_id = run_data["id"]

    resp = await client.get(f"/api/runs/{run_id}/branch-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["behind_count"] == 0
    assert data["ahead_count"] == 0
    assert data["can_merge_cleanly"] is True
    assert data["has_conflicts"] is False
    assert data["source_branch"] == "main"


async def test_branch_status_behind(
    client_with_repo: tuple[AsyncClient, Path, DrainFn],
) -> None:
    client, repo, drain = client_with_repo
    run_data = await _create_and_start_run(client, repo, drain)
    run_id = run_data["id"]

    # Add a commit on main
    _git(["checkout", "main"], cwd=repo)
    _commit_file(repo, "hotfix.py", "# hotfix", "Add hotfix")
    # Switch back so worktree stays valid
    _git(["checkout", "-"], cwd=repo)

    resp = await client.get(f"/api/runs/{run_id}/branch-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["behind_count"] == 1
    assert data["ahead_count"] == 0


async def test_back_merge(
    client_with_repo: tuple[AsyncClient, Path, DrainFn],
) -> None:
    client, repo, drain = client_with_repo
    run_data = await _create_and_start_run(client, repo, drain)
    run_id = run_data["id"]
    worktree_path = Path(run_data["worktree_path"])

    # Add a commit on main
    _git(["checkout", "main"], cwd=repo)
    _commit_file(repo, "hotfix.py", "# hotfix", "Add hotfix")
    _git(["checkout", "-"], cwd=repo)

    resp = await client.post(f"/api/runs/{run_id}/back-merge")
    assert resp.status_code == 200
    data = resp.json()
    assert data["merge_commit"]
    assert "main" in data["message"]

    # Verify the file is now in the worktree
    assert (worktree_path / "hotfix.py").exists()


async def test_back_merge_requires_active_or_paused(
    client_with_repo: tuple[AsyncClient, Path, DrainFn],
) -> None:
    """Back-merge should fail for non-ACTIVE/PAUSED runs."""
    client, repo, drain = client_with_repo

    # Create run but don't start it (stays DRAFT)
    resp = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": str(repo),
            "branch": "main",
        },
    )
    run_id = resp.json()["id"]

    resp = await client.post(f"/api/runs/{run_id}/back-merge")
    assert resp.status_code == 409


async def test_branch_status_no_worktree(
    client_with_repo: tuple[AsyncClient, Path, DrainFn],
) -> None:
    """Branch status should fail when run has no worktree."""
    client, _repo, drain = client_with_repo

    resp = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "not-a-git-repo",
            "branch": "main",
        },
    )
    run_id = resp.json()["id"]

    resp = await client.get(f"/api/runs/{run_id}/branch-status")
    assert resp.status_code == 400
