from __future__ import annotations

from datetime import timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config import RunStatus
from orchestrator.db import RunModel, StepModel, TaskModel
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
)
from orchestrator.runners import AgentRunner
from orchestrator.runners.types import ExecutionContext


BASE_SNAPSHOT_ID = "snapshot-fr09"


class _RunSeedIdGenerator:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id.replace("-", "")
        self._count = 0

    def next_id(self, prefix: str) -> str:
        self._count += 1
        return f"{prefix}-{self._run_id}-{self._count}"


class _UnusedAgentFactory:
    def create_runner(self, context: GraphDispatchContext) -> AgentRunner:
        raise AssertionError(f"unexpected runner creation for {context.node_id}")


async def test_fr09_execution_packets_and_prompt_hydration_are_readable_for_less_used_nodes(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
    tmp_path: Path,
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    run_id = f"graph-fr09-summarizer-{uuid4().hex[:8]}"
    await _save_graph_run(session_factory, run_id)
    await _seed_fr09_base_events(session_factory, run_id)
    clock = FakeClock()
    controller = GraphController(
        session_factory,
        clock,
        _RunSeedIdGenerator(run_id),
        auto_dispatch=False,
    )
    accepted = await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "submit_patch",
        {
            "patch_id": "patch-fr09-executable-packets",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": await controller.current_position(run_id),
            "ops": _fr09_summarizer_probe_ops(),
        },
    )
    assert [event.event_type for event in accepted.events].count("graph_patch_accepted") == 1

    scheduled = await controller.handle_command(
        run_id,
        accepted.projection_position,
        "schedule_tick",
        {
            "lease_seconds": 60,
            "max_grants": 1,
            "base_snapshot_id": BASE_SNAPSHOT_ID,
            "priorities": {"summarizer-1": 20, "gap-planner-1": 10},
        },
    )
    assert {
        event.payload["node_id"]
        for event in scheduled.events
        if event.event_type == "lease_granted"
    } == {"summarizer-1"}

    executor = GraphDispatchExecutor(
        session_factory,
        controller,
        _UnusedAgentFactory(),
        worktree_path=tmp_path,
    )
    dispatcher = OutboxDispatcher(session_factory, executor, clock)
    summarizer_context = await _capture_execution_context_from_pending_dispatch(
        executor,
        dispatcher,
        run_id=run_id,
        graph_patch_callback=False,
    )

    gap_run_id = f"graph-fr09-gap-{uuid4().hex[:8]}"
    await _save_graph_run(session_factory, gap_run_id)
    await _seed_fr09_base_events(session_factory, gap_run_id)
    gap_controller = GraphController(
        session_factory,
        clock,
        _RunSeedIdGenerator(gap_run_id),
        auto_dispatch=False,
    )
    accepted_gap = await gap_controller.handle_command(
        gap_run_id,
        await gap_controller.current_position(gap_run_id),
        "submit_patch",
        {
            "patch_id": "patch-fr09-gap-planner-packet",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": await gap_controller.current_position(gap_run_id),
            "ops": _fr09_gap_planner_probe_ops(),
        },
    )
    assert [event.event_type for event in accepted_gap.events].count("graph_patch_accepted") == 1

    scheduled_gap = await gap_controller.handle_command(
        gap_run_id,
        await gap_controller.current_position(gap_run_id),
        "schedule_tick",
        {
            "lease_seconds": 60,
            "max_grants": 1,
            "base_snapshot_id": BASE_SNAPSHOT_ID,
            "priorities": {"gap-planner-1": 20},
        },
    )
    assert {
        event.payload["node_id"]
        for event in scheduled_gap.events
        if event.event_type == "lease_granted"
    } == {"gap-planner-1"}
    gap_executor = GraphDispatchExecutor(
        session_factory,
        gap_controller,
        _UnusedAgentFactory(),
        worktree_path=tmp_path,
    )
    gap_dispatcher = OutboxDispatcher(session_factory, gap_executor, clock)
    gap_context = await _capture_execution_context_from_pending_dispatch(
        gap_executor,
        gap_dispatcher,
        run_id=gap_run_id,
        graph_patch_callback=True,
    )

    assert summarizer_context.node_kind == "summarizer"
    assert summarizer_context.available_tools is None
    assert "Summarizer context packet:" in summarizer_context.prompt
    assert '"source_records"' in summarizer_context.prompt
    assert '"candidate-source"' in summarizer_context.prompt
    assert '"schema": "AnalysisSummary"' in summarizer_context.prompt

    assert gap_context.node_kind == "planner"
    assert gap_context.node_role == "gap_planner"
    assert gap_context.graph_patch_callback is not None
    assert "Planner context packet:" in gap_context.prompt
    assert "gap_analysis_contract" in gap_context.prompt
    assert "create_corrective_work_region" in gap_context.prompt
    assert "create_successor_planner" not in gap_context.prompt
    assert gap_context.available_tools == [
        "attach_check",
        "attach_verifier",
        "create_corrective_region",
        "request_gate",
        "submit_graph_patch",
    ]

    events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    gap_events = await _get_json(
        client,
        f"/api/runs/{gap_run_id}/graph/events?payload_mode=full",
    )
    summarizer = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/summarizer-1?payload_mode=full",
    )
    gap_planner = await _get_json(
        client,
        f"/api/runs/{gap_run_id}/graph/nodes/gap-planner-1?payload_mode=full",
    )
    topology = await _get_json(client, f"/api/runs/{run_id}/graph/topology")
    gap_topology = await _get_json(client, f"/api/runs/{gap_run_id}/graph/topology")

    runtime_starts = {
        event["payload"]["node_id"]: event["payload"]["prompt_summary"]
        for event in [*events, *gap_events]
        if event["event_type"] == "node_state_changed"
        and event["payload"].get("trigger") == "runtime_start_acknowledged"
        and event["payload"].get("node_id") in {"summarizer-1", "gap-planner-1"}
    }
    assert runtime_starts == {
        "summarizer-1": summarizer["prompt_summary"],
        "gap-planner-1": gap_planner["prompt_summary"],
    }
    assert (
        summarizer["callback_history"][0]["payload"]["prompt_summary"]
        == summarizer["prompt_summary"]
    )
    assert (
        gap_planner["callback_history"][0]["payload"]["prompt_summary"]
        == gap_planner["prompt_summary"]
    )

    summarizer_summary = summarizer["prompt_summary"]
    assert summarizer_summary["packet_type"] == "summarizer"
    assert summarizer_summary["prompt_sections"] == ["summarizer_context_packet"]
    assert summarizer_summary["packet_keys"] == [
        "node_id",
        "required_summary_schema",
        "source_records",
        "task_region_id",
    ]
    assert summarizer_summary["required_summary_schema"]["schema"] == "AnalysisSummary"
    assert summarizer_summary["input_ports"] == {"source_records": ["candidate-source"]}
    assert summarizer_summary["bound_records"]["source_records"] == [
        {
            "record_id": "candidate-source",
            "record_kind": "output",
            "hydration_policy": "structured_json",
            "status": "accepted",
            "record_type": "candidate",
            "schema": "ImplementationCandidate",
            "producer_node_id": "worker-source",
            "port": "candidate",
        }
    ]

    gap_summary = gap_planner["prompt_summary"]
    assert gap_summary["packet_type"] == "gap_planner"
    assert "gap_analysis_contract" in gap_summary["packet_keys"]
    assert "gap_analysis_contract" in gap_summary["prompt_sections"]
    assert gap_summary["available_tools"] == [
        "attach_check",
        "attach_verifier",
        "create_corrective_region",
        "request_gate",
        "submit_graph_patch",
    ]
    assert gap_summary["input_ports"] == {"verification_evidence": ["verification-source"]}
    assert gap_summary["bound_records"]["verification_evidence"] == [
        {
            "record_id": "verification-source",
            "record_kind": "verification",
            "hydration_policy": "artifact_reference",
            "status": "accepted",
            "record_reference": {
                "record_id": "verification-source",
                "record_type": "verification_report",
                "schema": "VerificationReport",
                "producer_node_id": "verifier-source",
                "producer_port": "verification_report",
            },
        }
    ]
    assert gap_summary["lease"]["base_snapshot_id"] == BASE_SNAPSHOT_ID

    topology_edges = {
        edge["edge_id"]: edge for edge in [*topology["edges"], *gap_topology["edges"]]
    }
    assert (
        topology_edges["edge-candidate-summarizer"]["metadata"]["prompt_hydration_policy"]
        == "structured_json"
    )
    assert (
        topology_edges["edge-verification-gap"]["metadata"]["prompt_hydration_policy"]
        == "artifact_reference"
    )


