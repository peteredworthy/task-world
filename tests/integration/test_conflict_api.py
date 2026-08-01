"""Integration tests for conflict detection, resolution, and revert API endpoints.

Tests cover:
- Auto-commit on clean back-merge
- Conflict file listing via GET /review/conflicts
- Per-block conflict resolution via POST /review/conflicts/{path}/resolve
- Revert of a back-merge via POST /review/revert-back-merge

Each test gets its own FastAPI app and in-memory database; ``create_app`` is
cheap because compiled routes are cached and grafted onto every new app. No
cross-test naming discipline is needed here — hardcoded names and global
collection assertions are safe. See ``tests/integration/conftest.py``.

Merge/conflict *semantics* are unit-tested against real git in
``tests/unit/test_conflict_ops.py`` and ``tests/unit/test_branch_ops.py``;
these tests pin the API wiring (status codes, response schema, worktree
lookup). The worktree spawn (create + start + drain) dominates each test's
cost, so facets of the same response are asserted together in one test.
"""

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.git_helpers import _commit_file, _git
from tests.integration.signal_helpers import DrainFn

pytestmark = pytest.mark.slow

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


async def _setup_conflict(
    client: AsyncClient,
    repo: Path,
    drain: DrainFn,
    filename: str = "conflict.py",
    ours_content: str = "x = 'run_version'\n",
    theirs_content: str = "x = 'main_version'\n",
) -> tuple[str, Path]:
    """Helper: create a run with a conflicting back-merge in-progress.

    Returns (run_id, worktree_path).
    """
    run_data = await _create_and_start_run(client, repo, drain)
    run_id = run_data["id"]
    worktree_path = Path(run_data["worktree_path"])

    # Both branches add the same file with different content → conflict
    _commit_file(worktree_path, filename, ours_content, f"Run: add {filename}")
    _commit_file(repo, filename, theirs_content, f"Main: add {filename}")

    back_merge_resp = await client.post(f"/api/runs/{run_id}/back-merge")
    assert back_merge_resp.status_code == 200
    assert back_merge_resp.json()["status"] == "conflicts"

    return run_id, worktree_path


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/back-merge — clean merge
# ---------------------------------------------------------------------------


