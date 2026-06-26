"""FR-07 acceptance coverage for planner macro tool routing."""

from datetime import timezone
from typing import Any
from uuid import uuid4

import pytest

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config import RunStatus
from orchestrator.db import RunModel, StepModel, TaskModel
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import GraphController, GraphEventStore
from orchestrator.runners import route_tool_call


class _RunSeedIdGenerator:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id.replace("-", "")
        self._count = 0

    def next_id(self, prefix: str) -> str:
        self._count += 1
        return f"{prefix}-{self._run_id}-{self._count}"


async def test_fr07_macro_tools_route_expand_validate_and_read_back_patch_attempts(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    clock = FakeClock()
    run_id = f"graph-fr07-{uuid4().hex[:8]}"
    await _save_graph_run(session_factory, run_id)
    await _seed_fr07_graph(session_factory, run_id, clock)
    controller = GraphController(
        session_factory,
        clock,
        _RunSeedIdGenerator(run_id),
        auto_dispatch=False,
    )

    accepted_feedback = [
        await _route_macro(
            controller,
            run_id,
            "create_join",
            {
                "patch_id": "patch-fr07-create-join",
                "join_id": "join-fr07",
                "sources": [
                    {"node_id": "worker-source", "port": "candidate"},
                    {"node_id": "check-source", "port": "check_result"},
                ],
            },
        ),
        await _route_macro(
            controller,
            run_id,
            "request_gate",
            {
                "patch_id": "patch-fr07-human-gate",
                "gate_id": "gate-fr07-human",
                "reason": "Review macro-created human gate.",
                "options": ["approve", "reject", "defer"],
                "default_option": "defer",
            },
        ),
        await _route_macro(
            controller,
            run_id,
            "request_gate",
            {
                "patch_id": "patch-fr07-authority-gate",
                "gate_id": "gate-fr07-authority",
                "kind": "authority_request",
                "reason": "Worker needs scoped write authority.",
                "requested_authority": ["repo:docs/fr07.md:write"],
                "target_node_id": "worker-authority-target",
            },
        ),
        await _route_macro(
            controller,
            run_id,
            "retire_or_supersede",
            {
                "patch_id": "patch-fr07-retire",
                "target_id": "worker-retire-target",
                "action": "retire",
            },
        ),
        await _route_macro(
            controller,
            run_id,
            "retire_or_supersede",
            {
                "patch_id": "patch-fr07-supersede",
                "target_id": "worker-supersede-target",
                "action": "supersede",
                "replacement_ops": [
                    {
                        "op": "create_node",
                        "node": {
                            "node_id": "worker-supersede-replacement",
                            "kind": "worker",
                            "role": "builder",
                            "state": "planned",
                        },
                    }
                ],
            },
        ),
    ]
    assert accepted_feedback == ["accepted"] * 5

    malformed_feedback = await _route_macro(
        controller,
        run_id,
        "create_join",
        {"patch_id": "patch-fr07-malformed-join", "join_id": "join-bad"},
    )
    invalid_feedback = await _route_macro(
        controller,
        run_id,
        "request_gate",
        {
            "patch_id": "patch-fr07-invalid-authority",
            "gate_id": "gate-fr07-invalid-authority",
            "kind": "authority_request",
            "reason": "Missing requested authority should reject.",
        },
    )
    assert malformed_feedback.startswith("rejected: command_rejected:")
    assert invalid_feedback.startswith("rejected: command_rejected:")

    with pytest.raises(ValueError, match="not on the Codex server v1 allow-list"):
        await route_tool_call(
            "unknown_graph_macro",
            {"patch_id": "patch-fr07-disallowed", "base_graph_position": 0},
            _noop_checklist_update,
            _noop_submit,
            on_submit_graph_patch=_unexpected_patch_callback,
        )

    events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    patches = await _get_json(client, f"/api/runs/{run_id}/graph/patches")
    topology = await _get_json(client, f"/api/runs/{run_id}/graph/topology")
    join_node = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/join-fr07")
    human_gate = await _get_json(client, f"/api/runs/{run_id}/graph/nodes/gate-fr07-human")
    authority_gate = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/gate-fr07-authority?payload_mode=full",
    )
    retired_node = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/worker-retire-target",
    )
    superseded_node = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/worker-supersede-target",
    )
    replacement_node = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/worker-supersede-replacement",
    )

    patch_status = {attempt["patch_id"]: attempt["status"] for attempt in patches["attempts"]}
    assert patch_status == {
        "patch-fr07-create-join": "accepted",
        "patch-fr07-human-gate": "accepted",
        "patch-fr07-authority-gate": "accepted",
        "patch-fr07-retire": "accepted",
        "patch-fr07-supersede": "accepted",
    }
    rejected_command_reasons = [
        event["payload"]["reason"]
        for event in events
        if event["event_type"] == "command_rejected"
        and event["payload"]["command_type"] == "submit_patch"
    ]
    assert any(
        "create_join requires sources or source_ids" in reason
        for reason in rejected_command_reasons
    )
    assert any(
        "request_gate authority_request requires requested_authority" in reason
        for reason in rejected_command_reasons
    )

    edge_by_id = {edge["edge_id"]: edge for edge in topology["edges"]}
    assert {
        "edge-worker-source-candidate-to-join-fr07-1",
        "edge-check-source-check_result-to-join-fr07-2",
    } <= set(edge_by_id)
    assert join_node["kind"] == "join"
    assert edge_by_id["edge-worker-source-candidate-to-join-fr07-1"]["to_port"] == (
        "source_record_1"
    )
    assert edge_by_id["edge-check-source-check_result-to-join-fr07-2"]["to_port"] == (
        "source_record_2"
    )
    assert human_gate["kind"] == "human_gate"
    assert human_gate["state"] == "planned"
    authority_records = [
        event["payload"]
        for event in authority_gate["events"]
        if event["event_type"] == "output_record_accepted"
    ]
    assert authority_records[0]["record_type"] == "authority_request_record"
    assert authority_records[0]["value"]["requested_authority"] == ["repo:docs/fr07.md:write"]
    assert authority_records[0]["value"]["target_node_id"] == "worker-authority-target"
    assert retired_node["state"] == "retired"
    assert superseded_node["state"] == "retired"
    assert replacement_node["kind"] == "worker"
    assert replacement_node["state"] == "planned"
    assert any(event["event_type"] == "node_retired" for event in events)


