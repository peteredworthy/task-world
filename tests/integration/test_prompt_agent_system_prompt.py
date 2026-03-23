"""Integration tests for agent system prompt injection in the prompt endpoint.

Verifies that GET /api/runs/{run_id}/tasks/{task_id}/prompt:
- Prepends the resolved agent's system_prompt when an agent is configured
- Returns the task prompt unchanged when no agent fields are set (backward compat)
- Applies cascading resolution: task -> step -> routine -> system default
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.api.app import create_app
from orchestrator.config.enums import RoutineSource
from orchestrator.db.connection import init_db
from orchestrator.workflow.signals import InMemorySignalTransport
from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

_SEPARATOR = "\n\n---\n\n"


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    transport_obj = InMemorySignalTransport()
    app.state.signal_transport = transport_obj
    drain = make_drain_fn(app, transport_obj)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, drain
    await app.state.engine.dispose()


@pytest.fixture
async def client(client_and_drain: tuple[AsyncClient, DrainFn]) -> AsyncClient:
    return client_and_drain[0]


async def _create_agent(client: AsyncClient, name: str, system_prompt: str) -> str:
    """Create an agent config and return its id."""
    resp = await client.post(
        "/api/agents",
        json={"name": name, "system_prompt": system_prompt},
    )
    assert resp.status_code == 201, f"Failed to create agent: {resp.text}"
    return resp.json()["id"]


async def _setup_run_with_embedded_routine(
    client: AsyncClient,
    routine: dict[str, Any],
) -> tuple[str, str]:
    """Create run with embedded routine, start it, start first task. Returns (run_id, task_id)."""
    resp = await client.post(
        "/api/runs",
        json={"repo_name": "test-project", "branch": "main", "routine_embedded": routine},
    )
    assert resp.status_code == 201, f"Expected 201: {resp.text}"
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    await client.post(f"/api/runs/{run_id}/start")
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    return run_id, task_id


# ---------------------------------------------------------------------------
# Backward compatibility: no agent fields
# ---------------------------------------------------------------------------


async def test_prompt_unchanged_when_no_agent_fields(client: AsyncClient) -> None:
    """When the routine has no agent fields, the prompt is returned as-is."""
    routine: dict[str, Any] = {
        "id": "no-agent-routine",
        "name": "No Agent Routine",
        "steps": [
            {
                "id": "S-01",
                "title": "Step One",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task One",
                        "task_context": "Do something",
                        "requirements": [{"id": "R1", "desc": "It works"}],
                    }
                ],
            }
        ],
    }
    run_id, task_id = await _setup_run_with_embedded_routine(client, routine)

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert data["phase"] == "building"
    # System prompt should not contain the separator
    assert _SEPARATOR not in data["system"]


async def test_prompt_unchanged_via_file_based_routine(client: AsyncClient) -> None:
    """File-based routine without agent fields also returns prompt unchanged."""
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    await client.post(f"/api/runs/{run_id}/start")
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert _SEPARATOR not in data["system"]


# ---------------------------------------------------------------------------
# Agent system prompt prepended via routine-level agent
# ---------------------------------------------------------------------------


async def test_prompt_includes_agent_system_prompt_via_routine_level(
    client: AsyncClient,
) -> None:
    """Routine-level builder_agent system_prompt is prepended to the builder prompt."""
    agent_system = "You are a specialist builder agent."
    await _create_agent(client, "SpecialistBuilder", agent_system)

    routine: dict[str, Any] = {
        "id": "routine-agent-routine",
        "name": "Routine Agent Routine",
        "builder_agent": "SpecialistBuilder",
        "steps": [
            {
                "id": "S-01",
                "title": "Step One",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task One",
                        "task_context": "Build something",
                        "requirements": [{"id": "R1", "desc": "It works"}],
                    }
                ],
            }
        ],
    }
    run_id, task_id = await _setup_run_with_embedded_routine(client, routine)

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert data["phase"] == "building"
    system = data["system"]
    assert system.startswith(agent_system), "Agent system prompt should be at the start"
    assert _SEPARATOR in system, "Separator should be present"
    task_prompt_part = system.split(_SEPARATOR, 1)[1]
    assert len(task_prompt_part) > 0, "Task prompt part should not be empty"


# ---------------------------------------------------------------------------
# Cascading: task-level overrides step and routine
# ---------------------------------------------------------------------------


async def test_task_level_agent_overrides_routine_level(client: AsyncClient) -> None:
    """Task-level builder_agent takes priority over routine-level."""
    await _create_agent(client, "RoutineBuilderX", "ROUTINE prompt")
    await _create_agent(client, "TaskBuilderX", "TASK prompt")

    routine: dict[str, Any] = {
        "id": "cascade-task-routine",
        "name": "Cascade Task Routine",
        "builder_agent": "RoutineBuilderX",
        "steps": [
            {
                "id": "S-01",
                "title": "Step One",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task One",
                        "task_context": "Build",
                        "builder_agent": "TaskBuilderX",
                        "requirements": [{"id": "R1", "desc": "Done"}],
                    }
                ],
            }
        ],
    }
    run_id, task_id = await _setup_run_with_embedded_routine(client, routine)

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    system = resp.json()["system"]
    assert system.startswith("TASK prompt"), "Task-level agent should win"
    assert "ROUTINE prompt" not in system


# ---------------------------------------------------------------------------
# Cascading: step-level overrides routine
# ---------------------------------------------------------------------------


async def test_step_level_agent_overrides_routine_level(client: AsyncClient) -> None:
    """Step-level builder_agent takes priority over routine-level when task has none."""
    await _create_agent(client, "RoutineBuilderY", "ROUTINE-Y prompt")
    await _create_agent(client, "StepBuilderY", "STEP-Y prompt")

    routine: dict[str, Any] = {
        "id": "cascade-step-routine",
        "name": "Cascade Step Routine",
        "builder_agent": "RoutineBuilderY",
        "steps": [
            {
                "id": "S-01",
                "title": "Step One",
                "builder_agent": "StepBuilderY",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task One",
                        "task_context": "Build",
                        "requirements": [{"id": "R1", "desc": "Done"}],
                    }
                ],
            }
        ],
    }
    run_id, task_id = await _setup_run_with_embedded_routine(client, routine)

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    system = resp.json()["system"]
    assert system.startswith("STEP-Y prompt"), "Step-level agent should win over routine"
    assert "ROUTINE-Y prompt" not in system


# ---------------------------------------------------------------------------
# Verifier phase
# ---------------------------------------------------------------------------


async def test_verifier_prompt_includes_agent_system_prompt(
    client_and_drain: tuple[AsyncClient, DrainFn],
) -> None:
    """Agent system prompt is prepended in VERIFYING phase too."""
    client, drain = client_and_drain
    verifier_system = "You are a strict code reviewer agent."
    await _create_agent(client, "StrictVerifier", verifier_system)

    routine: dict[str, Any] = {
        "id": "verifier-agent-routine",
        "name": "Verifier Agent Routine",
        "verifier_agent": "StrictVerifier",
        "steps": [
            {
                "id": "S-01",
                "title": "Step One",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task One",
                        "task_context": "Build",
                        "requirements": [{"id": "R1", "desc": "Done"}],
                    }
                ],
            }
        ],
    }
    run_id, task_id = await _setup_run_with_embedded_routine(client, routine)

    # Advance to VERIFYING
    await client.patch(
        f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
        json={"status": "done"},
    )
    resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
    assert resp.status_code == 202
    await drain(run_id)
    task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
    assert task_resp.json()["status"] == "verifying"

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert data["phase"] == "verifying"
    system = data["system"]
    assert system.startswith(verifier_system)
    assert _SEPARATOR in system


# ---------------------------------------------------------------------------
# Unknown agent (not in DB) — graceful fallback
# ---------------------------------------------------------------------------


async def test_prompt_unchanged_when_agent_not_in_db(client: AsyncClient) -> None:
    """When the named agent doesn't exist in DB, prompt is returned unchanged (no crash)."""
    routine: dict[str, Any] = {
        "id": "missing-agent-routine",
        "name": "Missing Agent Routine",
        "builder_agent": "AgentThatDoesNotExist",
        "steps": [
            {
                "id": "S-01",
                "title": "Step One",
                "tasks": [
                    {
                        "id": "T-01",
                        "title": "Task One",
                        "task_context": "Build",
                        "requirements": [{"id": "R1", "desc": "Done"}],
                    }
                ],
            }
        ],
    }
    run_id, task_id = await _setup_run_with_embedded_routine(client, routine)

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    data = resp.json()
    # No separator — prompt returned as-is
    assert _SEPARATOR not in data["system"]
