"""Deterministic end-to-end harness for the dynamic execution graph.

This drives the *production* ``dynamic-graph-feature`` routine through the real
``GraphRunDriver`` / ``GraphController`` / ``GraphDispatchExecutor`` / pure kernel
stack against a temp SQLite database and a temp git repo, using **scripted**
in-process agents instead of a real LLM runner.

The whole point: the DG-5.1 saga (slices a..v plus 5.2b..d) found ~25 graph
*orchestration* bugs one expensive live run at a time — port-name mismatches,
missing required edges, gap-classification binding, lease recovery, premature
completion, and so on. None of those bugs were about agent intelligence; the
dispatch executor already synthesises every output record from the node
kind/role. A scripted runner that calls the same callbacks in the same order
exercises every one of those code paths deterministically, in CI, for zero
tokens.

Each scenario here corresponds to a real failure mode the live runs hit. New
live failures should be reproduced here *first*, then fixed.
"""

from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.config import load_routine_from_path
from orchestrator.config.enums import AgentRunnerType, RunStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.db import RunRepository, create_engine, create_session_factory, init_db
from orchestrator.graph import project_run_state, project_task_states
from orchestrator.graph_runtime import GraphController, GraphDispatchContext, GraphDispatchExecutor
from orchestrator.graph_runtime.store import GraphEventStore
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
from orchestrator.workflow import WorkflowService
from orchestrator.workflow.graph_driver import GraphRunDriver

ROUTINE_PATH = (
    Path(__file__).resolve().parents[2] / "routines" / "dynamic-graph-feature" / "routine.yaml"
)


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
    def __init__(self) -> None:
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{prefix}-{self._next}"
        self._next += 1
        return value


class AgentFactory:
    def __init__(self, agents: dict[str, AgentRunner], dispatch_order: list[str]) -> None:
        self._agents = agents
        self._dispatch_order = dispatch_order

    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        label = context.node_kind if context.node_kind != "planner" else context.node_role
        self._dispatch_order.append(label)
        return self._agents[context.node_kind]


# --------------------------------------------------------------------------- #
# Canonical patch shapes (mirroring graph_runtime.horizon_templates)            #
# --------------------------------------------------------------------------- #
def _root_planner_patch(proposed_by: str) -> dict[str, Any]:
    """Root planner builds the full work graph minus the final invariant check.

    Mirrors the shape of the accepted live smoke run ``0c053df6``: implementation
    + weak validation + a gap planner, plus the pre-wired corrective region whose
    worker is gated on the gap planner's ``classified_gap`` decision. The gap
    planner appends only the final invariant check, so a gap *no-op* is correctly
    rejected (a required ``classified_gap`` successor already exists).

    ``feature-region`` groups the implementation worker, its verifier, and the
    gap planner so the region reaches ``accepted`` once the candidate is graded;
    the corrective nodes share ``corrective_work_region`` as the gap-planner role
    policy requires.
    """

    return {
        "patch_id": "patch-ds-root-plan",
        "proposed_by_node_id": proposed_by,
        "base_graph_position": 0,
        "ops": [
            {
                "op": "create_node",
                "node": {
                    "node_id": "worker-ds-builder",
                    "kind": "worker",
                    "role": "builder",
                    "state": "planned",
                    "task_region_id": "feature-region",
                    "attempt_number": 1,
                    "candidate_id": "cand-ds",
                },
            },
            {
                "op": "create_node",
                "node": {
                    "node_id": "verifier-ds-initial",
                    "kind": "verifier",
                    "role": "verifier",
                    "state": "planned",
                    "task_region_id": "feature-region",
                    "candidate_id": "cand-ds",
                    "rubric": ["candidate satisfies the bound requirements"],
                },
            },
            {
                "op": "create_node",
                "node": {
                    "node_id": "planner-ds-gap",
                    "kind": "planner",
                    "role": "gap_planner",
                    "state": "planned",
                    "task_region_id": "feature-region",
                },
            },
            {
                "op": "create_node",
                "node": {
                    "node_id": "worker-ds-corrective",
                    "kind": "worker",
                    "role": "fixer",
                    "state": "planned",
                    "task_region_id": "corrective_work_region",
                    "attempt_number": 2,
                    "candidate_id": "cand-ds-fix",
                },
            },
            {
                "op": "create_node",
                "node": {
                    "node_id": "verifier-ds-corrective",
                    "kind": "verifier",
                    "role": "verifier",
                    "state": "planned",
                    "task_region_id": "corrective_work_region",
                    "candidate_id": "cand-ds-fix",
                    "rubric": ["corrective candidate resolves the classified gap"],
                },
            },
            {
                "op": "create_edge",
                "edge_id": "edge-ds-impl-validation",
                "from_node_id": "worker-ds-builder",
                "from_port": "candidate",
                "to_node_id": "verifier-ds-initial",
                "to_port": "candidate_under_test",
                "required": True,
                "accepted_record_selector": {"record_kinds": ["candidate"]},
            },
            {
                "op": "create_edge",
                "edge_id": "edge-ds-validation-gap",
                "from_node_id": "verifier-ds-initial",
                "from_port": "verification_report",
                "to_node_id": "planner-ds-gap",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {"record_kinds": ["verification", "check_result"]},
            },
            {
                "op": "create_edge",
                "edge_id": "edge-ds-gap-corrective",
                "from_node_id": "planner-ds-gap",
                "from_port": "classified_gap",
                "to_node_id": "worker-ds-corrective",
                "to_port": "classified_gap",
                "required": True,
                "accepted_record_selector": {"record_kinds": ["gap_analysis"]},
            },
            {
                "op": "create_edge",
                "edge_id": "edge-ds-corrective-validation",
                "from_node_id": "worker-ds-corrective",
                "from_port": "candidate",
                "to_node_id": "verifier-ds-corrective",
                "to_port": "candidate_under_test",
                "required": True,
                "accepted_record_selector": {"record_kinds": ["candidate"]},
            },
        ],
    }


