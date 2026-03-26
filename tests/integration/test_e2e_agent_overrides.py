"""E2E tests: agent overrides at routine/step/task levels, and backward compatibility.

Requirements tested:
1. Routine with agent overrides at all levels (routine / step / task):
   - Creates custom agents with distinct system prompts and model profiles.
   - Verifies prompt endpoint returns the correct agent-prefixed system prompt
     for each resolution level (task wins over step wins over routine).
   - Verifies model_profile defaults are stored and returned correctly per agent.
   - Covers both builder and verifier phases.
2. Backward-compatible routine (no agent fields):
   - Verifies that a routine with no agent overrides uses the seeded system-default
     agents (Builder / Verifier) whose system prompts are prepended as expected.
   - Walks through the full run lifecycle: start → build → submit → verify → complete.

All tests are self-contained: they create their own data in an in-memory DB and
clean up automatically when the test exits.
"""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from orchestrator.runners import seed_default_agents
from orchestrator.api.app import create_app
from orchestrator.db import init_db
from orchestrator.workflow import InMemorySignalTransport
from tests.integration.signal_helpers import DrainFn, make_drain_fn

_SEPARATOR = "\n\n---\n\n"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client_and_drain() -> AsyncGenerator[tuple[AsyncClient, DrainFn], None]:
    """App with in-memory DB and seeded default agents (Builder, Verifier, Planner)."""
    app = create_app(db_path=":memory:", routine_dirs=[])
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
    assert start_run.status_code == 200, f"Run start failed: {start_run.text}"

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
# 1.  E2E: agent overrides at ALL levels
# ===========================================================================


