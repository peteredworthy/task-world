"""FR-10 acceptance coverage for scheduler readiness readbacks."""

from datetime import timezone
from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config import RunStatus
from orchestrator.db import RunModel, StepModel, TaskModel
from orchestrator.graph import (
    Actor,
    ActorKind,
    FakeClock,
    HydratedEvent,
    NodeDeferredPayload,
    NodeStateChangedPayload,
    event_payload_json,
)
from orchestrator.graph_runtime import GraphController, GraphEventStore
from orchestrator.graph import build_graph_catalog
from orchestrator.graph import StoredEventEnvelope


BASE_SNAPSHOT_ID = "snapshot-fr10"


class _RunSeedIdGenerator:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id.replace("-", "")
        self._count = 0

    def next_id(self, prefix: str) -> str:
        self._count += 1
        return f"{prefix}-{self._run_id}-{self._count}"


async def test_fr10_scheduler_readiness_command_precondition_and_retry_readbacks(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    clock = FakeClock()
    run_id = f"graph-fr10-{uuid4().hex[:8]}"
    await _save_graph_run(session_factory, run_id)
    await _seed_fr10_graph(session_factory, run_id, clock)
    controller = GraphController(
        session_factory,
        clock,
        _RunSeedIdGenerator(run_id),
        auto_dispatch=False,
        catalog=build_graph_catalog(),
    )

    first_tick = await controller.handle_command(
        run_id,
        await controller.current_position(run_id),
        "schedule_tick",
        {
            "lease_seconds": 60,
            "max_grants": 1,
            "base_snapshot_id": BASE_SNAPSHOT_ID,
            "priorities": {
                "check-bound-command": 20,
                "worker-retry": 10,
                "check-missing-command": 5,
            },
        },
    )
    assert _event_payloads(first_tick.events, "node_deferred") == [
        NodeDeferredPayload(
            node_id="check-missing-command",
            reason="precondition_failed:has_command_definition",
        )
    ]
    assert any(
        event.event_type == "lease_granted"
        and event_payload_json(event)["node_id"] == "check-bound-command"
        for event in first_tick.events
    )

    retry_scheduled = await controller.handle_command(
        run_id,
        first_tick.projection_position,
        "agent_died",
        {
            "run_id": run_id,
            "lease_id": "lease-worker-retry",
            "execution_id": "exec-worker-retry",
            "reason": "process_exit",
            "retry_backoff_seconds": 60,
        },
    )
    retry_not_before = event_payload_json(retry_scheduled.events[2])["retry_not_before"]
    assert retry_scheduled.events[2].event_type == "runtime_retry_scheduled"
    assert event_payload_json(retry_scheduled.events[2])["retry_after_seconds"] == 60
    state_changed = retry_scheduled.events[4].payload
    assert isinstance(state_changed, NodeStateChangedPayload)
    assert state_changed.node_id == "worker-retry"
    assert state_changed.new_state == "blocked"
    assert state_changed.trigger == "agent_died_retry_backoff_scheduled"
    assert state_changed.retry_not_before == retry_not_before
    assert state_changed.attempt_number == 1

    immediate_tick = await controller.handle_command(
        run_id,
        retry_scheduled.projection_position,
        "schedule_tick",
        {
            "lease_seconds": 60,
            "max_grants": 1,
            "base_snapshot_id": BASE_SNAPSHOT_ID,
            "priorities": {"worker-retry": 20, "check-missing-command": 5},
        },
    )
    assert {
        payload.node_id: payload.reason
        for payload in _event_payloads(immediate_tick.events, "node_deferred")
    } == {
        "worker-retry": f"retry_backoff_until:{retry_not_before}",
    }

    scheduler_during_backoff = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/scheduler",
    )
    check_node_during_backoff = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/check-bound-command?payload_mode=full",
    )
    assert [lease["node_id"] for lease in scheduler_during_backoff["leases"]["active"]] == [
        "check-bound-command",
    ]
    assert scheduler_during_backoff["scheduler"]["blocked"] == [
        {
            "node_id": "check-missing-command",
            "reason": "precondition_failed:has_command_definition",
        },
        {
            "node_id": "worker-retry",
            "reason": f"retry_backoff_until:{retry_not_before}",
        },
    ]
    assert check_node_during_backoff["state"] == "leased"
    assert check_node_during_backoff["preconditions"] == ["has_command_definition"]
    assert check_node_during_backoff["command_definition"] == {
        "id": "check-bound-command",
        "command_binding": "dynamic_feature_hidden_oracle",
        "source": "dynamic_feature_hidden_oracle_binding",
        "deferred": True,
    }

    clock.advance(61)
    final_tick = await controller.handle_command(
        run_id,
        immediate_tick.projection_position,
        "schedule_tick",
        {
            "lease_seconds": 60,
            "max_grants": 1,
            "base_snapshot_id": BASE_SNAPSHOT_ID,
            "priorities": {"worker-retry": 20, "check-missing-command": 5},
        },
    )
    assert any(
        event.event_type == "lease_granted"
        and event_payload_json(event)["node_id"] == "worker-retry"
        for event in final_tick.events
    )

    events = await _get_json(client, f"/api/runs/{run_id}/graph/events?payload_mode=full")
    scheduler_after_backoff = await _get_json(client, f"/api/runs/{run_id}/graph/scheduler")
    retry_node = await _get_json(
        client,
        f"/api/runs/{run_id}/graph/nodes/worker-retry?payload_mode=full",
    )

    assert _event_types(events) >= {
        "agent_died",
        "lease_granted",
        "lease_revoked",
        "node_deferred",
        "node_ready",
        "runtime_retry_scheduled",
    }
    assert scheduler_after_backoff["scheduler"]["blocked"] == [
        {
            "node_id": "check-missing-command",
            "reason": "precondition_failed:has_command_definition",
        }
    ]
    assert [lease["node_id"] for lease in scheduler_after_backoff["leases"]["active"]] == [
        "worker-retry"
    ]
    assert retry_node["state"] == "leased"
    assert [
        event["event_type"]
        for event in retry_node["events"]
        if event["event_type"] in {"agent_died", "runtime_retry_scheduled", "lease_granted"}
    ] == ["lease_granted", "agent_died", "runtime_retry_scheduled", "lease_granted"]