class TestBackMergeClean:
    async def test_clean_merge_response_and_worktree_state(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """A clean back-merge returns status='clean', a 40-char merge SHA,
        no conflicts, and auto-commits so the worktree HEAD equals the SHA."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Commit a new file to main that doesn't touch anything on the run branch
        _commit_file(repo, "main_only.py", "x = 1\n", "Add main_only.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "clean"
        assert data["merge_commit_sha"] is not None
        assert len(data["merge_commit_sha"]) == 40
        assert data["conflict_files"] == []
        assert data["conflict_count"] == 0

        head_sha = _git(["rev-parse", "HEAD"], cwd=worktree_path)
        assert head_sha == data["merge_commit_sha"]


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/back-merge — conflicting merge
# ---------------------------------------------------------------------------


class TestBackMergeConflicts:
    async def test_conflict_merge_reports_files_and_skips_commit(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """A conflicting back-merge returns status='conflicts', lists the
        conflicting file, and does not auto-commit (null merge_commit_sha)."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "shared.py", "x = 'run'\n", "Run: shared.py")
        _commit_file(repo, "shared.py", "x = 'main'\n", "Main: shared.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "conflicts"
        assert "shared.py" in data["conflict_files"]
        assert data["conflict_count"] == 1
        assert data["merge_commit_sha"] is None

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
    async def test_conflict_listing_lifecycle(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """The conflicts list is empty with no merge in progress, then lists
        the conflicted file with unresolved status and parsed blocks after a
        conflicting back-merge."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        resp = await client.get(f"/api/runs/{run_id}/review/conflicts")
        assert resp.status_code == 200
        assert resp.json() == []

        _commit_file(worktree_path, "conflict.py", "x = 'run_version'\n", "Run: add conflict.py")
        _commit_file(repo, "conflict.py", "x = 'main_version'\n", "Main: add conflict.py")
        back_merge_resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert back_merge_resp.status_code == 200
        assert back_merge_resp.json()["status"] == "conflicts"

        resp = await client.get(f"/api/runs/{run_id}/review/conflicts")
        assert resp.status_code == 200
        files = resp.json()
        assert [f["path"] for f in files] == ["conflict.py"]
        assert files[0]["status"] == "unresolved"
        assert files[0]["block_count"] >= 1
        assert len(files[0]["blocks"]) >= 1
        block = files[0]["blocks"][0]
        assert block["index"] == 0
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


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/conflicts/{file_path}/resolve
# ---------------------------------------------------------------------------


class TestResolveConflict:
    async def test_resolve_ours_removes_markers(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Resolving with 'ours' removes conflict markers from the file."""
        client, repo, drain = client_with_repo
        run_id, worktree_path = await _setup_conflict(
            client, repo, drain, ours_content="x = 'run_version'\n"
        )

        resp = await client.post(
            f"/api/runs/{run_id}/review/conflicts/conflict.py/resolve",
            json={"resolutions": [{"block_index": 0, "choice": "ours"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "conflict.py"
        assert data["status"] == "resolved"
        assert data["remaining_conflicts"] == 0

        content = (worktree_path / "conflict.py").read_text()
        assert "<<<<<<" not in content
        assert "run_version" in content

    async def test_resolve_theirs_removes_markers(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Resolving with 'theirs' writes the theirs content and removes markers."""
        client, repo, drain = client_with_repo
        run_id, worktree_path = await _setup_conflict(
            client, repo, drain, theirs_content="x = 'main_version'\n"
        )

        resp = await client.post(
            f"/api/runs/{run_id}/review/conflicts/conflict.py/resolve",
            json={"resolutions": [{"block_index": 0, "choice": "theirs"}]},
        )
        assert resp.status_code == 200
        assert resp.json()["remaining_conflicts"] == 0

        content = (worktree_path / "conflict.py").read_text()
        assert "<<<<<<" not in content
        assert "main_version" in content

    async def test_resolve_manual_writes_custom_content(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Resolving with 'manual' writes the provided custom content."""
        client, repo, drain = client_with_repo
        run_id, worktree_path = await _setup_conflict(client, repo, drain)

        resp = await client.post(
            f"/api/runs/{run_id}/review/conflicts/conflict.py/resolve",
            json={
                "resolutions": [
                    {
                        "block_index": 0,
                        "choice": "manual",
                        "manual_content": "x = 'manually_resolved'\n",
                    }
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["remaining_conflicts"] == 0

        content = (worktree_path / "conflict.py").read_text()
        assert "manually_resolved" in content
        assert "<<<<<<" not in content

    async def test_resolve_invalid_bodies_return_422(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """An invalid choice, or manual choice without manual_content, returns
        422. Neither request mutates the worktree, so one conflict setup
        serves both checks. (Run lookup precedes body validation, so a real
        conflicted run is required to reach the 422.)"""
        client, repo, drain = client_with_repo
        run_id, _ = await _setup_conflict(client, repo, drain)

        resp = await client.post(
            f"/api/runs/{run_id}/review/conflicts/conflict.py/resolve",
            json={"resolutions": [{"block_index": 0, "choice": "invalid_choice"}]},
        )
        assert resp.status_code == 422

        resp = await client.post(
            f"/api/runs/{run_id}/review/conflicts/conflict.py/resolve",
            json={"resolutions": [{"block_index": 0, "choice": "manual"}]},
        )
        assert resp.status_code == 422

    async def test_resolve_nonexistent_file_returns_404(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Trying to resolve a file that has no conflicts returns 404."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.post(
            f"/api/runs/{run_id}/review/conflicts/nonexistent.py/resolve",
            json={"resolutions": [{"block_index": 0, "choice": "ours"}]},
        )
        assert resp.status_code == 404

    async def test_remaining_conflicts_decrements_after_partial_resolve(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """After resolving one of two conflicting files, remaining_conflicts == 1."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Create two conflicting files
        _commit_file(worktree_path, "file_a.py", "a = 'run'\n", "Run: file_a")
        _commit_file(worktree_path, "file_b.py", "b = 'run'\n", "Run: file_b")
        _commit_file(repo, "file_a.py", "a = 'main'\n", "Main: file_a")
        _commit_file(repo, "file_b.py", "b = 'main'\n", "Main: file_b")

        back_merge_resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert back_merge_resp.json()["status"] == "conflicts"
        assert back_merge_resp.json()["conflict_count"] == 2

        # Resolve only file_a — file_b still unresolved
        resp = await client.post(
            f"/api/runs/{run_id}/review/conflicts/file_a.py/resolve",
            json={"resolutions": [{"block_index": 0, "choice": "ours"}]},
        )
        assert resp.status_code == 200
        assert resp.json()["remaining_conflicts"] == 1


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/revert-back-merge
# ---------------------------------------------------------------------------


class TestRevertBackMerge:
    async def _setup_clean_merge(
        self, client: AsyncClient, repo: Path, drain: DrainFn
    ) -> tuple[str, Path, str]:
        """Helper: create a clean back-merge and return (run_id, worktree_path, merge_sha).

        Both branches diverge so the merge creates a real merge commit (not fast-forward).
        """
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Run branch diverges with its own commit (creates non-fast-forward merge)
        _commit_file(worktree_path, "run_change.py", "run = 1\n", "Run: add run_change.py")
        # Main gets a non-conflicting commit
        _commit_file(repo, "main_extra.py", "extra = 1\n", "Main: add main_extra.py")

        back_merge_resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert back_merge_resp.status_code == 200
        data = back_merge_resp.json()
        assert data["status"] == "clean"
        merge_sha = data["merge_commit_sha"]
        assert merge_sha is not None

        return run_id, worktree_path, merge_sha

    async def test_revert_clean_back_merge_resets_head(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Reverting a clean back-merge returns the reverted merge SHA and a
        new head, and moves the worktree HEAD to that new head."""
        client, repo, drain = client_with_repo
        run_id, worktree_path, merge_sha = await self._setup_clean_merge(client, repo, drain)

        resp = await client.post(f"/api/runs/{run_id}/review/revert-back-merge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reverted_commit"] == merge_sha
        assert data["new_head"] != merge_sha
        assert len(data["new_head"]) == 40

        actual_head = _git(["rev-parse", "HEAD"], cwd=worktree_path)
        assert actual_head == data["new_head"]

    async def test_revert_without_merge_commit_returns_409(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Revert when HEAD is not a merge commit (no back-merge done) returns 409."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        # No back-merge was performed; HEAD is a regular (non-merge) commit
        resp = await client.post(f"/api/runs/{run_id}/review/revert-back-merge")
        assert resp.status_code == 409

    async def test_revert_run_not_found_returns_404(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Revert on a nonexistent run returns 404."""
        client, _repo, drain = client_with_repo
        resp = await client.post("/api/runs/nonexistent-run-id/review/revert-back-merge")
        assert resp.status_code == 404

    async def test_revert_run_without_worktree_returns_409(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Revert on a run without a worktree returns 409."""
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

        resp = await client.post(f"/api/runs/{run_id}/review/revert-back-merge")
        assert resp.status_code == 409
