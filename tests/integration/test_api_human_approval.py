"""Integration tests for human approval API endpoint."""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.runners.executor import AgentRunnerExecutor
from orchestrator.api.app import create_app
from orchestrator.config import AgentRunnerType, GateType, RoutineSource, TaskStatus
from orchestrator.db import init_db
from orchestrator.config.models import (
    GateConfig,
    RequirementConfig,
    RoutineConfig,
    StepConfig,
    TaskConfig,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


@pytest.fixture
async def app() -> AsyncGenerator[FastAPI, None]:
    """Create a test app with in-memory database."""
    application = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(application.state.engine)
    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with in-memory database."""
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


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
            "repo_name": "test-project",
            "branch": "main",
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
            "repo_name": "test-project",
            "branch": "main",
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
            "repo_name": "test-project",
            "branch": "main",
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
            "repo_name": "test-project",
            "branch": "main",
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
async def test_approve_future_step_rejected(
    client: AsyncClient,
    routine_with_human_gate: RoutineConfig,
) -> None:
    """Approving a non-current step should fail with 409."""
    create_response = await client.post(
        "/api/runs",
        json={
            "repo_name": "test-project",
            "branch": "main",
            "routine_embedded": routine_with_human_gate.model_dump(mode="json"),
        },
    )
    assert create_response.status_code == 201
    run_data = create_response.json()
    run_id = run_data["id"]
    future_step_id = run_data["steps"][1]["id"]  # S-02 while current is S-01

    response = await client.post(
        f"/api/runs/{run_id}/steps/{future_step_id}/approve",
        json={
            "approved_by": "user@example.com",
            "comment": "Trying to approve future step",
        },
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_approve_step_audit_trail(
    client: AsyncClient,
    routine_with_human_gate: RoutineConfig,
) -> None:
    """Test approval records complete audit trail."""
    create_response = await client.post(
        "/api/runs",
        json={
            "repo_name": "test-project",
            "branch": "main",
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


@pytest.mark.asyncio
async def test_executor_stops_at_human_approval_gate(
    app: FastAPI,
) -> None:
    """Executor's _find_next_task returns blocked when step has unsatisfied human_approval gate."""
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory

    executor = AgentRunnerExecutor(
        session_factory=session_factory,
        spawn_agents=False,
    )

    # Create a run with a human_approval gate on the first step
    routine = RoutineConfig(
        id="gate-test",
        name="Gate Test",
        description="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="Gated Step",
                gate=GateConfig(
                    type=GateType.HUMAN_APPROVAL,
                    approval_prompt="Please review",
                ),
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Gated Task",
                        task_context="Work that needs approval first",
                        requirements=[
                            RequirementConfig(id="R1", desc="Do something"),
                        ],
                    )
                ],
            ),
        ],
    )

    async with session_factory() as session:
        from orchestrator.db import EventStore
        from orchestrator.db import RunRepository
        from orchestrator.state.factory import create_run_from_routine
        from orchestrator.workflow import LocalAutoVerifyRunner
        from orchestrator.workflow import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=routine,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.EMBEDDED,
        )
        run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run = await service.create_run(run)
        await session.commit()

        # Start the run (just changes status, no agent spawned because spawn_agents=False)
        run = await service.start_run(run.id)
        await session.commit()

        # Verify tasks are PENDING
        assert run.steps[0].tasks[0].status == TaskStatus.PENDING

        # The executor should detect the gate is unsatisfied
        from orchestrator.runners.executor import NoTaskReason

        task, reason = executor._find_next_task(run)
        assert task is None
        assert reason == NoTaskReason.BLOCKED_BY_GATE

        # Verify the gate helper directly
        assert executor._is_step_gate_satisfied(run, run.steps[0]) is False


@pytest.mark.asyncio
async def test_executor_proceeds_after_gate_approved(
    app: FastAPI,
) -> None:
    """After human_approval gate is satisfied, _find_next_task returns the task."""
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory

    executor = AgentRunnerExecutor(
        session_factory=session_factory,
        spawn_agents=False,
    )

    routine = RoutineConfig(
        id="gate-test-2",
        name="Gate Test 2",
        description="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="Gated Step",
                gate=GateConfig(
                    type=GateType.HUMAN_APPROVAL,
                    approval_prompt="Please review",
                ),
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Gated Task",
                        task_context="Work that needs approval first",
                        requirements=[
                            RequirementConfig(id="R1", desc="Do something"),
                        ],
                    )
                ],
            ),
        ],
    )

    async with session_factory() as session:
        from orchestrator.db import EventStore
        from orchestrator.db import RunRepository
        from orchestrator.state.factory import create_run_from_routine
        from orchestrator.state.models import HumanApproval
        from orchestrator.workflow import LocalAutoVerifyRunner
        from orchestrator.workflow import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=routine,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.EMBEDDED,
        )
        run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run = await service.create_run(run)
        await session.commit()

        run = await service.start_run(run.id)
        await session.commit()

        # Before approval: blocked
        from orchestrator.runners.executor import NoTaskReason

        task, reason = executor._find_next_task(run)
        assert reason == NoTaskReason.BLOCKED_BY_GATE
        assert task is None

        # Approve the step
        run.steps[0].human_approval = HumanApproval(
            approved_by="reviewer@example.com",
            approved_at=datetime.now(timezone.utc),
            comment="Approved",
        )

        # After approval: not blocked, task returned
        task, reason = executor._find_next_task(run)
        assert reason is None
        assert task is not None
        assert task.config_id == "T-01"