def _gap_planner_patch(proposed_by: str) -> dict[str, Any]:
    """Gap planner appends the final invariant check bound to corrective evidence.

    The check targets ``corrective_work_region`` (gap-planner role policy) and
    binds the *corrective* verifier's report, so completion waits on the fresh
    post-correction evidence. Submitting this accepted, non-empty patch is what
    flips the gap planner into emitting its ``classified_gap`` record, releasing
    the pre-wired corrective worker.
    """

    return {
        "patch_id": "patch-ds-gap-invariant",
        "proposed_by_node_id": proposed_by,
        "base_graph_position": 0,
        "ops": [
            {
                "op": "create_node",
                "node": {
                    "node_id": "check-ds-invariant",
                    "kind": "check",
                    "role": "invariant_gate",
                    "state": "planned",
                    "task_region_id": "corrective_work_region",
                    "command_binding": "dynamic_feature_hidden_oracle",
                },
            },
            {
                "op": "create_edge",
                "edge_id": "edge-ds-corrective-invariant",
                "from_node_id": "verifier-ds-corrective",
                "from_port": "verification_report",
                "to_node_id": "check-ds-invariant",
                "to_port": "verification_evidence",
                "required": True,
                "accepted_record_selector": {"record_kinds": ["verification", "check_result"]},
            },
        ],
    }


def _gap_planner_no_op() -> dict[str, Any]:
    return {"patch_id": "patch-ds-gap-no-op", "base_graph_position": 0, "ops": []}


# --------------------------------------------------------------------------- #
# Scripted agents                                                               #
# --------------------------------------------------------------------------- #
class _BaseAgent:
    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(agent_runner_type=AgentRunnerType.CLI_SUBPROCESS, name="scripted")

    async def cancel(self) -> None:
        return None


class WorkerAgent(_BaseAgent):
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
        await on_submit()
        return ExecutionResult(success=True)


class VerifierAgent(_BaseAgent):
    def __init__(self, grade: str = "A") -> None:
        self._grade = grade

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
            await on_grade("req-1", self._grade, None)
        await on_submit()
        return ExecutionResult(success=True)


class CheckAgent(_BaseAgent):
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
        await on_submit()
        return ExecutionResult(success=True)


class NoSubmitAgent(_BaseAgent):
    """Returns successfully without ever calling ``on_submit`` — the live failure
    mode behind DG-5.1d. The runtime must record ``agent_died`` and recover the
    lease instead of leaving it active and quiescing silently.
    """

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
        return ExecutionResult(success=True)


class DynamicPlannerAgent(_BaseAgent):
    """Drives both the root planner head and the appended gap planner.

    Routed purely by ``context.node_role`` so a single class handles the whole
    planner family the way the production dispatch does.
    """

    def __init__(self, *, gap_no_op_first: bool = False, root_skip_submit: bool = False) -> None:
        self._gap_no_op_first = gap_no_op_first
        self._root_skip_submit = root_skip_submit
        self.patch_feedback: list[str] = []

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
        assert context.graph_patch_callback is not None, "planner must receive patch callback"
        submit_patch = context.graph_patch_callback

        if context.node_role == "gap_planner":
            if self._gap_no_op_first:
                self.patch_feedback.append(await submit_patch(_gap_planner_no_op()))
            self.patch_feedback.append(await submit_patch(_gap_planner_patch(context.node_id)))
            await on_submit()
        else:
            self.patch_feedback.append(await submit_patch(_root_planner_patch(context.node_id)))
            # DG-5.1m: a root planner that has an accepted patch but exits without
            # plain submit must be completed by the guard, not re-leased for a
            # duplicate root patch.
            if not self._root_skip_submit:
                await on_submit()

        return ExecutionResult(success=True)


