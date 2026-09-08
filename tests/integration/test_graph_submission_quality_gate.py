"""Product-path proof for pre-staging graph submission quality gates."""

from __future__ import annotations

import asyncio
import json
import shlex
import subprocess
from pathlib import Path

import pydantic
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import AgentRunnerType, RunStatus, RoutineConfig, load_routine_from_path
from orchestrator.db import (
    GraphSubmissionGateAuditModel,
    GraphSubmissionGateAuditRepository,
    RunModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    PatchCommandContext,
    compile_routine,
    execution_attempts_view,
    leases_view,
    node_states_view,
    reliable_plan_assignment_carrier,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    StaticGraphAgentFactory,
    SubmissionGateCommand,
    capture_submission_gate_baseline,
    enforce_submission_quality_gate,
)
from tests.unit.graph_test_utils import canonical_event_payload
from orchestrator.runners.types import (
    AgentRunnerInfo,
    AgentMetadataCallback,
    ChecklistUpdateCallback,
    EscalationCallback,
    ExecutionContext,
    ExecutionResult,
    GradeCallback,
    LogLineCallback,
    SubmitCallback,
)
from orchestrator.runners import ReliablePlanToolPreflightError
from tests.integration.test_graph_runner_e2e import (
    AgentFactory,
    FixedClock,
    GradingAgent,
    SequentialIds,
    _init_repo,
    _read_events,
    _schedule_dispatch_and_wait,
    _seed_active_run,
)


async def _seed_read_only_discovery(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    run_id: str,
    clock: FixedClock,
    ids: SequentialIds,
) -> GraphController:
    routine_path = Path("routines/dynamic-graph-feature/routine.yaml")
    routine = load_routine_from_path(routine_path)
    compiled = compile_routine(
        routine,
        clock,
        ids,
        run_id=run_id,
        source_path=str(routine_path),
        run_config={
            "feature_spec_path": "docs/spec.md",
            "acceptance_command": "exit 97",
        },
    )
    compiled = [
        event.model_copy(update={"payload": {**event.payload, "state": "completed"}})
        if event.event_type == "node_created" and event.payload.get("node_id") == "planner-s-01"
        else event
        for event in compiled
    ]
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": compiled},
    )
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    patched = await controller.handle_command(
        run_id,
        started.projection_position,
        "submit_patch",
        {
            "patch_id": "read-only-discovery",
            "base_graph_position": started.projection_position,
            "macro_invocations": [
                {
                    "macro": "create_discovery_region",
                    "args": {
                        "region_id": "discovery",
                        "worker_id": "worker-discovery",
                        "semantic_schema_id": "reliable-plan-implementation-plan",
                        "semantic_schema_version": 1,
                        "objective": "Discover the implementation plan.",
                        "acceptance": ["plan is complete"],
                        "requirement_source_node_ids": ["requirement-dynamic-feature-acceptance"],
                    },
                }
            ],
        },
        context=PatchCommandContext(
            run_id=run_id,
            current_graph_position=started.projection_position,
            actor=Actor(kind=ActorKind.CONTROLLER, id="planner-s-01", role="planner"),
            actor_role="planner",
            proposed_by_node_id="planner-s-01",
        ),
    )
    assert any(event.event_type == "graph_patch_accepted" for event in patched.events)
    return controller


