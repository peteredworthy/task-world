"""Integration tests for review API endpoints (diff, diff/files, commits)."""

import os
import subprocess
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(args: list[str], cwd: Path) -> str:
    """Run a git command and return stdout."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PRE_COMMIT_ALLOW_NO_CONFIG"] = "1"
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
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
async def client_with_repo(
    git_repo: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, DrainFn], None]:
    """Test client with a real git repo as project."""
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
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, git_repo, drain
    await app.state.engine.dispose()


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
    async def test_aggregate_diff_empty_branch(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Aggregate diff on a branch with no changes returns empty diff."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/diff")
        assert resp.status_code == 200
        data = resp.json()
        assert "diff" in data
        assert "scope" in data
        assert data["scope"] == "aggregate"
        assert data["diff"] == ""

    async def test_aggregate_diff_with_changes(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Aggregate diff contains the changed file."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Commit a file in the worktree (run branch)
        _commit_file(worktree_path, "feature.py", "def foo():\n    return 1\n", "Add feature.py")

        resp = await client.get(f"/api/runs/{run_id}/review/diff")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope"] == "aggregate"
        assert "feature.py" in data["diff"]
        assert "+def foo():" in data["diff"]

    async def test_aggregate_diff_schema_fields(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """DiffResponse includes diff, scope, and optional file_path."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/diff")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) >= {"diff", "scope"}
        assert isinstance(data["diff"], str)
        assert isinstance(data["scope"], str)

    async def test_commit_scope_requires_ref(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """commit scope without ref returns 400."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/diff?scope=commit")
        assert resp.status_code == 400

    async def test_commit_scope_with_ref(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """commit scope with valid ref returns diff for that single commit."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        sha = _commit_file(
            worktree_path, "service.py", "class Service:\n    pass\n", "Add service.py"
        )

        resp = await client.get(f"/api/runs/{run_id}/review/diff?scope=commit&ref={sha}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope"] == "commit"
        assert "service.py" in data["diff"]
        # git show includes author metadata
        assert "Author:" in data["diff"]

    async def test_task_scope_with_ref(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """task scope with ref returns diff from merge-base to that commit."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "step1.py", "# step1\n", "Add step1.py")
        sha2 = _commit_file(worktree_path, "step2.py", "# step2\n", "Add step2.py")

        resp = await client.get(f"/api/runs/{run_id}/review/diff?scope=task&ref={sha2}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scope"] == "task"
        assert "step1.py" in data["diff"] or "step2.py" in data["diff"]

    async def test_task_scope_without_ref_falls_back_to_aggregate(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """task scope without ref behaves like aggregate."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "any.py", "# any\n", "Add any.py")

        resp = await client.get(f"/api/runs/{run_id}/review/diff?scope=task")
        assert resp.status_code == 200
        data = resp.json()
        assert "any.py" in data["diff"]

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

    async def test_multiple_commits_in_aggregate_diff(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Multiple commits on run branch all appear in aggregate diff."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "alpha.py", "# alpha\n", "Add alpha")
        _commit_file(worktree_path, "beta.py", "# beta\n", "Add beta")

        resp = await client.get(f"/api/runs/{run_id}/review/diff")
        assert resp.status_code == 200
        diff = resp.json()["diff"]
        assert "alpha.py" in diff
        assert "beta.py" in diff


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/review/diff/files
# ---------------------------------------------------------------------------


class TestGetDiffFiles:
    async def test_empty_branch_returns_empty_list(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """No changes → empty file list."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/diff/files")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_added_file_appears(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """An added file shows up with status 'added' and non-zero additions."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "new_file.py", "x = 1\ny = 2\n", "Add new_file.py")

        resp = await client.get(f"/api/runs/{run_id}/review/diff/files")
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) == 1
        f = files[0]
        assert f["path"] == "new_file.py"
        assert f["status"] == "added"
        assert f["additions"] > 0
        assert f["deletions"] == 0

    async def test_modified_file_appears(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """A modified file shows status 'modified' with additions and deletions."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # First, add README.md in the base (already exists as "# Test\n")
        # Modify it
        (worktree_path / "README.md").write_text("# Updated Title\nnew content\n")
        _git(["add", "README.md"], cwd=worktree_path)
        _git(["commit", "-m", "Modify README"], cwd=worktree_path)

        resp = await client.get(f"/api/runs/{run_id}/review/diff/files")
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) == 1
        f = files[0]
        assert f["path"] == "README.md"
        assert f["status"] == "modified"

    async def test_multiple_files_listed(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Multiple changed files all appear in the listing."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "file_a.py", "a = 1\n", "Add file_a")
        _commit_file(worktree_path, "file_b.py", "b = 2\n", "Add file_b")

        resp = await client.get(f"/api/runs/{run_id}/review/diff/files")
        assert resp.status_code == 200
        files = resp.json()
        paths = [f["path"] for f in files]
        assert "file_a.py" in paths
        assert "file_b.py" in paths

    async def test_response_schema(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Each file entry has required DiffFileEntry schema fields."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "schema_test.py", "val = 42\n", "Add schema_test")

        resp = await client.get(f"/api/runs/{run_id}/review/diff/files")
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) == 1
        entry = files[0]
        assert set(entry.keys()) >= {"path", "status", "additions", "deletions"}
        assert isinstance(entry["path"], str)
        assert isinstance(entry["status"], str)
        assert isinstance(entry["additions"], int)
        assert isinstance(entry["deletions"], int)

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

    async def test_additions_and_deletions_counted(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Additions and deletions are accurately counted."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Add a file with known content
        _commit_file(
            worktree_path,
            "counts.py",
            "line1\nline2\nline3\n",
            "Add counts.py",
        )

        resp = await client.get(f"/api/runs/{run_id}/review/diff/files")
        assert resp.status_code == 200
        files = resp.json()
        f = next(e for e in files if e["path"] == "counts.py")
        assert f["additions"] == 3
        assert f["deletions"] == 0


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/review/commits
# ---------------------------------------------------------------------------


class TestGetCommits:
    async def test_empty_branch_returns_empty_list(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """No commits beyond merge-base → empty commit list."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.get(f"/api/runs/{run_id}/review/commits")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_single_commit_listed(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """A single commit shows up with correct SHA and message."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        sha = _commit_file(worktree_path, "thing.py", "# thing\n", "Add thing.py")

        resp = await client.get(f"/api/runs/{run_id}/review/commits")
        assert resp.status_code == 200
        commits = resp.json()
        assert len(commits) == 1
        c = commits[0]
        assert c["sha"] == sha
        assert c["message"] == "Add thing.py"

    async def test_multiple_commits_newest_first(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Multiple commits appear in reverse chronological order (newest first)."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        sha1 = _commit_file(worktree_path, "first.py", "# first\n", "First commit")
        sha2 = _commit_file(worktree_path, "second.py", "# second\n", "Second commit")

        resp = await client.get(f"/api/runs/{run_id}/review/commits")
        assert resp.status_code == 200
        commits = resp.json()
        assert len(commits) == 2
        # Newest first
        assert commits[0]["sha"] == sha2
        assert commits[1]["sha"] == sha1

    async def test_commit_schema_fields(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Each commit entry contains all CommitEntry schema fields."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "schema.py", "# schema\n", "Schema test commit")

        resp = await client.get(f"/api/runs/{run_id}/review/commits")
        assert resp.status_code == 200
        commits = resp.json()
        assert len(commits) == 1
        c = commits[0]
        required_fields = {"sha", "short_sha", "message", "author", "timestamp"}
        assert required_fields.issubset(set(c.keys()))
        assert isinstance(c["sha"], str) and len(c["sha"]) == 40
        assert isinstance(c["short_sha"], str) and len(c["short_sha"]) == 7
        assert c["sha"].startswith(c["short_sha"])
        assert c["author"] == "Test"
        assert c["message"] == "Schema test commit"
        # timestamp is an ISO 8601 string
        assert isinstance(c["timestamp"], str)

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

    async def test_commit_not_listed_if_on_source_branch(
        self,
        client_with_repo: tuple[AsyncClient, Path, DrainFn],
    ) -> None:
        """Commits from source branch (before branch point) are excluded."""
        client, repo, drain = client_with_repo

        # Add a commit to main BEFORE creating the run
        _commit_file(repo, "main_file.py", "# on main\n", "Commit on main")

        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        # No commits on run branch yet
        resp = await client.get(f"/api/runs/{run_id}/review/commits")
        assert resp.status_code == 200
        commits = resp.json()
        shas = [c["sha"] for c in commits]
        main_head = _git(["rev-parse", "HEAD"], cwd=repo)
        assert main_head not in shas