# --------------------------------------------------------------------------- #
# Fixtures / helpers                                                            #
# --------------------------------------------------------------------------- #
@pytest.fixture
async def file_db(
    tmp_path: Path,
) -> AsyncGenerator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]], None]:
    engine = create_engine(tmp_path / "graph-dynamic-e2e.db")
    await init_db(engine)
    yield engine, create_session_factory(engine)
    await engine.dispose()


def _routine() -> RoutineConfig:
    return load_routine_from_path(ROUTINE_PATH)


def _run_config() -> dict[str, Any]:
    # feature_spec_content is supplied inline so the driver does not need to read
    # the spec from the worktree, keeping the harness self-contained.
    return {
        "feature_spec_path": "docs/dynamic-smoke.md",
        "feature_spec_content": "Produce dynamic-smoke output; validation-strengthened required.",
        "acceptance_command": "test -f docs/graph-approach/dynamic-smoke-output.txt",
        "hidden_oracle_command": "grep -q dynamic-smoke docs/graph-approach/dynamic-smoke-output.txt",
        "patch_budget": 8,
        "gap_policy_profile": "standard",
    }


def _init_repo(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("# tmp repo\n")
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
    config: dict[str, Any],
) -> None:
    run = create_run_from_routine(routine, repo_name=repo.name, source_branch="main", config=config)
    run.id = run_id
    run.execution_mode = "graph"
    run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
    run.worktree_path = str(repo)
    run.agent_runner_type = AgentRunnerType.CLI_SUBPROCESS
    async with session_factory() as session:
        service = WorkflowService(session)
        await service.create_run(run)


def _driver(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    repo: Path,
    agents: dict[str, AgentRunner],
    dispatch_order: list[str],
) -> GraphRunDriver:
    clock = FixedClock()
    ids = SequentialIds()

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
            AgentFactory(agents, dispatch_order),
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


async def _events(session_factory: async_sessionmaker[AsyncSession], run_id: str):
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


