"""Integration tests for the codex_server agent runner type."""

from pathlib import Path

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport
from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    signal_transport = InMemorySignalTransport()
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    app.state.signal_transport = signal_transport
    # Bypass model validation for tests that don't specifically test it.
    # An empty list causes validate_codex_model_selection to skip validation.
    app.state.codex_models_fn = lambda: []
    await init_db(app.state.engine)
    drain = make_drain_fn(app, signal_transport)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


@pytest.fixture
async def client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    c, _ = client_and_drain
    return c


async def _create_run_with_agent(
    client: AsyncClient, agent_runner_type: str, agent_runner_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Helper: create a run with the given agent runner type and return the response data."""
    body: dict[str, Any] = {
        "routine_id": "simple-routine",
        "repo_name": "proj-1",
        "branch": "main",
        "agent_runner_type": agent_runner_type,
    }
    if agent_runner_config is not None:
        body["agent_runner_config"] = agent_runner_config
    response = await client.post("/api/runs", json=body)
    assert response.status_code == 201
    return response.json()


async def test_create_run_with_codex_server(client: AsyncClient) -> None:
    """codex_server agent runner type is accepted and persisted on creation."""
    data = await _create_run_with_agent(client, "codex_server")
    assert data["agent_runner_type"] == "codex_server"
    assert data["status"] == "draft"


async def test_read_run_round_trip_codex_server(client: AsyncClient) -> None:
    """A run created with codex_server returns the same agent_runner_type on GET."""
    created = await _create_run_with_agent(client, "codex_server", {"model": "gpt-4o"})
    run_id = created["id"]

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_runner_type"] == "codex_server"
    assert data["agent_runner_config"] == {"model": "gpt-4o"}


async def test_update_run_agent_runner_type_to_codex_server(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Resuming a paused run with codex_server updates agent_runner_type correctly."""
    client, drain = client_and_drain
    response = await client.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "proj-codex",
            "branch": "main",
            "agent_runner_type": "cli_subprocess",
            "agent_runner_config": {"callback_channel": "rest"},
        },
    )
    assert response.status_code == 201
    run_id = response.json()["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202
    await drain(run_id)

    response = await client.post(
        f"/api/runs/{run_id}/resume",
        json={
            "agent_runner_type": "codex_server",
            "agent_runner_config": {"model": "gpt-4o"},
        },
    )
    assert response.status_code == 202
    await drain(run_id)
    data = (await client.get(f"/api/runs/{run_id}")).json()
    assert data["agent_runner_type"] == "codex_server"
    assert data["agent_runner_config"] == {"model": "gpt-4o"}


async def test_codex_server_display_name(client: AsyncClient) -> None:
    """codex_server agent runner type returns a non-empty display name."""
    data = await _create_run_with_agent(client, "codex_server")
    assert data["agent_runner_type_display"] == "Codex Server"
    assert data["agent_icon"] == "codex"


# ---------------------------------------------------------------------------
# Model validation — injected codex_models_fn
# ---------------------------------------------------------------------------


@pytest.fixture
async def client_with_known_models() -> AsyncGenerator[AsyncClient, None]:
    """App client with a deterministic codex_models_fn that reports one supported model."""
    signal_transport = InMemorySignalTransport()
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    app.state.signal_transport = signal_transport
    app.state.codex_models_fn = lambda: ["gpt-5.3-codex"]
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


async def test_create_run_rejects_unsupported_codex_model(
    client_with_known_models: AsyncClient,
) -> None:
    """Creating a codex_server run with gpt-5.2-codex (deprecated) returns 422."""
    response = await client_with_known_models.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "proj-1",
            "branch": "main",
            "agent_runner_type": "codex_server",
            "agent_runner_config": {"model": "gpt-5.2-codex"},
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "gpt-5.2-codex" in detail
    assert "gpt-5.3-codex" in detail


async def test_create_run_rejects_unsupported_codex_cli_model(
    client_with_known_models: AsyncClient,
) -> None:
    """Creating a cli_subprocess (codex) run with an unsupported model returns 422."""
    response = await client_with_known_models.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "proj-1",
            "branch": "main",
            "agent_runner_type": "cli_subprocess",
            "agent_runner_config": {"command": "codex", "model": "gpt-5.2-codex"},
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "gpt-5.2-codex" in detail


async def test_create_run_accepts_supported_codex_model(
    client_with_known_models: AsyncClient,
) -> None:
    """Creating a codex_server run with the known-good model succeeds."""
    response = await client_with_known_models.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "proj-1",
            "branch": "main",
            "agent_runner_type": "codex_server",
            "agent_runner_config": {"model": "gpt-5.3-codex"},
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["agent_runner_config"]["model"] == "gpt-5.3-codex"


async def test_create_run_without_model_skips_validation(
    client_with_known_models: AsyncClient,
) -> None:
    """Creating a codex_server run without specifying a model skips model validation."""
    response = await client_with_known_models.post(
        "/api/runs",
        json={
            "routine_id": "simple-routine",
            "repo_name": "proj-1",
            "branch": "main",
            "agent_runner_type": "codex_server",
        },
    )
    assert response.status_code == 201
