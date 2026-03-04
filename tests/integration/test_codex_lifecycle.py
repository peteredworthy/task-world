"""Integration tests for Codex agent lifecycle control paths.

Covers the full create→start→pause→resume→cancel lifecycle for the
``codex_server`` agent type, and validates the deterministic recovery
rule (healthy vs stale session) via the REST API.
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
        spawn_agents=False,
    )
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_codex_run(
    client: AsyncClient,
    agent_type: str = "codex_server",
    agent_config: dict[str, Any] | None = None,
    repo_name: str = "proj-codex",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "routine_id": "simple-routine",
        "repo_name": repo_name,
        "branch": "main",
        "agent_type": agent_type,
    }
    if agent_config:
        body["agent_config"] = agent_config
    resp = await client.post("/api/runs", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _start(client: AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _pause(client: AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/pause")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _resume(
    client: AsyncClient, run_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/resume", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _cancel(client: AsyncClient, run_id: str) -> dict[str, Any]:
    resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 200, resp.text
    return resp.json()


# ===========================================================================
# codex_server lifecycle
# ===========================================================================


async def test_codex_server_lifecycle_create(client: AsyncClient) -> None:
    """codex_server run is created in DRAFT status."""
    data = await _create_codex_run(client, "codex_server")
    assert data["agent_type"] == "codex_server"
    assert data["status"] == "draft"


async def test_codex_server_lifecycle_start(client: AsyncClient) -> None:
    """codex_server run transitions DRAFT → ACTIVE on start."""
    data = await _create_codex_run(client, "codex_server", repo_name="proj-cs-start")
    run_id = data["id"]
    started = await _start(client, run_id)
    assert started["status"] == "active"
    assert started["agent_type"] == "codex_server"


async def test_codex_server_lifecycle_pause(client: AsyncClient) -> None:
    """codex_server run transitions ACTIVE → PAUSED on pause."""
    data = await _create_codex_run(client, "codex_server", repo_name="proj-cs-pause")
    run_id = data["id"]
    await _start(client, run_id)
    paused = await _pause(client, run_id)
    assert paused["status"] == "paused"


async def test_codex_server_lifecycle_resume(client: AsyncClient) -> None:
    """codex_server run transitions PAUSED → ACTIVE on resume."""
    data = await _create_codex_run(client, "codex_server", repo_name="proj-cs-resume")
    run_id = data["id"]
    await _start(client, run_id)
    await _pause(client, run_id)
    resumed = await _resume(client, run_id)
    assert resumed["status"] == "active"


async def test_codex_server_lifecycle_cancel(client: AsyncClient) -> None:
    """codex_server run transitions ACTIVE → FAILED on cancel."""
    data = await _create_codex_run(client, "codex_server", repo_name="proj-cs-cancel")
    run_id = data["id"]
    await _start(client, run_id)
    cancelled = await _cancel(client, run_id)
    assert cancelled["status"] == "failed"


async def test_codex_server_lifecycle_resume_preserves_agent_config(
    client: AsyncClient,
) -> None:
    """Resuming codex_server preserves agent_config when none is supplied."""
    cfg = {"restrictions": "none", "model": "o3"}
    data = await _create_codex_run(
        client, "codex_server", agent_config=cfg, repo_name="proj-cs-cfg"
    )
    run_id = data["id"]
    await _start(client, run_id)
    await _pause(client, run_id)
    resumed = await _resume(client, run_id)
    assert resumed["agent_config"]["restrictions"] == "none"
    assert resumed["agent_config"]["model"] == "o3"


# ===========================================================================
# Recovery rule — local agent
# ===========================================================================


async def test_codex_lifecycle_recovery_local_no_pid_start_is_clean(
    client: AsyncClient,
) -> None:
    """codex_server run with no PID stored starts cleanly (no stale state)."""
    data = await _create_codex_run(
        client,
        "codex_server",
        agent_config={"callback_channel": "rest"},
        repo_name="proj-nopid",
    )
    run_id = data["id"]
    await _start(client, run_id)
    resp = await client.get(f"/api/runs/{run_id}")
    data2 = resp.json()
    assert data2["status"] == "active"
    assert "pid" not in data2.get("agent_config", {})
