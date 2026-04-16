"""Integration tests for project routine discovery from git repositories."""

import shutil
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource, discover_routines_in_repo, get_routine_from_repo
from orchestrator.db import init_db

from tests.integration.git_helpers import _git


def _add_flat_routine(repo: Path, routine_id: str, name: str = "Test Routine") -> None:
    """Add a flat file routine to the repo."""
    routines_dir = repo / "routines"
    routines_dir.mkdir(exist_ok=True)
    routine_yaml = f"""id: {routine_id}
name: {name}
description: A test routine
inputs: []
steps:
  - id: S-01
    title: Step One
    tasks:
      - id: T-01
        title: Task One
        task_context: Do the task
        requirements:
          - id: R-01
            desc: Do something
            priority: critical
        artifacts: []
"""
    (routines_dir / f"{routine_id}.yaml").write_text(routine_yaml)
    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", f"Add routine {routine_id}"], cwd=repo)


def _add_directory_routine(
    repo: Path, routine_id: str, name: str = "Dir Routine", with_scaffolding: bool = False
) -> None:
    """Add a directory-based routine to the repo."""
    routine_dir = repo / "routines" / routine_id
    routine_dir.mkdir(parents=True, exist_ok=True)
    routine_yaml = f"""id: {routine_id}
name: {name}
description: A directory-based routine
inputs: []
steps:
  - id: S-01
    title: Step One
    tasks:
      - id: T-01
        title: Task One
        task_context: Do the task
        requirements:
          - id: R-01
            desc: Do something
            priority: critical
        artifacts: []
"""
    (routine_dir / "routine.yaml").write_text(routine_yaml)

    if with_scaffolding:
        scaffolding_dir = routine_dir / "scaffolding"
        scaffolding_dir.mkdir(exist_ok=True)
        (scaffolding_dir / "template.md").write_text("# Template\n")

    _git(["add", "."], cwd=repo)
    _git(["commit", "-m", f"Add directory routine {routine_id}"], cwd=repo)


@pytest.fixture
def repo_with_routines(tmp_path: Path, _base_repo: Path) -> Path:
    """Create a git repo with sample routines.

    Uses shutil.copytree from the session-scoped base repo instead of
    git init + config + commit (saves ~150 ms per test).
    """
    return Path(shutil.copytree(str(_base_repo), str(tmp_path / "project")))


class TestDiscoverRoutinesInRepo:
    def test_no_routines_dir(self, repo_with_routines: Path) -> None:
        """Empty list when routines/ directory doesn't exist."""
        routines = discover_routines_in_repo(repo_with_routines, "main")
        assert routines == []

    def test_empty_routines_dir(self, repo_with_routines: Path) -> None:
        """Empty list when routines/ is empty."""
        (repo_with_routines / "routines").mkdir()
        _git(["add", "."], cwd=repo_with_routines)
        _git(["commit", "--allow-empty", "-m", "Add empty routines dir"], cwd=repo_with_routines)

        routines = discover_routines_in_repo(repo_with_routines, "main")
        assert routines == []

    def test_discover_flat_routine(self, repo_with_routines: Path) -> None:
        """Discovers flat file routines (routines/*.yaml)."""
        _add_flat_routine(repo_with_routines, "my-routine", "My Routine")

        routines = discover_routines_in_repo(repo_with_routines, "main")

        assert len(routines) == 1
        r = routines[0]
        assert r.config.id == "my-routine"
        assert r.config.name == "My Routine"
        assert r.source == RoutineSource.PROJECT
        assert r.path == "routines/my-routine.yaml"
        assert r.commit is not None and len(r.commit) == 40  # Full SHA
        assert r.has_scaffolding is False

    def test_discover_multiple_routines(self, repo_with_routines: Path) -> None:
        """Discovers multiple routines."""
        _add_flat_routine(repo_with_routines, "alpha", "Alpha")
        _add_flat_routine(repo_with_routines, "beta", "Beta")

        routines = discover_routines_in_repo(repo_with_routines, "main")

        assert len(routines) == 2
        ids = {r.config.id for r in routines}
        assert ids == {"alpha", "beta"}

    def test_discover_directory_routine(self, repo_with_routines: Path) -> None:
        """Discovers directory-based routines (routines/*/routine.yaml)."""
        _add_directory_routine(repo_with_routines, "feature-x", "Feature X")

        routines = discover_routines_in_repo(repo_with_routines, "main")

        assert len(routines) == 1
        r = routines[0]
        assert r.config.id == "feature-x"
        assert r.config.name == "Feature X"
        assert r.path == "routines/feature-x/routine.yaml"
        assert r.has_scaffolding is False

    def test_discover_directory_routine_with_scaffolding(self, repo_with_routines: Path) -> None:
        """Detects scaffolding directory in directory-based routines."""
        _add_directory_routine(
            repo_with_routines, "with-scaffold", "With Scaffold", with_scaffolding=True
        )

        routines = discover_routines_in_repo(repo_with_routines, "main")

        assert len(routines) == 1
        r = routines[0]
        assert r.config.id == "with-scaffold"
        assert r.has_scaffolding is True
        assert r.scaffolding_path == "routines/with-scaffold/scaffolding/"

    def test_discover_mixed_routines(self, repo_with_routines: Path) -> None:
        """Discovers both flat and directory-based routines."""
        _add_flat_routine(repo_with_routines, "flat-one", "Flat One")
        _add_directory_routine(repo_with_routines, "dir-one", "Dir One")

        routines = discover_routines_in_repo(repo_with_routines, "main")

        assert len(routines) == 2
        ids = {r.config.id for r in routines}
        assert ids == {"flat-one", "dir-one"}

    def test_discover_on_different_branch(self, repo_with_routines: Path) -> None:
        """Discovers routines from a specific branch."""
        # Add routine on main
        _add_flat_routine(repo_with_routines, "main-routine", "Main Routine")

        # Create feature branch and add a different routine
        _git(["checkout", "-b", "feature"], cwd=repo_with_routines)
        _add_flat_routine(repo_with_routines, "feature-routine", "Feature Routine")
        _git(["checkout", "main"], cwd=repo_with_routines)

        # Check main branch
        main_routines = discover_routines_in_repo(repo_with_routines, "main")
        assert len(main_routines) == 1
        assert main_routines[0].config.id == "main-routine"

        # Check feature branch
        feature_routines = discover_routines_in_repo(repo_with_routines, "feature")
        assert len(feature_routines) == 2
        ids = {r.config.id for r in feature_routines}
        assert ids == {"main-routine", "feature-routine"}

    def test_invalid_yaml_skipped(self, repo_with_routines: Path) -> None:
        """Invalid YAML files are silently skipped."""
        routines_dir = repo_with_routines / "routines"
        routines_dir.mkdir()
        (routines_dir / "invalid.yaml").write_text("not: valid: yaml: {{}")
        _add_flat_routine(repo_with_routines, "valid", "Valid")

        routines = discover_routines_in_repo(repo_with_routines, "main")

        assert len(routines) == 1
        assert routines[0].config.id == "valid"


