"""Shared fixtures for integration tests.

# Isolation model for the shared-app pattern

Tests that share a module-scoped FastAPI app + in-memory DB must not interfere
with each other, even when one dies mid-execution. The guarantees:

1. **Unique repo names per test** — ``git_repo`` uses ``uuid.uuid4().hex[:8]``,
   so filesystem paths and ``repo_name`` API keys never collide across tests
   or xdist workers.
2. **Server-generated run IDs** — every ``POST /api/runs`` returns a fresh
   UUID. No test can reference another test's run.
3. **Per-test cleanup** — ``client_with_repo``'s teardown lists runs by this
   test's unique ``repo_name`` and cancels any non-terminal ones. Background
   executor tasks from a failing test cannot leak CPU/DB-pool work into
   subsequent tests in the same module.
4. **Module-scoped, not session-scoped** — a poisoned app instance is bounded
   to one test file, never the whole suite.

The shared base repo (``_base_repo``) is session-scoped and read-only:
``git_repo`` copies it with ``shutil.copytree``. Reads from the shared base
cannot mutate it.
"""

import shutil
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

from tests.integration.git_helpers import _commit_file, _git, _init_repo
from tests.integration.signal_helpers import DrainFn, make_drain_fn

__all__ = ["_git", "_init_repo", "_commit_file", "_setup_conflict", "DrainFn"]

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

# Statuses considered "in flight" for teardown cleanup.
_NON_TERMINAL_RUN_STATUSES = frozenset({"active", "paused", "draft", "queued"})


# ---------------------------------------------------------------------------
# Shared git + app fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _base_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Read-only base git repo, initialised ONCE per xdist worker session.

    Per-test ``git_repo`` instances ``shutil.copytree`` from this; nothing
    writes to ``_base_repo`` directly, so it's safe to share.
    """
    base = tmp_path_factory.mktemp("base_repo")
    repo = base / "repo"
    repo.mkdir()
    _init_repo(repo)
    return repo


@pytest.fixture(scope="module")
async def _shared_app_fixture(
    tmp_path_factory: pytest.TempPathFactory,
) -> AsyncGenerator[tuple[AsyncClient, DrainFn, Path, Path, Any], None]:
    """Module-scoped FastAPI app + in-memory DB.

    One app instance per test file (module scope, NOT session). A bad test
    in file A cannot poison the app used by file B. Within a module,
    isolation comes from unique repo names + server-generated run UUIDs +
    per-test teardown cleanup in ``client_with_repo``.

    Yields ``(client, drain, repos_dir, worktrees_dir, app)``.
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
    """Per-test git repo with a UUID-suffixed name inside the shared repos_dir.

    UUID (not a counter) so the name is unique even if the same fixture is
    used across xdist workers or files. Copy-from-base avoids ~150 ms of
    ``git init`` + config + commit subprocesses per test.
    """
    _, _, repos_dir, _, _ = _shared_app_fixture
    repo = repos_dir / f"project_{uuid.uuid4().hex[:8]}"
    shutil.copytree(str(_base_repo), str(repo))
    return repo


@pytest.fixture
def repo_name() -> str:
    """Per-test unique repo name.

    Use this fixture in tests that share a module-scoped app and DB to avoid
    cross-test collisions on the ``repo_name`` API key. The UUID suffix
    guarantees uniqueness across tests and xdist workers.
    """
    return f"proj_{uuid.uuid4().hex[:8]}"


async def cleanup_runs_for_repo(client: AsyncClient, repo_name: str) -> None:
    """Cancel any non-terminal runs for ``repo_name`` (best-effort).

    Use in test fixture teardowns when sharing an app across tests, to keep a
    failing test from leaking background executor work into siblings. Scoped
    to ``repo_name``, which is unique per test (see ``git_repo``).
    """
    try:
        resp = await client.get("/api/runs", params={"repo_name": repo_name})
        if resp.status_code == 200:
            for run in resp.json().get("runs", []):
                if run.get("status") in _NON_TERMINAL_RUN_STATUSES:
                    await client.post(f"/api/runs/{run['id']}/cancel")
    except Exception:
        pass


@pytest.fixture
async def client_with_repo(
    _shared_app_fixture: tuple[AsyncClient, DrainFn, Path, Path, Any],
    git_repo: Path,
) -> AsyncGenerator[tuple[AsyncClient, Path, DrainFn], None]:
    """Yield ``(client, git_repo, drain)`` and cancel this test's runs on teardown.

    Cleanup is best-effort and scoped to ``git_repo.name`` (unique per test):
    listing by ``repo_name`` cannot see other tests' runs, so even a crashing
    cleanup cannot affect anyone else.
    """
    client, drain, _, _, _ = _shared_app_fixture
    yield client, git_repo, drain
    await cleanup_runs_for_repo(client, git_repo.name)


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
