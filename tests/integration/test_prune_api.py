"""Integration tests for prune API endpoints.

Tests POST /api/runs/{run_id}/review/prune/preview,
      POST /api/runs/{run_id}/review/prune/apply, and
      POST /api/runs/{run_id}/review/revert-file.

Uses real git repos via tmp_path fixtures; no mocking.

WARNING — shared fixture:
    The ``_shared_app_fixture`` defined below (module scope) reuses one
    FastAPI app + in-memory DB across every test in this file. Isolation
    relies on each test getting a uniquely-named ``git_repo`` (counter
    suffix) and on server-generated run UUIDs. Don't assert on global
    ``/api/runs`` counts; reference your run only by the ``id`` you
    received.
"""

import shutil
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport

from tests.integration.git_helpers import _commit_file, _git
from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def _shared_app_fixture(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncGenerator[tuple[AsyncClient, DrainFn, Path, Path], None]:
    """Shared FastAPI app + in-memory DB for all tests in this module.

    Each test creates its own git repo inside ``repos_dir`` (unique name),
    so the shared database accumulates multiple runs safely without conflicts.
    """
    from orchestrator.config.global_config import GlobalConfig, PathsConfig

    base = tmp_path_factory.mktemp("prune_api_shared")
    repos_dir = base / "repos"
    worktrees_dir = base / "worktrees"
    repos_dir.mkdir()
    worktrees_dir.mkdir()

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
        yield c, drain, repos_dir, worktrees_dir
    await app.state.engine.dispose()


_repo_counter = 0


@pytest.fixture
def git_repo(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path],
    _base_repo: Path,
) -> Path:
    """Create a uniquely-named git repo inside the shared repos_dir.

    Uses shutil.copytree from the session-scoped base repo instead of
    git init + config + commit (saves ~150 ms per test).
    """
    global _repo_counter
    _repo_counter += 1
    _, _, repos_dir, _ = _shared_app_fixture
    repo = repos_dir / f"project_{_repo_counter}"
    shutil.copytree(str(_base_repo), str(repo))
    return repo


@pytest.fixture
async def client_with_repo(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path],
    git_repo: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, DrainFn], None]:
    """Test client backed by the shared app, with a per-test git repo."""
    client, drain, _, _ = _shared_app_fixture
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
# POST /api/runs/{run_id}/review/prune/preview
# ---------------------------------------------------------------------------


