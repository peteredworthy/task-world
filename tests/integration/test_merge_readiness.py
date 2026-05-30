"""Integration tests for merge readiness endpoint and merge-back strategy.

Covers:
- Gate computation in various states (all pass, conflicts fail, tests fail, jobs running)
- Merge with squash creates single commit
- Merge with merge strategy preserves history
- 409 when gates are unmet

WARNING — shared fixture:
    The ``app_and_client`` adapter below wraps the module-scoped
    ``_shared_app_fixture`` (from ``tests/integration/conftest.py``) so every
    test in this file reuses one FastAPI app + in-memory DB. Isolation relies
    on: (1) ``git_repo`` having a UUID-suffixed name unique per test,
    (2) server-generated run UUIDs, (3) per-test teardown cancelling runs
    scoped to ``git_repo.name``. Don't assert on global ``/api/runs`` counts;
    reference your run only by the ``id`` you received.
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from orchestrator.config import RunStatus
from orchestrator.db import RunRepository
from orchestrator.db.access.mutations import save_run
from tests.integration.git_helpers import _commit_file, _git
from tests.integration.signal_helpers import DrainFn

# Shared app + git_repo come from tests/integration/conftest.py.


@pytest.fixture
async def app_and_client(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    git_repo: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, Any, DrainFn], None]:
    """Adapter: (client, git_repo, app, drain) shape this module expects.

    Cleans up by cancelling this test's runs (matched by unique repo_name).
    """
    from tests.integration.conftest import cleanup_runs_for_repo

    client, drain, _, _, app = _shared_app_fixture
    yield client, git_repo, app, drain
    await cleanup_runs_for_repo(client, git_repo.name)


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
        await save_run(repo.session, run)
        await session.commit()


# ---------------------------------------------------------------------------
# Gate computation tests
# ---------------------------------------------------------------------------


async def test_merge_readiness_all_pass(
    app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
) -> None:
    """All gates pass in a clean state (simple-routine, no conflicts, idle)."""
    client, repo, app, drain = app_and_client
    run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
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
    app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
) -> None:
    """no_unresolved_conflicts gate fails when the worktree has conflict files."""
    client, repo, app, drain = app_and_client
    run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
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


# ---------------------------------------------------------------------------
# Merge strategy tests
# ---------------------------------------------------------------------------


async def test_merge_back_with_strategy_squash(
    app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
) -> None:
    """Squash merge creates a single commit on source branch (squashes run history)."""
    client, repo, app, drain = app_and_client
    run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
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
    app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
) -> None:
    """Merge strategy preserves full run branch commit history on source branch."""
    client, repo, app, drain = app_and_client
    run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
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
    app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
) -> None:
    """merge-back returns 409 when readiness gates are not met (unresolved conflicts)."""
    client, repo, app, drain = app_and_client
    run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
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


async def test_merge_back_rejects_non_completed_run(
    app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
) -> None:
    """merge-back returns 409 for a run that is not completed."""
    client, repo, _app, drain = app_and_client
    run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
    run_id = run_data["id"]

    resp = await client.post(
        f"/api/runs/{run_id}/merge-back",
        json={"strategy": "squash"},
    )
    assert resp.status_code == 409
    assert "COMPLETED" in resp.json()["detail"]


async def test_merge_readiness_clean_merge_fail(
    app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
) -> None:
    """clean_merge gate fails when source branch has diverged with conflicting changes."""
    client, repo, app, drain = app_and_client
    run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
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
