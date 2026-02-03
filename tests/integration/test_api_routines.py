"""Integration tests for routine API endpoints."""

from pathlib import Path

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def empty_client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app(db_path=":memory:", routine_dirs=[])
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_list_routines(client: AsyncClient) -> None:
    response = await client.get("/api/routines")
    assert response.status_code == 200
    data = response.json()
    routines = data["routines"]
    # Should find valid_simple.yaml and valid_complete.yaml (invalid_with_ref.yaml is skipped)
    assert len(routines) >= 2
    ids = {r["id"] for r in routines}
    assert "simple-routine" in ids
    assert "complete-routine" in ids


async def test_list_routines_returns_summary_fields(client: AsyncClient) -> None:
    response = await client.get("/api/routines")
    data = response.json()
    simple = next(r for r in data["routines"] if r["id"] == "simple-routine")
    assert simple["name"] == "Simple Routine"
    assert simple["source"] == "local"
    assert simple["step_count"] == 1
    assert simple["input_count"] == 0


async def test_get_routine_by_id(client: AsyncClient) -> None:
    response = await client.get("/api/routines/complete-routine")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "complete-routine"
    assert data["name"] == "Complete Routine"
    assert data["source"] == "local"
    assert len(data["steps"]) == 2
    assert data["steps"][0]["id"] == "S-01"
    assert data["steps"][0]["task_count"] == 1
    assert data["steps"][1]["id"] == "S-02"
    assert data["steps"][1]["task_count"] == 2
    assert len(data["inputs"]) == 2


async def test_get_routine_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/routines/nonexistent")
    assert response.status_code == 404


async def test_empty_dir_returns_empty_list(empty_client: AsyncClient) -> None:
    response = await empty_client.get("/api/routines")
    assert response.status_code == 200
    assert response.json() == {"routines": []}