@pytest.mark.asyncio
@pytest.mark.parametrize("declared_batch_violation", [False, True])
async def test_dispatch_invalid_worker_contract_is_terminal_not_retryable_infrastructure(
    tmp_path: Path,
    declared_batch_violation: bool,
) -> None:
    engine = create_engine(tmp_path / "invalid-execution-contract.db")
    await init_db(engine)
    sessions: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    repo = tmp_path / "repo-invalid-contract"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "dispatch-invalid-execution-contract"
    agent = ContractGateAgent("readme")
    try:
        async with sessions() as session:
            session.add(
                RunModel(
                    id=run_id,
                    repo_name="invalid-contract-repo",
                    status=RunStatus.ACTIVE.value,
                    execution_mode="graph",
                    source_branch="main",
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )
            worker_payload = {
                "node_id": "worker-legacy-invalid",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "objective": "Implement the requested change.",
                "acceptance": ["requested behavior passes"],
                "access_mode": "write",
            }
            if declared_batch_violation:
                worker_payload.update(
                    {
                        "effect_contract": "effectful_write",
                        "semantic_stage": "corrective_work",
                    }
                )
            events = [
                EventEnvelope(
                    event_id="lifecycle-active",
                    run_id=run_id,
                    position=-1,
                    event_type="run_lifecycle_changed",
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    timestamp=clock.now(),
                    payload=canonical_event_payload(
                        "run_lifecycle_changed", {"to_state": "active"}
                    ),
                ),
                *(
                    [
                        EventEnvelope(
                            event_id="accepted-plan-producer",
                            run_id=run_id,
                            position=-1,
                            event_type="node_created",
                            schema_version=1,
                            actor=Actor(kind=ActorKind.CONTROLLER),
                            timestamp=clock.now(),
                            payload=canonical_event_payload(
                                "node_created",
                                {
                                    "node_id": "worker-plan-discovery",
                                    "kind": "worker",
                                    "role": "discovery",
                                    "state": "completed",
                                    "access_mode": "read_only",
                                    "effect_contract": "read_only_semantic",
                                    "semantic_stage": "discovery",
                                },
                            ),
                        ),
                        EventEnvelope(
                            event_id="accepted-plan",
                            run_id=run_id,
                            position=-1,
                            event_type="output_record_accepted",
                            schema_version=1,
                            actor=Actor(kind=ActorKind.CONTROLLER),
                            timestamp=clock.now(),
                            payload=canonical_event_payload(
                                "output_record_accepted",
                                {
                                    "record_id": "accepted-plan",
                                    "record_kind": "graph_record",
                                    "record_type": "semantic_artifact",
                                    "schema_version": 1,
                                    "producer_node_id": "worker-plan-discovery",
                                    "port": "semantic_artifact",
                                    "schema": "SemanticArtifact",
                                    "value": {
                                        "semantic_role": "implementation_plan",
                                        "schema_id": "declared-plan",
                                        "schema_version": 1,
                                        "content": {"batches": [{"batch_id": "batch-1"}]},
                                        "provenance": {"source": "test"},
                                        "source_record_ids": [],
                                        "requirement_ids": [],
                                        "task_region_id": "plan-discovery",
                                        "validation_status": "validated",
                                        "authority_status": "accepted",
                                    },
                                },
                            ),
                        ),
                    ]
                    if declared_batch_violation
                    else []
                ),
                EventEnvelope(
                    event_id="legacy-worker",
                    run_id=run_id,
                    position=-1,
                    event_type="node_created",
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    timestamp=clock.now(),
                    payload=canonical_event_payload(
                        "node_created",
                        worker_payload,
                    ),
                ),
            ]
            await GraphEventStore(session).append_events(run_id, 0, events)
            await session.commit()
        controller = GraphController(sessions, clock, ids, auto_dispatch=False)
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            AgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts-invalid-contract"),
        )
        dispatcher = OutboxDispatcher(sessions, executor, clock)
        scheduled = await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 60, "max_grants": 1, "base_snapshot_id": "baseline"},
        )
        assert any(event.event_type == "agent_dispatch_requested" for event in scheduled.events)
        await dispatcher.dispatch_pending()
        await executor.wait_for_all()

        events = await _read_events(sessions, run_id)
        failures = [
            event.payload
            for event in events
            if event.event_type == "output_record_accepted"
            and event.payload.get("record_type") == "failure_record"
        ]
        assert len(failures) == 1
        assert failures[0]["value"]["failure_class"] == "invalid_plan_failure"
        assert failures[0]["value"]["error_class"] == "invalid_execution_contract"
        assert failures[0]["value"]["retryable"] is False
        assert not any(
            event.event_type == "runtime_retry_scheduled"
            or event.payload.get("record_type") == "recovery_plan"
            for event in events
        )
        projection = await controller.read_projection(run_id)
        assert node_states_view(projection)["worker-legacy-invalid"] == "failed"
        assert all(lease.state != "active" for lease in leases_view(projection).values())
        assert (repo / "README.md").read_text(encoding="utf-8") != "candidate\n"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_prelaunch_reliable_assignment_error_is_durable_invalid_plan_failure(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "prelaunch-assignment-contract.db")
    await init_db(engine)
    sessions: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    repo = tmp_path / "repo-prelaunch-assignment"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "prelaunch-assignment-contract"
    assignment = {
        "runner_type": "codex_server",
        "model": "gpt-5.6-luna",
        "profile": "coder",
    }
    carrier = reliable_plan_assignment_carrier(
        skeleton_id="reliable-plan-fff4f6b7-v1",
        selected_runner_type="codex_server",
        arm={
            "arm_id": "luna-work-sol-verification",
            "planner": {**assignment, "model": "gpt-5.6-sol", "profile": "architect"},
            "discovery_worker": {**assignment, "profile": "summarizer"},
            "implementation_worker": assignment,
            "correction_worker": assignment,
            "verifier": {**assignment, "model": "gpt-5.6-sol"},
            "successor_planner": {**assignment, "profile": "architect"},
        },
    )
    expected_reason = (
        "reliable-plan execution is missing sealed assignment carrier; "
        "recreate the run with a qualified assignment arm"
    )
    try:
        async with sessions() as session:
            session.add(
                RunModel(
                    id=run_id,
                    repo_name="prelaunch-assignment-repo",
                    status=RunStatus.ACTIVE.value,
                    execution_mode="graph",
                    source_branch="main",
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )
            events = [
                EventEnvelope(
                    event_id="lifecycle-active",
                    run_id=run_id,
                    position=-1,
                    event_type="run_lifecycle_changed",
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    timestamp=clock.now(),
                    payload=canonical_event_payload(
                        "run_lifecycle_changed",
                        {"to_state": "active"},
                    ),
                ),
                EventEnvelope(
                    event_id="reliable-root",
                    run_id=run_id,
                    position=-1,
                    event_type="node_created",
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    timestamp=clock.now(),
                    payload=canonical_event_payload(
                        "node_created",
                        {
                            "node_id": "root",
                            "kind": "root",
                            "role": "run_root",
                            "state": "completed",
                            "reliable_plan_skeleton_id": carrier.skeleton_id,
                            "reliable_plan_assignment_carrier": carrier.model_dump(mode="json"),
                        },
                    ),
                ),
                EventEnvelope(
                    event_id="unstamped-worker",
                    run_id=run_id,
                    position=-1,
                    event_type="node_created",
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    timestamp=clock.now(),
                    payload=canonical_event_payload(
                        "node_created",
                        {
                            "node_id": "worker-missing-assignment",
                            "kind": "worker",
                            "role": "builder",
                            "state": "planned",
                            "objective": "Implement the bounded batch.",
                            "acceptance": ["bounded batch passes"],
                            "access_mode": "write",
                            "effect_contract": "effectful_write",
                            "reliable_plan_skeleton_id": carrier.skeleton_id,
                        },
                    ),
                ),
            ]
            await GraphEventStore(session).append_events(run_id, 0, events)
            await session.commit()

        controller = GraphController(sessions, clock, ids, auto_dispatch=False)
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            StaticGraphAgentFactory(AgentRunnerType.CODEX_SERVER),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts-prelaunch-assignment"),
        )
        dispatcher = OutboxDispatcher(sessions, executor, clock)
        scheduled = await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 60, "max_grants": 1, "base_snapshot_id": "baseline"},
        )
        assert any(event.event_type == "agent_dispatch_requested" for event in scheduled.events)

        await dispatcher.dispatch_pending(run_id=run_id)

        durable_events = await _read_events(sessions, run_id)
        failures = [
            event.payload["value"]
            for event in durable_events
            if event.event_type == "output_record_accepted"
            and event.payload.get("record_type") == "failure_record"
        ]
        assert failures == [
            {
                "failed_node_id": "worker-missing-assignment",
                "phase": "dispatch",
                "failure_class": "invalid_plan_failure",
                "error_class": "invalid_execution_contract",
                "retryable": False,
                "lease_id": scheduled.events[-2].payload["lease_id"],
                "execution_id": scheduled.events[-2].payload["execution_id"],
                "lease_generation": 1,
                "reason": expected_reason,
            }
        ]
        assert not any(
            event.payload.get("reason") == "runtime_execution_missing_no_callback"
            for event in durable_events
        )
        projection = await controller.read_projection(run_id)
        assert node_states_view(projection)["worker-missing-assignment"] == "failed"
        assert all(lease.state != "active" for lease in leases_view(projection).values())
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_planner_tool_preflight_error_is_durable_invalid_plan_failure(
    tmp_path: Path,
) -> None:
    class MissingSuccessorToolCatalog:
        def preflight(
            self,
            context: ExecutionContext,
            *,
            graph_mcp_available: bool,
        ) -> None:
            del context, graph_mcp_available
            raise ReliablePlanToolPreflightError(missing_tools=("create_successor_planner",))

    engine = create_engine(tmp_path / "planner-tool-preflight-contract.db")
    await init_db(engine)
    sessions: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    repo = tmp_path / "repo-planner-tool-preflight"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "planner-tool-preflight-contract"
    assignment = {
        "runner_type": "codex_server",
        "model": "gpt-5.6-luna",
        "profile": "coder",
    }
    carrier = reliable_plan_assignment_carrier(
        skeleton_id="reliable-plan-fff4f6b7-v1",
        selected_runner_type="codex_server",
        arm={
            "arm_id": "luna-work-sol-verification",
            "planner": {**assignment, "model": "gpt-5.6-sol", "profile": "architect"},
            "discovery_worker": {**assignment, "profile": "summarizer"},
            "implementation_worker": assignment,
            "correction_worker": assignment,
            "verifier": {**assignment, "model": "gpt-5.6-sol"},
            "successor_planner": {**assignment, "profile": "architect"},
        },
    )
    expected_reason = (
        "Agent runner 'reliable_plan' configuration error: planner tool preflight failed; "
        "missing tools: create_successor_planner"
    )
    try:
        async with sessions() as session:
            session.add(
                RunModel(
                    id=run_id,
                    repo_name="planner-tool-preflight-repo",
                    status=RunStatus.ACTIVE.value,
                    execution_mode="graph",
                    source_branch="main",
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )
            carrier_payload = carrier.model_dump(mode="json")
            events = [
                EventEnvelope(
                    event_id="lifecycle-active",
                    run_id=run_id,
                    position=-1,
                    event_type="run_lifecycle_changed",
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    timestamp=clock.now(),
                    payload=canonical_event_payload(
                        "run_lifecycle_changed",
                        {"to_state": "active"},
                    ),
                ),
                EventEnvelope(
                    event_id="reliable-root",
                    run_id=run_id,
                    position=-1,
                    event_type="node_created",
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    timestamp=clock.now(),
                    payload=canonical_event_payload(
                        "node_created",
                        {
                            "node_id": "root",
                            "kind": "root",
                            "role": "run_root",
                            "state": "completed",
                            "reliable_plan_skeleton_id": carrier.skeleton_id,
                            "reliable_plan_assignment_carrier": carrier_payload,
                        },
                    ),
                ),
                EventEnvelope(
                    event_id="reliable-planner",
                    run_id=run_id,
                    position=-1,
                    event_type="node_created",
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    timestamp=clock.now(),
                    payload=canonical_event_payload(
                        "node_created",
                        {
                            "node_id": "planner-preflight",
                            "kind": "planner",
                            "role": "planner",
                            "state": "planned",
                            "reliable_plan_skeleton_id": carrier.skeleton_id,
                            "reliable_plan_assignment_carrier": carrier_payload,
                            "reliable_plan_assignment_role": "planner",
                            "reliable_plan_selected_runner_type": "codex_server",
                            "runner_model_override": "gpt-5.6-sol",
                            "profile": "architect",
                        },
                    ),
                ),
            ]
            await GraphEventStore(session).append_events(run_id, 0, events)
            await session.commit()

        controller = GraphController(sessions, clock, ids, auto_dispatch=False)
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            StaticGraphAgentFactory(
                AgentRunnerType.CODEX_SERVER,
                graph_tool_catalog=MissingSuccessorToolCatalog(),
            ),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts-tool-preflight"),
        )
        dispatcher = OutboxDispatcher(sessions, executor, clock)
        scheduled = await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 60, "max_grants": 1, "base_snapshot_id": "baseline"},
        )
        assert any(event.event_type == "agent_dispatch_requested" for event in scheduled.events)

        completed = await dispatcher.dispatch_pending(run_id=run_id)

        assert len(completed) == 1
        assert completed[0].status == "completed"
        assert completed[0].attempts == 1
        assert completed[0].last_error is None
        durable_events = await _read_events(sessions, run_id)
        failures = [
            event.payload["value"]
            for event in durable_events
            if event.event_type == "output_record_accepted"
            and event.payload.get("record_type") == "failure_record"
        ]
        assert len(failures) == 1
        assert failures[0]["failed_node_id"] == "planner-preflight"
        assert failures[0]["failure_class"] == "invalid_plan_failure"
        assert failures[0]["error_class"] == "invalid_execution_contract"
        assert failures[0]["retryable"] is False
        assert failures[0]["reason"] == expected_reason
        assert not any(
            event.payload.get("reason") == "runtime_execution_missing_no_callback"
            for event in durable_events
        )
        projection = await controller.read_projection(run_id)
        assert node_states_view(projection)["planner-preflight"] == "failed"
        assert all(lease.state != "active" for lease in leases_view(projection).values())
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.timeout(90)
async def test_project_uv_gate_uses_disposable_virtualenv_and_exact_checkout() -> None:
    """A production-shaped uv command imports code from the detached snapshot."""
    repo = Path(__file__).resolve().parents[2]
    host_dependency = Path(pydantic.__file__ or "")
    assert host_dependency.is_file()
    host_dependency_before = host_dependency.read_bytes()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    probe = (
        "import orchestrator, pydantic, pathlib; "
        "dependency = pathlib.Path(pydantic.__file__); "
        "original = dependency.read_bytes(); "
        "\ntry: dependency.write_bytes(original + b'\\n# forbidden probe\\n'); mutated = True"
        "\nexcept OSError: mutated = False"
        "\nprint(orchestrator.__file__); print(dependency); print(mutated)"
    )
    command = f"uv run python -c {shlex.quote(probe)}"
    report = await enforce_submission_quality_gate(
        run_id="uv-hermetic-run",
        node_id="uv-hermetic-node",
        execution_id="uv-hermetic-execution",
        lease_id="uv-hermetic-lease",
        lease_generation=1,
        base_snapshot_id="uv-hermetic-base",
        base_tree_sha=tree,
        node_payload={
            "acceptance_commands": [command],
            "acceptance_command_timeout_seconds": 15,
        },
        dynamic_feature=None,
        worktree_path=repo,
        candidate_tree_sha=tree,
        snapshot_commit_sha=commit,
        resolved_commands=(
            SubmissionGateCommand(
                command=command,
                source="node_acceptance_commands",
                timeout_seconds=15,
            ),
        ),
    )

    imported_path_text, dependency_path_text, mutation_text = report.results[
        0
    ].stdout_tail.splitlines()
    imported_path = Path(imported_path_text)
    dependency_path = Path(dependency_path_text)
    assert report.status == "passed"
    assert imported_path.name == "__init__.py"
    assert "orchestrator-submission-gate-" in str(imported_path)
    assert imported_path.exists() is False
    assert dependency_path == host_dependency
    assert mutation_text == "False"
    assert host_dependency.read_bytes() == host_dependency_before


