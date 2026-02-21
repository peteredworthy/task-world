"""Integration tests for Codex agent lifecycle control paths.

Covers the full create→start→pause→resume→cancel lifecycle for both
``codex_server`` and ``codex_server_remote`` agent types, and validates the
deterministic recovery rule (healthy vs stale session) via the REST API.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
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


def _now_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ago_ts(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


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
    cfg = {"endpoint": "http://localhost:9000", "model": "o3"}
    data = await _create_codex_run(
        client, "codex_server", agent_config=cfg, repo_name="proj-cs-cfg"
    )
    run_id = data["id"]
    await _start(client, run_id)
    await _pause(client, run_id)
    resumed = await _resume(client, run_id)
    assert resumed["agent_config"]["endpoint"] == "http://localhost:9000"
    assert resumed["agent_config"]["model"] == "o3"


async def test_codex_server_lifecycle_agent_change_on_resume(
    client: AsyncClient,
) -> None:
    """Resuming a paused codex_server run can switch to codex_server_remote."""
    data = await _create_codex_run(client, "codex_server", repo_name="proj-cs-switch")
    run_id = data["id"]
    await _start(client, run_id)
    await _pause(client, run_id)
    resumed = await _resume(
        client,
        run_id,
        {
            "agent_type": "codex_server_remote",
            "agent_config": {
                "base_url": "https://codex.example.com",
                "session_id": "sess-new",
            },
        },
    )
    assert resumed["agent_type"] == "codex_server_remote"
    assert resumed["status"] == "active"


# ===========================================================================
# codex_server_remote lifecycle
# ===========================================================================


async def test_codex_server_remote_lifecycle_create(client: AsyncClient) -> None:
    """codex_server_remote run is created in DRAFT status."""
    data = await _create_codex_run(client, "codex_server_remote")
    assert data["agent_type"] == "codex_server_remote"
    assert data["status"] == "draft"


async def test_codex_server_remote_lifecycle_start(client: AsyncClient) -> None:
    """codex_server_remote run transitions DRAFT → ACTIVE on start."""
    data = await _create_codex_run(client, "codex_server_remote", repo_name="proj-csr-start")
    run_id = data["id"]
    started = await _start(client, run_id)
    assert started["status"] == "active"
    assert started["agent_type"] == "codex_server_remote"


async def test_codex_server_remote_lifecycle_pause(client: AsyncClient) -> None:
    """codex_server_remote run transitions ACTIVE → PAUSED on pause."""
    data = await _create_codex_run(client, "codex_server_remote", repo_name="proj-csr-pause")
    run_id = data["id"]
    await _start(client, run_id)
    paused = await _pause(client, run_id)
    assert paused["status"] == "paused"


async def test_codex_server_remote_lifecycle_resume(client: AsyncClient) -> None:
    """codex_server_remote run transitions PAUSED → ACTIVE on resume."""
    data = await _create_codex_run(client, "codex_server_remote", repo_name="proj-csr-resume")
    run_id = data["id"]
    await _start(client, run_id)
    await _pause(client, run_id)
    resumed = await _resume(client, run_id)
    assert resumed["status"] == "active"


async def test_codex_server_remote_lifecycle_cancel(client: AsyncClient) -> None:
    """codex_server_remote run transitions ACTIVE → FAILED on cancel."""
    data = await _create_codex_run(client, "codex_server_remote", repo_name="proj-csr-cancel")
    run_id = data["id"]
    await _start(client, run_id)
    cancelled = await _cancel(client, run_id)
    assert cancelled["status"] == "failed"


async def test_codex_server_remote_lifecycle_resume_with_new_session(
    client: AsyncClient,
) -> None:
    """Resuming with a new session_id replaces the stale one in agent_config."""
    old_ts = _ago_ts(200)  # well beyond default 120-min timeout
    data = await _create_codex_run(
        client,
        "codex_server_remote",
        agent_config={"session_id": "sess-old", "session_created_at": old_ts},
        repo_name="proj-csr-newses",
    )
    run_id = data["id"]
    await _start(client, run_id)
    await _pause(client, run_id)

    new_cfg = {
        "session_id": "sess-new",
        "session_created_at": _now_ts(),
        "base_url": "https://codex.example.com",
    }
    resumed = await _resume(client, run_id, {"agent_config": new_cfg})
    assert resumed["status"] == "active"
    assert resumed["agent_config"]["session_id"] == "sess-new"


# ===========================================================================
# Recovery rule — healthy vs stale session via agent_config inspection
# ===========================================================================


async def test_codex_lifecycle_recovery_healthy_session_preserved(
    client: AsyncClient,
) -> None:
    """A healthy (recent) session_id is preserved through pause/resume."""
    fresh_ts = _now_ts()
    data = await _create_codex_run(
        client,
        "codex_server_remote",
        agent_config={
            "session_id": "sess-healthy",
            "session_created_at": fresh_ts,
            "base_url": "https://codex.example.com",
        },
        repo_name="proj-healthy",
    )
    run_id = data["id"]
    await _start(client, run_id)
    await _pause(client, run_id)
    resumed = await _resume(client, run_id)
    # The session_id should still be in agent_config (healthy session = resume it)
    assert resumed["agent_config"].get("session_id") == "sess-healthy"


async def test_codex_lifecycle_recovery_stale_session_replaced_on_resume(
    client: AsyncClient,
) -> None:
    """A stale session_id can be replaced by providing a new agent_config on resume."""
    old_ts = _ago_ts(200)
    data = await _create_codex_run(
        client,
        "codex_server_remote",
        agent_config={"session_id": "sess-stale", "session_created_at": old_ts},
        repo_name="proj-stale",
    )
    run_id = data["id"]
    await _start(client, run_id)
    await _pause(client, run_id)

    # Caller explicitly replaces stale session with a fresh one.
    new_ts = _now_ts()
    resumed = await _resume(
        client,
        run_id,
        {
            "agent_config": {
                "session_id": "sess-fresh",
                "session_created_at": new_ts,
            }
        },
    )
    assert resumed["status"] == "active"
    assert resumed["agent_config"]["session_id"] == "sess-fresh"


async def test_codex_lifecycle_recovery_no_session_id_start_is_clean(
    client: AsyncClient,
) -> None:
    """When no session_id is stored the run starts with a clean config."""
    data = await _create_codex_run(
        client,
        "codex_server_remote",
        agent_config={"base_url": "https://codex.example.com"},
        repo_name="proj-nosess",
    )
    run_id = data["id"]
    await _start(client, run_id)
    # No session_id means no stale session to worry about — run is active.
    resp = await client.get(f"/api/runs/{run_id}")
    data2 = resp.json()
    assert data2["status"] == "active"
    assert "session_id" not in data2.get("agent_config", {})


async def test_codex_lifecycle_recovery_local_no_pid_start_is_clean(
    client: AsyncClient,
) -> None:
    """codex_server run with no PID stored starts cleanly (no stale state)."""
    data = await _create_codex_run(
        client,
        "codex_server",
        agent_config={"endpoint": "http://localhost:9000"},
        repo_name="proj-nopid",
    )
    run_id = data["id"]
    await _start(client, run_id)
    resp = await client.get(f"/api/runs/{run_id}")
    data2 = resp.json()
    assert data2["status"] == "active"
    assert "pid" not in data2.get("agent_config", {})
