"""Integration tests for conflict detection, resolution, and revert API endpoints.

Tests cover:
- Auto-commit on clean back-merge
- Conflict file listing via GET /review/conflicts
- Per-block conflict resolution via POST /review/conflicts/{path}/resolve
- Revert of a back-merge via POST /review/revert-back-merge
"""

import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db

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
async def client_with_repo(git_repo: Path) -> AsyncGenerator[tuple[AsyncClient, Path], None]:
    """Test client backed by a real git repo."""
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
        yield c, git_repo
    await app.state.engine.dispose()


async def _create_and_start_run(client: AsyncClient, project_path: Path) -> dict[str, Any]:
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

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "active"
    assert data["worktree_path"] is not None
    return data


async def _setup_conflict(
    client: AsyncClient,
    repo: Path,
    filename: str = "conflict.py",
    ours_content: str = "x = 'run_version'\n",
    theirs_content: str = "x = 'main_version'\n",
) -> tuple[str, Path]:
    """Helper: create a run with a conflicting back-merge in-progress.

    Returns (run_id, worktree_path).
    """
    run_data = await _create_and_start_run(client, repo)
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
    async def test_clean_merge_returns_status_clean(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """A clean back-merge returns status='clean'."""
        client, repo = client_with_repo
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]

        # Commit a new file to main that doesn't touch anything on the run branch
        _commit_file(repo, "main_only.py", "x = 1\n", "Add main_only.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert resp.status_code == 200
        assert resp.json()["status"] == "clean"

    async def test_clean_merge_returns_merge_commit_sha(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """A clean back-merge returns a non-null merge_commit_sha."""
        client, repo = client_with_repo
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]

        _commit_file(repo, "feature.py", "def feature(): pass\n", "Add feature.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["merge_commit_sha"] is not None
        assert len(data["merge_commit_sha"]) == 40

    async def test_clean_merge_worktree_head_matches_returned_sha(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """After a clean back-merge, the worktree HEAD equals the returned SHA (auto-committed)."""
        client, repo = client_with_repo
        run_data = await _create_and_start_run(client, repo)
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
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """A clean back-merge returns empty conflict_files and conflict_count=0."""
        client, repo = client_with_repo
        run_data = await _create_and_start_run(client, repo)
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
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Back-merge with conflicts returns status='conflicts'."""
        client, repo = client_with_repo
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "shared.py", "x = 'run'\n", "Run: shared.py")
        _commit_file(repo, "shared.py", "x = 'main'\n", "Main: shared.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert resp.status_code == 200
        assert resp.json()["status"] == "conflicts"

    async def test_conflict_merge_lists_conflict_files(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """The conflicting file appears in conflict_files."""
        client, repo = client_with_repo
        run_data = await _create_and_start_run(client, repo)
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
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Back-merge with conflicts returns null merge_commit_sha (no auto-commit)."""
        client, repo = client_with_repo
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "shared.py", "x = 'run'\n", "Run: shared.py")
        _commit_file(repo, "shared.py", "x = 'main'\n", "Main: shared.py")

        resp = await client.post(f"/api/runs/{run_id}/back-merge")
        assert resp.json()["merge_commit_sha"] is None

    async def test_conflict_merge_multiple_files(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """All conflicting files appear in the response when multiple files conflict."""
        client, repo = client_with_repo
        run_data = await _create_and_start_run(client, repo)
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
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """With no merge in progress, conflicts endpoint returns empty list."""
        client, repo = client_with_repo
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/conflicts")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_conflict_file_listed_with_path(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """After a conflicting back-merge, the conflict file is listed."""
        client, repo = client_with_repo
        run_id, _ = await _setup_conflict(client, repo, filename="conflict.py")

        resp = await client.get(f"/api/runs/{run_id}/review/conflicts")
        assert resp.status_code == 200
        files = resp.json()
        paths = [f["path"] for f in files]
        assert "conflict.py" in paths

    async def test_conflict_file_has_unresolved_status(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Each conflict file has status='unresolved'."""
        client, repo = client_with_repo
        run_id, _ = await _setup_conflict(client, repo)

        resp = await client.get(f"/api/runs/{run_id}/review/conflicts")
        files = resp.json()
        assert len(files) >= 1
        assert files[0]["status"] == "unresolved"

    async def test_conflict_file_has_blocks(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Each conflict file contains at least one conflict block."""
        client, repo = client_with_repo
        run_id, _ = await _setup_conflict(client, repo)

        resp = await client.get(f"/api/runs/{run_id}/review/conflicts")
        files = resp.json()
        assert files[0]["block_count"] >= 1
        assert len(files[0]["blocks"]) >= 1

    async def test_conflict_block_schema(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Each conflict block has index, ours_content, and theirs_content."""
        client, repo = client_with_repo
        run_id, _ = await _setup_conflict(
            client,
            repo,
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
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Conflicts endpoint on a run with no worktree returns 409."""
        client, repo = client_with_repo
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
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Conflicts endpoint for a nonexistent run returns 404."""
        client, _repo = client_with_repo
        resp = await client.get("/api/runs/nonexistent-run-id/review/conflicts")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/conflicts/{file_path}/resolve
# ---------------------------------------------------------------------------


class TestResolveConflict:
    async def test_resolve_ours_removes_markers(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Resolving with 'ours' removes conflict markers from the file."""
        client, repo = client_with_repo
        run_id, worktree_path = await _setup_conflict(
            client, repo, ours_content="x = 'run_version'\n"
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
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Resolving with 'theirs' writes the theirs content and removes markers."""
        client, repo = client_with_repo
        run_id, worktree_path = await _setup_conflict(
            client, repo, theirs_content="x = 'main_version'\n"
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
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Resolving with 'manual' writes the provided custom content."""
        client, repo = client_with_repo
        run_id, worktree_path = await _setup_conflict(client, repo)

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
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """An invalid choice value returns 422."""
        client, repo = client_with_repo
        run_id, _ = await _setup_conflict(client, repo)

        resp = await client.post(
            f"/api/runs/{run_id}/review/conflicts/conflict.py/resolve",
            json={"resolutions": [{"block_index": 0, "choice": "invalid_choice"}]},
        )
        assert resp.status_code == 422

    async def test_resolve_manual_without_content_returns_422(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Manual choice without manual_content returns 422."""
        client, repo = client_with_repo
        run_id, _ = await _setup_conflict(client, repo)

        resp = await client.post(
            f"/api/runs/{run_id}/review/conflicts/conflict.py/resolve",
            json={"resolutions": [{"block_index": 0, "choice": "manual"}]},
        )
        assert resp.status_code == 422

    async def test_resolve_nonexistent_file_returns_404(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Trying to resolve a file that has no conflicts returns 404."""
        client, repo = client_with_repo
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]

        resp = await client.post(
            f"/api/runs/{run_id}/review/conflicts/nonexistent.py/resolve",
            json={"resolutions": [{"block_index": 0, "choice": "ours"}]},
        )
        assert resp.status_code == 404

    async def test_remaining_conflicts_decrements_after_partial_resolve(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """After resolving one of two conflicting files, remaining_conflicts == 1."""
        client, repo = client_with_repo
        run_data = await _create_and_start_run(client, repo)
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
    async def _setup_clean_merge(self, client: AsyncClient, repo: Path) -> tuple[str, Path, str]:
        """Helper: create a clean back-merge and return (run_id, worktree_path, merge_sha).

        Both branches diverge so the merge creates a real merge commit (not fast-forward).
        """
        run_data = await _create_and_start_run(client, repo)
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
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Reverting a clean back-merge (real merge commit) returns 200."""
        client, repo = client_with_repo
        run_id, _, _ = await self._setup_clean_merge(client, repo)

        resp = await client.post(f"/api/runs/{run_id}/review/revert-back-merge")
        assert resp.status_code == 200

    async def test_revert_returns_reverted_commit_sha(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Revert response contains the SHA of the reverted merge commit."""
        client, repo = client_with_repo
        run_id, _, merge_sha = await self._setup_clean_merge(client, repo)

        resp = await client.post(f"/api/runs/{run_id}/review/revert-back-merge")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reverted_commit"] == merge_sha

    async def test_revert_returns_new_head(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Revert response contains a new_head SHA different from the merge SHA."""
        client, repo = client_with_repo
        run_id, worktree_path, merge_sha = await self._setup_clean_merge(client, repo)

        resp = await client.post(f"/api/runs/{run_id}/review/revert-back-merge")
        data = resp.json()
        assert data["new_head"] != merge_sha
        assert len(data["new_head"]) == 40

        # Worktree HEAD should match the returned new_head
        actual_head = _git(["rev-parse", "HEAD"], cwd=worktree_path)
        assert actual_head == data["new_head"]

    async def test_revert_without_merge_commit_returns_409(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Revert when HEAD is not a merge commit (no back-merge done) returns 409."""
        client, repo = client_with_repo
        run_data = await _create_and_start_run(client, repo)
        run_id = run_data["id"]

        # No back-merge was performed; HEAD is a regular (non-merge) commit
        resp = await client.post(f"/api/runs/{run_id}/review/revert-back-merge")
        assert resp.status_code == 409

    async def test_revert_run_not_found_returns_404(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Revert on a nonexistent run returns 404."""
        client, _repo = client_with_repo
        resp = await client.post("/api/runs/nonexistent-run-id/review/revert-back-merge")
        assert resp.status_code == 404

    async def test_revert_run_without_worktree_returns_409(
        self,
        client_with_repo: tuple[AsyncClient, Path],
    ) -> None:
        """Revert on a run without a worktree returns 409."""
        client, repo = client_with_repo
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
