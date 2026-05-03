"""Integration tests for run API input validation (agent_runner_type, merge_strategy, agent_runner_config)."""

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


# --- agent_runner_type validation ---


async def test_invalid_agent_runner_type_returns_422(client: AsyncClient) -> None:
    """Invalid agent_runner_type should return 422 with valid options listed."""
    resp = await client.post("/api/runs", json={**BASE_BODY, "agent_runner_type": "INVALID"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    # Pydantic wraps field_validator errors in the detail list
    assert any("Invalid agent_runner_type" in str(e) for e in detail)
    assert any("Valid options" in str(e) for e in detail)


async def test_uppercase_agent_runner_type_accepted(client: AsyncClient) -> None:
    """Agent runner type should be accepted case-insensitively."""
    resp = await client.post("/api/runs", json={**BASE_BODY, "agent_runner_type": "CODEX_SERVER"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_runner_type"] == "codex_server"


async def test_mixed_case_agent_runner_type_accepted(client: AsyncClient) -> None:
    """Mixed case agent runner type should be normalized to lowercase."""
    resp = await client.post("/api/runs", json={**BASE_BODY, "agent_runner_type": "Claude_SDK"})
    assert resp.status_code == 201
    assert resp.json()["agent_runner_type"] == "claude_sdk"


async def test_valid_lowercase_agent_runner_type_accepted(client: AsyncClient) -> None:
    """Standard lowercase agent runner type should work as before."""
    resp = await client.post("/api/runs", json={**BASE_BODY, "agent_runner_type": "user_managed"})
    assert resp.status_code == 201
    assert resp.json()["agent_runner_type"] == "user_managed"


async def test_null_agent_runner_type_accepted(client: AsyncClient) -> None:
    """Null/missing agent_runner_type should still be accepted."""
    resp = await client.post("/api/runs", json=BASE_BODY)
    assert resp.status_code == 201
    assert resp.json()["agent_runner_type"] is None


# --- merge_strategy validation ---


async def test_invalid_merge_strategy_returns_422(client: AsyncClient) -> None:
    """Invalid merge_strategy should return 422."""
    resp = await client.post("/api/runs", json={**BASE_BODY, "merge_strategy": "rebase"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any("Invalid merge_strategy" in str(e) for e in detail)


async def test_valid_merge_strategy_accepted(client: AsyncClient) -> None:
    """Valid merge_strategy should be accepted."""
    resp = await client.post("/api/runs", json={**BASE_BODY, "merge_strategy": "squash"})
    assert resp.status_code == 201
    assert resp.json()["merge_strategy"] == "squash"


async def test_uppercase_merge_strategy_accepted(client: AsyncClient) -> None:
    """Merge strategy should be accepted case-insensitively."""
    resp = await client.post("/api/runs", json={**BASE_BODY, "merge_strategy": "MERGE"})
    assert resp.status_code == 201
    assert resp.json()["merge_strategy"] == "merge"


# --- agent_runner_config key validation ---


async def test_unknown_agent_runner_config_keys_returns_422(client: AsyncClient) -> None:
    """Unknown agent_runner_config keys should return 422 with valid fields listed."""
    resp = await client.post(
        "/api/runs",
        json={
            **BASE_BODY,
            "agent_runner_type": "codex_server",
            "agent_runner_config": {"model": "gpt-4o", "foo": "bar", "baz": 42},
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "Unknown agent_runner_config fields" in detail
    assert "foo" in detail
    assert "baz" in detail
    assert "Valid fields" in detail


async def test_valid_agent_runner_config_keys_accepted(client: AsyncClient) -> None:
    """Valid agent_runner_config keys should be accepted."""
    resp = await client.post(
        "/api/runs",
        json={
            **BASE_BODY,
            "agent_runner_type": "codex_server",
            "agent_runner_config": {"model": "gpt-4o", "restrictions": "none"},
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_runner_config"]["model"] == "gpt-4o"
    assert data["agent_runner_config"]["restrictions"] == "none"


async def test_agent_runner_config_without_agent_runner_type_skips_validation(
    client: AsyncClient,
) -> None:
    """agent_runner_config without agent_runner_type should not validate keys (no schema to check against)."""
    resp = await client.post(
        "/api/runs",
        json={**BASE_BODY, "agent_runner_config": {"anything": "goes"}},
    )
    assert resp.status_code == 201


# --- resume endpoint validation ---


async def test_resume_invalid_agent_runner_type_returns_422(client: AsyncClient) -> None:
    """Invalid agent_runner_type on resume should return 422."""
    # Create and start a run, then pause it
    create_resp = await client.post(
        "/api/runs", json={**BASE_BODY, "agent_runner_type": "user_managed"}
    )
    assert create_resp.status_code == 201
    run_id = create_resp.json()["id"]

    # Start and pause the run
    await client.post(f"/api/runs/{run_id}/start")
    await client.post(f"/api/runs/{run_id}/pause")

    # Try to resume with invalid agent runner type
    resp = await client.post(f"/api/runs/{run_id}/resume", json={"agent_runner_type": "NOT_REAL"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert any("Invalid agent_runner_type" in str(e) for e in detail)


# --- list_runs status query param validation ---


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


# --- MergeBackRequest.strategy validation ---


async def test_merge_back_invalid_strategy_returns_422(client: AsyncClient) -> None:
    """Invalid merge-back strategy should return 422."""
    create_resp = await client.post(
        "/api/runs", json={**BASE_BODY, "agent_runner_type": "user_managed"}
    )
    run_id = create_resp.json()["id"]
    resp = await client.post(f"/api/runs/{run_id}/merge-back", json={"strategy": "rebase"})
    assert resp.status_code == 422


# --- RecoverRequest.additional_attempts validation ---


async def test_recover_negative_additional_attempts_returns_422(client: AsyncClient) -> None:
    """Negative additional_attempts should return 422."""
    create_resp = await client.post(
        "/api/runs", json={**BASE_BODY, "agent_runner_type": "user_managed"}
    )
    run_id = create_resp.json()["id"]
    resp = await client.post(
        f"/api/runs/{run_id}/recover",
        json={"target_task_id": "T-01", "additional_attempts": -1},
    )
    assert resp.status_code == 422


# --- BackwardTransitionRequest.target_step_index validation ---


async def test_backward_transition_negative_index_returns_422(client: AsyncClient) -> None:
    """Negative target_step_index should return 422."""
    create_resp = await client.post(
        "/api/runs", json={**BASE_BODY, "agent_runner_type": "user_managed"}
    )
    run_id = create_resp.json()["id"]
    resp = await client.post(
        f"/api/runs/{run_id}/transition-back",
        json={"target_step_index": -1},
    )
    assert resp.status_code == 422


# --- Query param bounds ---


async def test_list_runs_zero_recent_hours_returns_422(client: AsyncClient) -> None:
    """recent_hours=0 should return 422."""
    resp = await client.get("/api/runs", params={"recent_hours": 0})
    assert resp.status_code == 422


async def test_list_runs_zero_limit_returns_422(client: AsyncClient) -> None:
    """limit=0 should return 422."""
    resp = await client.get("/api/runs", params={"limit": 0})
    assert resp.status_code == 422
