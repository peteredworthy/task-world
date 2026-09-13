from __future__ import annotations

from pathlib import Path
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
    PatchOperationConflictError,
    StaticGraphAgentFactory,
    StaleProjectionError,
)


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
) -> int:
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
                run_config={
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
                },
            )
        },
    )
    accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    return started.projection_position


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
        allowed_tools=["construct_reliable_plan_region"],
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
            "checks": [],
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
    assert '"path":"macro_invocations[0].args"' in rendered_unavailable
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