@pytest.mark.asyncio
async def test_approve_step_respawns_agent_for_active_run(
    app: FastAPI,
    client: AsyncClient,
) -> None:
    """Approving a step on an ACTIVE run should attempt to re-spawn the agent."""
    routine = RoutineConfig(
        id="respawn-test",
        name="Respawn Test",
        description="Test agent re-spawn after approval",
        steps=[
            StepConfig(
                id="S-01",
                title="Gated Step",
                gate=GateConfig(
                    type=GateType.HUMAN_APPROVAL,
                    approval_prompt="Review before proceeding",
                ),
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Gated Task",
                        task_context="Do work",
                        requirements=[
                            RequirementConfig(id="R1", desc="Complete work"),
                        ],
                    )
                ],
            ),
        ],
    )

    # Create run
    create_resp = await client.post(
        "/api/runs",
        json={
            "repo_name": "test-project",
            "branch": "main",
            "routine_embedded": routine.model_dump(mode="json"),
            "agent_type": "cli_subprocess",
        },
    )
    assert create_resp.status_code == 201
    run_data = create_resp.json()
    run_id = run_data["id"]
    step_id = run_data["steps"][0]["id"]

    # Start the run (spawn_agents is False for :memory: DB, so no agent actually runs)
    start_resp = await client.post(f"/api/runs/{run_id}/start")
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "active"

    # All tasks should still be PENDING (agent didn't run because spawn_agents=False)
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    tasks = run_resp.json()["steps"][0]["tasks"]
    assert all(t["status"] == "pending" for t in tasks)

    # Approve the step - this should succeed and attempt to re-spawn
    # (spawn_for_run will return False because spawn_agents=False in test,
    # but the endpoint logic is exercised)
    approve_resp = await client.post(
        f"/api/runs/{run_id}/steps/{step_id}/approve",
        json={
            "approved_by": "reviewer@example.com",
            "comment": "Approved",
        },
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["human_approval"]["approved_by"] == "reviewer@example.com"

    # Verify the approval was persisted and run is still ACTIVE
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    assert run_resp.json()["status"] == "active"
    # Verify step shows as approved in the response
    step_data = run_resp.json()["steps"][0]
    assert step_data["approval_status"] == "approved"


@pytest.mark.asyncio
async def test_step_without_gate_not_blocked(
    app: FastAPI,
) -> None:
    """Steps without a human_approval gate should not be blocked."""
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory

    executor = AgentRunnerExecutor(
        session_factory=session_factory,
        spawn_agents=False,
    )

    routine = RoutineConfig(
        id="no-gate-test",
        name="No Gate Test",
        description="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="Normal Step",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Normal Task",
                        task_context="Just do work",
                        requirements=[
                            RequirementConfig(id="R1", desc="Do something"),
                        ],
                    )
                ],
            ),
        ],
    )

    async with session_factory() as session:
        from orchestrator.db import EventStore
        from orchestrator.db import RunRepository
        from orchestrator.state.factory import create_run_from_routine
        from orchestrator.workflow import LocalAutoVerifyRunner
        from orchestrator.workflow import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        repo = RunRepository(session)
        event_store = EventStore(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=routine,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.EMBEDDED,
        )
        run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run = await service.create_run(run)
        await session.commit()

        run = await service.start_run(run.id)
        await session.commit()

        # No gate - should not be blocked
        task, reason = executor._find_next_task(run)
        assert reason is None
        assert task is not None
        assert task.config_id == "T-01"


@pytest.mark.asyncio
async def test_executor_does_not_start_future_step_when_current_waiting_for_user_action(
    app: FastAPI,
) -> None:
    """Executor must not select future-step tasks while current step is blocked on clarification."""
    routine = RoutineConfig(
        id="clarification-block-test",
        name="Clarification Block Test",
        description="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="Current Step",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Current Task",
                        task_context="Needs clarification",
                        requirements=[RequirementConfig(id="R1", desc="Do something")],
                    )
                ],
            ),
            StepConfig(
                id="S-02",
                title="Future Step",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Future Task",
                        task_context="Should not start yet",
                        requirements=[RequirementConfig(id="R1", desc="Do next thing")],
                    )
                ],
            ),
        ],
    )

    from orchestrator.state.factory import create_run_from_routine

    run = create_run_from_routine(
        routine=routine,
        repo_name="test-project",
        source_branch="main",
        routine_source=RoutineSource.EMBEDDED,
    )
    run.current_step_index = 0
    run.steps[0].tasks[0].status = TaskStatus.PENDING_USER_ACTION
    run.steps[1].tasks[0].status = TaskStatus.PENDING

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    executor = AgentRunnerExecutor(session_factory=session_factory, spawn_agents=False)
    from orchestrator.runners.executor import NoTaskReason

    task, reason = executor._find_next_task(run)

    assert task is None
    assert reason == NoTaskReason.PENDING_USER_ACTION