class CorrectingGateAgent:
    """Uses actionable callback failure to correct and resubmit in one turn."""

    def __init__(self) -> None:
        self.first_rejection: str | None = None

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
            name="correcting-gate-agent",
        )

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
        del on_checklist_update, on_output, on_grade, on_agent_metadata, on_escalation
        try:
            await on_submit()
        except ValueError as exc:
            self.first_rejection = str(exc)
        else:
            raise AssertionError("submission unexpectedly passed its failing gate")
        Path(context.working_dir, "README.md").write_text("ready\n", encoding="utf-8")
        await on_submit()
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


class ContractGateAgent:
    """Mutates a real worktree and records a typed gate rejection, if any."""

    def __init__(self, mutation: str) -> None:
        self._mutation = mutation
        self.rejection: str | None = None
        self.execute_count = 0

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
            name="contract-gate-agent",
        )

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
        del on_checklist_update, on_output, on_grade, on_agent_metadata, on_escalation
        self.execute_count += 1
        worktree = Path(context.working_dir)
        if self._mutation == "readme":
            (worktree / "README.md").write_text("candidate\n", encoding="utf-8")
        elif self._mutation == "new_failure":
            (worktree / "new-failure").write_text("present\n", encoding="utf-8")
        else:
            raise AssertionError(f"unknown gate test mutation {self._mutation!r}")
        try:
            await on_submit()
        except ValueError as exc:
            self.rejection = str(exc)
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