async def _route_macro(
    controller: GraphController,
    run_id: str,
    tool_name: str,
    args: dict[str, Any],
) -> str:
    payload = dict(args)
    payload["base_graph_position"] = await controller.current_position(run_id)

    async def on_submit_graph_patch(patch_payload: dict[str, Any]) -> str:
        result = await controller.handle_command(
            run_id,
            await controller.current_position(run_id),
            "submit_patch",
            {
                **patch_payload,
                "proposed_by_node_id": "planner-fr07",
                "actor_role": "planner",
            },
        )
        if result.events[0].event_type == "graph_patch_accepted":
            return "accepted"
        reason = result.events[0].payload.get("reason") or result.events[0].payload.get(
            "rejection_reason"
        )
        return f"rejected: {result.events[0].event_type}: {reason}"

    return await route_tool_call(
        tool_name,
        payload,
        _noop_checklist_update,
        _noop_submit,
        on_submit_graph_patch=on_submit_graph_patch,
    )


async def _save_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    now = FakeClock().now().astimezone(timezone.utc).replace(tzinfo=None)
    run = RunModel(
        id=run_id,
        repo_name=f"graph-fr07-acceptance-repo-{run_id}",
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
                        title="Prove FR-07 macros",
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


async def _seed_fr07_graph(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    clock: FakeClock,
) -> None:
    events = [
        _event(run_id, clock, "run_lifecycle_changed", {"to_state": "active"}),
        _event(
            run_id,
            clock,
            "node_created",
            {
                "node_id": "planner-fr07",
                "kind": "planner",
                "role": "planner",
                "state": "running",
            },
        ),
        _event(
            run_id,
            clock,
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
            clock,
            "node_created",
            {
                "node_id": "check-source",
                "kind": "check",
                "role": "auto_verify",
                "state": "completed",
                "command_definition": {"argv": ["uv", "run", "pytest"]},
            },
        ),
        _event(
            run_id,
            clock,
            "node_created",
            {
                "node_id": "worker-authority-target",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
            },
        ),
        _event(
            run_id,
            clock,
            "node_created",
            {
                "node_id": "worker-retire-target",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
            },
        ),
        _event(
            run_id,
            clock,
            "node_created",
            {
                "node_id": "worker-supersede-target",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
            },
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()


def _event(
    run_id: str,
    clock: FakeClock,
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
        timestamp=clock.now(),
        payload=payload,
    )


async def _get_json(client: AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


async def _noop_checklist_update(_req_id: str, _status: Any, _note: str | None) -> None:
    return None


async def _noop_submit() -> None:
    return None


async def _unexpected_patch_callback(_payload: dict[str, Any]) -> str:
    raise AssertionError("disallowed tool should not invoke graph patch callback")
