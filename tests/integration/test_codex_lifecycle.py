"""Integration tests for Codex agent lifecycle control paths.

Covers the full create→start→pause→resume→cancel lifecycle for the
``codex_server`` agent runner type, and validates the deterministic recovery
rule (healthy vs stale session) via the REST API.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport

from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    signal_transport = InMemorySignalTransport()
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
        spawn_agents=False,
    )
    app.state.signal_transport = signal_transport
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_codex_run(
    client: AsyncClient,
    agent_runner_type: str = "codex_server",
    agent_runner_config: dict[str, Any] | None = None,
    repo_name: str = "proj-codex",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "routine_id": "simple-routine",
        "repo_name": repo_name,
        "branch": "main",
        "agent_runner_type": agent_runner_type,
    }
    if agent_runner_config:
        body["agent_runner_config"] = agent_runner_config
    resp = await client.post("/api/runs", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _start(client: AsyncClient, run_id: str, drain: DrainFn) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202, resp.text
    await drain(run_id)
    return (await client.get(f"/api/runs/{run_id}")).json()


async def _pause(client: AsyncClient, run_id: str, drain: DrainFn) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 202, resp.text
    await drain(run_id)
    return (await client.get(f"/api/runs/{run_id}")).json()


async def _resume(
    client: AsyncClient, run_id: str, drain: DrainFn, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/resume", json=body)
    assert resp.status_code == 202, resp.text
    await drain(run_id)
    return (await client.get(f"/api/runs/{run_id}")).json()


async def _cancel(client: AsyncClient, run_id: str, drain: DrainFn) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 202, resp.text
    await drain(run_id)
    return (await client.get(f"/api/runs/{run_id}")).json()


# ===========================================================================
# codex_server lifecycle
# ===========================================================================


async def test_codex_server_lifecycle_create(client: AsyncClient) -> None:
    """codex_server run is created in DRAFT status."""
    data = await _create_codex_run(client, "codex_server")
    assert data["agent_runner_type"] == "codex_server"
    assert data["status"] == "draft"


async def test_codex_server_lifecycle_start(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """codex_server run transitions DRAFT → ACTIVE on start."""
    client, drain = client_and_drain
    data = await _create_codex_run(client, "codex_server", repo_name="proj-cs-start")
    run_id = data["id"]
    started = await _start(client, run_id, drain)
    assert started["status"] == "active"
    assert started["agent_runner_type"] == "codex_server"


async def test_codex_server_lifecycle_pause(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """codex_server run transitions ACTIVE → PAUSED on pause."""
    client, drain = client_and_drain
    data = await _create_codex_run(client, "codex_server", repo_name="proj-cs-pause")
    run_id = data["id"]
    await _start(client, run_id, drain)
    paused = await _pause(client, run_id, drain)
    assert paused["status"] == "paused"


async def test_codex_server_lifecycle_resume(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """codex_server run transitions PAUSED → ACTIVE on resume."""
    client, drain = client_and_drain
    data = await _create_codex_run(client, "codex_server", repo_name="proj-cs-resume")
    run_id = data["id"]
    await _start(client, run_id, drain)
    await _pause(client, run_id, drain)
    resumed = await _resume(client, run_id, drain)
    assert resumed["status"] == "active"


async def test_codex_server_lifecycle_cancel(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """codex_server run transitions ACTIVE → FAILED on cancel."""
    client, drain = client_and_drain
    data = await _create_codex_run(client, "codex_server", repo_name="proj-cs-cancel")
    run_id = data["id"]
    await _start(client, run_id, drain)
    cancelled = await _cancel(client, run_id, drain)
    assert cancelled["status"] == "failed"


async def test_codex_server_lifecycle_resume_preserves_agent_runner_config(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Resuming codex_server preserves agent_runner_config when none is supplied."""
    client, drain = client_and_drain
    cfg = {"restrictions": "none", "model": "o3"}
    data = await _create_codex_run(
        client, "codex_server", agent_runner_config=cfg, repo_name="proj-cs-cfg"
    )
    run_id = data["id"]
    await _start(client, run_id, drain)
    await _pause(client, run_id, drain)
    resumed = await _resume(client, run_id, drain)
    assert resumed["agent_runner_config"]["restrictions"] == "none"
    assert resumed["agent_runner_config"]["model"] == "o3"


# ===========================================================================
# Recovery rule — local agent
# ===========================================================================


async def test_codex_lifecycle_recovery_local_no_pid_start_is_clean(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """codex_server run with no PID stored starts cleanly (no stale state)."""
    client, drain = client_and_drain
    data = await _create_codex_run(
        client,
        "codex_server",
        agent_runner_config={"callback_channel": "rest"},
        repo_name="proj-nopid",
    )
    run_id = data["id"]
    await _start(client, run_id, drain)
    resp = await client.get(f"/api/runs/{run_id}")
    data2 = resp.json()
    assert data2["status"] == "active"
    assert "pid" not in data2.get("agent_runner_config", {})
