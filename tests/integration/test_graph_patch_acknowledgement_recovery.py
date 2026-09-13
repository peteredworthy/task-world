from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
from typing import Any

import pytest

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import AgentRunnerType, RoutineConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    EventEnvelope,
    FakeClock,
    PatchCommandContext,
    SubmitPatchCommand,
    compile_routine,
    edges_view,
    event_factory,
    execution_attempts_view,
    expand_patch_macros,
    node_kinds_view,
    node_payload_view,
    non_gap_planner_completion_contract_satisfied,
    output_record_payloads_view,
    planner_generations_view,
)
from orchestrator.graph_runtime import (
    build_graph_mcp_server,
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    PatchOperationConflictError,
    StaticGraphAgentFactory,
    StaleProjectionError,
)
from orchestrator.runners import CodexServerAgent


class _AcknowledgementLost(RuntimeError):
    pass


class _CommitInterruption:
    def __init__(self, phase: str) -> None:
        self.phase = phase
        self.triggered = False

    async def __call__(
        self,
        phase: str,
        _run_id: str,
        command_type: str,
        _events: tuple[EventEnvelope, ...],
    ) -> None:
        if command_type == "submit_patch" and not any(
            event.event_type == "graph_patch_accepted" for event in _events
        ):
            raise AssertionError([(event.event_type, event.payload) for event in _events])
        if not self.triggered and command_type == "submit_patch" and phase == self.phase:
            self.triggered = True
            raise _AcknowledgementLost(phase)


class _Ids:
    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self.value = 0

    def next_id(self, prefix: str = "") -> str:
        self.value += 1
        return f"{self.namespace}-{prefix}-{self.value}"


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "dynamic-graph-feature",
            "name": "Patch reconciliation",
            "planner_generation_budget": 2,
            "semantic_artifact_schemas": [
                {
                    "schema_id": "ordered-plan",
                    "version": 1,
                    "semantic_role": "implementation_plan",
                    "json_schema": {
                        "type": "object",
                        "required": ["batches"],
                        "properties": {"batches": {"type": "array"}},
                    },
                }
            ],
            "steps": [
                {
                    "id": "plan",
                    "kind": "planner",
                    "title": "Plan one region",
                    "available_tools": [
                        "submit_graph_patch",
                        "construct_reliable_plan_region",
                    ],
                }
            ],
        }
    )


def _patch(base_graph_position: int, *, patch_id: str = "logical-region-1") -> dict[str, Any]:
    return {
        "patch_id": patch_id,
        "base_graph_position": base_graph_position,
        "macro_invocations": [
            {
                "macro": "construct_reliable_plan_region",
                "args": {
                    "operation_key": "logical-region-1",
                    "scope": "bounded feature",
                    "objective": "Discover and verify the bounded implementation plan.",
                    "requirement_ids": ["dynamic_feature_acceptance"],
                    "dependencies": [],
                    "acceptance": ["the plan covers the bounded feature"],
                    "checks": [],
                    "rubric": ["the plan is complete and independently executable"],
                },
            },
        ],
    }


async def _active_planner(
    controller: GraphController,
    run_id: str,
    clock: FakeClock,
    ids: _Ids,
    *,
    hidden_oracle_command: str | None = None,
    max_rejected_plan_proposals_per_planner: int | None = None,
    max_planner_executions_per_node: int | None = None,
) -> int:
    run_config: dict[str, Any] = {
        "acceptance_command": "true",
        "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
        "reliable_plan_selected_runner_type": "codex_server",
        "reliable_plan_one_horizon_authorized": True,
        "reliable_plan_remaining_horizons": 2,
        "reliable_plan_qualification_evidence_hash": "sha256:" + "a" * 64,
        "reliable_plan_model_assignments": {
            "arm_id": "durable-recovery-arm",
            **{
                role: {
                    "runner_type": "codex_server",
                    "model": "user-selected-model",
                    "profile": profile,
                }
                for role, profile in {
                    "planner": "architect",
                    "discovery_worker": "summarizer",
                    "implementation_worker": "coder",
                    "correction_worker": "coder",
                    "verifier": "coder",
                    "successor_planner": "architect",
                }.items()
            },
        },
    }
    if hidden_oracle_command is not None:
        run_config["hidden_oracle_command"] = hidden_oracle_command
    if max_rejected_plan_proposals_per_planner is not None:
        run_config["max_rejected_plan_proposals_per_planner"] = (
            max_rejected_plan_proposals_per_planner
        )
    if max_planner_executions_per_node is not None:
        run_config["max_planner_executions_per_node"] = max_planner_executions_per_node
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {
            "events": compile_routine(
                _routine(),
                clock,
                ids,
                run_id=run_id,
                run_config=run_config,
            )
        },
    )
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    return started.projection_position


