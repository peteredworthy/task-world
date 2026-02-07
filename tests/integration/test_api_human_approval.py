"""Integration tests for human approval API endpoint."""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import GateType, RoutineSource
from orchestrator.db.connection import init_db
from orchestrator.config.models import (
    GateConfig,
    RequirementConfig,
    RoutineConfig,
    StepConfig,
    TaskConfig,
)

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


@pytest.fixture
def routine_with_human_gate() -> RoutineConfig:
    """Routine with a human approval gate."""
    return RoutineConfig(
        id="test-human-gate",
        name="Test Human Gate",
        description="Test routine with human approval gate",
        steps=[
            StepConfig(
                id="S-01",
                title="First Step",
                gate=GateConfig(
                    type=GateType.HUMAN_APPROVAL,
                    approval_prompt="Please review the initial step results",
                    require_comment=True,
                ),
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Initial Task",
                        task_context="Do some initial work",
                        requirements=[
                            RequirementConfig(
                                id="R1",
                                desc="Complete initial work",
                            )
                        ],
                    )
                ],
            ),
            StepConfig(
                id="S-02",
                title="Second Step",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Follow-up Task",
                        task_context="Do follow-up work",
                        requirements=[
                            RequirementConfig(
                                id="R1",
                                desc="Complete follow-up work",
                            )
                        ],
                    )
                ],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_approve_step_endpoint(
    client: AsyncClient,
    routine_with_human_gate: RoutineConfig,
) -> None:
    """Test POST /api/runs/{run_id}/steps/{step_id}/approve endpoint."""
    # Create a run via API with embedded routine
    create_response = await client.post(
        "/api/runs",
        json={
            "project_id": "test-project",
            "routine_embedded": routine_with_human_gate.model_dump(mode="json"),
        },
    )
    assert create_response.status_code == 201
    run_data = create_response.json()
    run_id = run_data["id"]

    # Get step ID
    step_id = run_data["steps"][0]["id"]

    # Submit approval
    response = await client.post(
        f"/api/runs/{run_id}/steps/{step_id}/approve",
        json={
            "approved_by": "user@example.com",
            "comment": "Everything looks good, proceed",
        },
    )

    assert response.status_code == 200
    data = response.json()

    # Verify response
    assert data["id"] == step_id
    assert data["human_approval"] is not None
    assert data["human_approval"]["approved_by"] == "user@example.com"
    assert data["human_approval"]["comment"] == "Everything looks good, proceed"
    assert "approved_at" in data["human_approval"]

    # Verify persistence via GET
    run_response = await client.get(f"/api/runs/{run_id}")
    assert run_response.status_code == 200
    _ = run_response.json()  # Verify run is still accessible
    # Note: Currently StepSummary doesn't include human_approval field
    # We verified it works via the approval endpoint response


@pytest.mark.asyncio
async def test_approve_step_without_comment(
    client: AsyncClient,
    routine_with_human_gate: RoutineConfig,
) -> None:
    """Test approval without comment works (gate evaluation happens elsewhere)."""
    create_response = await client.post(
        "/api/runs",
        json={
            "project_id": "test-project",
            "routine_embedded": routine_with_human_gate.model_dump(mode="json"),
        },
    )
    assert create_response.status_code == 201
    run_data = create_response.json()
    run_id = run_data["id"]
    step_id = run_data["steps"][0]["id"]

    # Submit approval without comment
    response = await client.post(
        f"/api/runs/{run_id}/steps/{step_id}/approve",
        json={
            "approved_by": "user@example.com",
        },
    )

    # Endpoint succeeds (it just records approval)
    # Gate evaluation happens elsewhere
    assert response.status_code == 200
    data = response.json()
    assert data["human_approval"]["approved_by"] == "user@example.com"
    assert data["human_approval"]["comment"] is None


@pytest.mark.asyncio
async def test_approve_nonexistent_step(
    client: AsyncClient,
    routine_with_human_gate: RoutineConfig,
) -> None:
    """Test approval fails for nonexistent step."""
    create_response = await client.post(
        "/api/runs",
        json={
            "project_id": "test-project",
            "routine_embedded": routine_with_human_gate.model_dump(mode="json"),
        },
    )
    assert create_response.status_code == 201
    run_data = create_response.json()
    run_id = run_data["id"]

    # Try to approve nonexistent step
    response = await client.post(
        f"/api/runs/{run_id}/steps/nonexistent-step/approve",
        json={
            "approved_by": "user@example.com",
            "comment": "Looks good",
        },
    )

    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "step_not_found"


@pytest.mark.asyncio
async def test_approve_nonexistent_run(
    client: AsyncClient,
) -> None:
    """Test approval fails for nonexistent run."""
    response = await client.post(
        "/api/runs/nonexistent-run/steps/some-step/approve",
        json={
            "approved_by": "user@example.com",
            "comment": "Looks good",
        },
    )

    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "run_not_found"


@pytest.mark.asyncio
async def test_approve_step_multiple_times(
    client: AsyncClient,
    routine_with_human_gate: RoutineConfig,
) -> None:
    """Test step can be approved multiple times (last approval wins)."""
    create_response = await client.post(
        "/api/runs",
        json={
            "project_id": "test-project",
            "routine_embedded": routine_with_human_gate.model_dump(mode="json"),
        },
    )
    assert create_response.status_code == 201
    run_data = create_response.json()
    run_id = run_data["id"]
    step_id = run_data["steps"][0]["id"]

    # First approval
    response1 = await client.post(
        f"/api/runs/{run_id}/steps/{step_id}/approve",
        json={
            "approved_by": "user1@example.com",
            "comment": "First approval",
        },
    )
    assert response1.status_code == 200
    time1 = response1.json()["human_approval"]["approved_at"]

    # Second approval (override)
    response2 = await client.post(
        f"/api/runs/{run_id}/steps/{step_id}/approve",
        json={
            "approved_by": "user2@example.com",
            "comment": "Second approval overrides first",
        },
    )
    assert response2.status_code == 200
    data2 = response2.json()

    # Verify second approval is recorded
    assert data2["human_approval"]["approved_by"] == "user2@example.com"
    assert data2["human_approval"]["comment"] == "Second approval overrides first"
    time2 = data2["human_approval"]["approved_at"]
    assert time2 >= time1


@pytest.mark.asyncio
async def test_approve_step_audit_trail(
    client: AsyncClient,
    routine_with_human_gate: RoutineConfig,
) -> None:
    """Test approval records complete audit trail."""
    create_response = await client.post(
        "/api/runs",
        json={
            "project_id": "test-project",
            "routine_embedded": routine_with_human_gate.model_dump(mode="json"),
        },
    )
    assert create_response.status_code == 201
    run_data = create_response.json()
    run_id = run_data["id"]
    step_id = run_data["steps"][0]["id"]

    before = datetime.now(timezone.utc)

    # Submit approval
    response = await client.post(
        f"/api/runs/{run_id}/steps/{step_id}/approve",
        json={
            "approved_by": "auditor@example.com",
            "comment": "Audit trail test",
        },
    )

    after = datetime.now(timezone.utc)

    assert response.status_code == 200
    data = response.json()

    # Verify audit fields
    approval = data["human_approval"]
    assert approval["approved_by"] == "auditor@example.com"
    assert approval["comment"] == "Audit trail test"

    # Verify timestamp is reasonable
    approved_at = datetime.fromisoformat(approval["approved_at"].replace("Z", "+00:00"))
    assert before <= approved_at <= after
