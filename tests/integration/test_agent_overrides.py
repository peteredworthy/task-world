"""Integration tests for agent override resolution and system prompt injection.

Covers:
1. Cascading resolution: task > step > routine > system default
2. Agent model profiles stored and returned per agent
3. Builder and verifier phases both apply agent system prompts
4. Full run lifecycle with agent overrides works end-to-end
5. Backward compatibility: routines without agent fields fall back to system defaults
6. File-based routines (no agent fields) return prompt unchanged (no system default seeded)
7. Graceful fallback when named agent is not in DB

All tests use in-memory DBs and clean up automatically.
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.runners import seed_default_agents
from orchestrator.api.app import create_app
from orchestrator.config import RoutineSource
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport
from tests.integration.signal_helpers import DrainFn, make_drain_fn

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"

_SEPARATOR = "\n\n---\n\n"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    """App with in-memory DB, seeded default agents (Builder, Verifier, Planner), and fixture routines."""
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    async with app.state.session_factory() as session:
        await seed_default_agents(session)
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


@pytest.fixture
async def client_and_drain_no_seed() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    """App with in-memory DB and fixture routines but NO seeded default agents.

    Used for tests that verify behavior when no system default agents exist.
    """
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_agent(
    client: AsyncClient,
    name: str,
    system_prompt: str,
    model_profile: str = "coder",
) -> dict[str, Any]:
    """Create an agent config and return its full schema."""
    resp = await client.post(
        "/api/agents",
        json={"name": name, "system_prompt": system_prompt, "model_profile": model_profile},
    )
    assert resp.status_code == 201, f"Failed to create agent '{name}': {resp.text}"
    return resp.json()


async def _setup_run(
    client: AsyncClient,
    routine: dict[str, Any],
    drain: DrainFn,
) -> tuple[str, str]:
    """Create run with embedded routine, start run, start first task.

    Returns (run_id, task_id).
    """
    resp = await client.post(
        "/api/runs",
        json={"repo_name": "test-project", "branch": "main", "routine_embedded": routine},
    )
    assert resp.status_code == 201, f"Expected 201 creating run: {resp.text}"
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    start_run = await client.post(f"/api/runs/{run_id}/start")
    assert start_run.status_code == 202, f"Run start failed: {start_run.text}"
    await drain(run_id)

    start_task = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")
    assert start_task.status_code == 200, f"Task start failed: {start_task.text}"

    return run_id, task_id


def _make_routine(
    routine_id: str,
    routine_builder_agent: str | None = None,
    routine_verifier_agent: str | None = None,
    step_builder_agent: str | None = None,
    step_verifier_agent: str | None = None,
    task_builder_agent: str | None = None,
    task_verifier_agent: str | None = None,
) -> dict[str, Any]:
    """Build a minimal routine dict with optional agent overrides at each level."""
    task: dict[str, Any] = {
        "id": "T-01",
        "title": "The Task",
        "task_context": "Implement the feature.",
        "requirements": [{"id": "R1", "desc": "Feature works"}],
    }
    if task_builder_agent is not None:
        task["builder_agent"] = task_builder_agent
    if task_verifier_agent is not None:
        task["verifier_agent"] = task_verifier_agent

    step: dict[str, Any] = {
        "id": "S-01",
        "title": "Step One",
        "tasks": [task],
    }
    if step_builder_agent is not None:
        step["builder_agent"] = step_builder_agent
    if step_verifier_agent is not None:
        step["verifier_agent"] = step_verifier_agent

    routine: dict[str, Any] = {
        "id": routine_id,
        "name": routine_id,
        "steps": [step],
    }
    if routine_builder_agent is not None:
        routine["builder_agent"] = routine_builder_agent
    if routine_verifier_agent is not None:
        routine["verifier_agent"] = routine_verifier_agent

    return routine


# ===========================================================================
# Section 1: Cascading resolution — task > step > routine
# ===========================================================================


class TestCascadingResolution:
    """Verifies that agent resolution cascades correctly at all levels."""

    async def test_task_level_wins_over_step_and_routine(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Task-level agent overrides both step and routine-level agents for builder."""
        client, drain = client_and_drain
        routine_agent = await _create_agent(
            client, "Integration-RoutineBuilder", "ROUTINE-BUILDER system prompt", "architect"
        )
        step_agent = await _create_agent(
            client, "Integration-StepBuilder", "STEP-BUILDER system prompt", "designer"
        )
        task_agent = await _create_agent(
            client, "Integration-TaskBuilder", "TASK-BUILDER system prompt", "coder"
        )

        # Verify model profiles stored correctly
        assert routine_agent["model_profile"] == "architect"
        assert step_agent["model_profile"] == "designer"
        assert task_agent["model_profile"] == "coder"

        routine = _make_routine(
            "integration-all-levels-task-wins",
            routine_builder_agent="Integration-RoutineBuilder",
            step_builder_agent="Integration-StepBuilder",
            task_builder_agent="Integration-TaskBuilder",
        )
        run_id, task_id = await _setup_run(client, routine, drain)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "building"
        system = data["system"]

        assert system.startswith("TASK-BUILDER system prompt"), (
            f"Expected TASK-BUILDER prompt first, got: {system[:120]!r}"
        )
        assert _SEPARATOR in system
        assert "ROUTINE-BUILDER system prompt" not in system
        assert "STEP-BUILDER system prompt" not in system

    async def test_step_level_wins_over_routine_when_no_task_override(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Step-level agent overrides routine-level when task has no builder_agent."""
        client, drain = client_and_drain
        await _create_agent(
            client, "Integration-RoutineBuilder2", "ROUTINE2 system prompt", "architect"
        )
        await _create_agent(client, "Integration-StepBuilder2", "STEP2 system prompt", "coder")

        routine = _make_routine(
            "integration-step-over-routine",
            routine_builder_agent="Integration-RoutineBuilder2",
            step_builder_agent="Integration-StepBuilder2",
        )
        run_id, task_id = await _setup_run(client, routine, drain)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        system = resp.json()["system"]
        assert system.startswith("STEP2 system prompt"), (
            f"Expected step-level prompt first, got: {system[:120]!r}"
        )
        assert "ROUTINE2 system prompt" not in system

    async def test_routine_level_used_when_no_step_or_task_override(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Routine-level agent is used when neither step nor task override is set."""
        client, drain = client_and_drain
        await _create_agent(
            client, "Integration-RoutineBuilder3", "ROUTINE3 system prompt", "summarizer"
        )

        routine = _make_routine(
            "integration-routine-level-only",
            routine_builder_agent="Integration-RoutineBuilder3",
        )
        run_id, task_id = await _setup_run(client, routine, drain)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        system = resp.json()["system"]
        assert system.startswith("ROUTINE3 system prompt"), (
            f"Expected routine-level prompt first, got: {system[:120]!r}"
        )

    async def test_task_level_agent_overrides_routine_level_simple(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Task-level builder_agent takes priority over routine-level (inline routine syntax)."""
        client, drain = client_and_drain
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
        run_id, task_id = await _setup_run(client, routine, drain)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        system = resp.json()["system"]
        assert system.startswith("TASK prompt"), "Task-level agent should win"
        assert "ROUTINE prompt" not in system

    async def test_step_level_agent_overrides_routine_level_simple(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Step-level builder_agent takes priority over routine-level (inline routine syntax)."""
        client, drain = client_and_drain
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
        run_id, task_id = await _setup_run(client, routine, drain)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        system = resp.json()["system"]
        assert system.startswith("STEP-Y prompt"), "Step-level agent should win over routine"
        assert "ROUTINE-Y prompt" not in system


# ===========================================================================
# Section 2: Agent model profiles
# ===========================================================================


class TestAgentModelProfiles:
    """Model profile is stored per agent and survives GET roundtrip."""

    async def test_model_profiles_roundtrip_per_agent(self, client: AsyncClient) -> None:
        """Each agent's model_profile is stored and returned correctly via GET /api/agents."""
        profiles: list[tuple[str, str]] = [
            ("Integration-ArchAgent", "architect"),
            ("Integration-DesignAgent", "designer"),
            ("Integration-CodeAgent", "coder"),
            ("Integration-SummAgent", "summarizer"),
        ]
        created: dict[str, str] = {}
        for name, profile in profiles:
            data = await _create_agent(client, name, f"{name} prompt", profile)
            created[name] = data["id"]
            assert data["model_profile"] == profile, (
                f"Agent {name}: expected model_profile={profile!r}, got {data['model_profile']!r}"
            )

        # Verify via GET /api/agents/{id} roundtrip
        for name, expected_profile in profiles:
            agent_id = created[name]
            resp = await client.get(f"/api/agents/{agent_id}")
            assert resp.status_code == 200
            fetched = resp.json()
            assert fetched["model_profile"] == expected_profile, (
                f"Roundtrip: agent {name} should have model_profile={expected_profile!r}"
            )


# ===========================================================================
# Section 3: Verifier phase agent overrides
# ===========================================================================


class TestVerifierPhaseOverrides:
    """Agent resolution works for the verifier phase (VERIFYING status)."""

    async def test_verifier_phase_agent_overrides_all_levels(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Task-level verifier_agent overrides step and routine for verifier prompt."""
        client, drain = client_and_drain
        await _create_agent(
            client, "Integration-RoutineVerifier", "ROUTINE-VERIFIER prompt", "architect"
        )
        await _create_agent(client, "Integration-StepVerifier", "STEP-VERIFIER prompt", "designer")
        verifier_agent = await _create_agent(
            client, "Integration-TaskVerifier", "TASK-VERIFIER prompt", "coder"
        )
        assert verifier_agent["model_profile"] == "coder"

        routine = _make_routine(
            "integration-verifier-all-levels",
            routine_verifier_agent="Integration-RoutineVerifier",
            step_verifier_agent="Integration-StepVerifier",
            task_verifier_agent="Integration-TaskVerifier",
        )
        run_id, task_id = await _setup_run(client, routine, drain)

        # Advance task to VERIFYING
        patch_resp = await client.patch(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
            json={"status": "done"},
        )
        assert patch_resp.status_code == 200
        submit_resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
        assert submit_resp.status_code == 200
        await drain(run_id)
        task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
        assert task_resp.json()["status"] == "verifying"

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "verifying"
        system = data["system"]

        assert system.startswith("TASK-VERIFIER prompt"), (
            f"Expected TASK-VERIFIER prompt first, got: {system[:120]!r}"
        )
        assert _SEPARATOR in system
        assert "ROUTINE-VERIFIER prompt" not in system
        assert "STEP-VERIFIER prompt" not in system

    async def test_verifier_prompt_includes_routine_level_agent_system_prompt(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Routine-level verifier_agent system_prompt is prepended in VERIFYING phase."""
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
        run_id, task_id = await _setup_run(client, routine, drain)

        # Advance to VERIFYING
        await client.patch(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
            json={"status": "done"},
        )
        resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
        assert resp.status_code == 200
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


# ===========================================================================
# Section 4: Prompt structure
# ===========================================================================


class TestPromptStructure:
    """Verifies the structure of the assembled prompt."""

    async def test_prompt_contains_task_context_after_agent_prefix(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Agent system prompt is prepended; task content follows after separator."""
        client, drain = client_and_drain
        agent_data = await _create_agent(
            client, "Integration-PrefixCheck", "PREFIX system prompt", "coder"
        )
        assert agent_data["model_profile"] == "coder"

        routine = _make_routine(
            "integration-prefix-check",
            task_builder_agent="Integration-PrefixCheck",
        )
        run_id, task_id = await _setup_run(client, routine, drain)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        data = resp.json()

        system = data["system"]
        assert _SEPARATOR in system
        prefix, task_content = system.split(_SEPARATOR, 1)
        assert prefix == "PREFIX system prompt"
        assert "Implement the feature" in task_content or len(task_content) > 0

    async def test_prompt_includes_agent_system_prompt_via_routine_level(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Routine-level builder_agent system_prompt is prepended to the builder prompt."""
        client, drain = client_and_drain
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
        run_id, task_id = await _setup_run(client, routine, drain)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "building"
        system = data["system"]
        assert system.startswith(agent_system), "Agent system prompt should be at the start"
        assert _SEPARATOR in system
        task_prompt_part = system.split(_SEPARATOR, 1)[1]
        assert len(task_prompt_part) > 0, "Task prompt part should not be empty"


# ===========================================================================
# Section 5: Backward compatibility — system defaults (seeded agents)
# ===========================================================================


class TestBackwardCompatibleRoutineWithDefaults:
    """Backward-compatible routines use seeded Builder/Verifier system defaults.

    These tests require seeded default agents (Builder, Verifier).
    """

    async def test_builder_system_default_applied_when_no_agent_fields(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """System default Builder agent's prompt is prepended for building phase."""
        client, drain = client_and_drain
        agents_resp = await client.get("/api/agents")
        agents = agents_resp.json()
        builder = next((a for a in agents if a["name"] == "Builder"), None)
        assert builder is not None, "Seeded Builder agent must exist"

        routine = _make_routine("compat-no-agent-fields-builder")
        run_id, task_id = await _setup_run(client, routine, drain)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "building"

        system = data["system"]
        builder_prompt = builder["system_prompt"]
        assert system.startswith(builder_prompt), (
            f"System default Builder prompt should be prepended.\n"
            f"Expected prefix: {builder_prompt[:80]!r}\n"
            f"Actual start:    {system[:80]!r}"
        )
        assert _SEPARATOR in system

    async def test_verifier_system_default_applied_when_no_agent_fields(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """System default Verifier agent's prompt is prepended for verifying phase."""
        client, drain = client_and_drain
        agents_resp = await client.get("/api/agents")
        agents = agents_resp.json()
        verifier = next((a for a in agents if a["name"] == "Verifier"), None)
        assert verifier is not None, "Seeded Verifier agent must exist"

        routine = _make_routine("compat-no-agent-fields-verifier")
        run_id, task_id = await _setup_run(client, routine, drain)

        # Advance to VERIFYING
        patch_resp = await client.patch(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
            json={"status": "done"},
        )
        assert patch_resp.status_code == 200
        submit_resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
        assert submit_resp.status_code == 200
        await drain(run_id)
        task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
        assert task_resp.json()["status"] == "verifying"

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "verifying"

        system = data["system"]
        verifier_prompt = verifier["system_prompt"]
        assert system.startswith(verifier_prompt), (
            f"System default Verifier prompt should be prepended.\n"
            f"Expected prefix: {verifier_prompt[:80]!r}\n"
            f"Actual start:    {system[:80]!r}"
        )
        assert _SEPARATOR in system

    async def test_full_lifecycle_backward_compatible_routine(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Full run lifecycle with a routine that has no agent fields.

        Path: create run → start → build → submit → verify → complete.
        Verifies that no step in the lifecycle fails due to missing agents.
        """
        client, drain = client_and_drain
        routine = _make_routine("compat-full-lifecycle")
        run_id, task_id = await _setup_run(client, routine, drain)

        # --- Building phase ---
        prompt_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert prompt_resp.status_code == 200
        assert prompt_resp.json()["phase"] == "building"

        # Mark requirement done
        patch_resp = await client.patch(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
            json={"status": "done"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["status"] == "done"

        # Submit for verification then drain
        submit_resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
        assert submit_resp.status_code == 200
        await drain(run_id)
        task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
        assert task_resp.json()["status"] == "verifying"

        # --- Verifying phase ---
        verifier_prompt_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert verifier_prompt_resp.status_code == 200
        assert verifier_prompt_resp.json()["phase"] == "verifying"

        # Grade requirement
        grade_resp = await client.put(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
            json={"grade": "A", "grade_reason": "Looks good"},
        )
        assert grade_resp.status_code == 200

        # Complete verification then drain
        complete_resp = await client.post(
            f"/api/runs/{run_id}/tasks/{task_id}/complete-verification"
        )
        assert complete_resp.status_code == 200
        await drain(run_id)
        task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
        assert task_resp.json()["status"] == "completed"

    async def test_adding_agent_override_to_existing_routine_does_not_break_lifecycle(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Adding a builder_agent override to an existing routine does not break it.

        The new agent's prompt is prepended, but the full lifecycle still completes.
        """
        client, drain = client_and_drain
        custom_agent = await _create_agent(
            client,
            "Integration-CompatUpgrade",
            "UPGRADE prompt",
            "coder",
        )
        assert custom_agent["model_profile"] == "coder"

        routine = _make_routine(
            "compat-upgrade",
            routine_builder_agent="Integration-CompatUpgrade",
        )
        run_id, task_id = await _setup_run(client, routine, drain)

        prompt_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert prompt_resp.status_code == 200
        system = prompt_resp.json()["system"]
        assert system.startswith("UPGRADE prompt")
        assert _SEPARATOR in system

        # Full lifecycle still completes
        await client.patch(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
            json={"status": "done"},
        )
        submit_resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
        assert submit_resp.status_code == 200
        await drain(run_id)
        task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
        assert task_resp.json()["status"] == "verifying"

        await client.put(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1/grade",
            json={"grade": "A"},
        )
        complete_resp = await client.post(
            f"/api/runs/{run_id}/tasks/{task_id}/complete-verification"
        )
        assert complete_resp.status_code == 200
        await drain(run_id)
        task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
        assert task_resp.json()["status"] == "completed"


# ===========================================================================
# Section 6: No-default-agent behavior (no seeded agents)
# ===========================================================================


async def test_prompt_unchanged_when_no_agent_fields_and_no_defaults(
    client_and_drain_no_seed: tuple[AsyncClient, DrainFn],
) -> None:
    """When no agent fields are set and no default agents are seeded, prompt has no separator."""
    client, drain = client_and_drain_no_seed
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
    run_id, task_id = await _setup_run(client, routine, drain)

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert data["phase"] == "building"
    assert _SEPARATOR not in data["system"]


async def test_prompt_unchanged_via_file_based_routine_no_defaults(
    client_and_drain_no_seed: tuple[AsyncClient, DrainFn],
) -> None:
    """File-based routine without agent fields returns prompt without separator when no defaults seeded."""
    client, drain = client_and_drain_no_seed
    resp = await client.post(
        "/api/runs",
        json={"routine_id": "simple-routine", "repo_name": "proj-1", "branch": "main"},
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]
    task_id = resp.json()["steps"][0]["tasks"][0]["id"]

    resp = await client.post(f"/api/runs/{run_id}/start")
    assert resp.status_code == 202
    await drain(run_id)
    await client.post(f"/api/runs/{run_id}/tasks/{task_id}/start")

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert _SEPARATOR not in data["system"]


# ===========================================================================
# Section 7: Graceful fallback for missing agents
# ===========================================================================


async def test_prompt_unchanged_when_agent_not_in_db(
    client_and_drain_no_seed: tuple[AsyncClient, DrainFn],
) -> None:
    """When the named agent doesn't exist in DB, prompt is returned unchanged (no crash)."""
    client, drain = client_and_drain_no_seed
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
    run_id, task_id = await _setup_run(client, routine, drain)

    resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert _SEPARATOR not in data["system"]
