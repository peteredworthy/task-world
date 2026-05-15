"""Integration tests for review API router-level query validation."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

BASE_BODY = {"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"}


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


async def _create_run(client: AsyncClient) -> str:
    resp = await client.post("/api/runs", json={**BASE_BODY, "agent_runner_type": "cli_subprocess"})
    assert resp.status_code == 201
    return resp.json()["id"]


# --- Diff scope validation ---


async def test_diff_invalid_scope_returns_422(client: AsyncClient) -> None:
    """Invalid diff scope should return 422."""
    run_id = await _create_run(client)
    resp = await client.get(f"/api/runs/{run_id}/review/diff", params={"scope": "invalid"})
    assert resp.status_code == 422
    assert "Invalid scope" in resp.json()["detail"]


async def test_diff_files_invalid_scope_returns_422(client: AsyncClient) -> None:
    """Invalid diff/files scope should return 422."""
    run_id = await _create_run(client)
    resp = await client.get(f"/api/runs/{run_id}/review/diff/files", params={"scope": "commit"})
    assert resp.status_code == 422
    assert "Invalid scope" in resp.json()["detail"]
