"""Integration tests for review test execution API endpoints.

Covers POST /api/runs/{run_id}/review/test and
       GET  /api/runs/{run_id}/review/test/{test_run_id}.
"""

import asyncio
import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.db.connection import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> None:
    _git(["init"], cwd=path)
    _git(["config", "user.email", "test@test.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)
    (path / "README.md").write_text("# Test\n")
    _git(["add", "."], cwd=path)
    _git(["commit", "-m", "Initial commit"], cwd=path)
    _git(["branch", "-M", "main"], cwd=path)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _init_repo(repo)
    return repo


@pytest.fixture
async def client_with_auto_verify(
    git_repo: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, Any], None]:
    """Test client wired to a routine that has auto_verify commands."""
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
    routine_id: str = "auto-verify-routine",
) -> dict[str, Any]:
    """Create and start a run, returning run data including worktree_path."""
    resp = await client.post(
        "/api/runs",
        json={
            "routine_id": routine_id,
            "repo_name": project_path.name,
            "branch": "main",
        },
    )
    assert resp.status_code == 201, resp.text
    run_id = resp.json()["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "active"
    assert data["worktree_path"] is not None
    return data


async def _wait_for_completion(
    client: AsyncClient,
    run_id: str,
    test_run_id: str,
    timeout_iterations: int = 30,
) -> dict[str, Any]:
    """Poll GET endpoint until status is no longer 'running'."""
    data: dict[str, Any] = {}
    for _ in range(timeout_iterations):
        await asyncio.sleep(0.2)
        resp = await client.get(f"/api/runs/{run_id}/review/test/{test_run_id}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        if data["status"] != "running":
            break
    return data


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/test — start a test run
# ---------------------------------------------------------------------------


class TestStartTestRun:
    async def test_endpoint_starts_and_returns_202(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any]
    ) -> None:
        """POST /review/test returns HTTP 202 with a test_run_id and 'running' status."""
        client, repo, _app = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]

        resp = await client.post(f"/api/runs/{run_id}/review/test", json={})

        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert "test_run_id" in data
        assert isinstance(data["test_run_id"], str)
        assert len(data["test_run_id"]) > 0
        assert data["status"] == "running"

    async def test_no_auto_verify_returns_422(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any]
    ) -> None:
        """POST returns 422 when routine has no auto_verify commands."""
        client, repo, _app = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, routine_id="simple-routine")
        run_id = run_data["id"]

        resp = await client.post(f"/api/runs/{run_id}/review/test", json={})

        assert resp.status_code == 422, resp.text
        assert "auto_verify" in resp.json()["detail"].lower()

    async def test_run_not_found_returns_404(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any]
    ) -> None:
        """POST returns 404 for a non-existent run_id."""
        client, _repo, _app = client_with_auto_verify

        resp = await client.post("/api/runs/does-not-exist/review/test", json={})

        assert resp.status_code == 404

    async def test_run_without_worktree_returns_409(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any]
    ) -> None:
        """POST returns 409 when run exists but has no active worktree (not started)."""
        client, repo, _app = client_with_auto_verify
        resp = await client.post(
            "/api/runs",
            json={
                "routine_id": "auto-verify-routine",
                "repo_name": repo.name,
                "branch": "main",
            },
        )
        assert resp.status_code == 201
        run_id = resp.json()["id"]
        # Do NOT start the run — no worktree created

        resp = await client.post(f"/api/runs/{run_id}/review/test", json={})

        assert resp.status_code == 409

    async def test_concurrent_test_run_returns_409(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any]
    ) -> None:
        """POST returns 409 when a test run is already in progress for the same run."""
        client, repo, app = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]
        worktree_path = run_data["worktree_path"]

        from orchestrator.review.test_runner import TestRunner

        test_runner: TestRunner = app.state.test_runner

        # Directly inject a slow-running test to hold the "running" lock
        await test_runner.start_test_run(
            run_id=run_id,
            worktree_path=worktree_path,
            commands=["sleep 10"],
        )

        # Attempting a second run via the API must be rejected
        resp = await client.post(f"/api/runs/{run_id}/review/test", json={})

        assert resp.status_code == 409, resp.text
        assert "already in progress" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/review/test/{test_run_id} — poll test results
# ---------------------------------------------------------------------------


class TestGetTestRun:
    async def test_endpoint_completes_and_returns_status(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any]
    ) -> None:
        """Test run started via POST eventually completes with a terminal status."""
        client, repo, _app = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]

        post_resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert post_resp.status_code == 202
        test_run_id = post_resp.json()["test_run_id"]

        data = await _wait_for_completion(client, run_id, test_run_id)

        assert data["status"] in {"passed", "failed", "error"}
        assert data["test_run_id"] == test_run_id

    async def test_output_captured_in_log(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any]
    ) -> None:
        """log_output contains actual stdout produced by the test command."""
        client, repo, _app = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]

        post_resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert post_resp.status_code == 202
        test_run_id = post_resp.json()["test_run_id"]

        data = await _wait_for_completion(client, run_id, test_run_id)

        # The auto-verify routine runs: echo "tests passed"
        assert "tests passed" in data["log_output"]

    async def test_failure_reported_as_failed_status(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any]
    ) -> None:
        """A command that exits non-zero causes the test run to report 'failed'."""
        client, repo, app = client_with_auto_verify

        from orchestrator.review.test_runner import TestRunner

        test_runner: TestRunner = app.state.test_runner

        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]
        worktree_path = run_data["worktree_path"]

        # Inject a failing command directly into the test runner
        test_run_id = await test_runner.start_test_run(
            run_id=run_id,
            worktree_path=worktree_path,
            commands=["exit 1"],
        )

        data = await _wait_for_completion(client, run_id, test_run_id)

        assert data["status"] == "failed"

    async def test_response_contains_required_schema_fields(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any]
    ) -> None:
        """TestRunResult response includes test_run_id, status, log_output, started_at."""
        client, repo, _app = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]

        post_resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert post_resp.status_code == 202
        test_run_id = post_resp.json()["test_run_id"]

        data = await _wait_for_completion(client, run_id, test_run_id)

        required_fields = {"test_run_id", "status", "log_output", "started_at"}
        assert required_fields.issubset(set(data.keys()))
        assert data["test_run_id"] == test_run_id
        assert isinstance(data["log_output"], str)
        assert isinstance(data["started_at"], str)

    async def test_test_run_not_found_returns_404(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any]
    ) -> None:
        """GET with an unknown test_run_id returns 404."""
        client, repo, _app = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/test/unknown-test-run-id")

        assert resp.status_code == 404

    async def test_get_immediately_after_post_returns_valid_status(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any]
    ) -> None:
        """GET immediately after POST returns a valid status (running or terminal)."""
        client, repo, _app = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]

        post_resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert post_resp.status_code == 202
        test_run_id = post_resp.json()["test_run_id"]

        get_resp = await client.get(f"/api/runs/{run_id}/review/test/{test_run_id}")

        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["status"] in {"running", "passed", "failed", "error"}
        assert data["test_run_id"] == test_run_id
