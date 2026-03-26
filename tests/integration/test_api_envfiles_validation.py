"""Integration tests for envfiles API input validation."""

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


# --- revert_to validation ---


async def test_revert_invalid_revert_to_returns_422(client: AsyncClient) -> None:
    """Invalid revert_to value should return 422."""
    resp = await client.post(
        "/api/runs/some-run/env-files/revert",
        json={
            "revert_to": "invalid_point",
            "task_id": "T-01",
            "worktree_path": "/tmp/wt",
        },
    )
    assert resp.status_code == 422


async def test_revert_valid_revert_to_values(client: AsyncClient) -> None:
    """Valid revert_to values should pass schema validation (may fail later for other reasons)."""
    for revert_to in ["task_start", "run_start"]:
        resp = await client.post(
            "/api/runs/nonexistent/env-files/revert",
            json={
                "revert_to": revert_to,
                "task_id": "T-01",
                "worktree_path": "/tmp/wt",
            },
        )
        # Should not be a 422 for invalid revert_to; may be 404 for missing run
        assert resp.status_code != 422, f"revert_to={revert_to} wrongly rejected"


# --- snapshot_id traversal protection ---


async def test_copy_back_traversal_snapshot_id_returns_422(client: AsyncClient) -> None:
    """Snapshot ID with path traversal characters should return 422."""
    resp = await client.post(
        "/api/runs/some-run/env-files/copy-back",
        json={
            "target_dir": "/tmp/target",
            "snapshot_id": "../../../etc/passwd",
        },
    )
    assert resp.status_code == 422


async def test_copy_back_valid_snapshot_id(client: AsyncClient) -> None:
    """Valid snapshot_id formats should pass schema validation."""
    for snapshot_id in ["run_end", "run_start", "snap-123", "abc_DEF_012"]:
        resp = await client.post(
            "/api/runs/nonexistent/env-files/copy-back",
            json={
                "target_dir": "/tmp/target",
                "snapshot_id": snapshot_id,
            },
        )
        # Should not be 422 for bad snapshot_id
        assert resp.status_code != 422, f"snapshot_id={snapshot_id} wrongly rejected"