async def _capture_execution_context_from_pending_dispatch(
    executor: GraphDispatchExecutor,
    dispatcher: OutboxDispatcher,
    *,
    run_id: str,
    graph_patch_callback: bool,
) -> ExecutionContext:
    pending = [item for item in await dispatcher.pending_items() if item.run_id == run_id]
    assert len(pending) == 1
    context = await executor._build_dispatch_context(pending[0])

    async def _unused_graph_patch_callback(patch_payload: dict[str, Any]) -> str:
        raise AssertionError(f"unexpected graph patch callback: {patch_payload}")

    execution_context = executor._execution_context(
        context,
        graph_patch_callback=(_unused_graph_patch_callback if graph_patch_callback else None),
    )
    await executor._acknowledge_start(context)
    return execution_context


async def _save_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    now = FakeClock().now().astimezone(timezone.utc).replace(tzinfo=None)
    run = RunModel(
        id=run_id,
        repo_name=f"graph-fr09-acceptance-repo-{run_id}",
        status=RunStatus.ACTIVE.value,
        execution_mode="graph",
        source_branch="main",
        created_at=now,
        updated_at=now,
        current_step_index=0,
        steps=[
            StepModel(
                id=f"{run_id}-step-1",
                run_id=run_id,
                config_id="step-1",
                title="Step 1",
                order_index=0,
                tasks=[
                    TaskModel(
                        id=f"{run_id}-task-1",
                        step_id=f"{run_id}-step-1",
                        config_id="task-1",
                        title="Prove FR-09 packets",
                        order_index=0,
                        status="pending",
                        checklist=[],
                    )
                ],
            )
        ],
    )
    async with session_factory() as session:
        session.add(run)
        await session.commit()


