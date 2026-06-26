"""FR-01/FR-13/FR-18 acceptance harness.

FR-01: Graph run starts from a routine snapshot with multi-task typed topology,
       creates planner/worker/verifier/check nodes for two parallel regions, routes
       records, and completes only when all regions have passed invariants.

FR-13: Graph cannot silently stop while work is possible; blockers identify
       non-terminal states. Proofs:
       (a) invalid patch from active planner is rejected and durable in the
           graph event store and /graph/patches readback;
       (b) while one region is accepted and another is blocked by a failed
           check, final-blockers and /graph/regions correctly identify the
           incomplete region;
       (c) an invalid-actor patch submitted while the run is blocked does not
           corrupt graph state or remove the existing blockers;
       (d) no blockers once both regions complete.

FR-18: Harder-than-smoke end-to-end: two parallel task regions complete from
       planner-authorized topology through worker/verifier/check, with intermediate
       proof that the run cannot complete while one region is pending.
"""

from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api import create_app
from orchestrator.config import AgentRunnerType, RunStatus, RoutineConfig
from orchestrator.db import init_db
from orchestrator.graph import FakeClock
from orchestrator.graph_runtime import GraphController, GraphDispatchContext, GraphDispatchExecutor
from orchestrator.runners import AgentRunner
from orchestrator.runners.types import (
    AgentMetadataCallback,
    AgentRunnerInfo,
    ChecklistUpdateCallback,
    EscalationCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow import GraphRunDriver, WorkflowService


# --------------------------------------------------------------------------- #
# Deterministic clock / ids                                                     #
# --------------------------------------------------------------------------- #


class FixedClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: int) -> None:
        self._now += timedelta(seconds=seconds)


class SequentialIds:
    def __init__(self, namespace: str) -> None:
        self._namespace = namespace
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{self._namespace}-{prefix}-{self._next}"
        self._next += 1
        return value


# --------------------------------------------------------------------------- #
# Scripted agents                                                               #
# --------------------------------------------------------------------------- #


class MultiTaskPlannerAgent:
    """FR-01/FR-13 probe: submits an invalid patch (rejected) then a valid noop
    patch (accepted) before completing, proving the patch validator works during
    active planning and rejected patches are durable without corrupting state."""

    def __init__(self) -> None:
        self.invalid_feedback: str = ""
        self.valid_feedback: str = ""

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CODEX_SERVER, name="planner")

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        assert context.graph_patch_callback is not None

        # Step 1: submit invalid patch — check nodes must not expose
        # hidden_oracle_command directly (use command_binding instead).
        # The validator rejects this and the rejection is durable.
        self.invalid_feedback = await context.graph_patch_callback(
            {
                "patch_id": "patch-invalid-oracle-probe",
                "base_graph_position": 0,
                "ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "check-oracle-probe",
                            "kind": "check",
                            "role": "invariant_gate",
                            "state": "planned",
                            "task_region_id": "s-01/t-01",
                            "hidden_oracle_command": "grep -q oracle docs/test.txt",
                        },
                    }
                ],
            }
        )
        assert "rejected" in self.invalid_feedback, (
            f"expected rejected but got: {self.invalid_feedback!r}"
        )

        # Step 2: submit valid noop patch — empty ops, no read-set conflicts.
        # This satisfies the planner's must-have-accepted-patch requirement.
        self.valid_feedback = await context.graph_patch_callback(
            {
                "patch_id": "patch-multi-task-plan",
                "base_graph_position": 0,
                "ops": [],
            }
        )
        assert "accepted" in self.valid_feedback, (
            f"expected accepted but got: {self.valid_feedback!r}"
        )

        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class MultiTaskWorkerAgent:
    """Writes a task-specific artifact so each auto-verify check can pass."""

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CODEX_SERVER, name="worker")

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        node_id = context.node_id
        artifact_file = "docs/fr-e2e-t02.txt" if "t-02" in node_id else "docs/fr-e2e-t01.txt"
        artifact = Path(context.working_dir) / artifact_file
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(f"{node_id} completed\n")
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class VerifierAgent:
    """Grades requirement req-1 for whichever verifier is running."""

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CODEX_SERVER, name="verifier")

    async def execute(
        self,
        context: ExecutionContext,
        on_checklist_update: ChecklistUpdateCallback,
        on_submit: SubmitCallback,
        on_output: LogLineCallback | None = None,
        on_grade: GradeCallback | None = None,
        on_agent_metadata: AgentMetadataCallback | None = None,
        on_escalation: EscalationCallback | None = None,
    ) -> ExecutionResult:
        if on_grade is not None:
            await on_grade("req-1", "A", "artifact produced and verified")
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class AgentFactory:
    def __init__(self, agents: dict[str, AgentRunner]) -> None:
        self._agents = agents

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        return self._agents[context.node_kind]