async def _save_graph_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> None:
    now = FakeClock().now().astimezone(timezone.utc).replace(tzinfo=None)
    run = RunModel(
        id=run_id,
        repo_name=f"graph-fr10-acceptance-repo-{run_id}",
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
                        title="Prove FR-10 readiness",
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


async def _seed_fr10_graph(
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
                "node_id": "check-missing-command",
                "kind": "check",
                "state": "planned",
            },
        ),
        _event(
            run_id,
            clock,
            "node_created",
            {
                "node_id": "check-bound-command",
                "kind": "check",
                "state": "planned",
                "command_binding": "dynamic_feature_hidden_oracle",
            },
        ),
        _event(
            run_id,
            clock,
            "node_created",
            {
                "node_id": "worker-retry",
                "kind": "worker",
                "state": "running",
            },
        ),
        _event(
            run_id,
            clock,
            "lease_granted",
            {
                "node_id": "worker-retry",
                "lease_id": "lease-worker-retry",
                "generation": 1,
                "execution_id": "exec-worker-retry",
                "base_snapshot_id": BASE_SNAPSHOT_ID,
                "expires_at": "2026-01-01T00:05:00+00:00",
                "resource_claims": [],
            },
        ),
    ]
    async with session_factory() as session:
        await GraphEventStore(
            session,
            build_graph_catalog(),
        ).append_events(run_id, 0, events)
        await session.commit()


def _event(
    run_id: str,
    clock: FakeClock,
    event_type: str,
    payload: dict[str, Any],
) -> HydratedEvent:
    return (
        build_graph_catalog()
        .resolve_event(event_type)
        .hydrate(
            StoredEventEnvelope(
                event_id=f"{event_type}-{uuid4().hex}",
                run_id=run_id,
                position=-1,
                event_type=event_type,
                payload_schema_generation=2,
                actor=Actor(kind=ActorKind.CONTROLLER),
                timestamp=clock.now(),
                payload=payload,
            )
        )
    )


async def _get_json(client: AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def _event_payloads(events: list[HydratedEvent], event_type: str) -> list[NodeDeferredPayload]:
    return [
        event.payload
        for event in events
        if event.event_type == event_type and isinstance(event.payload, NodeDeferredPayload)
    ]


def _event_types(events: list[dict[str, Any]]) -> set[str]:
    return {event["event_type"] for event in events}
