"""Integration tests for review API endpoints (diff, diff/files, commits).

Each test gets its own FastAPI app and in-memory database; ``create_app`` is
cheap because compiled routes are cached and grafted onto every new app. No
cross-test naming discipline is needed here — hardcoded names and global
collection assertions are safe. See ``tests/integration/conftest.py``.

Diff/log *semantics* are unit-tested against real git in
``tests/unit/test_diff_ops.py``; these tests pin the API wiring. The worktree
spawn (create + start + drain) dominates each test's cost, so each endpoint
family is exercised as one narrative over a single run: assert the empty
state first, then layer commits and assert each response in sequence.
"""

from pathlib import Path
from typing import Any

from httpx import AsyncClient

from tests.integration.git_helpers import _commit_file, _git
from tests.integration.signal_helpers import DrainFn

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
# GET /api/runs/{run_id}/review/diff
# ---------------------------------------------------------------------------


class TestGetDiff:
    async def test_diff_scopes_lifecycle(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """One run exercises every diff scope: empty aggregate, aggregate
        with changes, commit scope (with and without ref), and task scope
        (with and without ref)."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Empty branch → empty aggregate diff, schema fields present
        resp = await client.get(f"/api/runs/{run_id}/review/diff")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) >= {"diff", "scope"}
        assert isinstance(data["diff"], str)
        assert data["scope"] == "aggregate"
        assert data["diff"] == ""

        sha1 = _commit_file(
            worktree_path, "feature.py", "def foo():\n    return 1\n", "Add feature.py"
        )

        # Aggregate diff contains the change
        resp = await client.get(f"/api/runs/{run_id}/review/diff")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope"] == "aggregate"
        assert "feature.py" in data["diff"]
        assert "+def foo():" in data["diff"]

        # commit scope without ref → 400
        resp = await client.get(f"/api/runs/{run_id}/review/diff?scope=commit")
        assert resp.status_code == 400

        # commit scope with ref → single-commit diff (git show includes author metadata)
        resp = await client.get(f"/api/runs/{run_id}/review/diff?scope=commit&ref={sha1}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope"] == "commit"
        assert "feature.py" in data["diff"]
        assert "Author:" in data["diff"]

        sha2 = _commit_file(worktree_path, "step2.py", "# step2\n", "Add step2.py")

        # task scope with ref → diff from merge-base to that commit
        resp = await client.get(f"/api/runs/{run_id}/review/diff?scope=task&ref={sha2}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope"] == "task"
        assert "feature.py" in data["diff"] or "step2.py" in data["diff"]

        # task scope without ref falls back to aggregate
        resp = await client.get(f"/api/runs/{run_id}/review/diff?scope=task")
        assert resp.status_code == 200
        assert "feature.py" in resp.json()["diff"]

        # Multiple commits all appear in the aggregate diff
        resp = await client.get(f"/api/runs/{run_id}/review/diff")
        assert resp.status_code == 200
        diff = resp.json()["diff"]
        assert "feature.py" in diff
        assert "step2.py" in diff

    async def test_run_not_found_returns_404(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        client, _repo, drain = client_with_repo
        resp = await client.get("/api/runs/nonexistent-run-id/review/diff")
        assert resp.status_code == 404

    async def test_run_without_worktree_returns_409(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Diff on a DRAFT run (no worktree) returns 409."""
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

        # Not started → no worktree
        resp = await client.get(f"/api/runs/{run_id}/review/diff")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/review/diff/files
# ---------------------------------------------------------------------------


class TestGetDiffFiles:
    async def test_diff_files_lifecycle(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """One run exercises the file listing: empty state, an added file
        with counted additions and full schema, a modified file, multiple
        files, and exclusion of upstream files after a clean back-merge."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # No changes → empty file list
        resp = await client.get(f"/api/runs/{run_id}/review/diff/files")
        assert resp.status_code == 200
        assert resp.json() == []

        _commit_file(worktree_path, "new_file.py", "line1\nline2\nline3\n", "Add new_file.py")

        # Added file: status, counted additions, full DiffFileEntry schema
        resp = await client.get(f"/api/runs/{run_id}/review/diff/files")
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) == 1
        entry = files[0]
        assert set(entry.keys()) >= {"path", "status", "additions", "deletions"}
        assert entry["path"] == "new_file.py"
        assert entry["status"] == "added"
        assert isinstance(entry["additions"], int)
        assert isinstance(entry["deletions"], int)
        assert entry["additions"] == 3
        assert entry["deletions"] == 0

        # Modified file appears with status 'modified'
        (worktree_path / "README.md").write_text("# Updated Title\nnew content\n")
        _git(["add", "README.md"], cwd=worktree_path)
        _git(["commit", "-m", "Modify README"], cwd=worktree_path)

        resp = await client.get(f"/api/runs/{run_id}/review/diff/files")
        assert resp.status_code == 200
        by_path = {f["path"]: f for f in resp.json()}
        assert set(by_path) == {"new_file.py", "README.md"}
        assert by_path["README.md"]["status"] == "modified"

        # Clean back-merge must not balloon the aggregate view with upstream files
        _commit_file(repo, "main_only.py", "main = True\n", "Add main_only.py")
        back_merge_resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert back_merge_resp.status_code == 200
        assert back_merge_resp.json()["status"] == "clean"

        resp = await client.get(f"/api/runs/{run_id}/review/diff/files")
        assert resp.status_code == 200
        paths = [entry["path"] for entry in resp.json()]
        assert "new_file.py" in paths
        assert "main_only.py" not in paths

    async def test_run_not_found_returns_404(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        client, _repo, drain = client_with_repo
        resp = await client.get("/api/runs/nonexistent/review/diff/files")
        assert resp.status_code == 404

    async def test_run_without_worktree_returns_409(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
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

        resp = await client.get(f"/api/runs/{run_id}/review/diff/files")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/review/commits
# ---------------------------------------------------------------------------


class TestGetCommits:
    async def test_commits_lifecycle(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """One run exercises the commit listing: source-branch commits are
        excluded, a single commit appears with full schema, ordering is
        newest-first, and a back-merge does not pull upstream commits into
        the branch history."""
        client, repo, drain = client_with_repo

        # Commit to main BEFORE creating the run — must never be listed
        _commit_file(repo, "main_file.py", "# on main\n", "Commit on main")
        pre_run_main_head = _git(["rev-parse", "HEAD"], cwd=repo)

        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # No commits beyond merge-base → empty list
        resp = await client.get(f"/api/runs/{run_id}/review/commits")
        assert resp.status_code == 200
        assert resp.json() == []

        sha1 = _commit_file(worktree_path, "first.py", "# first\n", "First commit")

        # Single commit with full CommitEntry schema
        resp = await client.get(f"/api/runs/{run_id}/review/commits")
        assert resp.status_code == 200
        commits = resp.json()
        assert len(commits) == 1
        c = commits[0]
        required_fields = {"sha", "short_sha", "message", "author", "timestamp"}
        assert required_fields.issubset(set(c.keys()))
        assert c["sha"] == sha1
        assert len(c["sha"]) == 40
        assert isinstance(c["short_sha"], str) and len(c["short_sha"]) == 7
        assert c["sha"].startswith(c["short_sha"])
        assert c["author"] == "Test"
        assert c["message"] == "First commit"
        assert isinstance(c["timestamp"], str)  # ISO 8601

        sha2 = _commit_file(worktree_path, "second.py", "# second\n", "Second commit")

        # Newest first
        resp = await client.get(f"/api/runs/{run_id}/review/commits")
        assert resp.status_code == 200
        commits = resp.json()
        assert [c["sha"] for c in commits] == [sha2, sha1]

        # Back-merge must not list source-branch commits in branch history
        main_sha = _commit_file(
            repo, "main_history.py", "main_history = True\n", "Add main history"
        )
        back_merge_resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert back_merge_resp.status_code == 200
        merge_sha = back_merge_resp.json()["merge_commit_sha"]
        assert back_merge_resp.json()["status"] == "clean"
        assert merge_sha is not None

        resp = await client.get(f"/api/runs/{run_id}/review/commits")
        assert resp.status_code == 200
        shas = [commit["sha"] for commit in resp.json()]
        assert sha1 in shas
        assert sha2 in shas
        assert merge_sha in shas
        assert main_sha not in shas
        assert pre_run_main_head not in shas

    async def test_run_not_found_returns_404(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        client, _repo, drain = client_with_repo
        resp = await client.get("/api/runs/nonexistent/review/commits")
        assert resp.status_code == 404

    async def test_run_without_worktree_returns_409(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
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

        resp = await client.get(f"/api/runs/{run_id}/review/commits")
        assert resp.status_code == 409
