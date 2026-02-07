"""Integration tests for run creation with env files."""

import pytest
from pathlib import Path
from collections.abc import AsyncGenerator
from httpx import ASGITransport, AsyncClient
from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.db.connection import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client(tmp_path: Path) -> AsyncGenerator[AsyncClient, None]:
    app = create_app(db_path=":memory:", routine_dirs=[(FIXTURES, RoutineSource.LOCAL)])
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


async def test_create_run_with_env_files_from_request(client: AsyncClient) -> None:
    """Test creating a run with env files specified in the request."""
    resp = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "project_id": "test-project",
            "env_files": {
                "source_dir": "/path/to/source",
                "files": [
                    {"path": ".env", "promote_on_success": True},
                    {"path": "config/.env.production", "promote_on_success": False},
                ],
            },
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["env_source_dir"] == "/path/to/source"
    assert len(data["env_file_specs"]) == 2
    assert data["env_file_specs"][0]["path"] == ".env"
    assert data["env_file_specs"][0]["promote_on_success"] is True
    assert data["env_file_specs"][1]["path"] == "config/.env.production"
    assert data["env_file_specs"][1]["promote_on_success"] is False


async def test_create_run_with_env_files_from_embedded_routine(client: AsyncClient) -> None:
    """Test creating a run with env files from embedded routine config."""
    resp = await client.post(
        "/api/runs",
        json={
            "project_id": "test-project",
            "routine_embedded": {
                "id": "test-routine",
                "name": "Test Routine",
                "steps": [
                    {
                        "id": "step1",
                        "title": "Step 1",
                        "tasks": [
                            {
                                "id": "task1",
                                "title": "Task 1",
                                "task_context": "Do something",
                                "requirements": [
                                    {"id": "r1", "desc": "Requirement 1"},
                                ],
                            }
                        ],
                    }
                ],
                "env_files": [
                    {"path": ".env.local", "promote_on_success": True},
                ],
            },
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["env_file_specs"]) == 1
    assert data["env_file_specs"][0]["path"] == ".env.local"
    assert data["env_file_specs"][0]["promote_on_success"] is True


async def test_create_run_request_overrides_routine_env_files(client: AsyncClient) -> None:
    """Test that request env files override routine env files."""
    resp = await client.post(
        "/api/runs",
        json={
            "project_id": "test-project",
            "routine_embedded": {
                "id": "test-routine",
                "name": "Test Routine",
                "steps": [
                    {
                        "id": "step1",
                        "title": "Step 1",
                        "tasks": [
                            {
                                "id": "task1",
                                "title": "Task 1",
                                "task_context": "Do something",
                                "requirements": [
                                    {"id": "r1", "desc": "Requirement 1"},
                                ],
                            }
                        ],
                    }
                ],
                "env_files": [
                    {"path": ".env.local", "promote_on_success": True},
                ],
            },
            "env_files": {
                "source_dir": "/override/path",
                "files": [
                    {"path": ".env.override", "promote_on_success": False},
                ],
            },
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    # Request should override routine
    assert data["env_source_dir"] == "/override/path"
    assert len(data["env_file_specs"]) == 1
    assert data["env_file_specs"][0]["path"] == ".env.override"
    assert data["env_file_specs"][0]["promote_on_success"] is False


async def test_create_run_without_env_files(client: AsyncClient) -> None:
    """Test creating a run without env files (defaults to empty)."""
    resp = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "project_id": "test-project",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["env_file_specs"] == []
    assert data["env_source_dir"] is None


async def test_create_run_with_empty_env_files_list_overrides_routine(client: AsyncClient) -> None:
    """Test that an empty env files list in request overrides routine config."""
    resp = await client.post(
        "/api/runs",
        json={
            "project_id": "test-project",
            "routine_embedded": {
                "id": "test-routine",
                "name": "Test Routine",
                "steps": [
                    {
                        "id": "step1",
                        "title": "Step 1",
                        "tasks": [
                            {
                                "id": "task1",
                                "title": "Task 1",
                                "task_context": "Do something",
                                "requirements": [
                                    {"id": "r1", "desc": "Requirement 1"},
                                ],
                            }
                        ],
                    }
                ],
                "env_files": [
                    {"path": ".env.local", "promote_on_success": True},
                ],
            },
            "env_files": {
                "files": [],  # Empty list overrides routine
            },
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["env_file_specs"] == []
