"""Integration tests for task approval/rejection API endpoints."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.config.models import (
    RequirementConfig,
    RoutineConfig,
    StepConfig,
    TaskConfig,
)
from orchestrator.db.connection import init_db

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with in-memory database."""
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


async def _create_run_with_approval_task(client: AsyncClient) -> tuple[str, str]:
    """Create a run with a task requiring approval, return (run_id, task_id)."""
    routine = RoutineConfig(
        id="approval-test-routine",
        name="Approval Test Routine",
        description="Test routine for approval",
        steps=[
            StepConfig(
                id="S-01",
                title="Test Step",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Test Task with Approval",
                        task_context="Do something that requires approval",
                        requirements=[
                            RequirementConfig(
                                id="R1",
                                desc="Complete the task correctly",
                            )
                        ],
                    )
                ],
            )
        ],
    )

    resp = await client.post(
        "/api/runs",
        json={
            "project_id": "test-project",
            "routine_embedded": routine.model_dump(mode="json"),
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    run_id = data["id"]
    task_id = data["steps"][0]["tasks"][0]["id"]

    # Start the run
    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 200

    return run_id, task_id


@pytest.mark.asyncio
async def test_approve_endpoint_exists(client: AsyncClient) -> None:
    """Test that approve endpoint exists and accepts requests."""
    run_id, task_id = await _create_run_with_approval_task(client)

    # Try to call approve endpoint (will fail due to wrong status, but endpoint should exist)
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/approve",
        json={"comment": "Test approval"},
    )
    # Should return 409 (Conflict) not 404 (Not Found), showing endpoint exists
    assert resp.status_code == 409
    data = resp.json()
    # Should have error field with invalid transition error
    assert "error" in data
    assert data["error"] == "invalid_transition"


@pytest.mark.asyncio
async def test_reject_endpoint_exists(client: AsyncClient) -> None:
    """Test that reject endpoint exists and accepts requests."""
    run_id, task_id = await _create_run_with_approval_task(client)

    # Try to call reject endpoint (will fail due to wrong status, but endpoint should exist)
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/reject",
        json={"reason": "Test rejection"},
    )
    # Should return 409 (Conflict) not 404 (Not Found), showing endpoint exists
    assert resp.status_code == 409
    data = resp.json()
    # Should have error field with invalid transition error
    assert "error" in data
    assert data["error"] == "invalid_transition"


@pytest.mark.asyncio
async def test_approve_from_wrong_status_returns_error(client: AsyncClient) -> None:
    """Test that calling approve from non-PENDING_USER_ACTION status returns error."""
    run_id, task_id = await _create_run_with_approval_task(client)

    # Task is in PENDING status initially
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"

    # Try to approve - should return 409 Conflict
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/approve",
        json={"comment": "Premature approval"},
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["error"] == "invalid_transition"
    assert data["from_status"] == "pending"


@pytest.mark.asyncio
async def test_reject_from_wrong_status_returns_error(client: AsyncClient) -> None:
    """Test that calling reject from non-PENDING_USER_ACTION status returns error."""
    run_id, task_id = await _create_run_with_approval_task(client)

    # Task is in PENDING status initially
    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"

    # Try to reject - should return 409 Conflict
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/reject",
        json={"reason": "Cannot reject from pending"},
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["error"] == "invalid_transition"
    assert data["from_status"] == "pending"


@pytest.mark.asyncio
async def test_approve_optional_comment(client: AsyncClient) -> None:
    """Test that comment parameter is optional in approve request."""
    run_id, task_id = await _create_run_with_approval_task(client)

    # Should accept request without comment (will fail due to status, but validates request structure)
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/approve",
        json={},
    )
    assert resp.status_code == 409  # Will fail transition, but request was valid
    assert "error" in resp.json()


@pytest.mark.asyncio
async def test_reject_optional_reason(client: AsyncClient) -> None:
    """Test that reason parameter is optional in reject request."""
    run_id, task_id = await _create_run_with_approval_task(client)

    # Should accept request without reason (will fail due to status, but validates request structure)
    resp = await client.post(
        f"/api/runs/{run_id}/tasks/{task_id}/reject",
        json={},
    )
    assert resp.status_code == 409  # Will fail transition, but request was valid
    assert "error" in resp.json()
