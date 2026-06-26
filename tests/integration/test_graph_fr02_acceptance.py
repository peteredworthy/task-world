"""FR-02 acceptance coverage for canonical node taxonomy readbacks."""

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
async def fr02_app() -> AsyncGenerator[tuple[AsyncClient, Any], None]:
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


async def test_fr02_canonical_taxonomy_nodes_are_created_and_readable(
    fr02_app: tuple[AsyncClient, Any],
) -> None:
    client, app = fr02_app
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    run_id = f"fr02-taxonomy-{uuid4().hex[:8]}"
    await _save_graph_run(session_factory, run_id)
    await _seed_base_graph(session_factory, run_id)
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
            "patch_id": "patch-fr02-taxonomy",
            "proposed_by_node_id": "planner-fr02",
            "actor_role": "planner",
            "base_graph_position": await controller.current_position(run_id),
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "requirement-fr02",
                        "kind": "requirement",
                        "role": "requirement",
                        "state": "planned",
                    },
                },
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "artifact-index-fr02",
                        "kind": "artifact_index",
                        "state": "planned",
                    },
                },
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "recovery-fr02",
                        "kind": "recovery",
                        "state": "planned",
                    },
                },
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "review-alias-fr02",
                        "kind": "review",
                        "state": "planned",
                    },
                },
            ],
        },
    )
    assert [event.event_type for event in accepted.events].count("graph_patch_accepted") == 1

    events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    topology = await _get_json(client, f"/api/runs/{run_id}/graph/topology")
    patches = await _get_json(client, f"/api/runs/{run_id}/graph/patches")
    final_blockers = await _get_json(client, f"/api/runs/{run_id}/graph/final-blockers")
    requirement = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/requirement-fr02")
    artifact_index = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/artifact-index-fr02",
    )
    recovery = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/recovery-fr02")
    review_alias = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/review-alias-fr02")

    assert [event["position"] for event in events] == list(range(1, len(events) + 1))
    node_created_ids = {
        event["payload"]["node_id"] for event in events if event["event_type"] == "node_created"
    }
    assert {
        "requirement-fr02",
        "artifact-index-fr02",
        "recovery-fr02",
        "review-alias-fr02",
    } <= node_created_ids

    assert len(patches["attempts"]) == 1
    patch_attempt = patches["attempts"][0]
    assert patch_attempt["patch_id"] == "patch-fr02-taxonomy"
    assert patch_attempt["proposed_by_node_id"] == "planner-fr02"
    assert patch_attempt["status"] == "accepted"
    assert patch_attempt["base_graph_position"] == 2
    assert patch_attempt["accepted_position"] == 3
    assert patch_attempt["rejection_reason"] is None
    assert patch_attempt["read_set_diff"] is None
    assert set(patch_attempt["created_node_ids"]) == {
        "requirement-fr02",
        "artifact-index-fr02",
        "recovery-fr02",
        "review-alias-fr02",
    }
    topology_nodes = {node["node_id"]: node for node in topology["nodes"]}
    assert topology_nodes["requirement-fr02"]["contract"]["node_type"] == "requirement"
    assert topology_nodes["artifact-index-fr02"]["contract"]["node_type"] == "artifact_index"
    assert topology_nodes["recovery-fr02"]["contract"]["node_type"] == "recovery"
    assert topology_nodes["review-alias-fr02"]["contract"]["node_type"] == "recovery"

    assert requirement["kind"] == "requirement"
    assert requirement["contract"]["node_type"] == "requirement"
    assert requirement["contract"]["handler_type"] == "controller"
    assert requirement["contract"]["roles"] == ["requirement"]
    assert requirement["contract"]["input_ports"]["routine_snapshot"]["schemas"] == [
        "RoutineSnapshot"
    ]
    assert requirement["contract"]["output_ports"]["requirement"]["schemas"] == ["Requirement"]
    assert requirement["contract"]["output_ports"]["requirement_record"]["record_types"] == [
        "requirement_record"
    ]

    assert artifact_index["kind"] == "artifact_index"
    assert artifact_index["contract"]["node_type"] == "artifact_index"
    assert artifact_index["contract"]["handler_type"] == "controller"
    assert artifact_index["contract"]["input_ports"]["file_state"]["schemas"] == ["FileStateRecord"]
    assert artifact_index["contract"]["input_ports"]["verification_report"]["schemas"] == [
        "VerificationReport"
    ]
    assert artifact_index["contract"]["output_ports"]["artifact_reference"]["record_types"] == [
        "artifact_reference"
    ]

    assert recovery["kind"] == "recovery"
    assert recovery["contract"]["node_type"] == "recovery"
    assert recovery["contract"]["handler_type"] == "controller"
    assert recovery["contract"]["input_ports"]["failure_record"]["schemas"] == ["FailureRecord"]
    assert recovery["contract"]["output_ports"]["recovery_plan"]["schemas"] == ["RecoveryPlan"]
    assert recovery["contract"]["output_ports"]["graph_patch_proposal"]["schemas"] == ["GraphPatch"]

    assert review_alias["kind"] == "review"
    assert review_alias["contract"] == recovery["contract"]
    blocker_node_ids = {blocker.get("node_id") for blocker in final_blockers["blockers"]}
    assert {"requirement-fr02", "artifact-index-fr02", "recovery-fr02"} <= blocker_node_ids


async def _save_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    now = FakeClock().now().astimezone(timezone.utc).replace(tzinfo=None)
    run = RunModel(
        id=run_id,
        repo_name=f"graph-fr02-acceptance-repo-{run_id}",
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
                        title="Prove FR-02 taxonomy",
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


async def _seed_base_graph(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    events = [
        _event(run_id, "run_lifecycle_changed", {"to_state": "active"}),
        _event(
            run_id,
            "node_created",
            {
                "node_id": "planner-fr02",
                "kind": "planner",
                "role": "planner",
                "state": "running",
            },
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()


def _event(
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> EventEnvelope:
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


async def _get_json(client: AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200, response.text
    return response.json()