# --------------------------------------------------------------------------- #
# Fixtures / helpers                                                            #
# --------------------------------------------------------------------------- #


@pytest.fixture
async def fr_e2e_app(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncClient, Any], None]:
    app = create_app(db_path=str(tmp_path / "fr-e2e.db"), routine_dirs=[])
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app
    await app.state.engine.dispose()


def _two_task_routine(*, t02_check_cmd: str = "test -f docs/fr-e2e-t02.txt") -> RoutineConfig:
    """Two parallel tasks in one step; planner plans, then workers/verifiers/checks run."""
    return RoutineConfig.model_validate(
        {
            "id": "fr-e2e-two-task",
            "name": "FR-01/13/18 Two-Task E2E",
            "execution_mode": "graph",
            "planner_generation_budget": 1,
            "steps": [
                {"id": "plan", "kind": "planner", "title": "Plan two-task work"},
                {
                    "id": "s-01",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "t-01",
                            "title": "Produce T-01 artifact",
                            "task_context": "Write the T-01 acceptance artifact.",
                            "artifacts": [{"path": "docs/fr-e2e-t01.txt"}],
                            "requirements": [
                                {"id": "req-1", "desc": "T-01 artifact produced and verified."}
                            ],
                            "verifier": {
                                "rubric": [
                                    {"id": "req-1", "text": "T-01 artifact produced and verified."}
                                ]
                            },
                            "auto_verify": {
                                "items": [
                                    {
                                        "id": "check-t01",
                                        "cmd": "test -f docs/fr-e2e-t01.txt",
                                    }
                                ]
                            },
                        },
                        {
                            "id": "t-02",
                            "title": "Produce T-02 artifact",
                            "task_context": "Write the T-02 acceptance artifact.",
                            "artifacts": [{"path": "docs/fr-e2e-t02.txt"}],
                            "requirements": [
                                {"id": "req-1", "desc": "T-02 artifact produced and verified."}
                            ],
                            "verifier": {
                                "rubric": [
                                    {"id": "req-1", "text": "T-02 artifact produced and verified."}
                                ]
                            },
                            "auto_verify": {
                                "items": [
                                    {
                                        "id": "check-t02",
                                        "cmd": t02_check_cmd,
                                    }
                                ]
                            },
                        },
                    ],
                },
            ],
        }
    )


def _init_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("# fr-e2e acceptance\n")
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "add", "README.md"], cwd=path, check=True, capture_output=True, text=True
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "init",
        ],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


async def _create_service(session: AsyncSession) -> WorkflowService:
    return WorkflowService(session)


async def _create_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    routine: RoutineConfig,
    *,
    run_id: str,
    repo: Path,
) -> None:
    run = create_run_from_routine(routine, repo_name=repo.name, source_branch="main")
    run.id = run_id
    run.execution_mode = "graph"
    run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
    run.worktree_path = str(repo)
    run.agent_runner_type = AgentRunnerType.CODEX_SERVER
    async with session_factory() as session:
        await WorkflowService(session).create_run(run)


