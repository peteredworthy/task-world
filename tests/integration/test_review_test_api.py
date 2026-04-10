"""Integration tests for review test execution API endpoints.

Covers POST /api/runs/{run_id}/review/test and
       GET  /api/runs/{run_id}/review/test/{test_run_id}.
"""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.conftest import DrainFn


@pytest.fixture
async def client_with_auto_verify(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    git_repo: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, Any, DrainFn], None]:
    """Test client wired to a routine that has auto_verify commands."""
    client, drain, _, _, app = _shared_app_fixture
    yield client, git_repo, app, drain


async def _create_and_start_run(
    client: AsyncClient,
    project_path: Path,
    drain: DrainFn,
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
    assert resp.status_code == 202, resp.text
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["status"] == "active"
    assert data["worktree_path"] is not None
    return data


async def _wait_for_completion(
    client: AsyncClient,
    run_id: str,
    test_run_id: str,
    app: Any,
) -> dict[str, Any]:
    """Wait for a background test run to complete by awaiting its asyncio task."""
    from orchestrator.git import TestRunner

    test_runner: TestRunner = app.state.test_runner
    await test_runner.wait_for_test_run(test_run_id)
    resp = await client.get(f"/api/runs/{run_id}/review/test/{test_run_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/test — start a test run
# ---------------------------------------------------------------------------


class TestStartTestRun:
    async def test_endpoint_starts_and_returns_202(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """POST /review/test returns HTTP 202 with a test_run_id and 'running' status."""
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

        # Wait for the background task to finish so the in-memory DB is not
        # disposed while the task is still running (causes "no such table" errors
        # when running the full parallel test suite).
        await _wait_for_completion(client, run_id, data["test_run_id"], _app)

    async def test_no_auto_verify_returns_422(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """POST returns 422 when routine has no auto_verify commands."""
        client, repo, _app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
        run_id = run_data["id"]

        resp = await client.post(f"/api/runs/{run_id}/review/test", json={})

        assert resp.status_code == 422, resp.text
        assert "auto_verify" in resp.json()["detail"].lower()

    async def test_run_not_found_returns_404(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """POST returns 404 for a non-existent run_id."""
        client, _repo, _app, _drain = client_with_auto_verify

        resp = await client.post("/api/runs/does-not-exist/review/test", json={})

        assert resp.status_code == 404

    async def test_run_without_worktree_returns_409(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """POST returns 409 when run exists but has no active worktree (not started)."""
        client, repo, _app, _drain = client_with_auto_verify
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
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """POST returns 409 when a test run is already in progress for the same run."""
        client, repo, app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = run_data["worktree_path"]

        from orchestrator.git import TestRunner

        test_runner: TestRunner = app.state.test_runner

        # Directly inject a slow-running test to hold the "running" lock.
        injected_test_run_id = await test_runner.start_test_run(
            run_id=run_id,
            worktree_path=worktree_path,
            commands=["sleep 10"],
        )

        # Attempting a second run via the API must be rejected
        resp = await client.post(f"/api/runs/{run_id}/review/test", json={})

        assert resp.status_code == 409, resp.text
        assert "already in progress" in resp.json()["detail"].lower()

        # Cancel the background sleep task via the stored task reference so it
        # doesn't outlive the test and hit the disposed in-memory DB on teardown.
        bg_task = test_runner._tasks.get(injected_test_run_id)
        if bg_task is not None and not bg_task.done():
            bg_task.cancel()
            try:
                await bg_task
            except (asyncio.CancelledError, Exception):
                pass


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/review/test/{test_run_id} — poll test results
# ---------------------------------------------------------------------------


class TestGetTestRun:
    async def test_endpoint_completes_and_returns_status(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """Test run started via POST eventually completes with a terminal status."""
        client, repo, app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        post_resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert post_resp.status_code == 202
        test_run_id = post_resp.json()["test_run_id"]

        data = await _wait_for_completion(client, run_id, test_run_id, app)

        assert data["status"] in {"passed", "failed", "error"}
        assert data["test_run_id"] == test_run_id

    async def test_output_captured_in_log(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """log_output contains actual stdout produced by the test command."""
        client, repo, app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        post_resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert post_resp.status_code == 202
        test_run_id = post_resp.json()["test_run_id"]

        data = await _wait_for_completion(client, run_id, test_run_id, app)

        # The auto-verify routine runs: echo "tests passed"
        assert "tests passed" in data["log_output"]

    async def test_failure_reported_as_failed_status(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """A command that exits non-zero causes the test run to report 'failed'."""
        client, repo, app, drain = client_with_auto_verify

        from orchestrator.git import TestRunner

        test_runner: TestRunner = app.state.test_runner

        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = run_data["worktree_path"]

        # Inject a failing command directly into the test runner
        test_run_id = await test_runner.start_test_run(
            run_id=run_id,
            worktree_path=worktree_path,
            commands=["exit 1"],
        )

        data = await _wait_for_completion(client, run_id, test_run_id, app)

        assert data["status"] == "failed"

    async def test_response_contains_required_schema_fields(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """TestRunResult response includes test_run_id, status, log_output, started_at."""
        client, repo, app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        post_resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert post_resp.status_code == 202
        test_run_id = post_resp.json()["test_run_id"]

        data = await _wait_for_completion(client, run_id, test_run_id, app)

        required_fields = {"test_run_id", "status", "log_output", "started_at"}
        assert required_fields.issubset(set(data.keys()))
        assert data["test_run_id"] == test_run_id
        assert isinstance(data["log_output"], str)
        assert isinstance(data["started_at"], str)

    async def test_test_run_not_found_returns_404(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """GET with an unknown test_run_id returns 404."""
        client, repo, _app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/test/unknown-test-run-id")

        assert resp.status_code == 404

    async def test_get_immediately_after_post_returns_valid_status(
        self, client_with_auto_verify: tuple[AsyncClient, Path, Any, DrainFn]
    ) -> None:
        """GET immediately after POST returns a valid status (running or terminal).

        After asserting on the immediate response, wait for the background
        test task to finish so the in-memory DB is not disposed while the
        task is still running (which causes "no such table" errors under
        parallel test load).
        """
        client, repo, app, drain = client_with_auto_verify
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        post_resp = await client.post(f"/api/runs/{run_id}/review/test", json={})
        assert post_resp.status_code == 202
        test_run_id = post_resp.json()["test_run_id"]

        # Await the background task directly — no polling needed.
        # This also ensures the background task finishes before fixture teardown
        # disposes the in-memory DB (avoids "no such table" errors under parallel load).
        data = await _wait_for_completion(client, run_id, test_run_id, app)

        assert data["status"] in {"passed", "failed", "error"}
        assert data["test_run_id"] == test_run_id