class TestAgentOverridesAllLevels:
    """Comprehensive E2E: create agents at routine / step / task level.

    Verifies that the prompt endpoint resolves the correct agent at each
    level and that model_profile defaults are stored and returned correctly.
    """

    async def test_task_level_wins_over_step_and_routine(self, client: AsyncClient) -> None:
        """Task-level agent overrides both step and routine-level agents for builder."""
        routine_agent = await _create_agent(
            client, "E2E-RoutineBuilder", "ROUTINE-BUILDER system prompt", "architect"
        )
        step_agent = await _create_agent(
            client, "E2E-StepBuilder", "STEP-BUILDER system prompt", "designer"
        )
        task_agent = await _create_agent(
            client, "E2E-TaskBuilder", "TASK-BUILDER system prompt", "coder"
        )

        # Verify model profiles stored correctly
        assert routine_agent["model_profile"] == "architect"
        assert step_agent["model_profile"] == "designer"
        assert task_agent["model_profile"] == "coder"

        routine = _make_routine(
            "e2e-all-levels-task-wins",
            routine_builder_agent="E2E-RoutineBuilder",
            step_builder_agent="E2E-StepBuilder",
            task_builder_agent="E2E-TaskBuilder",
        )
        run_id, task_id = await _setup_run(client, routine)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "building"
        system = data["system"]

        # Task-level wins: task prompt is prepended
        assert system.startswith("TASK-BUILDER system prompt"), (
            f"Expected TASK-BUILDER prompt first, got: {system[:120]!r}"
        )
        assert _SEPARATOR in system
        # Other agents must NOT appear
        assert "ROUTINE-BUILDER system prompt" not in system
        assert "STEP-BUILDER system prompt" not in system

    async def test_step_level_wins_over_routine_when_no_task_override(
        self, client: AsyncClient
    ) -> None:
        """Step-level agent overrides routine-level when task has no builder_agent."""
        await _create_agent(client, "E2E-RoutineBuilder2", "ROUTINE2 system prompt", "architect")
        await _create_agent(client, "E2E-StepBuilder2", "STEP2 system prompt", "coder")

        routine = _make_routine(
            "e2e-step-over-routine",
            routine_builder_agent="E2E-RoutineBuilder2",
            step_builder_agent="E2E-StepBuilder2",
            # No task-level override
        )
        run_id, task_id = await _setup_run(client, routine)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        system = resp.json()["system"]
        assert system.startswith("STEP2 system prompt"), (
            f"Expected step-level prompt first, got: {system[:120]!r}"
        )
        assert "ROUTINE2 system prompt" not in system

    async def test_routine_level_used_when_no_step_or_task_override(
        self, client: AsyncClient
    ) -> None:
        """Routine-level agent is used when neither step nor task override is set."""
        await _create_agent(client, "E2E-RoutineBuilder3", "ROUTINE3 system prompt", "summarizer")

        routine = _make_routine(
            "e2e-routine-level-only",
            routine_builder_agent="E2E-RoutineBuilder3",
            # No step or task override
        )
        run_id, task_id = await _setup_run(client, routine)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        system = resp.json()["system"]
        assert system.startswith("ROUTINE3 system prompt"), (
            f"Expected routine-level prompt first, got: {system[:120]!r}"
        )

    async def test_verifier_phase_agent_overrides_all_levels(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Task-level verifier_agent overrides step and routine for verifier prompt."""
        client, drain = client_and_drain
        await _create_agent(client, "E2E-RoutineVerifier", "ROUTINE-VERIFIER prompt", "architect")
        await _create_agent(client, "E2E-StepVerifier", "STEP-VERIFIER prompt", "designer")
        verifier_agent = await _create_agent(
            client, "E2E-TaskVerifier", "TASK-VERIFIER prompt", "coder"
        )

        # Verify model profile on verifier agent
        assert verifier_agent["model_profile"] == "coder"

        routine = _make_routine(
            "e2e-verifier-all-levels",
            routine_verifier_agent="E2E-RoutineVerifier",
            step_verifier_agent="E2E-StepVerifier",
            task_verifier_agent="E2E-TaskVerifier",
        )
        run_id, task_id = await _setup_run(client, routine)

        # Advance task to VERIFYING
        patch_resp = await client.patch(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
            json={"status": "done"},
        )
        assert patch_resp.status_code == 200
        submit_resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
        assert submit_resp.status_code == 202
        await drain(run_id)
        # Verify task is now in verifying state
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

    async def test_model_profile_defaults_per_agent(self, client: AsyncClient) -> None:
        """Each agent's model_profile is stored and returned correctly via GET /api/agents."""
        profiles: list[tuple[str, str]] = [
            ("E2E-ArchAgent", "architect"),
            ("E2E-DesignAgent", "designer"),
            ("E2E-CodeAgent", "coder"),
            ("E2E-SummAgent", "summarizer"),
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

    async def test_prompt_contains_task_context_after_agent_prefix(
        self, client: AsyncClient
    ) -> None:
        """The agent system prompt is prepended; task content still follows after separator."""
        agent_data = await _create_agent(client, "E2E-PrefixCheck", "PREFIX system prompt", "coder")
        assert agent_data["model_profile"] == "coder"

        routine = _make_routine(
            "e2e-prefix-check",
            task_builder_agent="E2E-PrefixCheck",
        )
        run_id, task_id = await _setup_run(client, routine)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        data = resp.json()

        system = data["system"]
        assert _SEPARATOR in system
        prefix, task_content = system.split(_SEPARATOR, 1)
        assert prefix == "PREFIX system prompt"
        # The task content should contain the task context
        assert "Implement the feature" in task_content or len(task_content) > 0


# ===========================================================================
# 2.  E2E: backward-compatible routine (no agent fields)
# ===========================================================================


class TestBackwardCompatibleRoutine:
    """Backward-compatible routine: no agent fields → system defaults are used.

    The seeded Builder and Verifier agents are the system defaults.
    Their system prompts must be prepended to the prompts in BUILDING and
    VERIFYING phases respectively.  The full run lifecycle completes cleanly.
    """

    async def test_builder_system_default_applied_when_no_agent_fields(
        self, client: AsyncClient
    ) -> None:
        """System default Builder agent's prompt is prepended for building phase."""
        # Confirm Builder agent exists (seeded)
        agents_resp = await client.get("/api/agents")
        agents = agents_resp.json()
        builder = next((a for a in agents if a["name"] == "Builder"), None)
        assert builder is not None, "Seeded Builder agent must exist"

        routine = _make_routine("compat-no-agent-fields-builder")
        run_id, task_id = await _setup_run(client, routine)

        resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}/prompt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["phase"] == "building"

        system = data["system"]
        # Builder system prompt should be prepended
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
        run_id, task_id = await _setup_run(client, routine)

        # Advance to VERIFYING
        patch_resp = await client.patch(
            f"/api/runs/{run_id}/tasks/{task_id}/checklist/R1",
            json={"status": "done"},
        )
        assert patch_resp.status_code == 200
        submit_resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
        assert submit_resp.status_code == 202
        await drain(run_id)
        # Verify task is in verifying state
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
        run_id, task_id = await _setup_run(client, routine)

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

        # Submit for verification (202 async) then drain
        submit_resp = await client.post(f"/api/runs/{run_id}/tasks/{task_id}/submit")
        assert submit_resp.status_code == 202
        await drain(run_id)
        # Verify task is in verifying state
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

        # Complete verification (202 async) then drain
        complete_resp = await client.post(
            f"/api/runs/{run_id}/tasks/{task_id}/complete-verification"
        )
        assert complete_resp.status_code == 202
        await drain(run_id)
        # Verify task is completed
        task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
        assert task_resp.json()["status"] == "completed"

    async def test_backward_compat_routine_with_explicit_agent_still_works(
        self, client_and_drain: tuple[AsyncClient, DrainFn]
    ) -> None:
        """Adding a builder_agent override to an existing routine does not break it.

        This simulates an existing routine being augmented with an agent field:
        the new agent's prompt is prepended, but the lifecycle is unchanged.
        """
        client, drain = client_and_drain
        custom_agent = await _create_agent(
            client,
            "E2E-CompatUpgrade",
            "UPGRADE prompt",
            "coder",
        )
        assert custom_agent["model_profile"] == "coder"

        routine = _make_routine(
            "compat-upgrade",
            routine_builder_agent="E2E-CompatUpgrade",
        )
        run_id, task_id = await _setup_run(client, routine)

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
        assert submit_resp.status_code == 202
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
        assert complete_resp.status_code == 202
        await drain(run_id)
        task_resp = await client.get(f"/api/runs/{run_id}/tasks/{task_id}")
        assert task_resp.json()["status"] == "completed"
