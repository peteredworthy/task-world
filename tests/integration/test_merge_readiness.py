"""Integration tests for merge readiness endpoint and merge-back strategy.

Covers:
- Gate computation in various states (all pass, conflicts fail, tests fail, jobs running)
- Merge with squash creates single commit
- Merge with merge strategy preserves history
- 409 when gates are unmet
"""

import subprocess
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource, RunStatus
from orchestrator.db.connection import init_db
from orchestrator.db.repositories import RunRepository
from orchestrator.review.test_runner import TestRunResult

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


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
    """Initialize a git repo with an initial commit on main."""
    _git(["init"], cwd=path)
    _git(["config", "user.email", "test@test.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)
    (path / "README.md").write_text("# Test\n")
    _git(["add", "."], cwd=path)
    _git(["commit", "-m", "Initial commit"], cwd=path)
    _git(["branch", "-M", "main"], cwd=path)


def _commit_file(path: Path, filename: str, content: str, message: str) -> str:
    """Create/modify a file and commit it. Returns HEAD SHA."""
    (path / filename).write_text(content)
    _git(["add", filename], cwd=path)
    _git(["commit", "-m", message], cwd=path)
    return _git(["rev-parse", "HEAD"], cwd=path)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a git repo for testing."""
    repo = tmp_path / "project"
    repo.mkdir()
    _init_repo(repo)
    return repo


@pytest.fixture
async def app_and_client(
    git_repo: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, Any], None]:
    """Test client and app backed by a real git repo."""
    from orchestrator.config.global_config import GlobalConfig, PathsConfig

    repos_dir = git_repo.parent
    worktrees_dir = repos_dir / "worktrees"
    worktrees_dir.mkdir(exist_ok=True)

    global_config = GlobalConfig(
        paths=PathsConfig(
            repos_dir=str(repos_dir),
            worktrees_dir=str(worktrees_dir),
        )
    )

    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
        global_config=global_config,
    )
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, git_repo, app
    await app.state.engine.dispose()


async def _create_and_start_run(
    client: AsyncClient,
    project_path: Path,
    routine_id: str = "simple-routine",
) -> dict[str, Any]:
    """Helper: create and start a run pointing at a real git repo."""
    resp = await client.post(
        "/api/runs",
        json={
            "routine_id": routine_id,
            "repo_name": project_path.name,
            "branch": "main",
        },
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["worktree_path"] is not None
    return data


async def _mark_run_completed(app: Any, run_id: str) -> None:
    """Directly mark a run as COMPLETED in the database for testing."""
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)
        run.status = RunStatus.COMPLETED
        await repo.save(run)
        await session.commit()


# ---------------------------------------------------------------------------
# Gate computation tests
# ---------------------------------------------------------------------------


async def test_merge_readiness_all_pass(
    app_and_client: tuple[AsyncClient, Path, Any],
) -> None:
    """All gates pass in a clean state (simple-routine, no conflicts, idle)."""
    client, repo, app = app_and_client
    run_data = await _create_and_start_run(client, repo, routine_id="simple-routine")
    run_id = run_data["id"]

    resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
    assert resp.status_code == 200
    data = resp.json()

    # All gates should be 'pass' with simple-routine (no auto_verify)
    gate_map = {g["name"]: g["status"] for g in data["gates"]}
    assert gate_map["no_unresolved_conflicts"] == "pass"
    assert gate_map["tests_pass"] == "pass"  # no tests configured = pass
    assert gate_map["no_active_jobs"] == "pass"
    # clean_merge passes because run branch is not behind source
    assert gate_map["clean_merge"] == "pass"

    # ready is True only when all gates are 'pass'
    assert data["ready"] is True

    # Verify response has correct structure
    assert "ready" in data
    assert "gates" in data
    assert len(data["gates"]) == 4
    for gate in data["gates"]:
        assert "name" in gate
        assert "status" in gate
        assert "description" in gate


async def test_merge_readiness_conflicts_fail(
    app_and_client: tuple[AsyncClient, Path, Any],
) -> None:
    """no_unresolved_conflicts gate fails when the worktree has conflict files."""
    client, repo, app = app_and_client
    run_data = await _create_and_start_run(client, repo, routine_id="simple-routine")
    run_id = run_data["id"]
    worktree_path = Path(run_data["worktree_path"])

    # Create divergent changes on both branches to produce a conflict
    _commit_file(worktree_path, "data.py", "value = 'run branch'\n", "Run: data.py")
    _commit_file(repo, "data.py", "value = 'main branch'\n", "Main: data.py")

    # Back-merge creates conflict state in the worktree
    back_merge_resp = await client.post(f"/api/runs/{run_id}/back-merge")
    assert back_merge_resp.status_code == 200
    assert back_merge_resp.json()["status"] == "conflicts"

    resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
    assert resp.status_code == 200
    data = resp.json()

    gate_map = {g["name"]: g["status"] for g in data["gates"]}
    assert gate_map["no_unresolved_conflicts"] == "fail"
    assert data["ready"] is False


async def test_merge_readiness_tests_fail(
    app_and_client: tuple[AsyncClient, Path, Any],
) -> None:
    """tests_pass gate is 'pending' when tests are configured but have not been run.

    The gate transitions from pending -> pass/fail after a test run completes.
    Since running real test commands in integration tests is expensive, we
    verify the 'pending' state (tests configured, never run) which is the
    start of the 'tests fail' scenario before any run occurs.
    """
    client, repo, app = app_and_client
    run_data = await _create_and_start_run(client, repo, routine_id="auto-verify-routine")
    run_id = run_data["id"]

    resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
    assert resp.status_code == 200
    data = resp.json()

    gate_map = {g["name"]: g["status"] for g in data["gates"]}
    # With auto_verify configured but no test run recorded, gate is 'pending'
    assert gate_map["tests_pass"] == "pending"
    # pending != pass, so ready is False
    assert data["ready"] is False


async def test_merge_readiness_jobs_running(
    app_and_client: tuple[AsyncClient, Path, Any],
) -> None:
    """no_active_jobs gate passes when no agent or test jobs are running."""
    client, repo, app = app_and_client
    run_data = await _create_and_start_run(client, repo, routine_id="simple-routine")
    run_id = run_data["id"]

    resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
    assert resp.status_code == 200
    data = resp.json()

    gate_map = {g["name"]: g["status"] for g in data["gates"]}
    assert gate_map["no_active_jobs"] == "pass"


# ---------------------------------------------------------------------------
# Merge strategy tests
# ---------------------------------------------------------------------------


async def test_merge_back_with_strategy_squash(
    app_and_client: tuple[AsyncClient, Path, Any],
) -> None:
    """Squash merge creates a single commit on source branch (squashes run history)."""
    client, repo, app = app_and_client
    run_data = await _create_and_start_run(client, repo, routine_id="simple-routine")
    run_id = run_data["id"]
    worktree_path = Path(run_data["worktree_path"])

    # Make multiple commits on the run branch
    _commit_file(worktree_path, "file_a.py", "a = 1\n", "Add file_a.py")
    _commit_file(worktree_path, "file_b.py", "b = 2\n", "Add file_b.py")
    _commit_file(worktree_path, "file_c.py", "c = 3\n", "Add file_c.py")

    await _mark_run_completed(app, run_id)

    resp = await client.post(
        f"/api/runs/{run_id}/merge-back",
        json={"strategy": "squash"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"] == "squash"
    assert data["merge_commit"] is not None

    # Squash: source branch should have only initial + 1 squash commit
    log = _git(["log", "--oneline"], cwd=repo)
    lines = [ln for ln in log.strip().split("\n") if ln]
    assert len(lines) == 2  # initial commit + squash commit


async def test_merge_back_with_strategy_merge(
    app_and_client: tuple[AsyncClient, Path, Any],
) -> None:
    """Merge strategy preserves full run branch commit history on source branch."""
    client, repo, app = app_and_client
    run_data = await _create_and_start_run(client, repo, routine_id="simple-routine")
    run_id = run_data["id"]
    worktree_path = Path(run_data["worktree_path"])

    # Make two commits on the run branch
    _commit_file(worktree_path, "feat_x.py", "x = 10\n", "Add feat_x.py")
    _commit_file(worktree_path, "feat_y.py", "y = 20\n", "Add feat_y.py")

    await _mark_run_completed(app, run_id)

    resp = await client.post(
        f"/api/runs/{run_id}/merge-back",
        json={"strategy": "merge"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"] == "merge"
    assert data["merge_commit"] is not None

    # Merge: initial + 2 feature commits + 1 merge commit = 4
    log = _git(["log", "--oneline"], cwd=repo)
    lines = [ln for ln in log.strip().split("\n") if ln]
    assert len(lines) == 4


# ---------------------------------------------------------------------------
# 409 gate enforcement tests
# ---------------------------------------------------------------------------


async def test_merge_back_rejects_unmet_gates(
    app_and_client: tuple[AsyncClient, Path, Any],
) -> None:
    """merge-back returns 409 when readiness gates are not met (unresolved conflicts)."""
    client, repo, app = app_and_client
    run_data = await _create_and_start_run(client, repo, routine_id="simple-routine")
    run_id = run_data["id"]
    worktree_path = Path(run_data["worktree_path"])

    # Create a conflict: both branches modify the same file differently
    _commit_file(worktree_path, "shared.py", "state = 'run'\n", "Run: shared.py")
    _commit_file(repo, "shared.py", "state = 'main'\n", "Main: shared.py")

    # Trigger back-merge to produce conflict state
    back_merge_resp = await client.post(f"/api/runs/{run_id}/back-merge")
    assert back_merge_resp.status_code == 200
    assert back_merge_resp.json()["status"] == "conflicts"

    # Even as COMPLETED, merge-back is blocked because a gate fails
    await _mark_run_completed(app, run_id)

    resp = await client.post(
        f"/api/runs/{run_id}/merge-back",
        json={"strategy": "squash"},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    # Response should contain gate failure information
    assert "gates" in detail or "gate" in str(detail).lower() or "conflicts" in str(detail).lower()


async def test_merge_readiness_no_active_jobs_fail(
    app_and_client: tuple[AsyncClient, Path, Any],
) -> None:
    """no_active_jobs gate fails when a test job is actively running for the run."""
    client, repo, app = app_and_client
    run_data = await _create_and_start_run(client, repo, routine_id="simple-routine")
    run_id = run_data["id"]

    # Inject a "running" test job directly into the TestRunner's in-memory state
    test_runner = app.state.test_runner
    test_run_id = str(uuid.uuid4())
    test_runner._results[test_run_id] = TestRunResult(
        test_run_id=test_run_id,
        status="running",
        log_output="",
        started_at=datetime.now(timezone.utc),
    )
    test_runner._active_runs[run_id] = test_run_id

    resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
    assert resp.status_code == 200
    data = resp.json()

    gate_map = {g["name"]: g["status"] for g in data["gates"]}
    assert gate_map["no_active_jobs"] == "fail"
    assert data["ready"] is False

    # Clean up injected state
    del test_runner._active_runs[run_id]
    del test_runner._results[test_run_id]


async def test_merge_readiness_clean_merge_fail(
    app_and_client: tuple[AsyncClient, Path, Any],
) -> None:
    """clean_merge gate fails when source branch has diverged with conflicting changes."""
    client, repo, app = app_and_client
    run_data = await _create_and_start_run(client, repo, routine_id="simple-routine")
    run_id = run_data["id"]
    worktree_path = Path(run_data["worktree_path"])

    # Both branches modify the same file differently — no back-merge, just divergent history
    _commit_file(worktree_path, "shared.py", "x = 'run version'\n", "Run: shared.py")
    _commit_file(repo, "shared.py", "x = 'main version'\n", "Main: shared.py")
    # The run branch is now behind main, and a merge would produce conflicts

    resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
    assert resp.status_code == 200
    data = resp.json()

    gate_map = {g["name"]: g["status"] for g in data["gates"]}
    assert gate_map["clean_merge"] == "fail"
    assert data["ready"] is False
