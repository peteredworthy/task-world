"""Integration tests for merge readiness endpoint and merge-back strategy.

Covers:
- Gate computation in various states (all pass, conflicts fail, divergence fail)
- Merge with squash creates single commit
- Merge with merge strategy preserves history
- 409 when gates are unmet or the run is not completed

Each test gets its own FastAPI app and in-memory database; ``create_app`` is
cheap because compiled routes are cached and grafted onto every new app. No
cross-test naming discipline is needed here — hardcoded names and global
collection assertions are safe. See ``tests/integration/conftest.py``.

Gate/merge *semantics* are unit-tested in ``tests/unit/test_merge_readiness.py``
and ``tests/unit/test_branch_ops.py``; these tests pin the API wiring. The
worktree spawn dominates each test's cost, so gate states that share a setup
are asserted in sequence over one run.
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from orchestrator.config import RunStatus
from orchestrator.db import RunRepository, commit_with_event_outbox, create_wired_event_store_v2
from orchestrator.db.access.mutations import save_run
from orchestrator.workflow import PersistentEventEmitter, RunWorktreeCommitCompleted
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


async def _mark_run_completed(app: Any, run_id: str, *, finalized: bool = False) -> None:
    """Directly mark a run as COMPLETED in the database for testing."""
    async with app.state.session_factory() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)
        run.status = RunStatus.COMPLETED
        await save_run(repo.session, run)
        if finalized:
            emitter = PersistentEventEmitter(create_wired_event_store_v2(session))
            await emitter.emit(
                RunWorktreeCommitCompleted(
                    run_id=run_id,
                    task_id="__run_finalization__",
                    worktree_path=run.worktree_path or "",
                    commit_type="graph_run_finalization",
                    message="Finalize graph run for merge disposition test",
                    created_commit=False,
                )
            )
            await commit_with_event_outbox(session)
        else:
            await session.commit()


# ---------------------------------------------------------------------------
# Gate computation tests
# ---------------------------------------------------------------------------


async def test_merge_readiness_all_pass_and_rejects_non_completed(
    app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
) -> None:
    """All gates pass in a clean state, but merge-back still returns 409
    while the run is not COMPLETED."""
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

    # Even with all gates green, an ACTIVE (non-completed) run cannot merge back
    resp = await client.post(
        f"/api/runs/{run_id}/merge-back",
        json={"strategy": "squash"},
    )
    assert resp.status_code == 409
    assert "COMPLETED" in resp.json()["detail"]


async def test_readiness_gates_through_conflict_lifecycle(
    app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
) -> None:
    """One diverged run walks the failing-gate states: clean_merge fails on
    conflicting divergence, no_unresolved_conflicts fails after the
    back-merge, and merge-back is 409-blocked even for a COMPLETED run."""
    client, repo, app, drain = app_and_client
    run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
    run_id = run_data["id"]
    worktree_path = Path(run_data["worktree_path"])

    # Both branches modify the same file differently — conflicting divergence
    _commit_file(worktree_path, "shared.py", "x = 'run version'\n", "Run: shared.py")
    _commit_file(repo, "shared.py", "x = 'main version'\n", "Main: shared.py")

    # Before any back-merge: a merge would conflict → clean_merge fails
    resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
    assert resp.status_code == 200
    data = resp.json()
    gate_map = {g["name"]: g["status"] for g in data["gates"]}
    assert gate_map["clean_merge"] == "fail"
    assert data["ready"] is False

    # Back-merge puts conflict markers in the worktree
    back_merge_resp = await client.post(f"/api/runs/{run_id}/back-merge")
    assert back_merge_resp.status_code == 200
    assert back_merge_resp.json()["status"] == "conflicts"

    resp = await client.get(f"/api/runs/{run_id}/review/merge-readiness")
    assert resp.status_code == 200
    data = resp.json()
    gate_map = {g["name"]: g["status"] for g in data["gates"]}
    assert gate_map["no_unresolved_conflicts"] == "fail"
    assert data["ready"] is False

    # Even as COMPLETED, merge-back is blocked because a gate fails
    await _mark_run_completed(app, run_id, finalized=True)

    resp = await client.post(
        f"/api/runs/{run_id}/merge-back",
        json={"strategy": "squash"},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    # A truthful branch disposition explains the concrete blocking condition.
    assert detail["merge_disposition"]["status"] in {"dirty", "blocked"}


async def test_branch_status_reports_each_truthful_merge_disposition(
    app_and_client: tuple[AsyncClient, Path, Any, DrainFn],
) -> None:
    """A zero-ahead branch is not called merged without a durable merge receipt."""
    client, repo, app, drain = app_and_client
    run_data = await _create_and_start_run(client, repo, drain, routine_id="simple-routine")
    run_id = run_data["id"]
    worktree_path = Path(run_data["worktree_path"])

    async def disposition() -> dict[str, Any]:
        response = await client.get(f"/api/runs/{run_id}/branch-status")
        assert response.status_code == 200
        return response.json()["merge_disposition"]

    blocked = await disposition()
    assert blocked["status"] == "blocked"
    assert "active" in blocked["reason"]

    await _mark_run_completed(app, run_id)
    unfinalized = await disposition()
    assert unfinalized["status"] == "unfinalized"

    await _mark_run_completed(app, run_id, finalized=True)
    no_changes = await disposition()
    assert no_changes["status"] == "no_changes"
    assert "no commits" in no_changes["reason"]

    _commit_file(worktree_path, "ready.py", "ready = True\n", "Create mergeable run change")
    ready = await disposition()
    assert ready["status"] == "ready"

    dirty_path = worktree_path / "ready.py"
    dirty_path.write_text("ready = False\n")
    dirty = await disposition()
    assert dirty["status"] == "dirty"

    dirty_path.write_text("ready = True\n")
    assert (await disposition())["status"] == "ready"

    merged = await client.post(f"/api/runs/{run_id}/merge-back", json={"strategy": "squash"})
    assert merged.status_code == 200
    merged_disposition = await disposition()
    assert merged_disposition["status"] == "merged"
    assert merged_disposition["merge_commit"] == merged.json()["merge_commit"]


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

    await _mark_run_completed(app, run_id, finalized=True)

    resp = await client.post(
        f"/api/runs/{run_id}/merge-back",
        json={"strategy": "squash"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategy"] == "squash"
    assert data["merge_commit"] is not None

    disposition = (await client.get(f"/api/runs/{run_id}/branch-status")).json()[
        "merge_disposition"
    ]
    assert disposition["status"] == "merged"
    assert disposition["merge_commit"] == data["merge_commit"]

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

    await _mark_run_completed(app, run_id, finalized=True)

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
