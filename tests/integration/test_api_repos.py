"""Integration tests for repos API endpoints."""

import subprocess
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app


@pytest.fixture
def repos_dir(tmp_path: Path) -> Path:
    """Create a repos directory with test repositories."""
    repos = tmp_path / "repos"
    repos.mkdir()
    return repos


@pytest.fixture
def sample_repo(repos_dir: Path) -> Path:
    """Create a sample git repository."""
    repo_path = repos_dir / "sample-repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    (repo_path / "README.md").write_text("# Sample Repo")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Create feature branches
    subprocess.run(
        ["git", "checkout", "-b", "feature/auth"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", "feature/login"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "-b", "bugfix/typo"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Back to main
    subprocess.run(
        ["git", "checkout", "main"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    return repo_path


@pytest.fixture
def app_with_repos(repos_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """Create an app with a custom repos directory."""
    # Monkeypatch to use our repos directory
    from orchestrator.config import global_config

    def patched_get_repos_path(self, base=None):
        return repos_dir

    monkeypatch.setattr(global_config.PathsConfig, "get_repos_path", patched_get_repos_path)

    app = create_app(db_path=":memory:", auth_disabled=True)
    return app


@pytest.fixture
async def client(app_with_repos):
    """Create an async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app_with_repos),
        base_url="http://test",
    ) as client:
        yield client


class TestListRepos:
    async def test_empty_repos_dir(self, client: AsyncClient) -> None:
        response = await client.get("/api/repos")
        assert response.status_code == 200
        data = response.json()
        assert data["repos"] == []

    async def test_with_repos(self, sample_repo: Path, client: AsyncClient) -> None:
        response = await client.get("/api/repos")
        assert response.status_code == 200
        data = response.json()
        assert len(data["repos"]) == 1
        assert data["repos"][0]["name"] == "sample-repo"


class TestGetRepo:
    async def test_existing_repo(self, sample_repo: Path, client: AsyncClient) -> None:
        response = await client.get("/api/repos/sample-repo")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "sample-repo"
        assert "default_branch" in data

    async def test_nonexistent_repo(self, client: AsyncClient) -> None:
        response = await client.get("/api/repos/nonexistent")
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "repo_not_found"


class TestListBranches:
    async def test_list_branches(self, sample_repo: Path, client: AsyncClient) -> None:
        response = await client.get("/api/repos/sample-repo/branches?include_remote=false")
        assert response.status_code == 200
        data = response.json()
        names = [b["name"] for b in data["branches"]]
        assert "main" in names or "master" in names
        assert "feature/auth" in names

    async def test_pattern_filter(self, sample_repo: Path, client: AsyncClient) -> None:
        response = await client.get(
            "/api/repos/sample-repo/branches?pattern=feature/*&include_remote=false"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["branches"]) == 2
        names = [b["name"] for b in data["branches"]]
        assert "feature/auth" in names
        assert "feature/login" in names

    async def test_nonexistent_repo(self, client: AsyncClient) -> None:
        response = await client.get("/api/repos/nonexistent/branches")
        assert response.status_code == 404


class TestBranchCount:
    async def test_count_all(self, sample_repo: Path, client: AsyncClient) -> None:
        response = await client.get("/api/repos/sample-repo/branches/count?include_remote=false")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 4  # main + feature/auth + feature/login + bugfix/typo

    async def test_count_with_pattern(self, sample_repo: Path, client: AsyncClient) -> None:
        response = await client.get(
            "/api/repos/sample-repo/branches/count?pattern=feature/*&include_remote=false"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert data["pattern"] == "feature/*"
