"""Integration tests for conflict resolution and revert API endpoints.

Tests cover:
- Per-block conflict resolution via POST /review/conflicts/{path}/resolve
- Revert of a back-merge via POST /review/revert-back-merge
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.conftest import (
    DrainFn,
    _commit_file,
    _git,
    _setup_conflict,
)


@pytest.fixture
async def client_with_repo(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    git_repo: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, DrainFn], None]:
    """Yield (client, git_repo, drain) using the shared app."""
    client, drain, _, _, _ = _shared_app_fixture
    yield client, git_repo, drain


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

    async def test_resolve_invalid_choice_returns_422(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """An invalid choice value returns 422."""
        client, repo, drain = client_with_repo
        run_id, _ = await _setup_conflict(client, repo, drain)

        resp = await client.post(
            f"/api/runs/{run_id}/review/conflicts/conflict.py/resolve",
            json={"resolutions": [{"block_index": 0, "choice": "invalid_choice"}]},
        )
        assert resp.status_code == 422

    async def test_resolve_manual_without_content_returns_422(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Manual choice without manual_content returns 422."""
        client, repo, drain = client_with_repo
        run_id, _ = await _setup_conflict(client, repo, drain)

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

    async def test_revert_clean_back_merge_succeeds(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Reverting a clean back-merge (real merge commit) returns 200."""
        client, repo, drain = client_with_repo
        run_id, _, _ = await self._setup_clean_merge(client, repo, drain)

        resp = await client.post(f"/api/runs/{run_id}/review/revert-back-merge")
        assert resp.status_code == 200

    async def test_revert_returns_reverted_commit_sha(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Revert response contains the SHA of the reverted merge commit."""
        client, repo, drain = client_with_repo
        run_id, _, merge_sha = await self._setup_clean_merge(client, repo, drain)

        resp = await client.post(f"/api/runs/{run_id}/review/revert-back-merge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reverted_commit"] == merge_sha

    async def test_revert_returns_new_head(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Revert response contains a new_head SHA different from the merge SHA."""
        client, repo, drain = client_with_repo
        run_id, worktree_path, merge_sha = await self._setup_clean_merge(client, repo, drain)

        resp = await client.post(f"/api/runs/{run_id}/review/revert-back-merge")
        data = resp.json()
        assert data["new_head"] != merge_sha
        assert len(data["new_head"]) == 40

        # Worktree HEAD should match the returned new_head
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