class TestGetRoutineFromRepo:
    def test_get_existing_routine(self, repo_with_routines: Path) -> None:
        """Gets a specific routine by ID."""
        _add_flat_routine(repo_with_routines, "target", "Target")
        _add_flat_routine(repo_with_routines, "other", "Other")

        routine = get_routine_from_repo(repo_with_routines, "main", "target")

        assert routine is not None
        assert routine.config.id == "target"
        assert routine.config.name == "Target"

    def test_get_nonexistent_routine(self, repo_with_routines: Path) -> None:
        """Returns None for non-existent routine."""
        _add_flat_routine(repo_with_routines, "exists", "Exists")

        routine = get_routine_from_repo(repo_with_routines, "main", "does-not-exist")

        assert routine is None


# --- API Tests ---


@pytest.fixture
def repos_dir(tmp_path: Path) -> Path:
    """Create a repos directory."""
    repos = tmp_path / "repos"
    repos.mkdir()
    return repos


@pytest.fixture
def app_with_repos(repos_dir: Path, repo_with_routines: Path, monkeypatch: pytest.MonkeyPatch):
    """Create an app with a custom repos directory containing our test repo."""
    import shutil

    from orchestrator.config import global_config

    # Copy repo into repos_dir
    target = repos_dir / "test-project"
    shutil.copytree(repo_with_routines, target)

    # Monkeypatch to use our repos directory
    def patched_get_repos_path(self, base=None):
        return repos_dir

    monkeypatch.setattr(global_config.PathsConfig, "get_repos_path", patched_get_repos_path)

    app = create_app(db_path=":memory:", auth_disabled=True)
    return app, target


@pytest.fixture
async def client_with_repo(
    app_with_repos: tuple,
) -> AsyncGenerator[tuple[AsyncClient, Path], None]:
    """Create test client with a repo in the repos directory."""
    app, target = app_with_repos
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, target
    await app.state.engine.dispose()


async def test_list_routines_empty(
    client_with_repo: tuple[AsyncClient, Path],
) -> None:
    """List routines returns empty when no routines exist."""
    client, _repo = client_with_repo

    response = await client.get("/api/repos/test-project/routines?branch=main")

    assert response.status_code == 200
    data = response.json()
    assert data["routines"] == []
    assert data["branch"] == "main"


async def test_list_routines_with_routines(
    client_with_repo: tuple[AsyncClient, Path],
) -> None:
    """List routines returns routines from the repo."""
    client, repo = client_with_repo
    _add_flat_routine(repo, "api-routine", "API Routine")

    response = await client.get("/api/repos/test-project/routines?branch=main")

    assert response.status_code == 200
    data = response.json()
    assert len(data["routines"]) == 1
    r = data["routines"][0]
    assert r["id"] == "api-routine"
    assert r["name"] == "API Routine"
    assert r["source"] == "PROJECT"
    assert r["path"] == "routines/api-routine.yaml"
    assert r["has_scaffolding"] is False
    assert "config" in r


async def test_get_routine(
    client_with_repo: tuple[AsyncClient, Path],
) -> None:
    """Get a specific routine by ID."""
    client, repo = client_with_repo
    _add_flat_routine(repo, "target-routine", "Target Routine")

    response = await client.get("/api/repos/test-project/routines/target-routine?branch=main")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "target-routine"
    assert data["name"] == "Target Routine"
    assert "config" in data


async def test_get_routine_not_found(
    client_with_repo: tuple[AsyncClient, Path],
) -> None:
    """Get routine returns 404 for non-existent routine."""
    client, _repo = client_with_repo

    response = await client.get("/api/repos/test-project/routines/nonexistent?branch=main")

    assert response.status_code == 404