def _driver(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    repo: Path,
    run_id: str,
    planner: AgentRunner | None = None,
) -> GraphRunDriver:
    clock = FixedClock()
    ids = SequentialIds(run_id)
    _planner = planner or MultiTaskPlannerAgent()

    def runtime_builder(
        session_factory_arg: async_sessionmaker[AsyncSession],
        clock_arg: Any,
        id_gen_arg: Any,
        *,
        worktree_path: str | Path,
        runner_type: AgentRunnerType,
        runner_config: dict[str, Any] | None = None,
    ) -> tuple[GraphController, GraphDispatchExecutor]:
        controller = GraphController(
            session_factory_arg, clock_arg, id_gen_arg, auto_dispatch=False
        )
        executor = GraphDispatchExecutor(
            session_factory_arg,
            controller,
            AgentFactory(
                {
                    "planner": _planner,
                    "worker": MultiTaskWorkerAgent(),
                    "verifier": VerifierAgent(),
                }
            ),
            worktree_path=repo,
        )
        return controller, executor

    return GraphRunDriver(
        session_factory,
        _create_service,
        clock=clock,
        id_gen=ids,
        runtime_builder=runtime_builder,
    )


async def _get_json(client: AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200, f"GET {path} → {response.status_code}: {response.text}"
    return response.json()


def _run_id() -> str:
    return f"fr-e2e-{uuid4().hex[:8]}"


# --------------------------------------------------------------------------- #
# Tests                                                                         #
# --------------------------------------------------------------------------- #


async def test_fr01_fr18_two_task_bootstrap_completes(
    fr_e2e_app: tuple[AsyncClient, Any],
    tmp_path: Path,
) -> None:
    """FR-01/FR-13/FR-18: two-task multi-region bootstrap completes with
    planner-submitted invalid-patch probe, multi-region evidence, and terminal
    no-blocker state.

    FR-01 coverage: bootstrap from a 2-task inline routine, compiler-created
    typed topology for two parallel regions, planner-authorized graph mutation,
    multi-region record routing, and completion only when both regions pass
    their invariants.

    FR-13 coverage (criterion a/d): the planner's invalid patch is rejected and
    durable in the event store; the completed run has no final blockers.

    FR-18 coverage: harder-than-smoke end-to-end scenario with parallel task
    regions, multi-region evidence accumulation, and terminal completion from
    planner-authorized topology through worker/verifier/check paths.
    """
    client, app = fr_e2e_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    repo = tmp_path / "fr-e2e-happy"
    _init_repo(repo)
    run_id = _run_id()
    routine = _two_task_routine()
    await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)

    planner_agent = MultiTaskPlannerAgent()
    outcome = await _driver(session_factory, repo=repo, run_id=run_id, planner=planner_agent).run(
        run_id
    )

    assert outcome.completed is True, outcome.blocked_reason

    # --- planner's invalid/valid patch feedback (FR-13 criterion a) ----------
    assert "rejected" in planner_agent.invalid_feedback
    assert "hidden_oracle_command" in planner_agent.invalid_feedback
    assert "accepted" in planner_agent.valid_feedback

    # --- public run / graph readbacks ----------------------------------------
    run = await _get_json(client, f"/api/runs/{run_id}")
    graph = await _get_json(client, f"/api/runs/{run_id}/graph")
    events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    regions = await _get_json(client, f"/api/runs/{run_id}/graph/regions")
    blockers = await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers")
    scheduler = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")
    patches = await _get_json(client, f"/api/runs/{run_id}/graph/patches")

    # FR-01/FR-18: run completed, execution mode graph
    assert run["status"] == RunStatus.COMPLETED.value
    assert run["execution_mode"] == "graph"
    assert graph["run_state"] == "completed"

    # FR-01: compiler-created nodes for both tasks are present
    node_states = graph["node_states"]
    assert node_states["planner-plan"] == "completed"
    assert node_states["worker-s-01-t-01"] == "completed"
    assert node_states["verifier-s-01-t-01"] == "completed"
    assert node_states["check-s-01-t-01-auto_verify-check-t01"] == "completed"
    assert node_states["worker-s-01-t-02"] == "completed"
    assert node_states["verifier-s-01-t-02"] == "completed"
    assert node_states["check-s-01-t-02-auto_verify-check-t02"] == "completed"

    # FR-01/FR-18: both regions accepted (completion requires both)
    region_states = {r["task_region_id"]: r["state"] for r in regions["regions"]}
    assert region_states.get("s-01/t-01") == "accepted", region_states
    assert region_states.get("s-01/t-02") == "accepted", region_states

    # FR-13 criterion d: no final blockers after completion
    assert blockers["blockers"] == [], blockers["blockers"]

    # FR-01/FR-18: no active leases after completion
    assert scheduler["leases"]["active"] == []

    # FR-13 criterion a: rejected patch is durable in /graph/patches
    rejected_attempts = [
        a for a in patches["attempts"] if a.get("patch_id") == "patch-invalid-oracle-probe"
    ]
    assert rejected_attempts, "rejected patch must appear in /graph/patches"
    assert rejected_attempts[0]["status"] == "rejected"

    # FR-13 criterion a: accepted noop patch is also durable in /graph/patches
    accepted_attempts = [
        a for a in patches["attempts"] if a.get("patch_id") == "patch-multi-task-plan"
    ]
    assert accepted_attempts, "accepted patch must appear in /graph/patches"
    assert accepted_attempts[0]["status"] == "accepted"

    # FR-18: both workers wrote their artifacts (multi-region evidence)
    event_types = [e["event_type"] for e in events]
    assert event_types.count("file_state_accepted") >= 2, (
        "expected file_state_accepted for both task workers"
    )
    verification_reports = [
        e
        for e in events
        if e["event_type"] == "output_record_accepted"
        and e["payload"].get("record_type") == "verification_report"
    ]
    assert len(verification_reports) >= 2, "expected verification_report for both tasks"

    check_results = [
        e
        for e in events
        if e["event_type"] == "output_record_accepted"
        and e["payload"].get("record_type") == "check_result"
        and e["payload"].get("value", {}).get("status") == "passed"
    ]
    assert len(check_results) >= 2, "expected passed check_result for both tasks"


async def test_fr13_partial_region_blockers_and_invalid_patch_in_blocked_state(
    fr_e2e_app: tuple[AsyncClient, Any],
    tmp_path: Path,
) -> None:
    """FR-13: blocked-progress scenarios and invalid-patch probe in blocked state.

    FR-13 coverage (criterion b/c):
    (b) while T-01 is accepted and T-02 is blocked by a failing check, the
        final-blockers readback and /graph/regions correctly identify the
        incomplete T-02 region, proving graph cannot silently complete while
        work is possible.
    (c) an invalid patch submitted while the run is in a blocked/quiescent
        state is rejected with diagnostics, leaves the blockers unchanged, and
        does not corrupt graph state — the run remains paused after the
        rejection.

    Also proves FR-01/FR-13: the planner invalid-patch probe (hidden_oracle_command)
    is durable even when submitted mid-planning in a partial-completion scenario.
    """
    client, app = fr_e2e_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    repo = tmp_path / "fr-e2e-blocked"
    _init_repo(repo)
    run_id = _run_id()
    # T-02's check command always fails, so T-02 region will be blocked.
    routine = _two_task_routine(t02_check_cmd="false")
    await _create_graph_run(session_factory, routine, run_id=run_id, repo=repo)

    planner_agent = MultiTaskPlannerAgent()
    outcome = await _driver(session_factory, repo=repo, run_id=run_id, planner=planner_agent).run(
        run_id
    )

    # Run must be blocked (T-02 check fails, region stays pending)
    assert outcome.completed is False, "expected blocked outcome"
    assert outcome.blocked_reason is not None

    # --- planner's invalid-patch probe was rejected even in blocked scenario --
    assert "rejected" in planner_agent.invalid_feedback
    assert "hidden_oracle_command" in planner_agent.invalid_feedback

    # --- public readbacks while blocked (FR-13 criterion b) ------------------
    run = await _get_json(client, f"/api/runs/{run_id}")
    graph = await _get_json(client, f"/api/runs/{run_id}/graph")
    regions = await _get_json(client, f"/api/runs/{run_id}/graph/regions")
    blockers_before = await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers")
    scheduler = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")

    assert run["status"] == RunStatus.PAUSED.value
    assert run["is_graph_backed"] is True
    assert graph["run_state"] == "paused"

    # FR-13 criterion b: T-01 is accepted, T-02 is pending
    region_states = {r["task_region_id"]: r["state"] for r in regions["regions"]}
    assert region_states.get("s-01/t-01") == "accepted", (
        f"expected T-01 accepted, got {region_states}"
    )
    assert region_states.get("s-01/t-02") != "accepted", (
        f"expected T-02 not accepted, got {region_states}"
    )

    # FR-13 criterion b: final blockers exist for T-02
    assert blockers_before["blockers"], "expected non-empty final-blockers while T-02 is pending"
    blocker_node_ids = {b.get("node_id") for b in blockers_before["blockers"]}
    assert any("t-02" in str(nid) for nid in blocker_node_ids), (
        f"expected T-02-related blocker, got {blocker_node_ids}"
    )

    # No active leases (quiescent blocked state)
    assert scheduler["leases"]["active"] == []

    # --- invalid patch submitted while blocked (FR-13 criterion c) -----------
    # The run is quiescent; the planner node has completed. Submitting a patch
    # with an unauthorized actor role proves the validator still works and the
    # blockers are unchanged after the rejection.
    controller = GraphController(
        session_factory,
        FakeClock(),
        SequentialIds(f"{run_id}-probe"),
        auto_dispatch=False,
    )
    current_position = await controller.current_position(run_id)
    await controller.handle_command(
        run_id,
        current_position,
        "submit_patch",
        {
            "patch_id": "patch-invalid-actor-blocked",
            "proposed_by_node_id": "planner-plan",
            "base_graph_position": 0,
            "actor_role": "fixer",  # unauthorized: only planner/gap_planner may submit
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "injected-node",
                        "kind": "worker",
                        "role": "builder",
                        "state": "planned",
                        "task_region_id": "s-01/t-02",
                    },
                }
            ],
        },
    )

    # --- verify rejection is durable and blockers are unchanged (FR-13 c) ----
    events_after = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    rejection_events = [
        e
        for e in events_after
        if e["event_type"] in {"command_rejected", "graph_patch_rejected"}
        and e["payload"].get("patch_id") == "patch-invalid-actor-blocked"
    ]
    assert rejection_events, "expected rejection event for unauthorized actor patch"
    assert any("fixer" in str(e["payload"].get("reason", "")) for e in rejection_events), (
        f"expected fixer-role rejection, got reasons: "
        f"{[e['payload'].get('reason') for e in rejection_events]}"
    )

    # Injected node must NOT appear in graph state
    graph_after = await _get_json(client, f"/api/runs/{run_id}/graph")
    assert "injected-node" not in graph_after["node_states"], "invalid patch must not create nodes"

    # FR-13 criterion c: blockers unchanged after invalid-patch rejection
    blockers_after = await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers")
    assert blockers_after["blockers"], "blockers must persist after invalid patch rejection"
    blocker_ids_after = {b.get("node_id") for b in blockers_after["blockers"]}
    assert any("t-02" in str(nid) for nid in blocker_ids_after), (
        f"expected T-02 blockers to persist, got {blocker_ids_after}"
    )

    # Run must still be paused (invalid patch did not unblock anything)
    run_after = await _get_json(client, f"/api/runs/{run_id}")
    assert run_after["status"] == RunStatus.PAUSED.value

    # /graph/patches shows the rejected attempt
    patches = await _get_json(client, f"/api/runs/{run_id}/graph/patches")
    invalid_actor_attempts = [
        a for a in patches["attempts"] if a.get("patch_id") == "patch-invalid-actor-blocked"
    ]
    assert invalid_actor_attempts, "rejected patch must appear in /graph/patches"
    assert invalid_actor_attempts[0]["status"] == "rejected"
