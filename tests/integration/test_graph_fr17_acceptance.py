from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api import create_app
from orchestrator.config import AgentRunnerType, RunStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.db import (
    GraphEventSummaryModel,
    GraphNodeDetailSummaryModel,
    GraphProjectionSnapshotModel,
    RunModel,
    init_db,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow import WorkflowService


@pytest.fixture
async def fr17_app(
    tmp_path,
) -> AsyncGenerator[tuple[AsyncClient, Any], None]:
    app = create_app(db_path=str(tmp_path / "fr17-app.db"), routine_dirs=[])
    await init_db(app.state.engine)
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app
    await app.state.engine.dispose()


async def test_fr17_less_used_readbacks_survive_projection_rebuild(
    fr17_app: tuple[AsyncClient, Any],
) -> None:
    client, app = fr17_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    run_id = f"fr17-readback-{uuid4().hex[:8]}"
    await _create_graph_run(session_factory, run_id)
    await _seed_less_used_readback_graph(session_factory, run_id)

    decision_response = await client.post(
        f"/api/runs/{run_id}/graph/decisions",
        json={
            "decision_type": "approval",
            "node_id": "gate-decision",
            "decision": "approved",
            "decider": {"kind": "human", "id": "fr17-reviewer"},
            "reason": "FR-17 API write/readback proof.",
        },
    )
    assert decision_response.status_code == 200, decision_response.text
    decision_event_types = [event["event_type"] for event in decision_response.json()["events"]]
    assert decision_event_types[:4] == [
        "approval_decision_recorded",
        "output_record_accepted",
        "input_bound",
        "node_state_changed",
    ]
    assert "node_deferred" in decision_event_types

    before = await _read_fr17_surfaces(client, run_id)
    await _assert_fr17_surfaces(run_id, before)

    await _delete_read_models(session_factory, run_id)
    after = await _read_fr17_surfaces(client, run_id)
    await _assert_fr17_surfaces(run_id, after)

    assert after["run"] == before["run"]
    assert after["graph"] == before["graph"]
    assert after["topology"] == before["topology"]
    assert after["scheduler"] == before["scheduler"]
    assert after["decisions"] == before["decisions"]
    assert after["patches"] == before["patches"]
    assert after["regions"] == before["regions"]
    assert after["final_blockers"] == before["final_blockers"]
    assert after["recovery_node"] == before["recovery_node"]
    assert after["review_node"] == before["review_node"]

    async with session_factory() as session:
        summary_count = await _count_model(session, GraphEventSummaryModel, run_id)
        snapshot_count = await _count_model(session, GraphProjectionSnapshotModel, run_id)
        node_detail_count = await _count_model(session, GraphNodeDetailSummaryModel, run_id)
    assert summary_count == before["graph"]["event_count"]
    assert snapshot_count == 1
    assert node_detail_count >= 2


async def _create_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    run = create_run_from_routine(
        _routine(),
        repo_name=f"fr17-repo-{run_id}",
        source_branch="main",
    )
    run.id = run_id
    run.execution_mode = "graph"
    run.routine_embedded = _routine().model_dump(mode="json", by_alias=True)
    run.agent_runner_type = AgentRunnerType.CODEX_SERVER
    async with session_factory() as session:
        await WorkflowService(session).create_run(run)
        stored = await session.get(RunModel, run_id)
        assert stored is not None
        stored.status = RunStatus.ACTIVE
        await session.commit()


async def _seed_less_used_readback_graph(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, _less_used_events(run_id))


def _less_used_events(run_id: str) -> list[EventEnvelope]:
    return [
        _event(run_id, "run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        _event(
            run_id,
            "node_created",
            {"node_id": "planner-fr17", "kind": "planner", "role": "planner", "state": "completed"},
        ),
        _event(
            run_id,
            "node_created",
            {
                "node_id": "worker-source",
                "kind": "worker",
                "role": "builder",
                "state": "completed",
                "task_region_id": "task-fr17",
                "resource_claims": [{"mode": "write", "scope": "paths", "paths": ["docs/"]}],
                "allowed_actions": ["submit_records", "raise_appeal"],
            },
        ),
        _event(
            run_id,
            "node_created",
            {
                "node_id": "recovery-1",
                "kind": "recovery",
                "state": "running",
                "task_region_id": "task-fr17",
                "preconditions": ["failure_record_bound"],
                "command_definition": {
                    "id": "recover-runtime",
                    "cmd": "controller:recover-failed-node",
                    "source": "controller",
                },
            },
        ),
        _event(
            run_id,
            "node_created",
            {
                "node_id": "review-1",
                "kind": "review",
                "state": "ready",
                "task_region_id": "task-fr17",
                "blocker": "merge_conflicts",
                "allowed_actions": ["record_decision"],
            },
        ),
        _event(run_id, "node_deferred", {"node_id": "review-1", "reason": "merge_conflicts"}),
        _event(
            run_id,
            "node_created",
            {
                "node_id": "appeal-1",
                "kind": "appeal",
                "state": "completed",
                "task_region_id": "task-fr17",
            },
        ),
        _event(
            run_id,
            "node_created",
            {
                "node_id": "gate-pending",
                "kind": "human_gate",
                "state": "ready",
                "task_region_id": "task-fr17",
                "gate_type": "human_approval",
                "prompt": "Approve FR-17 pending work?",
            },
        ),
        _event(
            run_id,
            "node_created",
            {
                "node_id": "gate-decision",
                "kind": "human_gate",
                "state": "ready",
                "task_region_id": "task-fr17",
                "gate_type": "human_approval",
                "prompt": "Approve FR-17 completed readback fixture?",
            },
        ),
        _event(
            run_id,
            "node_created",
            {
                "node_id": "consumer-1",
                "kind": "worker",
                "role": "builder",
                "state": "ready",
                "task_region_id": "task-fr17",
            },
        ),
        _event(
            run_id,
            "edge_created",
            {
                "edge_id": "edge-failure-recovery",
                "from_node_id": "worker-source",
                "from_port": "failure_record",
                "to_node_id": "recovery-1",
                "to_port": "failure_record",
                "required": True,
                "dependency_type": "input_binding",
                "binding_policy": "bind_first",
                "freshness_policy": "latest_only",
                "prompt_hydration_policy": "summary",
            },
        ),
        _event(
            run_id,
            "output_record_accepted",
            {
                "record_id": "failure-record-1",
                "record_kind": "output",
                "record_type": "failure_record",
                "producer_node_id": "worker-source",
                "port": "failure_record",
                "schema": "FailureRecord",
                "value": {
                    "failed_node_id": "worker-source",
                    "phase": "runtime",
                    "error_class": "agent_error",
                    "retryable": True,
                },
            },
        ),
        _event(
            run_id,
            "input_bound",
            {
                "edge_id": "edge-failure-recovery",
                "to_node_id": "recovery-1",
                "to_port": "failure_record",
                "record_ids": ["failure-record-1"],
                "bound_at_position": 12,
                "trigger": "record_accepted",
            },
        ),
        _event(
            run_id,
            "lease_granted",
            {
                "node_id": "recovery-1",
                "lease_id": "lease-recovery",
                "generation": 1,
                "execution_id": "exec-recovery",
                "expires_at": "2026-01-01T00:05:00+00:00",
            },
        ),
        _event(
            run_id,
            "output_record_accepted",
            {
                "record_id": "recovery-plan-1",
                "record_kind": "output",
                "record_type": "recovery_plan",
                "producer_node_id": "recovery-1",
                "port": "recovery_plan",
                "schema": "RecoveryPlan",
                "value": {"action": "retry", "target_node_id": "worker-source"},
            },
        ),
        _event(
            run_id,
            "node_state_changed",
            {
                "node_id": "recovery-1",
                "new_state": "completed",
                "trigger": "recovery_plan_recorded",
            },
        ),
        _event(
            run_id,
            "lease_released",
            {"node_id": "recovery-1", "lease_id": "lease-recovery", "generation": 1},
        ),
        _event(
            run_id,
            "edge_created",
            {
                "edge_id": "edge-recovery-consumer",
                "from_node_id": "recovery-1",
                "from_port": "recovery_plan",
                "to_node_id": "consumer-1",
                "to_port": "outstanding_failures",
                "required": False,
                "dependency_type": "input_binding",
                "binding_policy": "bind_latest",
                "freshness_policy": "latest_only",
                "prompt_hydration_policy": "full",
            },
        ),
        _event(
            run_id,
            "input_bound",
            {
                "edge_id": "edge-recovery-consumer",
                "to_node_id": "consumer-1",
                "to_port": "outstanding_failures",
                "record_ids": ["recovery-plan-1"],
                "bound_at_position": 19,
                "trigger": "record_accepted",
            },
        ),
        _event(
            run_id,
            "output_record_accepted",
            _decision_request_record(
                "decision-request-pending",
                "gate-pending",
                "Approve FR-17 pending work?",
            ),
        ),
        _event(
            run_id,
            "output_record_accepted",
            _decision_request_record(
                "decision-request-approved",
                "gate-decision",
                "Approve FR-17 completed readback fixture?",
            ),
        ),
        _event(
            run_id,
            "edge_created",
            {
                "edge_id": "edge-decision-consumer",
                "from_node_id": "gate-decision",
                "from_port": "decision_record",
                "to_node_id": "consumer-1",
                "to_port": "approval",
                "required": False,
                "dependency_type": "input_binding",
                "binding_policy": "bind_latest",
            },
        ),
        _event(
            run_id,
            "appeal_opened",
            {
                "node_id": "appeal-1",
                "appealed_node_id": "worker-source",
                "candidate_id": "candidate-fr17",
                "task_region_id": "task-fr17",
                "appeal_type": "invalid_test",
            },
        ),
        _event(
            run_id,
            "oversight_decision_recorded",
            {
                "node_id": "oversight-1",
                "appeal_node_id": "appeal-1",
                "appealed_node_id": "worker-source",
                "candidate_id": "candidate-fr17",
                "task_region_id": "task-fr17",
                "appeal_type": "invalid_test",
                "outcome": "rejected",
            },
        ),
        _event(
            run_id,
            "graph_patch_rejected",
            {
                "patch_id": "patch-fr17-rejected",
                "proposed_by_node_id": "planner-fr17",
                "base_graph_position": 3,
                "current_graph_position": 25,
                "actor_role": "planner",
                "reason": "invalid macro expansion for FR-17 fixture",
                "diagnostics": {"macro": "create_join", "valid": False},
                "created_node_ids": [],
                "created_edge_ids": [],
            },
        ),
    ]


def _decision_request_record(record_id: str, node_id: str, prompt: str) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "record_kind": "output",
        "record_type": "decision_request",
        "producer_node_id": node_id,
        "port": "decision_request",
        "schema": "DecisionRequest",
        "value": {
            "decision_type": "approval",
            "prompt": prompt,
            "options": ["approved", "rejected"],
            "default_option": "rejected",
            "consequence_summary": "FR-17 acceptance fixture.",
        },
    }