class TestPrunePreview:
    async def test_preview_file_mode_returns_stats(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Preview with file mode returns files_affected, hunks_removed, lines_removed."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "feature.py", "x = 1\ny = 2\n", "Add feature.py")

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/preview",
            json={
                "scope": "aggregate",
                "files": [{"path": "feature.py", "mode": "file"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["files_affected"] == 1
        assert data["hunks_removed"] >= 1
        assert data["lines_removed"] == 2
        assert "feature.py" not in data["resulting_diff"]

    async def test_preview_hunk_mode_returns_stats(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Preview with hunk mode returns stats for the selected hunks."""
        client, repo, drain = client_with_repo

        # Add the base file to main so it exists at merge-base (enables multi-hunk diffs)
        base_lines = [f"line{i}\n" for i in range(1, 21)]
        _commit_file(repo, "hunky.py", "".join(base_lines), "Add hunky.py to main")

        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Modify in worktree: two additions far apart → two separate hunks
        modified = (
            base_lines[:1] + ["top_add\n"] + base_lines[1:15] + ["bot_add\n"] + base_lines[15:]
        )
        (worktree_path / "hunky.py").write_text("".join(modified))
        _git(["add", "hunky.py"], cwd=worktree_path)
        _git(["commit", "-m", "Two hunks"], cwd=worktree_path)

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/preview",
            json={
                "scope": "aggregate",
                "files": [{"path": "hunky.py", "mode": "hunk", "hunks": [0]}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["files_affected"] == 1
        assert data["hunks_removed"] == 1
        assert data["lines_removed"] == 1

    async def test_preview_line_mode_returns_stats(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Preview with line mode returns stats for the selected line range."""
        client, repo, drain = client_with_repo

        # Add base file to main so it exists at merge-base
        _commit_file(repo, "lined.py", "keep\n", "Add lined.py to main")

        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # HEAD: keep, add1, add2  (add1=line2, add2=line3)
        (worktree_path / "lined.py").write_text("keep\nadd1\nadd2\n")
        _git(["add", "lined.py"], cwd=worktree_path)
        _git(["commit", "-m", "Add two lines"], cwd=worktree_path)

        # Preview line 2 only (add1)
        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/preview",
            json={
                "scope": "aggregate",
                "files": [
                    {
                        "path": "lined.py",
                        "mode": "line",
                        "lines": [{"start": 2, "end": 2}],
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["files_affected"] == 1
        assert data["lines_removed"] == 1

    async def test_preview_empty_files_returns_zero_stats(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Empty files list returns zero stats and the full current diff."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "thing.py", "content\n", "Add thing.py")

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/preview",
            json={"scope": "aggregate", "files": []},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["files_affected"] == 0
        assert data["hunks_removed"] == 0
        assert data["lines_removed"] == 0

    async def test_preview_does_not_modify_worktree(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Preview is read-only: HEAD and file content unchanged after preview."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "ro.py", "readonly content\n", "Add ro.py")
        head_before = _git(["rev-parse", "HEAD"], cwd=worktree_path)
        content_before = (worktree_path / "ro.py").read_text()

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/preview",
            json={
                "scope": "aggregate",
                "files": [{"path": "ro.py", "mode": "file"}],
            },
        )
        assert resp.status_code == 200

        assert _git(["rev-parse", "HEAD"], cwd=worktree_path) == head_before
        assert (worktree_path / "ro.py").read_text() == content_before

    async def test_preview_schema_fields(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """PrunePreviewResponse includes all required fields with correct types."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "schema.py", "v = 1\n", "Add schema.py")

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/preview",
            json={
                "scope": "aggregate",
                "files": [{"path": "schema.py", "mode": "file"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        required = {"resulting_diff", "files_affected", "hunks_removed", "lines_removed"}
        assert required.issubset(set(data.keys()))
        assert isinstance(data["resulting_diff"], str)
        assert isinstance(data["files_affected"], int)
        assert isinstance(data["hunks_removed"], int)
        assert isinstance(data["lines_removed"], int)

    async def test_preview_run_not_found_returns_404(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        client, _repo, drain = client_with_repo
        resp = await client.post(
            "/api/runs/nonexistent-run-id/review/prune/preview",
            json={"scope": "aggregate", "files": []},
        )
        assert resp.status_code == 404

    async def test_preview_no_worktree_returns_409(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Preview on a DRAFT run (no worktree) returns 409."""
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

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/preview",
            json={"scope": "aggregate", "files": []},
        )
        assert resp.status_code == 409

    async def test_preview_resulting_diff_excludes_pruned_file(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """resulting_diff does not contain the pruned file but keeps other files."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "prune_me.py", "prune\n", "Add prune_me.py")
        _commit_file(worktree_path, "keep_me.py", "keep\n", "Add keep_me.py")

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/preview",
            json={
                "scope": "aggregate",
                "files": [{"path": "prune_me.py", "mode": "file"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "prune_me.py" not in data["resulting_diff"]
        assert "keep_me.py" in data["resulting_diff"]

    async def test_preview_multi_hunk_file_hunk_selection(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Preview with hunk mode accurately counts lines for selected hunks only."""
        client, repo, drain = client_with_repo

        # Add base file to main so it exists at merge-base (enables multi-hunk diff)
        base_lines = [f"ln{i}\n" for i in range(1, 21)]
        _commit_file(repo, "mh.py", "".join(base_lines), "Add mh.py to main")

        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Two sets of additions far apart → two separate hunks
        modified = base_lines[:1] + ["A\n"] + base_lines[1:15] + ["B\n", "C\n"] + base_lines[15:]
        (worktree_path / "mh.py").write_text("".join(modified))
        _git(["add", "mh.py"], cwd=worktree_path)
        _git(["commit", "-m", "Two hunks"], cwd=worktree_path)

        # Preview only hunk 1 (B and C)
        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/preview",
            json={
                "scope": "aggregate",
                "files": [{"path": "mh.py", "mode": "hunk", "hunks": [1]}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["files_affected"] == 1
        assert data["hunks_removed"] == 1
        assert data["lines_removed"] == 2  # B and C


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/prune/apply
# ---------------------------------------------------------------------------


class TestPruneApply:
    async def test_apply_file_mode_removes_added_file(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """File-mode apply removes a newly added file from the worktree."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "new_feat.py", "def foo(): pass\n", "Add new_feat.py")
        assert (worktree_path / "new_feat.py").exists()

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/apply",
            json={
                "scope": "aggregate",
                "files": [{"path": "new_feat.py", "mode": "file"}],
            },
        )
        assert resp.status_code == 200
        assert not (worktree_path / "new_feat.py").exists()

    async def test_apply_file_mode_restores_modified_file(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """File-mode apply restores a modified file to its base content."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Modify README (which exists at base)
        (worktree_path / "README.md").write_text("# Changed Title\nextra line\n")
        _git(["add", "README.md"], cwd=worktree_path)
        _git(["commit", "-m", "Modify README"], cwd=worktree_path)

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/apply",
            json={
                "scope": "aggregate",
                "files": [{"path": "README.md", "mode": "file"}],
            },
        )
        assert resp.status_code == 200
        # README should be restored to "# Test\n"
        assert (worktree_path / "README.md").read_text() == "# Test\n"

    async def test_apply_creates_commit(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """apply creates a new commit on the branch."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "to_prune.py", "content\n", "Add to_prune.py")
        head_before = _git(["rev-parse", "HEAD"], cwd=worktree_path)

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/apply",
            json={
                "scope": "aggregate",
                "files": [{"path": "to_prune.py", "mode": "file"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        head_after = _git(["rev-parse", "HEAD"], cwd=worktree_path)
        assert head_after != head_before
        assert data["commit_sha"] == head_after
        assert len(data["commit_sha"]) == 40

    async def test_apply_returns_correct_stats(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """apply returns files_affected, hunks_removed, lines_removed."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "f.py", "a\nb\nc\n", "Add f.py")

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/apply",
            json={
                "scope": "aggregate",
                "files": [{"path": "f.py", "mode": "file"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["files_affected"] == 1
        assert data["lines_removed"] == 3
        assert "event_id" in data
        assert isinstance(data["event_id"], str)

    async def test_apply_empty_selection_returns_400(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Empty files selection returns 400."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/apply",
            json={"scope": "aggregate", "files": []},
        )
        assert resp.status_code == 400

    async def test_apply_preserves_unselected_files(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Files not in selection are not modified."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "prune.py", "prune\n", "Add prune.py")
        _commit_file(worktree_path, "keep.py", "keep\n", "Add keep.py")

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/apply",
            json={
                "scope": "aggregate",
                "files": [{"path": "prune.py", "mode": "file"}],
            },
        )
        assert resp.status_code == 200
        assert not (worktree_path / "prune.py").exists()
        assert (worktree_path / "keep.py").exists()
        assert (worktree_path / "keep.py").read_text() == "keep\n"

    async def test_apply_hunk_mode_removes_selected_hunk(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Hunk-mode apply removes the selected hunk while keeping others."""
        client, repo, drain = client_with_repo

        # Add base file to main so it exists at merge-base (enables multi-hunk diff)
        base_lines = [f"L{i}\n" for i in range(1, 21)]
        _commit_file(repo, "hunky.py", "".join(base_lines), "Add hunky.py to main")

        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Two additions far apart → two separate hunks in the diff
        modified = (
            base_lines[:1] + ["top_add\n"] + base_lines[1:15] + ["bot_add\n"] + base_lines[15:]
        )
        (worktree_path / "hunky.py").write_text("".join(modified))
        _git(["add", "hunky.py"], cwd=worktree_path)
        _git(["commit", "-m", "Two additions"], cwd=worktree_path)

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/apply",
            json={
                "scope": "aggregate",
                "files": [{"path": "hunky.py", "mode": "hunk", "hunks": [0]}],
            },
        )
        assert resp.status_code == 200
        content = (worktree_path / "hunky.py").read_text()
        assert "top_add" not in content
        assert "bot_add" in content

    async def test_apply_line_mode_removes_selected_lines(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Line-mode apply removes only the selected lines."""
        client, repo, drain = client_with_repo

        # Add base file to main so it exists at merge-base (diff shows only added line)
        _commit_file(repo, "lined.py", "keep1\nkeep2\n", "Add lined.py to main")

        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # HEAD: keep1, ADD, keep2  (ADD is HEAD line 2)
        (worktree_path / "lined.py").write_text("keep1\nADD\nkeep2\n")
        _git(["add", "lined.py"], cwd=worktree_path)
        _git(["commit", "-m", "Add ADD"], cwd=worktree_path)

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/apply",
            json={
                "scope": "aggregate",
                "files": [
                    {
                        "path": "lined.py",
                        "mode": "line",
                        "lines": [{"start": 2, "end": 2}],
                    }
                ],
            },
        )
        assert resp.status_code == 200
        content = (worktree_path / "lined.py").read_text()
        assert "ADD" not in content
        assert "keep1" in content
        assert "keep2" in content

    async def test_apply_run_not_found_returns_404(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        client, _repo, drain = client_with_repo
        resp = await client.post(
            "/api/runs/nonexistent/review/prune/apply",
            json={"scope": "aggregate", "files": []},
        )
        assert resp.status_code == 404

    async def test_apply_no_worktree_returns_409(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
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

        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/apply",
            json={"scope": "aggregate", "files": []},
        )
        assert resp.status_code == 409

    async def test_apply_multi_hunk_partial_prune(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Apply can prune a subset of hunks from a multi-hunk file."""
        client, repo, drain = client_with_repo

        # Add base file to main so it exists at merge-base (enables multi-hunk diff)
        base_lines = [f"x{i}\n" for i in range(1, 25)]
        _commit_file(repo, "partial.py", "".join(base_lines), "Add partial.py to main")

        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # Two additions far apart → two separate hunks
        modified = base_lines[:1] + ["HUNK0\n"] + base_lines[1:18] + ["HUNK1\n"] + base_lines[18:]
        (worktree_path / "partial.py").write_text("".join(modified))
        _git(["add", "partial.py"], cwd=worktree_path)
        _git(["commit", "-m", "Two hunks"], cwd=worktree_path)

        # Only prune hunk 1 (HUNK1)
        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/apply",
            json={
                "scope": "aggregate",
                "files": [{"path": "partial.py", "mode": "hunk", "hunks": [1]}],
            },
        )
        assert resp.status_code == 200
        content = (worktree_path / "partial.py").read_text()
        assert "HUNK0" in content
        assert "HUNK1" not in content

    async def test_apply_adjacent_line_prune(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Apply line-mode correctly removes a subset of adjacent added lines."""
        client, repo, drain = client_with_repo

        # Add base file to main so it exists at merge-base
        _commit_file(repo, "adj.py", "before\nafter\n", "Add adj.py to main")

        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        # HEAD: before(1), A(2), B(3), C(4), after(5)
        (worktree_path / "adj.py").write_text("before\nA\nB\nC\nafter\n")
        _git(["add", "adj.py"], cwd=worktree_path)
        _git(["commit", "-m", "Adjacent adds"], cwd=worktree_path)

        # Remove only B (line 3)
        resp = await client.post(
            f"/api/runs/{run_id}/review/prune/apply",
            json={
                "scope": "aggregate",
                "files": [
                    {
                        "path": "adj.py",
                        "mode": "line",
                        "lines": [{"start": 3, "end": 3}],
                    }
                ],
            },
        )
        assert resp.status_code == 200
        content = (worktree_path / "adj.py").read_text()
        assert "A" in content
        assert "B" not in content
        assert "C" in content
        assert "before" in content
        assert "after" in content


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/review/revert-file
# ---------------------------------------------------------------------------


class TestRevertFileEndpoint:
    async def test_revert_removes_added_file(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """revert-file removes a newly added file from the worktree."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "fresh.py", "new code\n", "Add fresh.py")
        assert (worktree_path / "fresh.py").exists()

        resp = await client.post(
            f"/api/runs/{run_id}/review/revert-file",
            json={"file_path": "fresh.py"},
        )
        assert resp.status_code == 200
        assert not (worktree_path / "fresh.py").exists()

    async def test_revert_restores_modified_file(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """revert-file restores a modified file to its base content."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        (worktree_path / "README.md").write_text("# Modified\nmore lines\n")
        _git(["add", "README.md"], cwd=worktree_path)
        _git(["commit", "-m", "Modify README"], cwd=worktree_path)

        resp = await client.post(
            f"/api/runs/{run_id}/review/revert-file",
            json={"file_path": "README.md"},
        )
        assert resp.status_code == 200
        assert (worktree_path / "README.md").read_text() == "# Test\n"

    async def test_revert_creates_commit(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """revert-file creates a new commit and returns its SHA."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "torevert.py", "code\n", "Add torevert.py")
        head_before = _git(["rev-parse", "HEAD"], cwd=worktree_path)

        resp = await client.post(
            f"/api/runs/{run_id}/review/revert-file",
            json={"file_path": "torevert.py"},
        )
        assert resp.status_code == 200
        data = resp.json()
        head_after = _git(["rev-parse", "HEAD"], cwd=worktree_path)
        assert head_after != head_before
        assert data["commit_sha"] == head_after
        assert len(data["commit_sha"]) == 40

    async def test_revert_response_schema(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """revert-file response contains commit_sha, file_path, and reverted_to."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]
        worktree_path = Path(run_data["worktree_path"])

        _commit_file(worktree_path, "schema.py", "v = 1\n", "Add schema.py")

        resp = await client.post(
            f"/api/runs/{run_id}/review/revert-file",
            json={"file_path": "schema.py"},
        )
        assert resp.status_code == 200
        data = resp.json()
        required = {"commit_sha", "file_path", "reverted_to"}
        assert required.issubset(set(data.keys()))
        assert data["file_path"] == "schema.py"
        assert isinstance(data["reverted_to"], str)
        assert len(data["reverted_to"]) == 40

    async def test_revert_missing_file_path_returns_422(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Request body without file_path returns 422."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        resp = await client.post(
            f"/api/runs/{run_id}/review/revert-file",
            json={},
        )
        assert resp.status_code == 422

    async def test_revert_run_not_found_returns_404(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        client, _repo, drain = client_with_repo
        resp = await client.post(
            "/api/runs/nonexistent/review/revert-file",
            json={"file_path": "any.py"},
        )
        assert resp.status_code == 404

    async def test_revert_no_worktree_returns_409(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
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

        resp = await client.post(
            f"/api/runs/{run_id}/review/revert-file",
            json={"file_path": "any.py"},
        )
        assert resp.status_code == 409

    async def test_revert_file_already_at_base_returns_500(
        self, client_with_repo: tuple[AsyncClient, Path, DrainFn]
    ) -> None:
        """Reverting a file with no diff from base returns 500 (GitCommandError)."""
        client, repo, drain = client_with_repo
        run_data = await _create_and_start_run(client, repo, drain)
        run_id = run_data["id"]

        # README.md has no changes on the run branch — already at base
        resp = await client.post(
            f"/api/runs/{run_id}/review/revert-file",
            json={"file_path": "README.md"},
        )
        assert resp.status_code == 500
