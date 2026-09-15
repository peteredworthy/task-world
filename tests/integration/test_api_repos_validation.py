"""Narrow API seam for repository and model-discovery URL validation."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


async def _clone_always_fails(url: str, dest: Path) -> None:
    """Make a valid-scheme request stop at the clone boundary."""
    raise HTTPException(status_code=422, detail="Failed to clone: test boundary")


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    app.state.git_cloner = _clone_always_fails
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as value:
        yield value
    await app.state.engine.dispose()


async def test_url_validation_rejects_unsafe_schemes_at_api_boundary(
    client: AsyncClient,
) -> None:
    repository = await client.post("/api/repos", json={"url": "file:///etc/passwd"})
    assert repository.status_code == 422
    assert "http://" in repository.json()["detail"]

    models = await client.get(
        "/api/agent-runners/local-models",
        params={"base_url": "file:///etc/passwd"},
    )
    assert models.status_code == 422
    assert "http://" in models.json()["detail"]