@pytest.mark.asyncio
async def test_dispatch_rejects_incomplete_incident_plan_verifier_before_runner_execute(
    tmp_path: Path,
) -> None:
    fixture_path = Path(__file__).parents[1] / "fixtures/graph/ca8faa94_plan_verifier.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    node_payload = dict(fixture["node"])
    node_payload.pop("objective")
    # Cache authority belongs to the incident's routine snapshot.  This focused
    # dispatch graph has no snapshot record; omit only that unrelated carrier so
    # execution reaches the verifier-contract preflight under test.
    node_payload.pop("cache_authority_hash")
    requirement = fixture["requirement"]
    artifact = fixture["artifact"]

    engine = create_engine(tmp_path / "invalid-plan-verifier-contract.db")
    await init_db(engine)
    sessions: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    repo = tmp_path / "repo-invalid-plan-verifier-contract"
    _init_repo(repo)
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "dispatch-invalid-plan-verifier-contract"
    runner = ContractGateAgent("readme")
    try:
        async with sessions() as session:
            session.add(
                RunModel(
                    id=run_id,
                    repo_name="invalid-plan-verifier-contract-repo",
                    status=RunStatus.ACTIVE.value,
                    execution_mode="graph",
                    source_branch="main",
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )
            raw_events = [
                (
                    "run_lifecycle_changed",
                    {"to_state": "active"},
                ),
                (
                    "node_created",
                    {
                        "node_id": "requirement-dynamic-feature-acceptance",
                        "kind": "requirement",
                        "state": "completed",
                    },
                ),
                (
                    "output_record_accepted",
                    requirement,
                ),
                (
                    "node_created",
                    {
                        "node_id": "worker-discovery-description-first",
                        "kind": "worker",
                        "role": "discovery",
                        "state": "completed",
                        "access_mode": "read_only",
                        "effect_contract": "read_only_semantic",
                        "semantic_stage": "discovery",
                    },
                ),
                (
                    "output_record_accepted",
                    artifact,
                ),
                (
                    "node_created",
                    node_payload,
                ),
                (
                    "edge_created",
                    {
                        "edge_id": (
                            "edge-requirement-dynamic-feature-acceptance-requirement-to-"
                            "verifier-plan-description-first"
                        ),
                        "from_node_id": "requirement-dynamic-feature-acceptance",
                        "from_port": "requirement",
                        "to_node_id": "verifier-plan-description-first",
                        "to_port": "requirement_1",
                        "required": True,
                        "accepted_record_selector": {
                            "record_type": "requirement_record",
                        },
                    },
                ),
                (
                    "edge_created",
                    {
                        "edge_id": (
                            "edge-worker-discovery-description-first-semantic-plan-to-"
                            "verifier-plan-description-first"
                        ),
                        "from_node_id": "worker-discovery-description-first",
                        "from_port": "semantic_artifact",
                        "to_node_id": "verifier-plan-description-first",
                        "to_port": "semantic_artifact",
                        "required": True,
                        "accepted_record_selector": {
                            "record_type": "semantic_artifact",
                            "schema": "SemanticArtifact",
                            "semantic_schema_id": "reliable-plan-implementation-plan",
                            "semantic_schema_version": 1,
                            "authority_status": "accepted",
                        },
                    },
                ),
                (
                    "input_bound",
                    {
                        "edge_id": (
                            "edge-requirement-dynamic-feature-acceptance-requirement-to-"
                            "verifier-plan-description-first"
                        ),
                        "to_node_id": "verifier-plan-description-first",
                        "to_port": "requirement_1",
                        "record_ids": ["requirement-dynamic-feature-acceptance"],
                    },
                ),
                (
                    "input_bound",
                    {
                        "edge_id": (
                            "edge-worker-discovery-description-first-semantic-plan-to-"
                            "verifier-plan-description-first"
                        ),
                        "to_node_id": "verifier-plan-description-first",
                        "to_port": "semantic_artifact",
                        "record_ids": [
                            "semantic-artifact-exec-34522d387f504b62a3c18e8c8fa33ac8-"
                            "semantic_artifact"
                        ],
                    },
                ),
            ]
            events = [
                EventEnvelope(
                    event_id=f"incident-{index}",
                    run_id=run_id,
                    position=-1,
                    event_type=event_type,
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    timestamp=clock.now(),
                    payload=canonical_event_payload(event_type, payload),
                )
                for index, (event_type, payload) in enumerate(raw_events)
            ]
            await GraphEventStore(session).append_events(run_id, 0, events)
            await session.commit()

        controller = GraphController(sessions, clock, ids, auto_dispatch=False)
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            AgentFactory({"verifier": runner}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(
                tmp_path / "artifacts-invalid-plan-verifier-contract"
            ),
        )
        dispatcher = OutboxDispatcher(sessions, executor, clock)
        scheduled = await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {"lease_seconds": 60, "max_grants": 1, "base_snapshot_id": "baseline"},
        )
        assert any(event.event_type == "agent_dispatch_requested" for event in scheduled.events)

        await dispatcher.dispatch_pending()
        await executor.wait_for_all()

        assert runner.execute_count == 0
        events = await _read_events(sessions, run_id)
        failures = [
            event.payload
            for event in events
            if event.event_type == "output_record_accepted"
            and event.payload.get("record_type") == "failure_record"
        ]
        assert len(failures) == 1
        assert failures[0]["value"]["failure_class"] == "invalid_plan_failure"
        assert failures[0]["value"]["error_class"] == "invalid_execution_contract"
        assert failures[0]["value"]["retryable"] is False
        assert "missing or empty fields: objective" in failures[0]["value"]["reason"]
        assert not any(
            event.event_type == "runtime_retry_scheduled"
            or event.payload.get("record_type") == "recovery_plan"
            or event.payload.get("reason") == "runner_died"
            for event in events
        )
        projection = await controller.read_projection(run_id)
        assert node_states_view(projection)["verifier-plan-description-first"] == "failed"
        assert all(lease.state != "active" for lease in leases_view(projection).values())
        assert (repo / "README.md").read_text(encoding="utf-8") != "candidate\n"
    finally:
        await engine.dispose()


