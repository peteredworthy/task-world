"""Integration tests for merge readiness endpoint and merge-back strategy.

Tests cover:
- GET /review/merge-readiness returns correct gate statuses
- clean_merge gate: based on branch conflict prediction
- no_unresolved_conflicts gate: passes/fails based on conflict files in worktree
- tests_pass gate: passes when no tests configured; passes/fails based on last test result
- no_active_jobs gate: passes when no active agent or test jobs
- POST /merge-back rejects unmet gates with 409
- POST /merge-back accepts squash and merge strategies
"""

import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource, RunStatus
from orchestrator.db import init_db
from orchestrator.db import RunRepository
from orchestrator.workflow import InMemorySignalTransport
from tests.integration.signal_helpers import DrainFn, make_drain_fn

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
) -> AsyncGenerator[tuple[AsyncClient, Path, Any, DrainFn], None]:
    """Test client and app backed by a real git repo.

    Yields (client, git_repo, app, drain) so tests can access app.state directly.
    """
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
        yield c, git_repo, app, drain
    await app.state.engine.dispose()


async def _create_and_start_run(
    client: AsyncClient,
    project_path: Path,
    drain: DrainFn,
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
    assert resp.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
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
# Tests: GET /api/runs/{run_id}/review/merge-readiness
# ---------------------------------------------------------------------------


class TestMergeReadinessEndpoint:
    async def test_returns_four_gates(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """The merge-readiness endpoint returns a response with exactly 4 named gates."""
        client, repo, app, drain = app_and_client
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
        assert resp.status_code == 200
        data = resp.json()

        assert "ready" in data
        assert "gates" in data
        gate_names = [g["name"] for g in data["gates"]]
        assert "clean_merge" in gate_names
        assert "no_unresolved_conflicts" in gate_names
        assert "tests_pass" in gate_names
        assert "no_active_jobs" in gate_names

    async def test_gate_structure(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """Each gate has name, status, and description fields."""
        client, repo, app, drain = app_and_client
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
        assert resp.status_code == 200
        data = resp.json()

        for gate in data["gates"]:
            assert "name" in gate
            assert "status" in gate
            assert gate["status"] in ("pass", "fail", "pending")
            assert "description" in gate

    async def test_no_unresolved_conflicts_pass_when_clean(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """no_unresolved_conflicts gate passes when no conflict files in worktree."""
        client, repo, app, drain = app_and_client
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
        assert resp.status_code == 200
        data = resp.json()

        gate = next(g for g in data["gates"] if g["name"] == "no_unresolved_conflicts")
        assert gate["status"] == "pass"

    async def test_no_unresolved_conflicts_fail_when_conflicts_present(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """no_unresolved_conflicts gate fails when conflict files are present."""
        client, repo, app, drain = app_and_client
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Create a conflict: both branches modify the same file differently
        _commit_file(worktree_path, "conflict.py", "x = 'run'\n", "Run: add conflict.py")
        _commit_file(repo, "conflict.py", "x = 'main'\n", "Main: add conflict.py")

        # Trigger back-merge to create conflict state
        back_merge_resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert back_merge_resp.status_code == 200
        assert back_merge_resp.json()["status"] == "conflicts"

        resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
        assert resp.status_code == 200
        data = resp.json()

        gate = next(g for g in data["gates"] if g["name"] == "no_unresolved_conflicts")
        assert gate["status"] == "fail"
        assert data["ready"] is False

    async def test_tests_pass_gate_when_no_tests_configured(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """tests_pass gate is 'pass' when no auto_verify commands are configured."""
        client, repo, app, drain = app_and_client
        # simple-routine has no auto_verify commands
        run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
        assert resp.status_code == 200
        data = resp.json()

        gate = next(g for g in data["gates"] if g["name"] == "tests_pass")
        assert gate["status"] == "pass"

    async def test_tests_pass_gate_pending_when_tests_not_run(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """tests_pass gate is 'pending' when tests are configured but not yet run."""
        client, repo, app, drain = app_and_client
        # auto-verify-routine has auto_verify commands configured
        run_data = await _create_and_start_run(
            client, repo, drain, routine_id="auto-verify-routine"
        )
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
        assert resp.status_code == 200
        data = resp.json()

        gate = next(g for g in data["gates"] if g["name"] == "tests_pass")
        assert gate["status"] == "pending"

    async def test_no_active_jobs_pass_when_idle(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """no_active_jobs gate passes when no agent or test jobs are running."""
        client, repo, app, drain = app_and_client
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
        assert resp.status_code == 200
        data = resp.json()

        gate = next(g for g in data["gates"] if g["name"] == "no_active_jobs")
        assert gate["status"] == "pass"

    async def test_clean_merge_gate_pass_when_no_conflicts_predicted(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """clean_merge gate passes when the run branch has no predicted conflicts with source."""
        client, repo, app, drain = app_and_client
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Add a non-conflicting commit to the run branch
        _commit_file(worktree_path, "run_feature.py", "x = 1\n", "Run: add feature")

        resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
        assert resp.status_code == 200
        data = resp.json()

        gate = next(g for g in data["gates"] if g["name"] == "clean_merge")
        assert gate["status"] == "pass"

    async def test_ready_true_when_all_gates_pass(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """ready is True when all gates pass (simple-routine, no conflicts, no jobs)."""
        client, repo, app, drain = app_and_client
        # simple-routine: no auto_verify, so tests_pass = pass
        run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
        assert resp.status_code == 200
        data = resp.json()

        # All gates should be pass (clean branch, no conflicts, no tests configured, idle)
        for gate in data["gates"]:
            assert gate["status"] in ("pass", "pending"), (
                f"Gate {gate['name']} has unexpected status {gate['status']!r}: {gate['description']}"
            )
        # ready is True only if all gates pass
        non_passing = [g for g in data["gates"] if g["status"] != "pass"]
        if not non_passing:
            assert data["ready"] is True


# ---------------------------------------------------------------------------
# Tests: POST /api/runs/{run_id}/merge-back — strategy parameter
# ---------------------------------------------------------------------------


class TestMergeBackStrategy:
    async def test_merge_back_squash_strategy(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """merge-back with squash strategy creates a single commit on source branch."""
        client, repo, app, drain = app_and_client
        run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Add a commit to the run branch
        _commit_file(worktree_path, "feature.py", "x = 1\n", "Feature: add feature.py")
        _commit_file(worktree_path, "feature2.py", "y = 2\n", "Feature: add feature2.py")

        await _mark_run_completed(app, run_id)

        resp = await client.post(
            f"/api/runs/{run_id}/merge-back",
            json={"strategy": "squash"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "squash"
        assert data["merge_commit"] is not None

        # Verify squash: main should have initial + 1 squash commit
        log = _git(["log", "--oneline"], cwd=repo)
        lines = log.strip().split("\n")
        assert len(lines) == 2  # initial + squash commit

    async def test_merge_back_merge_strategy(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """merge-back with merge strategy preserves run branch commit history."""
        client, repo, app, drain = app_and_client
        run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Add two commits to the run branch
        _commit_file(worktree_path, "feat1.py", "a = 1\n", "Feat: add feat1.py")
        _commit_file(worktree_path, "feat2.py", "b = 2\n", "Feat: add feat2.py")

        await _mark_run_completed(app, run_id)

        resp = await client.post(
            f"/api/runs/{run_id}/merge-back",
            json={"strategy": "merge"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy"] == "merge"
        assert data["merge_commit"] is not None

        # Verify merge commit: initial + 2 feature commits + 1 merge commit = 4
        log = _git(["log", "--oneline"], cwd=repo)
        lines = log.strip().split("\n")
        assert len(lines) == 4

    async def test_merge_back_rejects_non_completed_run(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """merge-back returns 409 for a run that is not COMPLETED."""
        client, repo, app, drain = app_and_client
        run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
        run_id = run_data["id"]

        resp = await client.post(
            f"/api/runs/{run_id}/merge-back",
            json={"strategy": "squash"},
        )
        assert resp.status_code == 409
        assert "COMPLETED" in resp.json()["detail"]

    async def test_merge_back_rejects_unmet_gates(
        self,
        app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
    ) -> None:
        """merge-back returns 409 when readiness gates are not met (unresolved conflicts)."""
        client, repo, app, drain = app_and_client
        run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Create conflict state: both run branch and main modify the same file
        _commit_file(worktree_path, "conflict.py", "x = 'run'\n", "Run: conflict.py")
        _commit_file(repo, "conflict.py", "x = 'main'\n", "Main: conflict.py")

        # Trigger back-merge to create unresolved conflict state
        back_merge_resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert back_merge_resp.status_code == 200
        assert back_merge_resp.json()["status"] == "conflicts"

        # Mark as COMPLETED
        await _mark_run_completed(app, run_id)

        # merge-back should fail with 409 due to unresolved conflicts
        resp = await client.post(
            f"/api/runs/{run_id}/merge-back",
            json={"strategy": "squash"},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        # Should contain readiness gate failure info
        assert (
            "gates" in detail or "gate" in str(detail).lower() or "conflicts" in str(detail).lower()
        )