async def _seed_fr09_base_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [
                _event(run_id, "run_lifecycle_changed", {"to_state": "active"}),
                _event(
                    run_id,
                    "node_created",
                    {
                        "node_id": "planner-1",
                        "kind": "planner",
                        "role": "planner",
                        "state": "running",
                    },
                ),
                _event(
                    run_id,
                    "node_created",
                    {
                        "node_id": "worker-source",
                        "kind": "worker",
                        "role": "builder",
                        "state": "completed",
                    },
                ),
                _event(
                    run_id,
                    "node_created",
                    {
                        "node_id": "verifier-source",
                        "kind": "verifier",
                        "role": "verifier",
                        "state": "completed",
                    },
                ),
                _event(
                    run_id,
                    "output_record_accepted",
                    {
                        "record_id": "candidate-source",
                        "record_kind": "output",
                        "record_type": "candidate",
                        "producer_node_id": "worker-source",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "candidate for summarizer"},
                    },
                ),
                _event(
                    run_id,
                    "output_record_accepted",
                    {
                        "record_id": "verification-source",
                        "record_kind": "verification",
                        "record_type": "verification_report",
                        "producer_node_id": "verifier-source",
                        "port": "verification_report",
                        "schema": "VerificationReport",
                        "value": {"verdict": "failed"},
                    },
                ),
            ],
        )
        await session.commit()


def _fr09_summarizer_probe_ops() -> list[dict[str, Any]]:
    return [
        {
            "op": "create_node",
            "node": {
                "node_id": "summarizer-1",
                "kind": "summarizer",
                "state": "ready",
                "task_region_id": "task-fr09",
            },
        },
        {
            "op": "create_edge",
            "edge_id": "edge-candidate-summarizer",
            "from_node_id": "worker-source",
            "from_port": "candidate",
            "to_node_id": "summarizer-1",
            "to_port": "source_records",
            "required": True,
            "prompt_hydration_policy": "structured_json",
        },
    ]


def _fr09_gap_planner_probe_ops() -> list[dict[str, Any]]:
    return [
        {
            "op": "create_node",
            "node": {
                "node_id": "gap-planner-1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "ready",
                "task_region_id": "task-fr09",
            },
        },
        {
            "op": "create_edge",
            "edge_id": "edge-verification-gap",
            "from_node_id": "verifier-source",
            "from_port": "verification_report",
            "to_node_id": "gap-planner-1",
            "to_port": "verification_evidence",
            "required": True,
            "accepted_record_selector": {"record_kinds": ["verification"]},
            "prompt_hydration_policy": "artifact_reference",
        },
    ]


async def _get_json(client: AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def _event(run_id: str, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{uuid4().hex}",
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )
