"""Integration tests for back-merge and conflict detection API endpoints.

Tests cover:
- Auto-commit on clean back-merge (POST /review/back-merge)
- Conflict detection (POST /review/back-merge with conflicts)
- Conflict file listing (GET /review/conflicts)

WARNING — shared fixture:
    The ``client_with_repo`` / ``git_repo`` / ``_shared_app_fixture`` fixtures
    come from ``tests/integration/conftest.py`` and reuse a single FastAPI app
    + in-memory DB across every test in this file (module scope). Isolation
    relies on: (1) ``git_repo`` having a UUID-suffixed name unique per test,
    (2) server-generated run UUIDs, (3) per-test teardown cancelling runs
    scoped to ``git_repo.name``. Don't assert on global ``/api/runs`` counts;
    reference your run only by the ``id`` you received.
"""

from pathlib import Path
from typing import Any

from httpx import AsyncClient

from tests.integration.conftest import (
    DrainFn,
    _commit_file,
    _git,
    _setup_conflict,
)

# Fixtures (client_with_repo, git_repo, _shared_app_fixture) come from
# tests/integration/conftest.py. See that module for isolation guarantees.


async def _create_and_start_run(
    client: AsyncClient, project_path: Path, drain: DrainFn
) -> dict[str, Any]:
    """Helper: create and start a run pointing at a real git repo."""
    resp = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": project_path.name,
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


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/back-merge — clean merge
# ---------------------------------------------------------------------------


class TestBackMergeClean:
    async def test_clean_merge_returns_status_clean(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """A clean back-merge returns status='clean'."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        # Commit a new file to main that doesn't touch anything on the run branch
        _commit_file(repo, "main_only.py", "x = 1\n", "Add main_only.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert resp.status_code == 200
        assert resp.json()["status"] == "clean"

    async def test_clean_merge_returns_merge_commit_sha(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """A clean back-merge returns a non-null merge_commit_sha."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        _commit_file(repo, "feature.py", "def feature(): pass\n", "Add feature.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["merge_commit_sha"] is not None
        assert len(data["merge_commit_sha"]) == 40

    async def test_clean_merge_worktree_head_matches_returned_sha(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """After a clean back-merge, the worktree HEAD equals the returned SHA (auto-committed)."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(repo, "new_file.py", "val = 42\n", "Add new_file.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert resp.status_code == 200
        merge_sha = resp.json()["merge_commit_sha"]

        head_sha = _git(["rev-parse", "HEAD"], cwd=worktree_path)
        assert head_sha == merge_sha

    async def test_clean_merge_no_conflict_files(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """A clean back-merge returns empty conflict_files and conflict_count=0."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        _commit_file(repo, "clean.py", "clean = True\n", "Add clean.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["conflict_files"] == []
        assert data["conflict_count"] == 0


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/back-merge — conflicting merge
# ---------------------------------------------------------------------------


class TestBackMergeConflicts:
    async def test_conflict_merge_returns_conflicts_status(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Back-merge with conflicts returns status='conflicts'."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "shared.py", "x = 'run'\n", "Run: shared.py")
        _commit_file(repo, "shared.py", "x = 'main'\n", "Main: shared.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert resp.status_code == 200
        assert resp.json()["status"] == "conflicts"

    async def test_conflict_merge_lists_conflict_files(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """The conflicting file appears in conflict_files."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "shared.py", "x = 'run'\n", "Run: shared.py")
        _commit_file(repo, "shared.py", "x = 'main'\n", "Main: shared.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        data = resp.json()
        assert "shared.py" in data["conflict_files"]
        assert data["conflict_count"] >= 1

    async def test_conflict_merge_null_commit_sha(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Back-merge with conflicts returns null merge_commit_sha (no auto-commit)."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "shared.py", "x = 'run'\n", "Run: shared.py")
        _commit_file(repo, "shared.py", "x = 'main'\n", "Main: shared.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert resp.json()["merge_commit_sha"] is None

    async def test_conflict_merge_multiple_files(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """All conflicting files appear in the response when multiple files conflict."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "alpha.py", "a = 'run'\n", "Run: alpha.py")
        _commit_file(worktree_path, "beta.py", "b = 'run'\n", "Run: beta.py")
        _commit_file(repo, "alpha.py", "a = 'main'\n", "Main: alpha.py")
        _commit_file(repo, "beta.py", "b = 'main'\n", "Main: beta.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        data = resp.json()
        assert data["status"] == "conflicts"
        assert "alpha.py" in data["conflict_files"]
        assert "beta.py" in data["conflict_files"]
        assert data["conflict_count"] == 2


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/review/conflicts
# ---------------------------------------------------------------------------


class TestGetConflicts:
    async def test_no_active_merge_returns_empty_list(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """With no merge in progress, conflicts endpoint returns empty list."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/conflicts")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_conflict_file_listed_with_path(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """After a conflicting back-merge, the conflict file is listed."""
        client, repo, drain = client_with_repo
        run_id, _ = await _setup_conflict(client, repo, drain, filename="conflict.py")

        resp = await client.get(f"/api/runs/{run_id}/review/conflicts")
        assert resp.status_code == 200
        files = resp.json()
        paths = [f["path"] for f in files]
        assert "conflict.py" in paths

    async def test_conflict_file_has_unresolved_status(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Each conflict file has status='unresolved'."""
        client, repo, drain = client_with_repo
        run_id, _ = await _setup_conflict(client, repo, drain)

        resp = await client.get(f"/api/runs/{run_id}/review/conflicts")
        files = resp.json()
        assert len(files) >= 1
        assert files[0]["status"] == "unresolved"

    async def test_conflict_file_has_blocks(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Each conflict file contains at least one conflict block."""
        client, repo, drain = client_with_repo
        run_id, _ = await _setup_conflict(client, repo, drain)

        resp = await client.get(f"/api/runs/{run_id}/review/conflicts")
        files = resp.json()
        assert files[0]["block_count"] >= 1
        assert len(files[0]["blocks"]) >= 1

    async def test_conflict_block_schema(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Each conflict block has index, ours_content, and theirs_content."""
        client, repo, drain = client_with_repo
        run_id, _ = await _setup_conflict(
            client,
            repo,
            drain,
            ours_content="x = 'run_version'\n",
            theirs_content="x = 'main_version'\n",
        )

        resp = await client.get(f"/api/runs/{run_id}/review/conflicts")
        block = resp.json()[0]["blocks"][0]
        assert block["index"] == 0
        assert "ours_content" in block
        assert "theirs_content" in block
        assert "run_version" in block["ours_content"]
        assert "main_version" in block["theirs_content"]

    async def test_run_without_worktree_returns_409(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Conflicts endpoint on a run with no worktree returns 409."""
        client, repo, drain = client_with_repo
        resp = await client.post(
            "/api/runs",
            json={
                "routine_id": "simple-routine",
                "repo_name": repo.name,
                "branch": "main",
            },
        )
        assert resp.status_code == 201
        run_id = resp.json()["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/conflicts")
        assert resp.status_code == 409

    async def test_run_not_found_returns_404(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Conflicts endpoint for a nonexistent run returns 404."""
        client, _repo, drain = client_with_repo
        resp = await client.get("/api/runs/nonexistent-run-id/review/conflicts")
        assert resp.status_code == 404