class HostileReadOnlySemanticAgent:
    """Attempts residue in its runner cwd, then submits a typed semantic artifact."""

    def __init__(self, *, block: bool = False) -> None:
        self.block = block
        self.started = asyncio.Event()
        self.working_dir: Path | None = None

    @property
    def info(self) -> AgentRunnerInfo:
        return AgentRunnerInfo(
            agent_runner_type=AgentRunnerType.CLI_SUBPROCESS,
            name="hostile-read-only-semantic-agent",
        )

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
        del on_checklist_update, on_output, on_grade, on_agent_metadata, on_escalation
        self.working_dir = Path(context.working_dir)
        assert self.working_dir.name == "snapshot"
        assert "orchestrator-submission-gate-" in str(self.working_dir)
        (self.working_dir / "README.md").write_text("hostile runner mutation\n")
        (self.working_dir / ".ignored-read-only-residue").write_text("residue\n")
        self.started.set()
        if self.block:
            await asyncio.Event().wait()
        await on_submit(
            {
                "outputs": {
                    "semantic_artifact": {
                        "summary": "Read-only discovery result",
                        "batches": [
                            {
                                "batch_id": "batch-1",
                                "objective": "Implement the requested feature",
                                "acceptance": ["downstream checks pass"],
                            }
                        ],
                    }
                }
            }
        )
        return ExecutionResult(success=True)

    async def cancel(self) -> None:
        return None


