"""Integration tests for verifier model pinning via the HTTP API.

Verifies that:
- Run creation stores verifier_model from agent_config
- verifier_model is persisted and survives a round-trip through the DB
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.db.connection import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


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


async def _create_run(
    client: AsyncClient,
    agent_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a run with optional agent_config and return the response body."""
    body: dict[str, Any] = {
        "routine_id": "simple-routine",
        "repo_name": "proj-1",
        "branch": "main",
        "agent_type": "claude_sdk",
    }
    if agent_config is not None:
        body["agent_config"] = agent_config
    resp = await client.post("/api/runs", json=body)
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    return resp.json()


async def test_run_creation_stores_verifier_model(client: AsyncClient) -> None:
    """Run created with agent_config model should store it as verifier_model."""
    data = await _create_run(client, agent_config={"model": "claude-opus-4-5"})
    assert data["verifier_model"] == "claude-opus-4-5"


async def test_run_creation_verifier_model_none_when_no_agent_config(
    client: AsyncClient,
) -> None:
    """Run created without agent_config should have verifier_model=None."""
    resp = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "proj-1",
            "branch": "main",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data.get("verifier_model") is None


async def test_run_creation_verifier_model_none_when_model_not_in_agent_config(
    client: AsyncClient,
) -> None:
    """Run created with agent_config but no model key should have verifier_model=None."""
    data = await _create_run(client, agent_config={"max_turns": 30})
    assert data.get("verifier_model") is None


async def test_verifier_model_persisted_on_get(client: AsyncClient) -> None:
    """verifier_model should survive a DB round-trip (GET after POST)."""
    created = await _create_run(client, agent_config={"model": "claude-haiku-4-5"})
    run_id = created["id"]

    resp = await client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["verifier_model"] == "claude-haiku-4-5"
