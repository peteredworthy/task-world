"""Integration tests for review test-runner endpoints (POST/GET /review/test)."""

import shutil
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.config.global_config import GlobalConfig, PathsConfig
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport
from tests.integration.conftest import cleanup_runs_for_repo
from tests.integration.signal_helpers import DrainFn
from tests.integration.signal_helpers import make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client_with_auto_verify(
    tmp_path: Path,
    _base_repo: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, Any, DrainFn], None]:
    """Function-scoped app so background test-run callbacks cannot poison sibling tests."""
    repos_dir = tmp_path / "repos"
    worktrees_dir = tmp_path / "worktrees"
    repos_dir.mkdir()
    worktrees_dir.mkdir()
    git_repo = repos_dir / f"project_{uuid.uuid4().hex[:8]}"
    shutil.copytree(str(_base_repo), str(git_repo))

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
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, git_repo, app, drain
        for test_run_id in list(app.state.test_runner._tasks):  # pyright: ignore[reportPrivateUsage]
            await app.state.test_runner.wait_for_test_run(test_run_id)
        await cleanup_runs_for_repo(client, git_repo.name)
    await app.state.engine.dispose()


async def _create_and_start_run(
    client: AsyncClient,
    project_path: Path,
    drain: DrainFn,
    routine_id: str = "auto-verify-routine",
) -> dict[str, Any]:
    """Helper: create and start a run for the given routine."""
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
    assert resp.status_code == 202, resp.text
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "active"
    assert data["worktree_path"] is not None
    return data


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/test
# ---------------------------------------------------------------------------


class TestStartTestRun:
    async def test_start_test_run_returns_id(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """POST /review/test returns a test_run_id and 'running' status."""
        client, repo, _app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert "test_run_id" in data
        assert isinstance(data["test_run_id"], str)
        assert len(data["test_run_id"]) > 0
        assert data["status"] == "running"

    async def test_no_auto_verify_returns_422(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """422 when the routine has no auto_verify commands configured."""
        client, repo, _app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
        run_id = run_data["id"]

        resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert resp.status_code == 422, resp.text
        assert "auto_verify" in resp.json()["detail"].lower()

    async def test_run_not_found_returns_404(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        client, _repo, _app, _drain = client_with_auto_verify
        resp = await client.post("/api/runs/nonexistent-run/review/test", json={})
        assert resp.status_code == 404

    async def test_run_without_worktree_returns_409(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """409 when the run has no active worktree."""
        client, repo, _app, _drain = client_with_auto_verify
        # Create run but don't start it (so no worktree)
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

        resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert resp.status_code == 409

    async def test_concurrent_test_run_returns_409(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """409 when a test run is already in progress for this run."""
        client, repo, app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        from datetime import datetime, timezone

        from orchestrator.git import TestRunner, TestRunResult

        test_runner: TestRunner = app.state.test_runner

        active_id = "already-running"
        test_runner._results[active_id] = TestRunResult(  # pyright: ignore[reportPrivateUsage]
            test_run_id=active_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        test_runner._active_runs[run_id] = active_id  # pyright: ignore[reportPrivateUsage]

        resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert resp.status_code == 409, resp.text
        assert "already in progress" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/review/test/{test_run_id}
# ---------------------------------------------------------------------------


class TestGetTestRun:
    async def test_get_test_run_returns_running_status(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """GET immediately after POST returns 'running' or completed status."""
        client, repo, app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        post_resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert post_resp.status_code == 202
        test_run_id = post_resp.json()["test_run_id"]

        get_resp = await client.get(f"/api/runs/{run_id}/review/test/{test_run_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["test_run_id"] == test_run_id
        assert data["status"] in {"running", "passed", "failed", "error"}
        await app.state.test_runner.wait_for_test_run(test_run_id)

    async def test_test_run_completes_with_results(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """After completion, GET returns final status with log_output."""
        client, repo, app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        post_resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert post_resp.status_code == 202
        test_run_id = post_resp.json()["test_run_id"]

        await app.state.test_runner.wait_for_test_run(test_run_id)
        get_resp = await client.get(f"/api/runs/{run_id}/review/test/{test_run_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()

        assert data["status"] in {"passed", "failed", "error"}
        assert "started_at" in data
        assert data["log_output"] != "" or data["status"] == "error"

    async def test_test_run_captures_output(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """log_output contains actual stdout from the test command."""
        client, repo, app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        post_resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert post_resp.status_code == 202
        test_run_id = post_resp.json()["test_run_id"]

        await app.state.test_runner.wait_for_test_run(test_run_id)
        get_resp = await client.get(f"/api/runs/{run_id}/review/test/{test_run_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()

        # The routine's auto_verify command is `echo "tests passed"`
        assert "tests passed" in data["log_output"]

    async def test_test_run_reports_failure(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """A command that exits non-zero produces 'failed' status."""
        client, repo, app, drain = client_with_auto_verify

        from orchestrator.git import TestRunner

        test_runner: TestRunner = app.state.test_runner

        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = run_data["worktree_path"]

        # Start a test run directly with a command that will fail
        test_run_id = await test_runner.start_test_run(
            run_id=run_id,
            worktree_path=worktree_path,
            commands=["exit 1"],
        )

        await test_runner.wait_for_test_run(test_run_id)
        get_resp = await client.get(f"/api/runs/{run_id}/review/test/{test_run_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()

        assert data["status"] == "failed"

    async def test_test_run_not_found_returns_404(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """GET with unknown test_run_id returns 404."""
        client, repo, _app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/test/nonexistent-id")
        assert resp.status_code == 404

    async def test_test_run_schema_fields(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """TestRunResult response contains all required schema fields."""
        client, repo, app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        post_resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert post_resp.status_code == 202
        test_run_id = post_resp.json()["test_run_id"]

        await app.state.test_runner.wait_for_test_run(test_run_id)
        get_resp = await client.get(f"/api/runs/{run_id}/review/test/{test_run_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()

        required_fields = {"test_run_id", "status", "log_output", "started_at"}
        assert required_fields.issubset(set(data.keys()))
        assert data["test_run_id"] == test_run_id
        assert isinstance(data["log_output"], str)
        assert isinstance(data["started_at"], str)