@pytest.mark.asyncio
async def test_reliable_plan_rejection_limit_survives_executor_reconstruction(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "proposal-limit.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    clock = FakeClock()
    ids = _Ids("proposal-limit")
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    run_id = "proposal-limit-run"
    await _active_planner(
        controller,
        run_id,
        clock,
        ids,
        max_rejected_plan_proposals_per_planner=2,
        max_planner_executions_per_node=1,
    )

    async def reject_with(
        executor: GraphDispatchExecutor,
        patch_id: str,
        *,
        malformed_command: bool = False,
    ) -> str:
        projection = await controller.read_projection(run_id)
        async with sessions() as session:
            events = await GraphEventStore(session).read_run(run_id)
        planner_payload = node_payload_view(projection, "planner-plan")
        assert isinstance(planner_payload, dict)
        context = GraphDispatchContext(
            run_id=run_id,
            node_id="planner-plan",
            node_kind="planner",
            node_role="planner",
            node_payload=planner_payload,
            requirements=[],
            worktree_path=str(tmp_path),
            lease_id="lease-limit",
            lease_generation=1,
            execution_id="execution-limit",
            base_snapshot_id="routine-snapshot",
            dispatch_event_id="dispatch-limit",
            graph_projection=projection,
            graph_events=list(events),
            graph_position=max(event.position for event in events),
        )
        request: dict[str, Any] = {
            "patch_id": patch_id,
            "base_graph_position": max(event.position for event in events),
            "macro_invocations": [
                {
                    "macro": "construct_reliable_plan_region",
                    "args": {
                        "operation_key": patch_id,
                        "scope": "bounded feature",
                        "objective": "invalid request",
                        "requirement_ids": ["missing-requirement"],
                        "dependencies": [],
                        "acceptance": ["never accepted"],
                        "checks": [],
                        "rubric": ["must be valid"],
                    },
                }
            ],
        }
        if malformed_command:
            request.pop("base_graph_position")
        return await executor._submit_graph_patch_callback(context, request)

    try:
        first_executor = GraphDispatchExecutor(
            sessions,
            controller,
            _FailIfCalledAgentFactory(),
            worktree_path=tmp_path,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
        async with sessions() as session:
            initial_events = await GraphEventStore(session).read_run(run_id)
        initial_dispatch_ids = {
            event.event_id
            for event in initial_events
            if event.event_type == "agent_dispatch_requested"
        }

        first = await reject_with(
            first_executor,
            "invalid-1",
            malformed_command=True,
        )
        assert "invalid_command_payload" in first

        reconstructed = GraphDispatchExecutor(
            sessions,
            GraphController(sessions, clock, _Ids("rebuilt"), auto_dispatch=False),
            _FailIfCalledAgentFactory(),
            worktree_path=tmp_path,
            artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
        )
        second = await reject_with(reconstructed, "invalid-2")
        assert "unknown_requirement_identity" in second
        third = await reject_with(reconstructed, "must-not-evaluate")
        assert "proposal_rejection_limit_exhausted" in third
        assert "unknown_requirement_identity" not in third

        async with sessions() as session:
            store = GraphEventStore(session)
            assert await store.reliable_plan_rejection_count(run_id, "planner-plan") == 3
            events = await store.read_run(run_id)
        exhaustion = [
            event
            for event in events
            if event.event_type == "command_rejected"
            and event.payload.get("reason") == "proposal_rejection_limit_exhausted"
        ]
        assert len(exhaustion) == 1
        assert exhaustion[0].payload["budget"] == 2
        assert exhaustion[0].payload["count"] == 2
        planner = node_payload_view(await controller.read_projection(run_id), "planner-plan")
        assert planner is not None and planner["max_attempts"] == 1
        assert "missing-requirement" not in str(exhaustion[0].payload)
        assert {
            event.event_id for event in events if event.event_type == "agent_dispatch_requested"
        } == initial_dispatch_ids
    finally:
        await engine.dispose()


class _FailIfCalledAgentFactory:
    def __init__(self) -> None:
        self.calls = 0

    def preflight(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls += 1
        raise AssertionError("patch admission must not preflight an agent runner")

    def create_runner(self, *_args: Any, **_kwargs: Any) -> Any:
        self.calls += 1
        raise AssertionError("patch admission must not create an agent runner")


class _SingleCodexFactory:
    def __init__(self, agent: CodexServerAgent) -> None:
        self._agent = agent

    def preflight(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def create_runner(self, *_args: Any, **_kwargs: Any) -> CodexServerAgent:
        return self._agent


class _NeverFinishingPlannerTransport:
    def __init__(self, base_graph_position: int) -> None:
        self.sent: list[dict[str, Any]] = []
        self.recv_cancelled = False
        self._messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for message in (
            {"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "test"}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"thread": {"id": "thread-capped"}},
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "result": {"turn": {"id": "turn-capped", "status": "inProgress"}},
            },
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "item/tool/call",
                "params": {
                    "tool": "construct_reliable_plan_region",
                    "arguments": {
                        "patch_id": "terminal-invalid-plan",
                        "base_graph_position": base_graph_position,
                        "operation_key": "terminal-invalid-plan",
                        "scope": "bounded feature",
                        "objective": "invalid proposal",
                        "requirement_ids": ["missing-requirement"],
                        "dependencies": [],
                        "acceptance": ["never accepted"],
                        "checks": [],
                        "rubric": ["must be valid"],
                    },
                },
            },
        ):
            self._messages.put_nowait(message)

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    async def recv(self) -> dict[str, Any]:
        try:
            return await self._messages.get()
        except asyncio.CancelledError:
            self.recv_cancelled = True
            raise

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize("rejection_before_dispatch", [False, True])
async def test_managed_capped_planner_stops_transport_and_terminalizes_without_retry(
    tmp_path: Path,
    rejection_before_dispatch: bool,
) -> None:
    engine = create_engine(tmp_path / "managed-proposal-limit.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    clock = FakeClock()
    ids = _Ids("managed-limit")
    artifact_store = FilesystemArtifactStore(tmp_path / "managed-limit-artifacts")
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    run_id = "managed-proposal-limit-run"
    start_position = await _active_planner(
        controller,
        run_id,
        clock,
        ids,
        max_rejected_plan_proposals_per_planner=1,
        max_planner_executions_per_node=3,
    )
    worktree = tmp_path / "managed-limit-worktree"
    worktree.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=worktree, check=True)
    (worktree / "README.md").write_text("# bounded planner\n")
    subprocess.run(["git", "add", "README.md"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "Initial"], cwd=worktree, check=True)

    try:
        if rejection_before_dispatch:
            projection = await controller.read_projection(run_id)
            async with sessions() as session:
                initial_events = await GraphEventStore(session).read_run(run_id)
            planner_payload = node_payload_view(projection, "planner-plan")
            assert isinstance(planner_payload, dict)
            rejection_context = GraphDispatchContext(
                run_id=run_id,
                node_id="planner-plan",
                node_kind="planner",
                node_role="planner",
                node_payload=planner_payload,
                requirements=[],
                worktree_path=str(worktree),
                lease_id="pre-crash-lease",
                lease_generation=1,
                execution_id="pre-crash-execution",
                base_snapshot_id="routine-snapshot",
                dispatch_event_id="pre-crash-dispatch",
                graph_projection=projection,
                graph_events=initial_events,
                graph_position=start_position,
            )
            pre_crash_executor = GraphDispatchExecutor(
                sessions,
                controller,
                _FailIfCalledAgentFactory(),
                worktree_path=worktree,
                artifact_store=artifact_store,
            )
            feedback = await pre_crash_executor._submit_graph_patch_callback(
                rejection_context,
                {
                    "patch_id": "persisted-before-cancel",
                    "base_graph_position": start_position,
                    "macro_invocations": [
                        {
                            "macro": "construct_reliable_plan_region",
                            "args": {
                                "operation_key": "persisted-before-cancel",
                                "scope": "bounded feature",
                                "objective": "invalid proposal",
                                "requirement_ids": ["missing-requirement"],
                                "dependencies": [],
                                "acceptance": ["never accepted"],
                                "checks": [],
                                "rubric": ["must be valid"],
                            },
                        }
                    ],
                },
            )
            assert "unknown_requirement_identity" in feedback

        scheduled = await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "schedule_tick",
            {
                "max_grants": 1,
                "lease_seconds": 60,
                "base_snapshot_id": "baseline",
                "priorities": {"planner-plan": 100},
            },
        )
        dispatch_item = next(
            item for item in scheduled.outbox_items if item.kind == "agent_dispatch"
        )
        transport = _NeverFinishingPlannerTransport(scheduled.projection_position)
        executor = GraphDispatchExecutor(
            sessions,
            controller,
            _SingleCodexFactory(CodexServerAgent(api_key=None, _transport=transport, _environ={})),
            worktree_path=worktree,
            artifact_store=artifact_store,
        )

        await executor.dispatch(dispatch_item)
        await asyncio.wait_for(executor.wait_for_all(), timeout=2)
        await asyncio.sleep(0)
        assert transport.recv_cancelled is (not rejection_before_dispatch)
        assert executor.is_running(str(dispatch_item.payload["execution_id"])) is False

        before_recovery = await controller.read_projection(run_id)
        attempt = next(iter(execution_attempts_view(before_recovery).values()))
        assert attempt.state == "recovery_requested"
        assert attempt.recovery_reason == "invalid_planner_proposal"
        assert attempt.retry_after_recovery is False

        completed = await OutboxDispatcher(sessions, executor, clock).dispatch_pending(
            run_id=run_id,
            allowed_kinds=frozenset({"runner_recovery"}),
        )
        assert [item.kind for item in completed] == ["runner_recovery"]
        async with sessions() as session:
            events = await GraphEventStore(session).read_run(run_id)
        assert any(
            event.event_type == "node_state_changed"
            and event.payload.get("node_id") == "planner-plan"
            and event.payload.get("new_state") == "failed"
            and event.payload.get("trigger") == "invalid_planner_proposal"
            for event in events
        )
        assert not any(event.event_type == "runtime_retry_scheduled" for event in events)
        assert sum(event.event_type == "agent_dispatch_requested" for event in events) == 1
        if rejection_before_dispatch:
            assert transport.sent == []
        else:
            tool_response = next(message for message in transport.sent if message.get("id") == 10)
            assert (
                "unknown_requirement_identity" in tool_response["result"]["contentItems"][0]["text"]
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "check",
        "hidden_oracle_command",
        "accepted",
        "expected_code",
        "expected_path",
    ),
    [
        pytest.param(
            {"name": "missing-command"},
            None,
            False,
            "value_error",
            '"path":"macro_invocations[0].args.checks[0]"',
            id="missing-command",
        ),
        pytest.param(
            {"name": "blank-command", "command_definition": {"cmd": "   "}},
            None,
            False,
            "invalid_command_definition",
            '"path":"macro_invocations[0].args.checks[0].command_definition"',
            id="blank-cmd",
        ),
        pytest.param(
            {
                "name": "malformed-argv",
                "command_definition": {"argv": ["", "--must-not-run"]},
            },
            None,
            False,
            "invalid_command_definition",
            '"path":"macro_invocations[0].args.checks[0].command_definition"',
            id="malformed-argv-first-token",
        ),
        pytest.param(
            {"name": "explicit-command", "command_definition": {"cmd": "true"}},
            None,
            True,
            None,
            None,
            id="valid-explicit-command",
        ),
        pytest.param(
            {"name": "bound-command", "command_binding": "dynamic_feature_hidden_oracle"},
            "true",
            True,
            None,
            None,
            id="valid-supported-binding",
        ),
        pytest.param(
            {"name": "absent-oracle", "command_binding": "dynamic_feature_hidden_oracle"},
            None,
            False,
            "unavailable_command_binding",
            '"path":"macro_invocations[0].args.checks[0].command_binding"',
            id="acceptance-does-not-replace-absent-hidden-oracle",
        ),
    ],
)
async def test_check_admission_matrix_crosses_mcp_controller_and_store(
    tmp_path: Path,
    check: dict[str, Any],
    hidden_oracle_command: str | None,
    accepted: bool,
    expected_code: str | None,
    expected_path: str | None,
) -> None:
    engine = create_engine(tmp_path / "check-admission.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    clock = FakeClock()
    ids = _Ids("check-admission")
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    run_id = "check-admission-run"
    base_position = await _active_planner(
        controller,
        run_id,
        clock,
        ids,
        hidden_oracle_command=hidden_oracle_command,
    )
    projection = await controller.read_projection(run_id)
    async with sessions() as session:
        before_events = await GraphEventStore(session).read_run(run_id)
    planner_payload = node_payload_view(projection, "planner-plan")
    assert isinstance(planner_payload, dict)
    context = GraphDispatchContext(
        run_id=run_id,
        node_id="planner-plan",
        node_kind="planner",
        node_role="planner",
        node_payload=planner_payload,
        requirements=[],
        worktree_path=str(tmp_path),
        lease_id="lease-admission",
        lease_generation=1,
        execution_id="execution-admission",
        base_snapshot_id="routine-snapshot",
        dispatch_event_id="dispatch-admission",
        graph_projection=projection,
        graph_events=list(before_events),
        graph_position=base_position,
    )
    factory = _FailIfCalledAgentFactory()
    executor = GraphDispatchExecutor(
        sessions,
        controller,
        factory,
        worktree_path=tmp_path,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )

    async def on_patch(payload: dict[str, Any]) -> str:
        return await executor._submit_graph_patch_callback(context, payload)

    mcp = build_graph_mcp_server(
        on_patch,
        None,
        allowed_tools=["construct_reliable_plan_region"],
    )
    patch_id = "check-admission-patch"
    result = await mcp.call_tool(
        "construct_reliable_plan_region",
        {
            "patch_id": patch_id,
            "base_graph_position": base_position,
            "operation_key": "check-admission-operation",
            "scope": "bounded feature",
            "objective": "Construct an admitted initial plan region.",
            "requirement_ids": ["dynamic_feature_acceptance"],
            "dependencies": [],
            "acceptance": ["the plan is complete"],
            "checks": [check],
            "rubric": ["the plan is independently executable"],
        },
    )
    rendered = " ".join(str(item) for item in result)
    async with sessions() as session:
        after_events = await GraphEventStore(session).read_run(run_id)
    accepted_for_patch = [
        event
        for event in after_events
        if event.event_type == "graph_patch_accepted" and event.payload.get("patch_id") == patch_id
    ]
    leases_before = {
        event.event_id for event in before_events if event.event_type == "lease_granted"
    }
    leases_after = {event.event_id for event in after_events if event.event_type == "lease_granted"}

    assert factory.calls == 0
    assert leases_after == leases_before
    if accepted:
        assert f"graph patch {patch_id} accepted" in rendered
        assert len(accepted_for_patch) == 1
        assert max(event.position for event in after_events) > base_position
    else:
        assert f"graph patch {patch_id} rejected" in rendered
        assert not accepted_for_patch
        assert expected_code is not None and expected_code in rendered
        assert expected_path is not None and expected_path in rendered
        assert "--must-not-run" not in rendered
        assert "--must-not-run" not in str(after_events)

    await engine.dispose()


@pytest.mark.asyncio
async def test_macro_mcp_callback_accepts_omitted_ops_through_controller(tmp_path: Path) -> None:
    """Exercise the production MCP normalization and dispatch callback together."""
    engine = create_engine(tmp_path / "macro-mcp.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    clock = FakeClock()
    ids = _Ids("macro-mcp")
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    run_id = "macro-mcp-run"
    base_position = await _active_planner(controller, run_id, clock, ids)
    projection = await controller.read_projection(run_id)
    async with sessions() as session:
        events = await GraphEventStore(session).read_run(run_id)
    planner_payload = node_payload_view(projection, "planner-plan")
    assert isinstance(planner_payload, dict)
    context = GraphDispatchContext(
        run_id=run_id,
        node_id="planner-plan",
        node_kind="planner",
        node_role="planner",
        node_payload=planner_payload,
        requirements=[],
        worktree_path=str(tmp_path),
        lease_id="lease-mcp",
        lease_generation=1,
        execution_id="execution-mcp",
        base_snapshot_id="routine-snapshot",
        dispatch_event_id="dispatch-mcp",
        graph_projection=projection,
        graph_events=list(events),
        graph_position=base_position,
    )
    executor = GraphDispatchExecutor(
        sessions,
        controller,
        StaticGraphAgentFactory(AgentRunnerType.CODEX_SERVER),
        worktree_path=tmp_path,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )

    async def on_patch(payload: dict[str, Any]) -> str:
        return await executor._submit_graph_patch_callback(context, payload)

    mcp = build_graph_mcp_server(
        on_patch,
        None,
        allowed_tools=["submit_graph_patch", "construct_reliable_plan_region"],
    )
    result = await mcp.call_tool(
        "construct_reliable_plan_region",
        {
            "patch_id": "macro-mcp-patch",
            "base_graph_position": base_position,
            "operation_key": "macro-mcp-operation",
            "scope": "bounded feature",
            "objective": "Construct the initial plan region.",
            "requirement_ids": ["dynamic_feature_acceptance"],
            "dependencies": [],
            "acceptance": ["the plan is complete"],
            "checks": [
                {
                    "name": "project tests",
                    "command_definition": {"cmd": "true"},
                }
            ],
            "rubric": ["the plan is independently executable"],
        },
    )

    assert "graph patch macro-mcp-patch accepted" in " ".join(str(item) for item in result)
    async with sessions() as session:
        updated_events = await GraphEventStore(session).read_run(run_id)
    assert any(
        event.event_type == "graph_patch_accepted"
        and event.payload.get("patch_id") == "macro-mcp-patch"
        for event in updated_events
    )
    assert max(event.position for event in updated_events) > base_position

    lease_grants_before_null = {
        event.event_id for event in updated_events if event.event_type == "lease_granted"
    }
    explicit_null_result = await mcp.call_tool(
        "submit_graph_patch",
        {
            "patch_id": "macro-mcp-explicit-null",
            "base_graph_position": max(event.position for event in updated_events),
            "ops": None,
        },
    )
    rendered_null = " ".join(str(item) for item in explicit_null_result)
    assert "graph patch macro-mcp-explicit-null rejected" in rendered_null
    assert '"path":"ops"' in rendered_null
    assert "list_type" in rendered_null
    async with sessions() as session:
        updated_events = await GraphEventStore(session).read_run(run_id)
    lease_grants_after_null = {
        event.event_id for event in updated_events if event.event_type == "lease_granted"
    }
    assert len(lease_grants_after_null) == len(lease_grants_before_null)
    assert lease_grants_after_null == lease_grants_before_null
    assert not any(
        event.event_type == "graph_patch_accepted"
        and event.payload.get("patch_id") == "macro-mcp-explicit-null"
        for event in updated_events
    )

    null_command_result = await mcp.call_tool(
        "construct_reliable_plan_region",
        {
            "patch_id": "macro-mcp-null-command",
            "base_graph_position": max(event.position for event in updated_events),
            "operation_key": "macro-mcp-null-command-operation",
            "scope": "bounded feature",
            "objective": "Construct the initial plan region.",
            "requirement_ids": ["dynamic_feature_acceptance"],
            "dependencies": [],
            "acceptance": ["the plan is complete"],
            "checks": [{"name": "null-check", "command_binding": None}],
            "rubric": ["the plan is independently executable"],
        },
    )
    rendered_null_command = " ".join(str(item) for item in null_command_result)
    assert "invalid macro arguments" in rendered_null_command
    assert "value_error" in rendered_null_command
    assert '"path":"macro_invocations[0].args.checks[0]"' in rendered_null_command
    async with sessions() as session:
        updated_events = await GraphEventStore(session).read_run(run_id)
    assert not any(
        event.event_type == "graph_patch_accepted"
        and event.payload.get("patch_id") == "macro-mcp-null-command"
        for event in updated_events
    )

    rejected_result = await mcp.call_tool(
        "construct_reliable_plan_region",
        {
            "patch_id": "macro-mcp-invalid-requirement",
            "base_graph_position": max(event.position for event in updated_events),
            "operation_key": "macro-mcp-invalid-operation",
            "scope": "bounded feature",
            "objective": "Construct the initial plan region.",
            "requirement_ids": ["unknown-requirement"],
            "dependencies": [],
            "acceptance": ["the plan is complete"],
            "checks": [],
            "rubric": ["the plan is independently executable"],
        },
    )
    rendered_rejection = " ".join(str(item) for item in rejected_result)
    assert "requested reliable-plan requirement is unavailable" in rendered_rejection
    assert "unknown_requirement_identity" in rendered_rejection
    assert '"path":"macro_invocations[0].args"' in rendered_rejection
    assert "list_type" not in rendered_rejection
    assert '"path":"ops"' not in rendered_rejection
    async with sessions() as session:
        after_rejection_events = await GraphEventStore(session).read_run(run_id)

    unavailable_result = await mcp.call_tool(
        "construct_reliable_plan_region",
        {
            "patch_id": "macro-mcp-unavailable-binding",
            "base_graph_position": max(event.position for event in after_rejection_events),
            "operation_key": "macro-mcp-unavailable-operation",
            "scope": "bounded feature",
            "objective": "Construct the initial plan region.",
            "requirement_ids": ["dynamic_feature_acceptance"],
            "dependencies": [],
            "acceptance": ["the plan is complete"],
            "checks": [
                {"name": "hidden-check", "command_binding": "dynamic_feature_hidden_oracle"}
            ],
            "rubric": ["the plan is independently executable"],
        },
    )
    rendered_unavailable = " ".join(str(item) for item in unavailable_result)
    assert "check command binding is unavailable" in rendered_unavailable
    assert "unavailable_command_binding" in rendered_unavailable
    assert '"path":"macro_invocations[0].args.checks[0].command_binding"' in rendered_unavailable
    assert "list_type" not in rendered_unavailable
    assert '"path":"ops"' not in rendered_unavailable

    async with sessions() as session:
        after_unavailable_events = await GraphEventStore(session).read_run(run_id)
    invalid_args_result = await mcp.call_tool(
        "construct_reliable_plan_region",
        {
            "patch_id": "macro-mcp-invalid-arguments",
            "base_graph_position": max(event.position for event in after_unavailable_events),
            "operation_key": "macro-mcp-invalid-arguments-operation",
            "scope": "bounded feature",
            "objective": "Construct the initial plan region.",
            "requirement_ids": ["dynamic_feature_acceptance"],
            "dependencies": [],
            "acceptance": ["the plan is complete"],
            "checks": [
                {
                    "name": "invalid-check",
                    "command_binding": "unsupported-sentinel",
                    "secret_token": "must-not-be-returned",
                }
            ],
            "rubric": ["the plan is independently executable"],
        },
    )
    rendered_invalid_args = " ".join(str(item) for item in invalid_args_result)
    assert "invalid macro arguments" in rendered_invalid_args
    assert "literal_error" in rendered_invalid_args
    assert '"path":"macro_invocations[0].args.checks[0].command_binding"' in (rendered_invalid_args)
    assert '"path":"macro_invocations[0].args.checks[0].<redacted>"' in rendered_invalid_args
    assert "unsupported-sentinel" not in rendered_invalid_args
    assert "must-not-be-returned" not in rendered_invalid_args
    assert "list_type" not in rendered_invalid_args
    assert '"path":"ops"' not in rendered_invalid_args
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("batch_ids", "remaining_horizons", "dependencies", "expected_rejection_code"),
    [
        (["batch-1", "batch-2"], 2, [], None),
        (["batch-1"], 1, [], None),
        (["batch-1"], 1, ["batch-1"], "dependency_self_reference"),
        (["batch-1"], 1, ["not-a-plan-batch"], "dependency_not_declared"),
        (
            ["batch-1", "batch-2"],
            2,
            ["batch-2"],
            "dependency_not_materialized",
        ),
    ],
)
async def test_successor_macro_crosses_mcp_controller_and_store(
    tmp_path: Path,
    batch_ids: list[str],
    remaining_horizons: int,
    dependencies: list[str],
    expected_rejection_code: str | None,
) -> None:
    engine = create_engine(tmp_path / "successor-mcp.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    clock = FakeClock()
    ids = _Ids("successor-mcp")
    controller = GraphController(sessions, clock, ids, auto_dispatch=False)
    run_id = "successor-mcp-run"
    compiled = compile_routine(
        _routine(),
        clock,
        ids,
        run_id=run_id,
        run_config={
            "acceptance_command": "true",
            "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
            "reliable_plan_selected_runner_type": "codex_server",
            "reliable_plan_one_horizon_authorized": True,
            "reliable_plan_remaining_horizons": remaining_horizons,
            "reliable_plan_qualification_evidence_hash": "sha256:" + "b" * 64,
            "reliable_plan_model_assignments": {
                "arm_id": "successor-public-path",
                **{
                    role: {
                        "runner_type": "codex_server",
                        "model": "user-selected-model",
                        "profile": profile,
                    }
                    for role, profile in {
                        "planner": "architect",
                        "discovery_worker": "summarizer",
                        "implementation_worker": "coder",
                        "correction_worker": "coder",
                        "verifier": "coder",
                        "successor_planner": "architect",
                    }.items()
                },
            },
        },
    )
    root_payload = next(
        event.payload
        for event in compiled
        if event.event_type == "node_created" and event.payload.get("node_id") == "root"
    )
    carrier = root_payload["reliable_plan_assignment_carrier"]
    make_event = event_factory(run_id, "seed_compiled_events", clock, ids)
    plan_record = {
        "record_id": "accepted-plan",
        "record_kind": "graph_record",
        "record_type": "semantic_artifact",
        "schema_version": 1,
        "producer_node_id": "worker-discovery",
        "producer_port": "semantic_artifact",
        "port": "semantic_artifact",
        "schema": "SemanticArtifact",
        "value": {
            "semantic_role": "implementation_plan",
            "schema_id": "ordered-plan",
            "schema_version": 1,
            "content": {"batches": [{"batch_id": batch_id} for batch_id in batch_ids]},
            "provenance": {"source": "discovery"},
            "source_record_ids": ["requirement-dynamic-feature-acceptance"],
            "requirement_ids": ["dynamic_feature_acceptance"],
            "task_region_id": "discovery",
            "validation_status": "validated",
            "authority_status": "accepted",
        },
    }
    plan_report = {
        "record_id": "plan-verification-passed",
        "record_kind": "verification",
        "record_type": "verification_report",
        "producer_node_id": "verifier-plan",
        "port": "verification_report",
        "schema": "VerificationReport",
        "candidate_id": "accepted-plan",
        "candidate_record_id": "accepted-plan",
        "candidate_record_ids": ["accepted-plan"],
        "task_region_id": "plan-verification",
        "outcome": "passed",
        "value": {"outcome": "passed", "grades": []},
        "evaluated_record_ids": ["accepted-plan", "requirement-dynamic-feature-acceptance"],
    }
    seeded = await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {
            "events": [
                *compiled,
                make_event(
                    "node_created",
                    {
                        "node_id": "worker-discovery",
                        "kind": "worker",
                        "role": "discovery",
                        "state": "completed",
                        "semantic_stage": "discovery",
                    },
                ),
                make_event(
                    "node_created",
                    {
                        "node_id": "verifier-plan",
                        "kind": "verifier",
                        "role": "verifier",
                        "state": "completed",
                        "semantic_stage": "plan_verification",
                    },
                ),
                make_event(
                    "node_created",
                    {
                        "node_id": "planner-successor-h1",
                        "kind": "planner",
                        "role": "planner",
                        "state": "planned",
                        "semantic_stage": "successor_planning",
                        "task_region_id": "successor-region-h1",
                        "planning_horizon": 1,
                        "generation_index": 1,
                        "reliable_plan_skeleton_id": "reliable-plan-fff4f6b7-v1",
                        "reliable_plan_one_horizon_authorized": True,
                        "reliable_plan_remaining_horizons": remaining_horizons,
                        "reliable_plan_assignment_carrier": carrier,
                        "reliable_plan_assignment_role": "successor_planner",
                        "reliable_plan_selected_runner_type": "codex_server",
                        "reliable_plan_qualification_evidence_hash": "sha256:" + "b" * 64,
                        "runner_model_override": "user-selected-model",
                        "profile": "architect",
                    },
                ),
                make_event(
                    "edge_created",
                    {
                        "edge_id": "plan-report-to-successor-h1",
                        "from_node_id": "verifier-plan",
                        "from_port": "verification_report",
                        "to_node_id": "planner-successor-h1",
                        "to_port": "verification_report",
                        "accepted_record_selector": {
                            "record_type": "verification_report",
                            "outcome": "passed",
                        },
                    },
                ),
                make_event("output_record_accepted", plan_record),
                make_event("output_record_accepted", plan_report),
                make_event(
                    "input_bound",
                    {
                        "edge_id": "plan-report-to-successor-h1",
                        "to_node_id": "planner-successor-h1",
                        "to_port": "verification_report",
                        "record_ids": ["plan-verification-passed"],
                        "bound_at_position": len(compiled) + 5,
                    },
                ),
            ]
        },
    )
    accepted_run = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted_run.projection_position, "start")
    projection = await controller.read_projection(run_id)
    async with sessions() as session:
        before_events = await GraphEventStore(session).read_run(run_id)
    planner_payload = node_payload_view(projection, "planner-successor-h1")
    assert isinstance(planner_payload, dict)
    assert planner_payload["semantic_stage"] == "successor_planning"
    assert planner_payload["planning_horizon"] == 1
    assert planner_payload["generation_index"] == 1
    context = GraphDispatchContext(
        run_id=run_id,
        node_id="planner-successor-h1",
        node_kind="planner",
        node_role="planner",
        node_payload=planner_payload,
        requirements=[],
        worktree_path=str(tmp_path),
        lease_id="lease-successor",
        lease_generation=1,
        execution_id="execution-successor",
        base_snapshot_id="routine-snapshot",
        dispatch_event_id="dispatch-successor",
        graph_projection=projection,
        graph_events=list(before_events),
        graph_position=started.projection_position,
    )
    factory = _FailIfCalledAgentFactory()
    executor = GraphDispatchExecutor(
        sessions,
        controller,
        factory,
        worktree_path=tmp_path,
        artifact_store=FilesystemArtifactStore(tmp_path / "artifacts"),
    )

    async def on_patch(payload: dict[str, Any]) -> str:
        return await executor._submit_graph_patch_callback(context, payload)

    mcp = build_graph_mcp_server(
        on_patch,
        None,
        allowed_tools=["construct_reliable_plan_region"],
    )
    patch_id = "successor-mcp-patch"
    result = await mcp.call_tool(
        "construct_reliable_plan_region",
        {
            "patch_id": patch_id,
            "base_graph_position": started.projection_position,
            "operation_key": "construct-batch-1",
            "scope": "batch-1",
            "objective": "Implement and verify the first declared batch.",
            "requirement_ids": ["dynamic_feature_acceptance"],
            "dependencies": dependencies,
            "acceptance": ["batch-1 obligations pass"],
            "checks": [
                {
                    "name": "batch check",
                    "command_definition": {"cmd": "/private/tmp/stage3_oracle.sh"},
                }
            ],
            "rubric": ["the first batch is independently verified"],
        },
    )
    rendered = " ".join(str(item) for item in result)
    if expected_rejection_code is not None:
        assert expected_rejection_code in rendered
        assert '"path":"macro_invocations[0].args.dependencies"' in rendered
        async with sessions() as session:
            rejected_events = await GraphEventStore(session).read_run(run_id)
        matching_rejections = [
            event
            for event in rejected_events
            if event.event_type == "command_rejected" and event.payload.get("patch_id") == patch_id
        ]
        assert len(matching_rejections) == 1
        assert matching_rejections[0].payload["diagnostics"]["errors"] == [
            {
                "path": "macro_invocations[0].args.dependencies",
                "code": expected_rejection_code,
                "message": matching_rejections[0].payload["diagnostics"]["errors"][0]["message"],
            }
        ]
        assert factory.calls == 0
        await engine.dispose()
        return
    assert f"graph patch {patch_id} accepted" in rendered
    async with sessions() as session:
        after_events = await GraphEventStore(session).read_run(run_id)
    accepted_events = [
        event
        for event in after_events
        if event.event_type == "graph_patch_accepted" and event.payload.get("patch_id") == patch_id
    ]
    assert len(accepted_events) == 1
    assert factory.calls == 0
    assert {event.event_id for event in after_events if event.event_type == "lease_granted"} == {
        event.event_id for event in before_events if event.event_type == "lease_granted"
    }

    updated = await controller.read_projection(run_id)
    created_node_ids = {
        node_id
        for node_id in node_kinds_view(updated)
        if node_id not in node_kinds_view(projection)
    }
    created_payloads = [node_payload_view(updated, node_id) or {} for node_id in created_node_ids]
    effectful = [
        payload
        for payload in created_payloads
        if payload.get("semantic_stage") == "effectful_batch"
    ]
    assert {payload.get("kind") for payload in effectful} == {"worker", "check", "verifier"}
    assert all(payload.get("declared_batch_id") == "batch-1" for payload in effectful)
    # A horizon-1 successor planner owns the first effectful horizon. The next
    # controller-stamped successor advances to horizon/generation 2.
    effectful_by_kind = {payload["kind"]: payload for payload in effectful}
    assert effectful_by_kind["worker"]["planning_horizon"] == 1
    assert effectful_by_kind["verifier"]["planning_horizon"] == 1
    assert (
        effectful_by_kind["check"]["task_region_id"]
        == effectful_by_kind["worker"]["task_region_id"]
    )
    successors = [
        payload
        for payload in created_payloads
        if payload.get("semantic_stage") == "successor_planning"
    ]
    if remaining_horizons > 1:
        assert len(successors) == 1
        assert successors[0]["planning_horizon"] == 2
        assert successors[0]["generation_index"] == 2
        assert successors[0]["reliable_plan_remaining_horizons"] == 1
        assert successors[0]["reliable_plan_assignment_carrier"] == carrier
        assert successors[0]["runner_model_override"] == "user-selected-model"
    else:
        assert successors == []
        assert (
            sum(payload.get("semantic_stage") == "final_acceptance" for payload in created_payloads)
            == 1
        )
        assert (
            sum(payload.get("semantic_stage") == "final_audit" for payload in created_payloads) == 1
        )
        assert sum(payload.get("kind") == "final_gate" for payload in created_payloads) == 1
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption_phase", ["before_commit", "after_commit"])
async def test_patch_retry_reconciles_commit_or_retries_rolled_back_operation_once(
    tmp_path: Path,
    interruption_phase: str,
) -> None:
    engine = create_engine(tmp_path / f"patch-{interruption_phase}.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    clock = FakeClock()
    first_ids = _Ids("first")
    interruption = _CommitInterruption(interruption_phase)
    controller = GraphController(
        sessions,
        clock,
        first_ids,
        auto_dispatch=False,
        command_commit_observer=interruption,
    )
    run_id = f"patch-{interruption_phase}"
    try:
        base_position = await _active_planner(controller, run_id, clock, first_ids)
        context = PatchCommandContext(
            run_id=run_id,
            current_graph_position=base_position,
            proposed_by_node_id="planner-plan",
            actor_role="planner",
        )
        projection_before_patch = await controller.read_projection(run_id)
        patch_command = SubmitPatchCommand.model_validate(_patch(base_position))
        expand_patch_macros(
            patch_command.ops,
            patch_command.macro_invocations,
            "planner-plan",
            projection=projection_before_patch,
            patch_id=patch_command.patch_id,
        )
        with pytest.raises(_AcknowledgementLost, match=interruption_phase):
            await controller.handle_command(
                run_id,
                base_position,
                "submit_patch",
                _patch(base_position),
                context=context,
            )

        async with sessions() as session:
            events_after_interruption = await GraphEventStore(session).read_run(run_id)
        committed_before_retry = any(
            event.event_type == "graph_patch_accepted"
            and event.payload.get("patch_id") == "logical-region-1"
            for event in events_after_interruption
        )
        assert committed_before_retry is (interruption_phase == "after_commit")

        reconstructed = GraphController(
            sessions,
            clock,
            _Ids("reconstructed"),
            auto_dispatch=False,
        )
        if interruption_phase == "after_commit":
            with pytest.raises(StaleProjectionError):
                await reconstructed.handle_command(
                    run_id,
                    base_position,
                    "submit_patch",
                    _patch(base_position, patch_id="missing-context-envelope"),
                )
            wrong_run_context = context.model_copy(update={"run_id": "different-run"})
            with pytest.raises(StaleProjectionError):
                await reconstructed.handle_command(
                    run_id,
                    base_position,
                    "submit_patch",
                    _patch(base_position, patch_id="wrong-context-envelope"),
                    context=wrong_run_context,
                )
        # The caller deliberately retries its original position and payload;
        # after-commit recovery must discover the prior durable outcome.
        retried = await reconstructed.handle_command(
            run_id,
            base_position,
            "submit_patch",
            _patch(base_position, patch_id="retry-transport-envelope"),
            context=context,
        )
        if interruption_phase == "after_commit":
            assert retried.reconciled_patch_id == "logical-region-1"
            assert retried.events == []
            assert len(retried.reconciled_successor_planner_node_ids) == 1
        else:
            assert retried.reconciled_patch_id is None
            assert any(event.event_type == "graph_patch_accepted" for event in retried.events)

        projection = await reconstructed.read_projection(run_id)
        async with sessions() as session:
            durable_events = await GraphEventStore(session).read_run(run_id)
        accepted_patches = [
            event
            for event in durable_events
            if event.event_type == "graph_patch_accepted"
            and event.payload.get("operation_key") == "logical-region-1"
        ]
        assert len(accepted_patches) == 1
        assert accepted_patches[0].payload["patch_id"] == (
            "logical-region-1"
            if interruption_phase == "after_commit"
            else "retry-transport-envelope"
        )
        conflicting = _patch(base_position, patch_id="conflicting-transport-envelope")
        invocation = conflicting["macro_invocations"]
        assert isinstance(invocation, list)
        invocation[0]["args"]["objective"] = "A different semantic operation."
        with pytest.raises(PatchOperationConflictError, match="different intent"):
            await reconstructed.handle_command(
                run_id,
                base_position,
                "submit_patch",
                conflicting,
                context=context,
            )
        assert planner_generations_view(projection)["planner-plan"] == 0
        assert len(node_kinds_view(projection)) == len(set(node_kinds_view(projection)))
        assert len(edges_view(projection)) == len(set(edges_view(projection)))
        record_ids = list(output_record_payloads_view(projection))
        assert len(record_ids) == len(set(record_ids))
        created_by_stage: dict[str, list[str]] = {}
        for node_id in node_kinds_view(projection):
            stage = (node_payload_view(projection, node_id) or {}).get("semantic_stage")
            if isinstance(stage, str):
                created_by_stage.setdefault(stage, []).append(node_id)
        assert len(created_by_stage["discovery"]) == 1
        assert len(created_by_stage["plan_verification"]) == 1
        assert len(created_by_stage["successor_planning"]) == 1
        successor = node_payload_view(projection, created_by_stage["successor_planning"][0])
        assert successor is not None
        assert successor["generation_index"] == 1
        assert successor["reliable_plan_remaining_horizons"] == 2
        assert non_gap_planner_completion_contract_satisfied(projection, "planner-plan")
    finally:
        await engine.dispose()
