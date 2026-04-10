"""Integration smoke tests for run API router-level validation.

Pure Pydantic field validators (agent_type, merge_strategy, BackwardTransitionRequest,
RecoverRequest, ResumeRunRequest, MergeBackRequest) are tested in
tests/unit/test_api_runs_validation.py.

This file covers validation logic that lives in the router itself (not in Pydantic
models) and therefore requires an HTTP request to exercise:
  - agent_config key validation (done in the create-run handler)
  - list_runs status query-param validation (done in the handler)
  - list_runs integer-bounds query-param validation (FastAPI Query constraints)
"""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

BASE_BODY = {"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"}


@pytest.fixture(scope="module")
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


# --- agent_config key validation (router-level) ---


async def test_unknown_agent_config_keys_returns_422(client: AsyncClient) -> None:
    """Unknown agent_config keys should return 422 with valid fields listed."""
    resp = await client.post(
        "/api/runs",
        json={
            **BASE_BODY,
            "agent_type": "codex_server",
            "agent_config": {"model": "gpt-4o", "foo": "bar", "baz": 42},
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "Unknown agent_config fields" in detail
    assert "foo" in detail
    assert "baz" in detail
    assert "Valid fields" in detail


async def test_valid_agent_config_keys_accepted(client: AsyncClient) -> None:
    """Valid agent_config keys should be accepted."""
    resp = await client.post(
        "/api/runs",
        json={
            **BASE_BODY,
            "agent_type": "codex_server",
            "agent_config": {"model": "gpt-4o", "restrictions": "none"},
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_config"]["model"] == "gpt-4o"
    assert data["agent_config"]["restrictions"] == "none"


async def test_agent_config_without_agent_type_skips_validation(client: AsyncClient) -> None:
    """agent_config without agent_type should not validate keys (no schema to check against)."""
    resp = await client.post(
        "/api/runs",
        json={**BASE_BODY, "agent_config": {"anything": "goes"}},
    )
    assert resp.status_code == 201


# --- list_runs status query param validation (router-level) ---


async def test_list_runs_invalid_status_returns_422(client: AsyncClient) -> None:
    """Invalid status query param should return 422 with valid options."""
    resp = await client.get("/api/runs", params={"status": "bogus"})
    assert resp.status_code == 422
    body = resp.json()
    assert "Invalid status" in body["detail"]
    assert "Valid options" in body["detail"]


async def test_list_runs_valid_status_accepted(client: AsyncClient) -> None:
    """Valid status query param should work."""
    resp = await client.get("/api/runs", params={"status": "draft"})
    assert resp.status_code == 200


# --- Query param bounds (FastAPI Query constraints) ---


async def test_list_runs_zero_recent_hours_returns_422(client: AsyncClient) -> None:
    """recent_hours=0 should return 422."""
    resp = await client.get("/api/runs", params={"recent_hours": 0})
    assert resp.status_code == 422


async def test_list_runs_zero_limit_returns_422(client: AsyncClient) -> None:
    """limit=0 should return 422."""
    resp = await client.get("/api/runs", params={"limit": 0})
    assert resp.status_code == 422
