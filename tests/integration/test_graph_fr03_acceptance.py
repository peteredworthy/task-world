from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import timezone
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api import create_app
from orchestrator.config import RunStatus
from orchestrator.db import RunModel, StepModel, TaskModel, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphController, GraphEventStore


@pytest.fixture
async def fr03_app() -> AsyncGenerator[tuple[AsyncClient, Any], None]:
    app = create_app(db_path=":memory:", routine_dirs=[])
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app
    await app.state.engine.dispose()


class _RunSeedIdGenerator:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id.replace("-", "")
        self._count = 0

    def next_id(self, prefix: str) -> str:
        self._count += 1
        return f"{prefix}-{self._run_id}-{self._count}"


async def test_fr03_less_used_contracts_govern_validation_runtime_and_readbacks(
    fr03_app: tuple[AsyncClient, Any],
) -> None:
    client, app = fr03_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    run_id = f"fr03-contracts-{uuid4().hex[:8]}"
    await _save_graph_run(session_factory, run_id)
    await _seed_fr03_base_events(session_factory, run_id)
    controller = GraphController(
        session_factory,
        FakeClock(),
        _RunSeedIdGenerator(run_id),
        auto_dispatch=False,
    )

    accepted = await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "submit_patch",
        {
            "patch_id": "patch-fr03-less-used-contracts",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": await controller.current_position(run_id),
            "ops": _less_used_contract_ops(),
        },
    )
    assert [event.event_type for event in accepted.events].count("graph_patch_accepted") == 1, [
        event.payload.get("reason") for event in accepted.events
    ]
    rejected = await controller.handle_command(
        run_id,
        accepted.projection_position,
        "submit_patch",
        {
            "patch_id": "patch-fr03-bad-review-port",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": accepted.projection_position,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "review-bad",
                        "kind": "review",
                        "state": "planned",
                        "inputs": [{"port": "candidate_under_test"}],
                    },
                }
            ],
        },
    )
    assert [event.event_type for event in rejected.events] == ["graph_patch_rejected"]
    assert "unknown input port" in str(rejected.events[0].payload["reason"])

    joined = await controller.handle_command(
        run_id,
        rejected.projection_position,
        "evaluate_join",
        {
            "node_id": "join-1",
            "record_id": "join-result-fr03",
        },
    )
    assert [event.event_type for event in joined.events] == [
        "output_record_accepted",
        "node_state_changed",
    ]
    assert joined.events[0].payload["record_type"] == "join_result"
    assert joined.events[0].payload["value"] == {
        "status": "ready",
        "source_record_ids": ["candidate-1"],
    }

    events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    topology = await _get_json(client, f"/api/runs/{run_id}/graph/topology")
    patches = await _get_json(client, f"/api/runs/{run_id}/graph/patches")
    scheduler = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")
    summarizer = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/summarizer-1")
    join = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/join-1?payload_mode=full")
    review = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/review-1")
    gap_planner = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/gap-planner-1")
    authority_gate = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/authority-1")
    final_blockers = await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers")

    assert [event["position"] for event in events] == list(range(1, len(events) + 1))
    assert summarizer["contract"]["node_type"] == "summarizer"
    assert summarizer["contract"]["handler_type"] == "agent"
    assert summarizer["contract"]["input_ports"]["source_records"]["cardinality"] == "many"
    assert summarizer["contract"]["output_ports"]["analysis_summary"]["schemas"] == [
        "AnalysisSummary"
    ]
    assert summarizer["input_ports"] == {"source_records": ["candidate-1"]}

    assert join["contract"]["node_type"] == "join"
    assert join["contract"]["handler_type"] == "controller"
    assert join["contract"]["output_ports"]["join_result"]["schemas"] == ["JoinResult"]
    assert join["input_ports"] == {"source_record_1": ["candidate-1"]}
    assert join["output_records"][0]["record_id"] == "join-result-fr03"
    assert "join_evaluated" in [event["payload"].get("trigger") for event in join["events"]]

    assert review["kind"] == "review"
    assert review["contract"]["node_type"] == "recovery"
    assert review["contract"]["handler_type"] == "controller"
    assert review["contract"]["input_ports"]["failure_record"]["schemas"] == ["FailureRecord"]
    assert review["contract"]["output_ports"]["recovery_plan"]["schemas"] == ["RecoveryPlan"]
    assert review["resource_claims"] == [
        {"mode": "review_write", "scope": "external", "external_resource_key": "review-queue"}
    ]
    assert review["allowed_actions"] == ["record_decision"]
    assert review["preconditions"] == ["has_command_definition"]
    assert review["command_definition"] == {
        "id": "manual-review",
        "cmd": "controller:review",
    }

    assert gap_planner["contract"]["node_type"] == "gap_planner"
    assert gap_planner["contract"]["allowed_tools"] == [
        "attach_check",
        "attach_verifier",
        "create_corrective_region",
        "request_gate",
        "submit_graph_patch",
    ]
    assert gap_planner["contract"]["input_ports"]["verification_evidence"]["schemas"] == [
        "CheckResult",
        "VerificationReport",
    ]

    assert authority_gate["contract"]["node_type"] == "authority_request"
    assert authority_gate["contract"]["handler_type"] == "human"
    assert authority_gate["contract"]["input_ports"]["authority_request_record"]["schemas"] == [
        "AuthorityRequest"
    ]
    assert authority_gate["contract"]["output_ports"]["authority_decision"]["schemas"] == [
        "AuthorityDecision"
    ]

    summarizer_edge = next(
        edge for edge in topology["edges"] if edge["edge_id"] == "edge-candidate-summarizer"
    )
    assert summarizer_edge["metadata"]["prompt_hydration_policy"] == "structured_json"
    assert summarizer_edge["target_port_contract"]["cardinality"] == "many"
    assert summarizer_edge["binding"]["binding_policy"] == "bind_all"
    assert summarizer_edge["binding"]["record_ids"] == ["candidate-1", "candidate-2"]
    assert summarizer_edge["binding"]["record_bound_positions"] == {
        "candidate-1": 17,
        "candidate-2": 18,
    }

    join_edge = next(edge for edge in topology["edges"] if edge["edge_id"] == "edge-candidate-join")
    assert join_edge["target_port_contract"]["record_types"] == [
        "candidate",
        "check_result",
        "file_state",
        "verification_report",
    ]
    assert join_edge["binding"]["binding_policy"] == "bind_first"
    assert join_edge["binding"]["record_ids"] == ["candidate-1"]

    patch_statuses = {attempt["patch_id"]: attempt["status"] for attempt in patches["attempts"]}
    assert patch_statuses["patch-fr03-less-used-contracts"] == "accepted"
    assert patch_statuses["patch-fr03-bad-review-port"] == "rejected"
    rejected_attempt = next(
        attempt
        for attempt in patches["attempts"]
        if attempt["patch_id"] == "patch-fr03-bad-review-port"
    )
    assert "unknown input port" in rejected_attempt["rejection_reason"]

    assert "summarizer-1" in scheduler["scheduler"]["ready"]
    assert scheduler["leases"] == {"active": [], "suspended": []}
    blocker_node_ids = {blocker.get("node_id") for blocker in final_blockers["blockers"]}
    assert "summarizer-1" in blocker_node_ids
    assert "review-1" in blocker_node_ids