def _submission_gate_routine(
    command: str,
    accepted_fingerprints: list[str],
) -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "submission-gate-contract",
            "name": "Submission gate contract",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Task 1",
                            "accepted_baseline_failure_fingerprints": (accepted_fingerprints),
                            "auto_verify": {
                                "items": [
                                    {
                                        "id": "required-gate",
                                        "cmd": command,
                                        "must": True,
                                    }
                                ]
                            },
                        }
                    ],
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_gate_rejects_before_stage_then_persists_exact_witness_after_correction(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "submission-gate.db")
    await init_db(engine)
    session_factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    repo = tmp_path / "repo"
    _init_repo(repo)
    config_dir = repo / ".task-world"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        'test_command: "grep -q ready README.md"\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", ".task-world/config.yaml"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "declare submission gate",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    clock = FixedClock()
    ids = SequentialIds()
    run_id = "submission-gate-same-session"
    agent = CorrectingGateAgent()

    try:
        controller = await _seed_active_run(session_factory, run_id, clock, ids)
        executor = GraphDispatchExecutor(
            session_factory,
            controller,
            AgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
        dispatcher = OutboxDispatcher(session_factory, executor, clock)

        await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

        assert agent.first_rejection is not None
        assert agent.first_rejection.startswith("submit callback rejected:")
        assert '"disposition":"rejected"' in agent.first_rejection
        assert '"rejection_category":"candidate_check_failed"' in agent.first_rejection
        assert '"exit_code":1' in agent.first_rejection
        assert "grep -q ready README.md" in agent.first_rejection
        events = await _read_events(session_factory, run_id)
        staged = [event for event in events if event.event_type == "runner_submission_staged"]
        assert len(staged) == 1
        witness = staged[0].payload["validation_witness"]
        assert witness["run_id"] == run_id
        assert witness["node_id"] == "worker-step-1-task-1"
        assert witness["execution_id"] == staged[0].payload["execution_id"]
        assert witness["lease_id"] == staged[0].payload["lease_id"]
        assert witness["lease_generation"] == staged[0].payload["lease_generation"]
        assert witness["base_snapshot_id"] == staged[0].payload["base_snapshot_id"]
        assert witness["disposition"] == "passed"
        assert witness["validated_boundary"] == {
            "snapshot_id": staged[0].payload["staged_snapshot_id"],
            "snapshot_ref": staged[0].payload["staged_snapshot_ref"],
            "commit_sha": staged[0].payload["staged_commit_sha"],
            "tree_sha": staged[0].payload["staged_tree_sha"],
            "boundary_hash": staged[0].payload["boundary_hash"],
        }
        (command,) = witness["commands"]
        assert command["source"] == "project_test_command"
        assert command["timeout_seconds"] == 600
        assert command["status"] == "passed"
        assert command["exit_code"] == 0
        assert command["duration_ms"] >= 0
        assert command["stdout_bytes"] >= 0
        assert command["stderr_bytes"] >= 0
        assert len(command["command_sha256"]) == 64
        assert len(command["stdout_sha256"]) == 64
        assert len(command["stderr_sha256"]) == 64
        assert witness["baseline"]["base_tree_sha"]
        assert witness["baseline"]["status"] == "failed"

        async with session_factory() as session:
            audits = await GraphSubmissionGateAuditRepository(session).list_for_run(
                run_id, limit=20
            )
        assert [audit.phase for audit in audits] == [
            "baseline",
            "submission",
            "submission",
        ]
        assert [audit.status for audit in audits] == ["failed", "failed", "passed"]
        assert audits[0].base_tree_sha == witness["baseline"]["base_tree_sha"]
        assert audits[1].candidate_tree_sha is not None
        assert audits[1].failure_fingerprint is None
        assert audits[1].report["results"][0]["failure_identity_status"] == "unknown"
        assert audits[2].candidate_tree_sha == witness["validated_boundary"]["tree_sha"]

        projection = await controller.read_projection(run_id)
        attempt = execution_attempts_view(projection)[staged[0].payload["execution_id"]]
        assert attempt.validation_witness is not None
        # Only the corrected submission staged/finalized. The rejected callback
        # neither consumed its lease nor created a competing execution.
        assert len(leases_view(projection)) == 1
        assert node_states_view(projection)["worker-step-1-task-1"] == "completed"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "mutation", "baseline_status", "accepted", "expected_disposition"),
    [
        ("unchanged_explicit", "readme", "failed", True, "baseline_exempted"),
        ("unchanged_missing", "readme", "failed", False, "failed"),
        ("changed_failure", "readme", "failed", False, "failed"),
        ("new_failure", "new_failure", "passed", False, "failed"),
    ],
)
async def test_compiled_gate_contract_survives_seed_and_controls_full_dispatch(
    tmp_path: Path,
    scenario: str,
    mutation: str,
    baseline_status: str,
    accepted: bool,
    expected_disposition: str,
) -> None:
    """Use the real seed/controller/dispatcher/Git/CAS path for gate authority."""
    engine = create_engine(tmp_path / f"{scenario}.db")
    await init_db(engine)
    session_factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    repo = tmp_path / f"repo-{scenario}"
    _init_repo(repo)
    marker = tmp_path / f"{scenario}-gate-executions"
    marker_arg = shlex.quote(str(marker))
    if scenario in {"unchanged_explicit", "unchanged_missing"}:
        command = (
            f"printf x >> {marker_arg}; "
            "printf 'FAILED tests/unit/test_known.py::test_red - details\\n' >&2; exit 8"
        )
    elif scenario == "changed_failure":
        command = (
            f"printf x >> {marker_arg}; "
            "if grep -q candidate README.md; then "
            "printf 'FAILED tests/unit/test_after.py::test_red - details\\n' >&2; "
            "else printf 'FAILED tests/unit/test_before.py::test_red - details\\n' >&2; fi; "
            "exit 8"
        )
    else:
        command = (
            f"printf x >> {marker_arg}; "
            "if test -f new-failure; then "
            "printf 'FAILED tests/unit/test_new.py::test_red - details\\n' >&2; exit 9; fi"
        )

    probe_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    probe_tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    probe = await capture_submission_gate_baseline(
        run_id="fingerprint-probe",
        node_id="worker-step-1-task-1",
        execution_id="exec-probe",
        lease_id="lease-probe",
        lease_generation=1,
        base_snapshot_id="snapshot-probe",
        base_tree_sha=probe_tree,
        node_payload={"acceptance_commands": [command]},
        dynamic_feature=None,
        worktree_path=repo,
        snapshot_commit_sha=probe_commit,
    )
    assert probe.status == baseline_status
    declared = (
        list(probe.failure_fingerprints)
        if scenario in {"unchanged_explicit", "changed_failure"}
        else []
    )
    marker.unlink()

    clock = FixedClock()
    ids = SequentialIds()
    run_id = f"full-dispatch-{scenario}"
    agent = ContractGateAgent(mutation)
    artifact_store = FilesystemArtifactStore(tmp_path / f"artifacts-{scenario}")
    try:
        controller = await _seed_active_run(
            session_factory,
            run_id,
            clock,
            ids,
            routine=_submission_gate_routine(command, declared),
        )
        executor = GraphDispatchExecutor(
            session_factory,
            controller,
            AgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=artifact_store,
        )
        dispatcher = OutboxDispatcher(session_factory, executor, clock)

        await _schedule_dispatch_and_wait(controller, dispatcher, executor, run_id)

        events = await _read_events(session_factory, run_id)
        baseline_event = next(
            event for event in events if event.event_type == "runner_baseline_recorded"
        )
        async with session_factory() as session:
            repository = GraphSubmissionGateAuditRepository(session)
            original_audits = await repository.list_for_run(run_id, limit=20)
        assert [audit.phase for audit in original_audits] == ["baseline", "submission"]
        assert [audit.status for audit in original_audits] == [
            baseline_status,
            expected_disposition,
        ]
        baseline_audit, submission_audit = original_audits
        assert baseline_audit.base_tree_sha == baseline_event.payload["baseline_tree_sha"]
        assert baseline_audit.report["base_tree_sha"] == baseline_audit.base_tree_sha
        assert baseline_audit.report["results"][0]["command"] == command
        assert baseline_audit.report["results"][0]["source"] == "node_acceptance_commands"
        assert submission_audit.candidate_tree_sha is not None
        assert submission_audit.candidate_tree_sha != submission_audit.base_tree_sha
        assert marker.read_text(encoding="utf-8") == "xx"

        canonical_audits = tuple(
            (
                audit.id,
                audit.phase,
                audit.status,
                audit.base_tree_sha,
                audit.candidate_tree_sha,
                audit.failure_fingerprint,
                audit.report,
            )
            for audit in original_audits
        )
        async with session_factory() as session:
            await session.execute(
                delete(GraphSubmissionGateAuditModel).where(
                    GraphSubmissionGateAuditModel.run_id == run_id
                )
            )
            await session.commit()
        async with session_factory() as session:
            rebuilt = await GraphSubmissionGateAuditRepository(session).list_for_run(
                run_id, limit=20
            )
        assert (
            tuple(
                (
                    audit.id,
                    audit.phase,
                    audit.status,
                    audit.base_tree_sha,
                    audit.candidate_tree_sha,
                    audit.failure_fingerprint,
                    audit.report,
                )
                for audit in rebuilt
            )
            == canonical_audits
        )

        terminal_types = (
            "runner_submission_staged",
            "runner_completion_witnessed",
            "runner_execution_finalized",
            "callback_accepted",
            "lease_released",
        )
        counts = {
            event_type: sum(event.event_type == event_type for event in events)
            for event_type in terminal_types
        }
        if accepted:
            assert agent.rejection is None
            assert counts == {event_type: 1 for event_type in terminal_types}
            ordered = [event.event_type for event in events if event.event_type in terminal_types]
            assert ordered == list(terminal_types)
            staged = next(
                event for event in events if event.event_type == "runner_submission_staged"
            )
            witness = staged.payload["validation_witness"]
            assert witness["disposition"] == "baseline_exempted"
            assert witness["baseline"] == baseline_audit.report
            assert witness["baseline"]["base_tree_sha"] == baseline_audit.base_tree_sha
            assert witness["baseline"]["failure_fingerprints"] == declared
            assert witness["commands"][0]["command"] == command
            assert witness["commands"][0]["status"] == "failed"
            assert witness["commands"][0]["source"] == "node_acceptance_commands"
            assert witness["validated_boundary"] == {
                "snapshot_id": staged.payload["staged_snapshot_id"],
                "snapshot_ref": staged.payload["staged_snapshot_ref"],
                "commit_sha": staged.payload["staged_commit_sha"],
                "tree_sha": staged.payload["staged_tree_sha"],
                "boundary_hash": staged.payload["boundary_hash"],
            }
            assert submission_audit.candidate_tree_sha == staged.payload["staged_tree_sha"]
            assert submission_audit.report["status"] == "baseline_exempted"
            assert (
                submission_audit.report["candidate_tree_sha"] == staged.payload["staged_tree_sha"]
            )
        else:
            assert agent.rejection is not None
            assert '"rejection_category":"candidate_check_failed"' in agent.rejection
            assert counts == {event_type: 0 for event_type in terminal_types}
            failure = submission_audit.report["results"][0]
            assert failure["command"] == command
            assert failure["source"] == "node_acceptance_commands"
            assert failure["status"] == "failed"
            assert submission_audit.failure_fingerprint is not None
            if scenario == "unchanged_missing":
                assert (
                    submission_audit.failure_fingerprint
                    in baseline_audit.report["failure_fingerprints"]
                )
            elif scenario == "changed_failure":
                assert (
                    submission_audit.failure_fingerprint
                    not in baseline_audit.report["failure_fingerprints"]
                )
            else:
                assert baseline_audit.report["failure_fingerprints"] == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True], ids=["success", "cancel"])
async def test_read_only_semantic_runner_uses_disposable_exact_baseline_checkout(
    tmp_path: Path,
    cancelled: bool,
) -> None:
    engine = create_engine(tmp_path / f"read-only-{cancelled}.db")
    await init_db(engine)
    session_factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    repo = tmp_path / f"repo-read-only-{cancelled}"
    _init_repo(repo)
    (repo / ".gitignore").write_text(".ignored-*\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "ignore runner residue"], cwd=repo, check=True)
    baseline_bytes = (repo / "README.md").read_bytes()
    clock = FixedClock()
    ids = SequentialIds()
    run_id = f"read-only-dispatch-{cancelled}"
    agent = HostileReadOnlySemanticAgent(block=cancelled)
    try:
        controller = await _seed_read_only_discovery(
            session_factory,
            run_id=run_id,
            clock=clock,
            ids=ids,
        )
        async with session_factory() as session:
            session.add(
                RunModel(
                    id=run_id,
                    repo_name=f"repo-{cancelled}",
                    status=RunStatus.ACTIVE.value,
                    execution_mode="graph",
                    source_branch="main",
                    created_at=clock.now(),
                    updated_at=clock.now(),
                )
            )
            await session.commit()
        executor = GraphDispatchExecutor(
            session_factory,
            controller,
            AgentFactory({"worker": agent, "verifier": GradingAgent("A")}),
            worktree_path=repo,
            artifact_store=FilesystemArtifactStore(tmp_path / f"artifacts-{cancelled}"),
        )
        dispatcher = OutboxDispatcher(session_factory, executor, clock)
        scheduled = await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {
                "lease_seconds": 60,
                "max_grants": 1,
                "base_snapshot_id": "baseline",
                "priorities": {"worker-discovery": 100},
            },
        )
        assert any(
            event.event_type == "agent_dispatch_requested"
            and event.payload.get("node_id") == "worker-discovery"
            for event in scheduled.events
        ), [
            (event.event_type, event.payload.get("node_id"), event.payload.get("reason"))
            for event in scheduled.events
        ]
        await dispatcher.dispatch_pending()
        await asyncio.wait_for(agent.started.wait(), timeout=5)
        if cancelled:
            executor.cancel_all()
            with pytest.raises(asyncio.CancelledError):
                await executor.wait_for_all()
        else:
            await executor.wait_for_all()

        assert agent.working_dir is not None
        assert agent.working_dir.exists() is False
        assert (repo / "README.md").read_bytes() == baseline_bytes
        assert (repo / ".ignored-read-only-residue").exists() is False
        async with session_factory() as session:
            audits = await GraphSubmissionGateAuditRepository(session).list_for_run(
                run_id, limit=20
            )
        assert audits[0].phase == "baseline"
        assert audits[0].status == "no_configured_commands"
        assert audits[0].report["results"] == []
        if not cancelled:
            assert audits[1].phase == "submission"
            assert audits[1].status == "no_configured_commands"
    finally:
        await engine.dispose()