async def _read_fr17_surfaces(client: AsyncClient, run_id: str) -> dict[str, Any]:
    return {
        "run": await _get_json(client, f"/api/runs/{run_id}"),
        "graph": await _get_json(client, f"/api/runs/{run_id}/graph"),
        "events": await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full"),
        "topology": await _get_json(client, f"/api/runs/{run_id}/graph/topology"),
        "scheduler": await _get_json(client, f"/api/runs/{run_id}/graph/scheduler"),
        "decisions": await _get_json(client, f"/api/runs/{run_id}/graph/decisions"),
        "patches": await _get_json(client, f"/api/runs/{run_id}/graph/patches"),
        "regions": await _get_json(client, f"/api/runs/{run_id}/graph/regions"),
        "final_blockers": await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers"),
        "recovery_node": await _get_json(
            client, f"/api/runs/{run_id}/graph/nodes/recovery-1?payload_mode=full"
        ),
        "review_node": await _get_json(client, f"/api/runs/{run_id}/graph/nodes/review-1"),
    }


async def _assert_fr17_surfaces(run_id: str, surfaces: dict[str, Any]) -> None:
    run = surfaces["run"]
    graph = surfaces["graph"]
    events = surfaces["events"]
    topology = surfaces["topology"]
    scheduler = surfaces["scheduler"]
    decisions = surfaces["decisions"]
    patches = surfaces["patches"]
    regions = surfaces["regions"]
    blockers = surfaces["final_blockers"]
    recovery_node = surfaces["recovery_node"]
    review_node = surfaces["review_node"]

    assert run["status"] == "active"
    assert run["is_graph_backed"] is True
    assert graph["run_state"] == "active"
    assert graph["event_count"] == len(events)
    assert [event["position"] for event in events] == list(range(1, len(events) + 1))
    assert graph["node_states"]["recovery-1"] == "completed"
    assert graph["node_states"]["review-1"] == "ready"
    assert graph["leases"]["lease-recovery"]["state"] == "released"

    recovery_edge = next(
        edge for edge in topology["edges"] if edge["edge_id"] == "edge-recovery-consumer"
    )
    assert recovery_edge["metadata"]["binding_policy"] == "bind_latest"
    assert recovery_edge["binding"]["record_ids"] == ["recovery-plan-1"]
    assert recovery_edge["binding"]["record_bound_positions"] == {"recovery-plan-1": 19}
    assert recovery_edge["bound_records"][0]["record_type"] == "recovery_plan"

    decision_edge = next(
        edge for edge in topology["edges"] if edge["edge_id"] == "edge-decision-consumer"
    )
    assert decision_edge["binding"]["record_ids"] == ["decision_record-gate-decision"]
    assert decision_edge["bound_records"][0]["record_type"] == "decision_record"

    assert recovery_node["kind"] == "recovery"
    assert recovery_node["input_ports"]["failure_record"] == ["failure-record-1"]
    assert recovery_node["output_records"][0]["record_type"] == "recovery_plan"
    assert recovery_node["active_lease"]["state"] == "released"
    assert recovery_node["preconditions"] == ["failure_record_bound"]
    assert recovery_node["command_definition"]["id"] == "recover-runtime"
    assert recovery_node["callback_history"] == []
    assert "node_state_changed" in [event["event_type"] for event in recovery_node["events"]]

    assert review_node["kind"] == "review"
    assert review_node["contract"]["node_type"] == "recovery"
    assert "recovery_plan" in review_node["contract"]["output_ports"]
    assert review_node["allowed_actions"] == ["record_decision"]
    assert decisions["pending_gates"] == [
        {
            "node_id": "gate-pending",
            "gate_type": "human_approval",
            "prompt": "Approve FR-17 pending work?",
            "options": ["approved", "rejected"],
            "default_option": "rejected",
            "consequence_summary": "FR-17 acceptance fixture.",
        }
    ]
    assert decisions["appeals"] == [
        {"node_id": "appeal-1", "state": "completed", "outcome": "rejected"}
    ]
    assert decisions["review"] == {"ready": False, "blockers": ["review-1: merge_conflicts"]}

    assert scheduler["event_count"] == graph["event_count"]
    assert "review-1" in scheduler["scheduler"]["ready"]
    assert scheduler["scheduler"]["blocked"] == []
    assert scheduler["leases"] == {"active": [], "suspended": []}

    assert patches["attempts"][0]["patch_id"] == "patch-fr17-rejected"
    assert patches["attempts"][0]["status"] == "rejected"
    assert patches["attempts"][0]["diagnostics"]["actor_role"] == "planner"
    assert patches["attempts"][0]["diagnostics"]["diagnostics"] == {
        "macro": "create_join",
        "valid": False,
    }

    assert regions["event_count"] == graph["event_count"]
    assert regions["regions"]
    assert regions["regions"][0]["task_region_id"] == "task-fr17"
    assert blockers["event_count"] == graph["event_count"]
    assert any(blocker["task_region_id"] == "task-fr17" for blocker in blockers["blockers"])


async def _delete_read_models(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                delete(GraphEventSummaryModel).where(GraphEventSummaryModel.run_id == run_id)
            )
            await session.execute(
                delete(GraphProjectionSnapshotModel).where(
                    GraphProjectionSnapshotModel.run_id == run_id
                )
            )
            await session.execute(
                delete(GraphNodeDetailSummaryModel).where(
                    GraphNodeDetailSummaryModel.run_id == run_id
                )
            )


async def _count_model(session: AsyncSession, model: Any, run_id: str) -> int:
    value = await session.scalar(
        select(func.count()).select_from(model).where(model.run_id == run_id)
    )
    assert value is not None
    return int(value)


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
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "fr17-acceptance",
            "name": "FR-17 Acceptance",
            "execution_mode": "graph",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Readback fixture",
                            "task_context": "Exercise less-used graph readbacks.",
                            "requirements": [{"id": "req-1", "desc": "Readbacks are coherent."}],
                            "verifier": {"rubric": [{"id": "req-1", "text": "Coherent."}]},
                        }
                    ],
                }
            ],
        }
    )