async def _save_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    now = FakeClock().now().astimezone(timezone.utc).replace(tzinfo=None)
    run = RunModel(
        id=run_id,
        repo_name=f"graph-fr03-acceptance-repo-{run_id}",
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
                        title="Prove FR-03 contracts",
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


async def _seed_fr03_base_events(
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
                        "record_id": "candidate-1",
                        "record_kind": "output",
                        "record_type": "candidate",
                        "producer_node_id": "worker-source",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "first candidate"},
                    },
                ),
                _event(
                    run_id,
                    "output_record_accepted",
                    {
                        "record_id": "candidate-2",
                        "record_kind": "verification",
                        "record_type": "candidate",
                        "producer_node_id": "worker-source",
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "value": {"summary": "second candidate"},
                    },
                ),
                _event(
                    run_id,
                    "output_record_accepted",
                    {
                        "record_id": "verification-1",
                        "record_kind": "output",
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


def _less_used_contract_ops() -> list[dict[str, Any]]:
    return [
        {
            "op": "create_node",
            "node": {
                "node_id": "summarizer-1",
                "kind": "summarizer",
                "state": "ready",
                "task_region_id": "task-fr03",
            },
        },
        {
            "op": "create_node",
            "node": {
                "node_id": "join-1",
                "kind": "join",
                "role": "fan_out_join",
                "state": "ready",
                "task_region_id": "task-fr03",
            },
        },
        {
            "op": "create_node",
            "node": {
                "node_id": "review-1",
                "kind": "review",
                "state": "ready",
                "task_region_id": "task-fr03",
                "resource_claims": [
                    {
                        "mode": "review_write",
                        "scope": "external",
                        "external_resource_key": "review-queue",
                    }
                ],
                "allowed_actions": ["record_decision"],
                "preconditions": ["has_command_definition"],
                "command_definition": {
                    "id": "manual-review",
                    "cmd": "controller:review",
                },
            },
        },
        {
            "op": "create_node",
            "node": {
                "node_id": "gap-planner-1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "ready",
                "task_region_id": "task-fr03",
            },
        },
        {
            "op": "create_node",
            "node": {
                "node_id": "authority-1",
                "kind": "authority_request",
                "state": "ready",
                "task_region_id": "task-fr03",
                "authority_request_record": {
                    "requested_authority": ["repo:docs/**:write"],
                    "target_node_id": "worker-source",
                    "reason": "FR-03 contract authority fixture.",
                },
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
        {
            "op": "create_edge",
            "edge_id": "edge-candidate-join",
            "from_node_id": "worker-source",
            "from_port": "candidate",
            "to_node_id": "join-1",
            "to_port": "source_record_1",
            "required": True,
            "prompt_hydration_policy": "inline_summary",
        },
        {
            "op": "create_edge",
            "edge_id": "edge-verification-gap",
            "from_node_id": "verifier-source",
            "from_port": "verification_report",
            "to_node_id": "gap-planner-1",
            "to_port": "verification_evidence",
            "required": True,
            "accepted_record_selector": {"record_kinds": ["verification", "check_result"]},
            "prompt_hydration_policy": "artifact_reference",
        },
        {
            "op": "create_edge",
            "edge_id": "edge-authority-request",
            "from_node_id": "authority-1",
            "from_port": "authority_decision",
            "to_node_id": "worker-source",
            "to_port": "authority",
            "required": False,
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