async def _run_status(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> RunStatus:
    async with session_factory() as session:
        return (await RunRepository(session).get(run_id)).status


# --------------------------------------------------------------------------- #
# Scenarios                                                                     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_dynamic_full_happy_path_completes(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """End-to-end: planner -> builder -> verifier -> gap -> corrective -> check.

    Proves the entire dynamic carrier closes the loop deterministically, with no
    real runner and no manual graph mutation. This is the regression net the
    DG-5.1 saga lacked.
    """

    _, session_factory = file_db
    repo = tmp_path / "repo-happy"
    _init_repo(repo)
    run_id = "graph-dynamic-happy"
    await _create_graph_run(
        session_factory, _routine(), run_id=run_id, repo=repo, config=_run_config()
    )
    dispatch_order: list[str] = []
    driver = _driver(
        session_factory,
        repo=repo,
        agents={
            "planner": DynamicPlannerAgent(),
            "worker": WorkerAgent(),
            "verifier": VerifierAgent("A"),
            "check": CheckAgent(),
        },
        dispatch_order=dispatch_order,
    )

    outcome = await driver.run(run_id)

    events = await _events(session_factory, run_id)
    assert dispatch_order == [
        "planner",
        "worker",
        "verifier",
        "gap_planner",
        "worker",
        "verifier",
        "check",
    ]
    assert outcome.completed is True, outcome.blocked_reason
    assert project_run_state(events) == "completed"
    assert await _run_status(session_factory, run_id) == RunStatus.COMPLETED

    accepted_patches = [
        event.payload.get("patch_id")
        for event in events
        if event.event_type == "graph_patch_accepted"
    ]
    assert accepted_patches == ["patch-ds-root-plan", "patch-ds-gap-invariant"]

    task_states = project_task_states(events)
    assert task_states, "expected dynamic task regions to be projected"
    assert all(state == "accepted" for state in task_states.values()), task_states


@pytest.mark.asyncio
async def test_dynamic_gap_no_op_is_rejected_then_corrective_completes(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """Gap planner no-op (DG-5.1j) is rejected because a required classified_gap
    successor is unsatisfied; the rejected-patch guard (DG-5.1p) keeps the node
    alive, and the corrective patch then drives the run to completion.
    """

    _, session_factory = file_db
    repo = tmp_path / "repo-gap-noop"
    _init_repo(repo)
    run_id = "graph-dynamic-gap-noop"
    await _create_graph_run(
        session_factory, _routine(), run_id=run_id, repo=repo, config=_run_config()
    )
    dispatch_order: list[str] = []
    planner = DynamicPlannerAgent(gap_no_op_first=True)
    driver = _driver(
        session_factory,
        repo=repo,
        agents={
            "planner": planner,
            "worker": WorkerAgent(),
            "verifier": VerifierAgent("A"),
            "check": CheckAgent(),
        },
        dispatch_order=dispatch_order,
    )

    outcome = await driver.run(run_id)

    events = await _events(session_factory, run_id)
    assert outcome.completed is True, outcome.blocked_reason
    assert project_run_state(events) == "completed"

    rejected = [
        event.payload.get("reason")
        for event in events
        if event.event_type in {"graph_patch_rejected", "command_rejected"}
    ]
    assert any(reason and "classified_gap" in reason for reason in rejected), (
        f"expected a classified_gap no-op rejection, got {rejected}"
    )


@pytest.mark.asyncio
async def test_dynamic_run_does_not_complete_while_final_invariant_unmet(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """The final invariant check exists and is bound, but its agent exits without
    submitting. Two guarantees must hold together:

    * the runtime records ``agent_died`` and recovers the lease (DG-5.1d) rather
      than leaving an active lease and quiescing silently;
    * the run does **not** reach ``completed`` while the final invariant check is
      unsatisfied (DG-5.1t / DG-3.3 premature-completion guard).
    """

    _, session_factory = file_db
    repo = tmp_path / "repo-no-submit-check"
    _init_repo(repo)
    run_id = "graph-dynamic-no-submit-check"
    await _create_graph_run(
        session_factory, _routine(), run_id=run_id, repo=repo, config=_run_config()
    )
    dispatch_order: list[str] = []
    driver = _driver(
        session_factory,
        repo=repo,
        agents={
            "planner": DynamicPlannerAgent(),
            "worker": WorkerAgent(),
            "verifier": VerifierAgent("A"),
            "check": NoSubmitAgent(),  # final invariant check never submits
        },
        dispatch_order=dispatch_order,
    )

    outcome = await driver.run(run_id)

    events = await _events(session_factory, run_id)
    assert outcome.completed is False
    assert outcome.blocked_reason is not None
    assert project_run_state(events) != "completed"
    assert await _run_status(session_factory, run_id) == RunStatus.PAUSED
    assert any(
        event.event_type == "agent_died"
        and "without submit" in str(event.payload.get("reason", ""))
        for event in events
    ), "expected an agent_died 'exited without submit' event for the check node"


@pytest.mark.asyncio
async def test_dynamic_root_planner_accepted_patch_then_no_submit_does_not_duplicate(
    file_db: tuple[AsyncEngine, async_sessionmaker[AsyncSession]],
    tmp_path: Path,
) -> None:
    """DG-5.1m: a root planner that gets an accepted patch but exits without plain
    submit is completed by the guard and is *not* re-leased for a duplicate root
    patch. Exactly one ``patch-ds-root-plan`` is accepted and the run still
    completes through the appended graph.
    """

    _, session_factory = file_db
    repo = tmp_path / "repo-root-no-submit"
    _init_repo(repo)
    run_id = "graph-dynamic-root-no-submit"
    await _create_graph_run(
        session_factory, _routine(), run_id=run_id, repo=repo, config=_run_config()
    )
    dispatch_order: list[str] = []
    driver = _driver(
        session_factory,
        repo=repo,
        agents={
            "planner": DynamicPlannerAgent(root_skip_submit=True),
            "worker": WorkerAgent(),
            "verifier": VerifierAgent("A"),
            "check": CheckAgent(),
        },
        dispatch_order=dispatch_order,
    )

    outcome = await driver.run(run_id)

    events = await _events(session_factory, run_id)
    root_patches = [
        event
        for event in events
        if event.event_type == "graph_patch_accepted"
        and event.payload.get("patch_id") == "patch-ds-root-plan"
    ]
    assert len(root_patches) == 1, "root planner must not produce a duplicate accepted patch"
    assert outcome.completed is True, outcome.blocked_reason
    assert project_run_state(events) == "completed"
