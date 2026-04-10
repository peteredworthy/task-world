"""Shared fixtures for integration tests."""

import os
import shutil
import subprocess
import uuid
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
# Shared git + app fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _base_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a fully-initialized git repo ONCE per worker session to use as a clone source."""
    base = tmp_path_factory.mktemp("base_repo")
    repo = base / "repo"
    repo.mkdir()
    _init_repo(repo)
    return repo


@pytest.fixture(scope="session")
async def _shared_app_fixture(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncGenerator[tuple[AsyncClient, DrainFn, Path, Path, Any], None]:
    """Shared FastAPI app + in-memory DB for all tests in a module.

    Yields (client, drain, repos_dir, worktrees_dir, app).
    Tests that don't need ``app`` can simply ignore the last element.
    """
    from orchestrator.config.global_config import GlobalConfig, PathsConfig

    base = tmp_path_factory.mktemp("shared_app")
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
        yield c, drain, repos_dir, worktrees_dir, app
    await app.state.engine.dispose()


@pytest.fixture
def git_repo(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    _base_repo: Path,
) -> Path:
    """Copy the base repo to get a uniquely-named git repo in the shared repos_dir.

    Uses shutil.copytree instead of git clone + config calls (~80 ms/test saved).
    The base repo's .git/config already includes user.email/user.name so no
    extra git config subprocess calls are needed.
    """
    _, _, repos_dir, _, _ = _shared_app_fixture
    repo = repos_dir / f"project_{uuid.uuid4().hex[:8]}"
    shutil.copytree(str(_base_repo), str(repo))
    return repo


# ---------------------------------------------------------------------------
# Shared async conflict helpers
# ---------------------------------------------------------------------------


async def _setup_conflict(
    client: AsyncClient,
    repo: Path,
    drain: DrainFn,
    filename: str = "conflict.py",
    ours_content: str = "x = 'run_version'\n",
    theirs_content: str = "x = 'main_version'\n",
) -> tuple[str, Path]:
    """Helper: create a run with a conflicting back-merge in-progress.

    Creates and starts a run using ``simple-routine``, commits diverging changes
    to both branches, then triggers a back-merge to put the run in conflict state.

    Returns (run_id, worktree_path).
    """
    # Inline run creation to avoid circular imports with test modules
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

    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 202
    await drain(run_id)
    run_data = (await client.get(f"/api/runs/{run_id}")).json()
    assert run_data["status"] == "active"
    worktree_path = Path(run_data["worktree_path"])

    # Both branches add the same file with different content → conflict
    _commit_file(worktree_path, filename, ours_content, f"Run: add {filename}")
    _commit_file(repo, filename, theirs_content, f"Main: add {filename}")

    back_merge_resp = await client.post(f"/api/runs/{run_id}/back-merge")
    assert back_merge_resp.status_code == 200
    assert back_merge_resp.json()["status"] == "conflicts"

    return run_id, worktree_path
