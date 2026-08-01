from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.config.models import RoutineConfig
from orchestrator.db import (
    EventV2Model,
    GraphProjectionSnapshotModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import (
    PROJECTION_SCHEMA_VERSION,
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    PatchCommandContext,
    SequentialIdGenerator,
    initial_projection,
    projection_to_checkpoint,
    reduce_event,
)
from orchestrator.graph_runtime import (
    GraphController,
    GraphEventStore,
    StaleProjectionError,
    seed_run,
)
from orchestrator.graph_runtime.store import graph_aggregate_id
from tests.unit.graph_test_utils import canonical_event_payload


@pytest.fixture(scope="module")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


def _event(event_id: str, run_id: str, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        causation_id="test",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "snapshot-routine",
            "name": "Snapshot Routine",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [{"id": "task-1", "title": "Task 1"}],
                }
            ],
        }
    )


def _rebuild_projection(events: list[EventEnvelope]) -> dict[str, Any]:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


@pytest.mark.asyncio
async def test_append_read_round_trip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-round-trip"
    events = [
        _event("evt-1", run_id, "run_lifecycle_changed", {"to_state": "active"}),
        _event("evt-2", run_id, "node_created", {"node_id": "worker-1", "kind": "worker"}),
    ]

    async with session_factory() as session:
        async with session.begin():
            stored = await GraphEventStore(session).append_events(run_id, 0, events)

    async with session_factory() as session:
        read_back = await GraphEventStore(session).read_run(run_id)

    assert [event.position for event in stored] == [1, 2]
    assert read_back == stored


@pytest.mark.asyncio
async def test_compact_readers_filter_union_fields_by_event_type_and_mode(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-compact-payload-boundary"
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    lifecycle_payload = {
        "command_type": "accept_run",
        "event_id": "legacy-payload-event-id",
        "from_state": "draft",
        "to_state": "queued",
        "trigger": "accept_run_command_accepted",
    }
    outbox_payload = {
        "run_id": run_id,
        "outbox_id": 7,
        "event_id": "requeued-event-id",
        "kind": "agent_dispatch",
        "previous_status": "failed",
        "previous_attempts": 3,
        "previous_last_error": "dispatch failed",
        "operator": "human-operator",
        "graph_position": 2,
    }
    events = [
        EventEnvelope(
            event_id="lifecycle-envelope-id",
            run_id=run_id,
            position=1,
            event_type="run_lifecycle_changed",
            schema_version=1,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=timestamp,
            payload=lifecycle_payload,
        ),
        EventEnvelope(
            event_id="outbox-envelope-id",
            run_id=run_id,
            position=2,
            event_type="outbox_requeued",
            schema_version=1,
            actor=Actor(kind=ActorKind.HUMAN),
            timestamp=timestamp,
            payload=outbox_payload,
        ),
    ]
    async with session_factory() as session:
        session.add_all(
            EventV2Model(
                aggregate_id=graph_aggregate_id(run_id),
                version=event.position,
                event_type=event.event_type,
                payload=event.model_dump_json(),
                timestamp=event.timestamp.isoformat(),
            )
            for event in events
        )
        await session.commit()

    expected_lifecycle = {
        field: value for field, value in lifecycle_payload.items() if field != "event_id"
    }
    async with session_factory() as session:
        store = GraphEventStore(session)
        readers_and_expected_outbox = (
            (store.read_run_projection, outbox_payload),
            (store.read_run_light, outbox_payload),
            (store.read_run_summary_rebuild, outbox_payload),
            (store.read_run_node_detail, outbox_payload),
        )
        for reader, expected_outbox in readers_and_expected_outbox:
            compact = await reader(run_id)
            assert compact[0].event_id == "lifecycle-envelope-id"
            assert compact[0].payload == expected_lifecycle
            assert compact[1].event_id == "outbox-envelope-id"
            assert compact[1].payload == expected_outbox


@pytest.mark.asyncio
async def test_projection_snapshot_tail_matches_full_rebuild(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-snapshot-tail-parity"
    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)

    seed = await seed_run(session_factory, _routine(), run_id=run_id, clock=clock, id_gen=ids)
    accepted = await controller.handle_command(run_id, seed.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {"max_grants": 0, "base_snapshot_id": "S0"},
    )

    async with session_factory() as session:
        store = GraphEventStore(session)
        events = await store.read_run(run_id)
        checkpoint = await store.read_projection_checkpoint(run_id)

    assert checkpoint is not None
    assert checkpoint.position == max(event.position for event in events)
    assert checkpoint.schema_version == PROJECTION_SCHEMA_VERSION
    assert checkpoint.projection == _rebuild_projection(events)


@pytest.mark.asyncio
async def test_handle_command_uses_valid_snapshot_without_parsing_old_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-command-valid-snapshot-no-replay"
    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)

    seed = await seed_run(session_factory, _routine(), run_id=run_id, clock=clock, id_gen=ids)
    accepted = await controller.handle_command(run_id, seed.projection_position, "accept_run")

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                update(EventV2Model)
                .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
                .where(EventV2Model.version == 1)
                .values(payload="{not valid event json")
            )

    result = await controller.handle_command(
        run_id,
        accepted.projection_position,
        "record_requirement_revision",
        {
            "requirement_id": "R-1",
            "version_id": "R-1.v1",
            "classification": "copy",
        },
    )

    assert [event.event_type for event in result.events] == ["requirement_revision_recorded"]


@pytest.mark.asyncio
async def test_submit_patch_uses_events_since_base_when_snapshot_tail_is_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-stale-patch-history"
    controller = GraphController(
        session_factory,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    setup_events = [
        _event("evt-run-active", run_id, "run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "evt-worker-stale",
            run_id,
            "node_created",
            {"node_id": "worker-stale", "kind": "worker", "role": "builder", "state": "planned"},
        ),
        _event(
            "evt-worker-stale-cancelled",
            run_id,
            "node_state_changed",
            {
                "node_id": "worker-stale",
                "new_state": "cancelled",
                "trigger": "test_conflict",
            },
        ),
    ]
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, setup_events)

    result = await controller.handle_command(
        run_id,
        3,
        "submit_patch",
        {
            "patch_id": "patch-stale",
            "base_graph_position": 2,
            "ops": [{"op": "retire_node", "node_id": "worker-stale"}],
        },
        context=PatchCommandContext(
            run_id=run_id,
            current_graph_position=3,
            proposed_by_node_id="planner-1",
            actor_role="planner",
        ),
    )

    assert [event.event_type for event in result.events] == ["graph_patch_rejected"]
    assert result.events[0].payload["reason"] == "stale patch conflicts with invalidating events"
    assert result.events[0].payload["read_set_diff"]["conflicting_event_ids"] == [
        "evt-worker-stale-cancelled"
    ]


@pytest.mark.asyncio
async def test_schedule_tick_uses_valid_snapshot_without_parsing_old_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-schedule-valid-snapshot-no-replay"
    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)

    seed = await seed_run(session_factory, _routine(), run_id=run_id, clock=clock, id_gen=ids)
    accepted = await controller.handle_command(run_id, seed.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                update(EventV2Model)
                .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
                .where(EventV2Model.version == 1)
                .values(payload="{not valid event json")
            )

    result = await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {"max_grants": 0, "base_snapshot_id": "S0"},
    )

    assert all(event.event_type != "command_rejected" for event in result.events)


@pytest.mark.asyncio
async def test_callback_idempotency_uses_valid_snapshot_without_replay(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-callback-idempotency-snapshot"
    controller = GraphController(
        session_factory,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    setup_events = [
        _event("evt-run-active", run_id, "run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "evt-worker",
            run_id,
            "node_created",
            {"node_id": "planner-1", "kind": "planner", "role": "planner", "state": "running"},
        ),
        _event(
            "evt-lease",
            run_id,
            "lease_granted",
            {
                "lease_id": "lease-1",
                "node_id": "planner-1",
                "generation": 1,
                "execution_id": "exec-1",
                "base_snapshot_id": "S0",
            },
        ),
    ]
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, setup_events)

    payload = {
        "node_id": "planner-1",
        "execution_id": "exec-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "base_snapshot_id": "S0",
        "observed_graph_position": 3,
        "idempotency_key": "callback-key-1",
        "payload_hash": "callback-hash-1",
    }
    first = await controller.handle_command(run_id, 3, "submit_callback", payload)
    second = await controller.handle_command(
        run_id,
        first.projection_position,
        "submit_callback",
        payload,
    )

    assert [event.event_type for event in first.events] == [
        "callback_accepted",
        "node_state_changed",
        "lease_released",
    ]
    assert [event.event_type for event in second.events] == ["callback_duplicate_returned"]
    assert second.events[0].payload["prior_result"]["outcome"] == "callback_accepted"


@pytest.mark.asyncio
async def test_projection_snapshot_schema_mismatch_is_rebuilt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-snapshot-version-rebuild"
    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)

    seed = await seed_run(session_factory, _routine(), run_id=run_id, clock=clock, id_gen=ids)
    accepted = await controller.handle_command(run_id, seed.projection_position, "accept_run")

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                update(GraphProjectionSnapshotModel)
                .where(GraphProjectionSnapshotModel.run_id == run_id)
                .values(
                    decisions={
                        "_projection_schema_version": PROJECTION_SCHEMA_VERSION - 1,
                        "_projection_checkpoint": {"bad": "data"},
                        "_projection_terminal": False,
                    }
                )
            )

    await controller.handle_command(run_id, accepted.projection_position, "start")

    async with session_factory() as session:
        store = GraphEventStore(session)
        events = await store.read_run(run_id)
        checkpoint = await store.read_projection_checkpoint(run_id)

    assert checkpoint is not None
    assert checkpoint.schema_version == PROJECTION_SCHEMA_VERSION
    assert checkpoint.projection == _rebuild_projection(events)


@pytest.mark.asyncio
async def test_append_invalidates_legacy_v12_flat_projection_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-append-legacy-v12-snapshot"
    seed_event = _event("evt-seed", run_id, "run_lifecycle_changed", {"to_state": "active"})
    appended_event = _event(
        "evt-appended",
        run_id,
        "node_created",
        {"node_id": "worker-1", "kind": "worker"},
    )

    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, [seed_event])

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                update(GraphProjectionSnapshotModel)
                .where(GraphProjectionSnapshotModel.run_id == run_id)
                .values(
                    decisions={
                        "_projection_schema_version": 12,
                        "_projection_checkpoint": {"run_state": "active"},
                        "_projection_terminal": False,
                    }
                )
            )

    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session)
            stored = await store.append_events(run_id, 1, [appended_event])
            assert [event.event_id for event in stored] == ["evt-appended"]
            assert await session.get(GraphProjectionSnapshotModel, run_id) is None
            rebuilt_snapshot = await store.read_projection_snapshot(run_id)
            rebuilt = await store.read_projection_checkpoint(run_id)

    async with session_factory() as session:
        store = GraphEventStore(session)
        events = await store.read_run(run_id)
        checkpoint = await store.read_projection_checkpoint(run_id)

    assert [event.event_id for event in events] == ["evt-seed", "evt-appended"]
    assert rebuilt_snapshot is not None
    assert rebuilt is not None
    assert checkpoint is not None
    assert checkpoint.schema_version == PROJECTION_SCHEMA_VERSION
    assert checkpoint.position == 2
    assert checkpoint.projection == _rebuild_projection(events)


@pytest.mark.asyncio
async def test_append_invalidates_current_malformed_projection_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-append-malformed-current-snapshot"
    seed_event = _event("evt-seed", run_id, "run_lifecycle_changed", {"to_state": "active"})
    appended_event = _event(
        "evt-appended",
        run_id,
        "node_created",
        {"node_id": "worker-1", "kind": "worker"},
    )

    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, [seed_event])

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                update(GraphProjectionSnapshotModel)
                .where(GraphProjectionSnapshotModel.run_id == run_id)
                .values(
                    decisions={
                        "_projection_schema_version": PROJECTION_SCHEMA_VERSION,
                        "_projection_checkpoint": {"not": "a canonical projection"},
                        "_projection_terminal": False,
                    }
                )
            )

    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session)
            stored = await store.append_events(run_id, 1, [appended_event])
            assert [event.event_id for event in stored] == ["evt-appended"]
            assert await session.get(GraphProjectionSnapshotModel, run_id) is None
            rebuilt_snapshot = await store.read_projection_snapshot(run_id)
            rebuilt = await store.read_projection_checkpoint(run_id)

    async with session_factory() as session:
        store = GraphEventStore(session)
        events = await store.read_run(run_id)
        checkpoint = await store.read_projection_checkpoint(run_id)

    assert [event.event_id for event in events] == ["evt-seed", "evt-appended"]
    assert rebuilt_snapshot is not None
    assert rebuilt is not None
    assert checkpoint is not None
    assert checkpoint.schema_version == PROJECTION_SCHEMA_VERSION
    assert checkpoint.position == 2
    assert checkpoint.projection == _rebuild_projection(events)


@pytest.mark.asyncio
async def test_current_projection_snapshot_with_invalid_integrity_is_rebuilt(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-snapshot-integrity-rebuild"
    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)

    seed = await seed_run(session_factory, _routine(), run_id=run_id, clock=clock, id_gen=ids)
    accepted = await controller.handle_command(run_id, seed.projection_position, "accept_run")
    async with session_factory() as session:
        store = GraphEventStore(session)
        checkpoint = await store.read_projection_checkpoint(run_id)
    assert checkpoint is not None
    malformed = projection_to_checkpoint(checkpoint.projection)
    malformed["scheduling"]["ready_node_ids"] = ["missing-node"]

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                update(GraphProjectionSnapshotModel)
                .where(GraphProjectionSnapshotModel.run_id == run_id)
                .values(
                    decisions={
                        "_projection_schema_version": PROJECTION_SCHEMA_VERSION,
                        "_projection_checkpoint": malformed,
                        "_projection_terminal": False,
                    }
                )
            )

    await controller.handle_command(run_id, accepted.projection_position, "start")

    async with session_factory() as session:
        store = GraphEventStore(session)
        events = await store.read_run(run_id)
        repaired = await store.read_projection_checkpoint(run_id)

    assert repaired is not None
    assert repaired.projection == _rebuild_projection(events)


@pytest.mark.asyncio
async def test_current_partial_projection_checkpoint_is_rebuilt_and_rewritten(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-snapshot-partial-rebuild"
    assert PROJECTION_SCHEMA_VERSION == 13
    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)

    seed = await seed_run(session_factory, _routine(), run_id=run_id, clock=clock, id_gen=ids)
    await controller.handle_command(run_id, seed.projection_position, "accept_run")

    async with session_factory() as session:
        store = GraphEventStore(session)
        checkpoint = await store.read_projection_checkpoint(run_id)
    assert checkpoint is not None
    malformed = projection_to_checkpoint(checkpoint.projection)
    malformed.pop("usage")

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                update(GraphProjectionSnapshotModel)
                .where(GraphProjectionSnapshotModel.run_id == run_id)
                .values(
                    decisions={
                        "_projection_schema_version": PROJECTION_SCHEMA_VERSION,
                        "_projection_checkpoint": malformed,
                        "_projection_terminal": False,
                    }
                )
            )

    async with session_factory() as session:
        store = GraphEventStore(session)
        snapshot = await store.read_projection_snapshot(run_id)
        events = await store.read_run(run_id)
        rebuilt = await store.read_projection_checkpoint(run_id)

    assert snapshot is not None
    assert rebuilt is not None
    assert rebuilt.position == max(event.position for event in events)
    assert rebuilt.projection == _rebuild_projection(events)
    assert "usage" in rebuilt.projection.model_dump(mode="json")


@pytest.mark.asyncio
async def test_idle_schedule_tick_does_not_duplicate_node_deferred(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-idle-deferral-dedup"
    controller = GraphController(
        session_factory,
        FakeClock(),
        SequentialIdGenerator(),
        auto_dispatch=False,
    )
    setup_events = [
        _event("evt-run-active", run_id, "run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "evt-worker",
            run_id,
            "node_created",
            {"node_id": "worker-1", "kind": "worker", "state": "planned"},
        ),
    ]
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, setup_events)

    first = await controller.handle_command(
        run_id,
        2,
        "schedule_tick",
        {"max_grants": 0, "base_snapshot_id": "S0"},
    )
    second = await controller.handle_command(
        run_id,
        first.projection_position,
        "schedule_tick",
        {"max_grants": 0, "base_snapshot_id": "S0"},
    )

    first_deferrals = [event for event in first.events if event.event_type == "node_deferred"]
    second_deferrals = [event for event in second.events if event.event_type == "node_deferred"]
    assert len(first_deferrals) == 1
    assert second_deferrals == []

    async with session_factory() as session:
        snapshot = await GraphEventStore(session).read_projection_snapshot(run_id)

    assert snapshot is not None
    assert first_deferrals[0].payload["reason"] == "max_grants_reached"
    assert snapshot.scheduler["blocked"] == []


@pytest.mark.asyncio
async def test_incremental_scheduler_snapshot_matches_canonical_rebuild_for_max_grants(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-scheduler-snapshot-parity"
    events = [
        _event(
            "evt-worker-maxed",
            run_id,
            "node_created",
            {"node_id": "worker-maxed", "kind": "worker", "state": "ready"},
        ),
        _event(
            "evt-worker-maxed-deferred",
            run_id,
            "node_deferred",
            {"node_id": "worker-maxed", "reason": "max_grants_reached"},
        ),
        _event(
            "evt-worker-input",
            run_id,
            "node_created",
            {"node_id": "worker-input", "kind": "worker", "state": "planned"},
        ),
        _event(
            "evt-worker-input-deferred",
            run_id,
            "node_deferred",
            {"node_id": "worker-input", "reason": "missing_required_input:candidate"},
        ),
        _event(
            "evt-worker-resource",
            run_id,
            "node_created",
            {"node_id": "worker-resource", "kind": "worker", "state": "ready"},
        ),
        _event(
            "evt-worker-resource-deferred",
            run_id,
            "node_deferred",
            {"node_id": "worker-resource", "reason": "resource_conflict:write:write"},
        ),
    ]
    expected = {
        "ready": ["worker-maxed", "worker-resource"],
        "blocked": [{"node_id": "worker-input", "reason": "missing_required_input:candidate"}],
        "waiting_resources": [
            {"node_id": "worker-resource", "reason": "resource_conflict:write:write"}
        ],
        "waiting_gates": [],
    }

    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session)
            await store.append_events(run_id, 0, events)
            incremental = await store.read_projection_snapshot(run_id)

        assert incremental is not None
        incremental_scheduler = dict(incremental.scheduler)

        async with session.begin():
            rebuilt = await store.rebuild_read_models(run_id)

        assert rebuilt is not None
        rebuilt_scheduler = dict(rebuilt.scheduler)

    assert incremental_scheduler == expected
    assert rebuilt_scheduler == expected


@pytest.mark.asyncio
async def test_projection_checkpoint_records_terminal_flag(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    terminal_run_id = "store-terminal-recovery-skip"
    active_run_id = "store-active-recovery-arm"
    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session)
            await store.append_events(
                terminal_run_id,
                0,
                [
                    _event(
                        "evt-terminal",
                        terminal_run_id,
                        "run_lifecycle_changed",
                        {"to_state": "completed"},
                    )
                ],
            )
            await store.append_events(
                active_run_id,
                0,
                [
                    _event(
                        "evt-active",
                        active_run_id,
                        "run_lifecycle_changed",
                        {"to_state": "active"},
                    )
                ],
            )
            terminal_checkpoint = await store.read_projection_checkpoint(terminal_run_id)
            active_checkpoint = await store.read_projection_checkpoint(active_run_id)

    assert terminal_checkpoint is not None
    assert active_checkpoint is not None
    assert terminal_checkpoint.terminal is True
    assert active_checkpoint.terminal is False


@pytest.mark.asyncio
async def test_append_events_stores_durable_input_binding_position(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-input-bound-position"
    events = [
        _event("evt-node", run_id, "node_created", {"node_id": "verifier-1", "kind": "verifier"}),
        _event(
            "evt-input",
            run_id,
            "input_bound",
            {
                "edge_id": "edge-candidate",
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-1"],
                "bound_at_position": 0,
            },
        ),
    ]

    async with session_factory() as session:
        async with session.begin():
            stored = await GraphEventStore(session).append_events(run_id, 0, events)

    async with session_factory() as session:
        read_back = await GraphEventStore(session).read_run(run_id)

    assert stored[1].position == 2
    assert stored[1].payload["bound_at_position"] == 2
    assert read_back[1].payload["bound_at_position"] == 2


@pytest.mark.asyncio
async def test_append_events_adds_durable_base_fields_to_accepted_records(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-record-base-fields"
    events = [
        _event(
            "evt-candidate",
            run_id,
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-1",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "done"},
            },
        ),
        _event(
            "evt-file-state",
            run_id,
            "file_state_accepted",
            {
                "record_id": "file-state-1",
                "record_kind": "file_state",
                "producer_node_id": "worker-1",
                "port": "file_state",
                "schema": "FileStateRecord",
                "snapshot_id": "snapshot-1",
                "base_snapshot_id": "S0",
                "verdict": "captured",
            },
        ),
        _event(
            "evt-verification",
            run_id,
            "output_record_accepted",
            {
                "record_id": "verification-1",
                "record_kind": "verification",
                "producer_node_id": "verifier-1",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-1",
                "outcome": "passed",
                "value": {
                    "outcome": "passed",
                    "grades": [
                        {
                            "requirement_id": "R-1",
                            "grade": "A",
                            "reason": "satisfied",
                        }
                    ],
                },
            },
        ),
        _event(
            "evt-check",
            run_id,
            "output_record_accepted",
            {
                "record_id": "check-1",
                "record_kind": "output",
                "record_type": "check_result",
                "producer_node_id": "check-1",
                "port": "check_result",
                "schema": "CheckResult",
                "value": {
                    "status": "passed",
                    "classification": "passed",
                    "command_id": "unit-check",
                },
            },
        ),
        _event(
            "evt-decision-request",
            run_id,
            "output_record_accepted",
            {
                "record_id": "decision-request-1",
                "record_kind": "graph_record",
                "producer_node_id": "gate-1",
                "port": "decision_request",
                "schema": "DecisionRequest",
                "value": {
                    "decision_type": "approval",
                    "options": ["approve", "reject"],
                    "default_option": "reject",
                    "consequence_summary": "Approve planner expansion.",
                },
            },
        ),
        _event(
            "evt-authority-request",
            run_id,
            "output_record_accepted",
            {
                "record_id": "authority-request-1",
                "record_kind": "graph_record",
                "producer_node_id": "authority-1",
                "port": "authority_request_record",
                "schema": "AuthorityRequest",
                "value": {
                    "requested_authority": ["repo:docs/**:write"],
                    "target_node_id": "worker-docs",
                    "reason": "Worker needs docs write access.",
                },
            },
        ),
        _event(
            "evt-failure",
            run_id,
            "output_record_accepted",
            {
                "record_id": "failure-1",
                "record_kind": "graph_record",
                "record_type": "failure_record",
                "producer_node_id": "worker-1",
                "port": "failure_record",
                "schema": "FailureRecord",
                "value": {
                    "failed_node_id": "worker-1",
                    "phase": "runtime",
                    "error_class": "max_attempts_exhausted",
                    "retryable": False,
                },
            },
        ),
        _event(
            "evt-recovery-plan",
            run_id,
            "output_record_accepted",
            {
                "record_id": "recovery-plan-1",
                "record_kind": "output",
                "record_type": "recovery_plan",
                "producer_node_id": "recovery-1",
                "port": "recovery_plan",
                "schema": "RecoveryPlan",
                "value": {
                    "action": "retry",
                    "responsible_actor": "controller",
                    "graph_changes": [],
                    "reason": "retry after transient worker failure",
                },
            },
        ),
        _event(
            "evt-run-context",
            run_id,
            "output_record_accepted",
            {
                "record_id": "run-context",
                "record_kind": "graph_record",
                "record_type": "run_context",
                "producer_node_id": "root",
                "port": "run_context",
                "schema": "RunContext",
                "value": {
                    "routine_id": "routine-1",
                    "routine_name": "Routine",
                },
            },
        ),
        _event(
            "evt-routine-snapshot",
            run_id,
            "output_record_accepted",
            {
                "record_id": "routine-snapshot-record",
                "record_kind": "graph_record",
                "record_type": "routine_snapshot",
                "producer_node_id": "routine-snapshot",
                "port": "snapshot",
                "schema": "RoutineSnapshot",
                "value": {
                    "routine_id": "routine-1",
                    "name": "Routine",
                    "content_hash": "abc123",
                    "step_count": 1,
                    "task_count": 1,
                },
            },
        ),
        _event(
            "evt-artifact-reference",
            run_id,
            "output_record_accepted",
            {
                "record_id": "artifact-reference-1",
                "record_kind": "graph_record",
                "record_type": "artifact_reference",
                "producer_node_id": "context-1",
                "port": "artifact",
                "schema": "ContextArtifact",
                "value": {
                    "artifact_id": "spec",
                    "artifact_type": "context_source",
                    "uri": "docs/spec.md",
                },
            },
        ),
    ]

    async with session_factory() as session:
        async with session.begin():
            stored = await GraphEventStore(session).append_events(run_id, 0, events)

    async with session_factory() as session:
        read_back = await GraphEventStore(session).read_run(run_id)

    candidate = stored[0].payload
    assert candidate["record_type"] == "candidate"
    assert candidate["schema_version"] == 1
    assert candidate["producer_port"] == "candidate"
    assert candidate["run_id"] == run_id
    assert candidate["created_at"] == "2026-01-01T00:00:00+00:00"
    assert candidate["graph_position"] == 1
    assert candidate["payload"] == {"summary": "done"}

    file_state = stored[1].payload
    assert file_state["record_type"] == "file_state"
    assert file_state["schema_version"] == 1
    assert file_state["producer_port"] == "file_state"
    assert file_state["run_id"] == run_id
    assert file_state["created_at"] == "2026-01-01T00:00:00+00:00"
    assert file_state["graph_position"] == 2
    assert file_state["payload"] == {
        "snapshot_id": "snapshot-1",
        "base_snapshot_id": "S0",
        "verdict": "captured",
    }

    verification = stored[2].payload
    assert verification["record_type"] == "verification_report"
    assert verification["schema_version"] == 1
    assert verification["producer_port"] == "verification_report"
    assert verification["run_id"] == run_id
    assert verification["created_at"] == "2026-01-01T00:00:00+00:00"
    assert verification["graph_position"] == 3
    assert verification["payload"] == {
        "outcome": "passed",
        "grades": [{"requirement_id": "R-1", "grade": "A", "reason": "satisfied"}],
    }

    check_result = stored[3].payload
    assert check_result["record_type"] == "check_result"
    assert check_result["schema_version"] == 1
    assert check_result["producer_port"] == "check_result"
    assert check_result["run_id"] == run_id
    assert check_result["created_at"] == "2026-01-01T00:00:00+00:00"
    assert check_result["graph_position"] == 4
    assert check_result["payload"]["status"] == "passed"
    assert check_result["payload"]["classification"] == "passed"
    assert check_result["payload"]["command_id"] == "unit-check"

    decision_request = stored[4].payload
    assert decision_request["record_type"] == "decision_request"
    assert decision_request["schema_version"] == 1
    assert decision_request["producer_port"] == "decision_request"
    assert decision_request["run_id"] == run_id
    assert decision_request["graph_position"] == 5
    assert decision_request["payload"] == {
        "decision_type": "approval",
        "options": ["approve", "reject"],
        "default_option": "reject",
        "consequence_summary": "Approve planner expansion.",
    }

    authority_request = stored[5].payload
    assert authority_request["record_type"] == "authority_request_record"
    assert authority_request["schema_version"] == 1
    assert authority_request["producer_port"] == "authority_request_record"
    assert authority_request["run_id"] == run_id
    assert authority_request["graph_position"] == 6
    assert authority_request["payload"] == {
        "requested_authority": ["repo:docs/**:write"],
        "target_node_id": "worker-docs",
        "reason": "Worker needs docs write access.",
    }

    failure = stored[6].payload
    assert failure["record_type"] == "failure_record"
    assert failure["schema_version"] == 1
    assert failure["producer_port"] == "failure_record"
    assert failure["run_id"] == run_id
    assert failure["graph_position"] == 7
    assert failure["payload"] == {
        "failed_node_id": "worker-1",
        "phase": "runtime",
        "error_class": "max_attempts_exhausted",
        "retryable": False,
    }

    recovery_plan = stored[7].payload
    assert recovery_plan["record_type"] == "recovery_plan"
    assert recovery_plan["schema_version"] == 1
    assert recovery_plan["producer_port"] == "recovery_plan"
    assert recovery_plan["run_id"] == run_id
    assert recovery_plan["graph_position"] == 8
    assert recovery_plan["payload"] == {
        "action": "retry",
        "responsible_actor": "controller",
        "graph_changes": [],
        "reason": "retry after transient worker failure",
    }

    run_context = stored[8].payload
    assert run_context["record_type"] == "run_context"
    assert run_context["schema_version"] == 1
    assert run_context["producer_port"] == "run_context"
    assert run_context["run_id"] == run_id
    assert run_context["graph_position"] == 9
    assert run_context["payload"] == {"routine_id": "routine-1", "routine_name": "Routine"}

    routine_snapshot = stored[9].payload
    assert routine_snapshot["record_type"] == "routine_snapshot"
    assert routine_snapshot["schema_version"] == 1
    assert routine_snapshot["producer_port"] == "snapshot"
    assert routine_snapshot["run_id"] == run_id
    assert routine_snapshot["graph_position"] == 10
    assert routine_snapshot["payload"] == {
        "routine_id": "routine-1",
        "name": "Routine",
        "content_hash": "abc123",
        "step_count": 1,
        "task_count": 1,
    }

    artifact_reference = stored[10].payload
    assert artifact_reference["record_type"] == "artifact_reference"
    assert artifact_reference["schema_version"] == 1
    assert artifact_reference["producer_port"] == "artifact"
    assert artifact_reference["run_id"] == run_id
    assert artifact_reference["graph_position"] == 11
    assert artifact_reference["payload"] == {
        "artifact_id": "spec",
        "artifact_type": "context_source",
        "uri": "docs/spec.md",
    }
    assert read_back == stored


@pytest.mark.asyncio
async def test_append_events_rejects_malformed_accepted_record_atomically(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-record-base-rejection"
    events = [
        _event("evt-node", run_id, "node_created", {"node_id": "worker-1", "kind": "worker"}),
        _event(
            "evt-bad-record",
            run_id,
            "output_record_accepted",
            {
                "record_id": "candidate-1",
                "record_kind": "output",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "done"},
            },
        ),
    ]
    events[1] = events[1].model_copy(
        update={
            "payload": {
                "record_id": "candidate-1",
                "record_kind": "output",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "done"},
            }
        }
    )

    with pytest.raises(ValueError, match="missing durable record base field: producer_node_id"):
        async with session_factory() as session:
            async with session.begin():
                await GraphEventStore(session).append_events(run_id, 0, events)

    async with session_factory() as session:
        store = GraphEventStore(session)
        assert await store.current_position(run_id) == 0
        assert await store.read_run(run_id) == []


@pytest.mark.asyncio
async def test_append_events_rejects_invalid_supplied_durable_base_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-record-base-invalid"

    with pytest.raises(ValueError, match="invalid durable record schema_version"):
        async with session_factory() as session:
            async with session.begin():
                await GraphEventStore(session).append_events(
                    run_id,
                    0,
                    [
                        _event(
                            "evt-bad-schema",
                            run_id,
                            "output_record_accepted",
                            {
                                "record_id": "candidate-1",
                                "record_kind": "output",
                                "producer_node_id": "worker-1",
                                "port": "candidate",
                                "schema": "ImplementationCandidate",
                                "schema_version": 0,
                                "value": {"summary": "done"},
                            },
                        )
                    ],
                )

    with pytest.raises(ValueError, match="producer_port does not match port"):
        async with session_factory() as session:
            async with session.begin():
                await GraphEventStore(session).append_events(
                    run_id,
                    0,
                    [
                        _event(
                            "evt-bad-port",
                            run_id,
                            "output_record_accepted",
                            {
                                "record_id": "candidate-1",
                                "record_kind": "output",
                                "producer_node_id": "worker-1",
                                "producer_port": "check_result",
                                "port": "candidate",
                                "schema": "ImplementationCandidate",
                                "value": {"summary": "done"},
                            },
                        )
                    ],
                )

    async with session_factory() as session:
        store = GraphEventStore(session)
        assert await store.current_position(run_id) == 0
        assert await store.read_run(run_id) == []


@pytest.mark.asyncio
async def test_per_run_isolation(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session)
            await store.append_events(
                "store-run-a",
                0,
                [_event("evt-a", "store-run-a", "node_created", {"node_id": "a"})],
            )
            await store.append_events(
                "store-run-b",
                0,
                [_event("evt-b", "store-run-b", "node_created", {"node_id": "b"})],
            )

    async with session_factory() as session:
        store = GraphEventStore(session)
        run_a = await store.read_run("store-run-a")
        run_b = await store.read_run("store-run-b")

    assert [event.run_id for event in run_a] == ["store-run-a"]
    assert [event.run_id for event in run_b] == ["store-run-b"]


@pytest.mark.asyncio
async def test_unique_version_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-conflict"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(
                run_id,
                0,
                [_event("evt-conflict-1", run_id, "node_created", {"node_id": "n1"})],
            )

    with pytest.raises(StaleProjectionError):
        async with session_factory() as session:
            async with session.begin():
                await GraphEventStore(session).append_events(
                    run_id,
                    0,
                    [_event("evt-conflict-2", run_id, "node_created", {"node_id": "n2"})],
                )


@pytest.mark.asyncio
async def test_unique_constraint_race_surfaces_stale_projection_error(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "graph-race.db")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    run_id = "store-race"

    try:
        async with session_factory() as reader_one, session_factory() as reader_two:
            position_one = await GraphEventStore(reader_one).current_position(run_id)
            position_two = await GraphEventStore(reader_two).current_position(run_id)

        assert position_one == 0
        assert position_two == 0

        async with session_factory() as session:
            async with session.begin():
                await GraphEventStore(session).append_events(
                    run_id,
                    position_one,
                    [_event("evt-race-1", run_id, "node_created", {"node_id": "n1"})],
                )

        with pytest.raises(StaleProjectionError):
            async with session_factory() as session:
                async with session.begin():
                    await GraphEventStore(session).append_events(
                        run_id,
                        position_two,
                        [_event("evt-race-2", run_id, "node_created", {"node_id": "n2"})],
                    )

        async with session_factory() as session:
            rows = await session.execute(
                select(EventV2Model).where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            )
            stored_rows = list(rows.scalars())
            events = await GraphEventStore(session).read_run(run_id)

        assert len(stored_rows) == 1
        assert [event.event_id for event in events] == ["evt-race-1"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_graph_stream_coexists_with_legacy_workflow_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Legacy workflow events live in events_v2 under aggregate_id == run_id.
    The graph stream is namespaced (graph:<run_id>) so the two never contend
    for (aggregate_id, version) and never leak into each other's reads."""
    run_id = "store-coexist"
    async with session_factory() as session:
        async with session.begin():
            # Legacy workflow event at version 1 for the same run.
            session.add(
                EventV2Model(
                    aggregate_id=run_id,
                    version=1,
                    event_type="run_created",
                    payload='{"run_id": "store-coexist"}',
                    timestamp="2026-01-01T00:00:00+00:00",
                )
            )

    async with session_factory() as session:
        async with session.begin():
            store = GraphEventStore(session)
            # Graph stream starts empty despite the legacy row.
            assert await store.current_position(run_id) == 0
            # Appending at expected_position=0 must not collide with the
            # legacy row's (aggregate_id, version=1).
            await store.append_events(
                run_id,
                0,
                [_event("evt-coexist-1", run_id, "node_created", {"node_id": "n1"})],
            )

    async with session_factory() as session:
        store = GraphEventStore(session)
        events = await store.read_run(run_id)
        assert [event.event_id for event in events] == ["evt-coexist-1"]
        assert await store.current_position(run_id) == 1


@pytest.mark.asyncio
async def test_read_from_offset(session_factory: async_sessionmaker[AsyncSession]) -> None:
    run_id = "store-offset"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(
                run_id,
                0,
                [
                    _event("evt-offset-1", run_id, "node_created", {"node_id": "n1"}),
                    _event("evt-offset-2", run_id, "node_created", {"node_id": "n2"}),
                    _event("evt-offset-3", run_id, "node_created", {"node_id": "n3"}),
                ],
            )

    async with session_factory() as session:
        events = await GraphEventStore(session).read_run(run_id, from_position=2)

    assert [event.event_id for event in events] == ["evt-offset-2", "evt-offset-3"]


@pytest.mark.asyncio
async def test_read_run_summaries_avoids_heavy_payload_materialization(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-summary"
    large_payload = [{"path": f".venv/file-{index}.py"} for index in range(1000)]

    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(
                run_id,
                0,
                [
                    _event(
                        "evt-summary-1",
                        run_id,
                        "callback_accepted",
                        {
                            "node_id": "worker-1",
                            "lease_id": "lease-1",
                            "payload": {
                                "output_records": [
                                    {
                                        "record_kind": "file_state",
                                        "ignored": large_payload,
                                    }
                                ]
                            },
                        },
                    ),
                    _event(
                        "evt-summary-2",
                        run_id,
                        "node_created",
                        {
                            "node_id": "worker-1",
                            "kind": "worker",
                            "state": "planned",
                        },
                    ),
                    _event(
                        "evt-summary-3",
                        run_id,
                        "output_record_accepted",
                        {
                            "record_id": "verification-1",
                            "record_kind": "verification",
                            "record_type": "verification_report",
                            "producer_node_id": "verifier-1",
                            "port": "verification_report",
                            "schema": "VerificationReport",
                            "candidate_id": "candidate-1",
                            "outcome": "passed",
                            "value": {
                                "outcome": "passed",
                                "grades": [{"requirement_id": "R-1", "grade": "A"}],
                            },
                        },
                    ),
                ],
            )

    async with session_factory() as session:
        summaries = await GraphEventStore(session).read_run_summaries(run_id)
        verifier_detail = await GraphEventStore(session).read_node_detail_summary(
            run_id,
            "verifier-1",
        )

    assert [summary.event_id for summary in summaries] == [
        "evt-summary-1",
        "evt-summary-2",
        "evt-summary-3",
    ]
    assert summaries[0].payload == {
        "execution_id": "execution-1",
        "lease_generation": 1,
        "lease_id": "lease-1",
        "node_id": "worker-1",
        "reason": "accepted",
    }
    assert summaries[1].payload == {
        "kind": "worker",
        "node_id": "worker-1",
        "state": "planned",
    }
    assert summaries[2].payload == {
        "outcome": "passed",
        "port": "verification_report",
        "producer_node_id": "verifier-1",
        "record_id": "verification-1",
        "record_kind": "verification",
        "value": {
            "outcome": "passed",
            "grades": [{"requirement_id": "R-1", "grade": "A"}],
        },
    }
    assert verifier_detail is not None
    assert verifier_detail.output_records == [
        {
            "candidate_id": "candidate-1",
            "outcome": "passed",
            "port": "verification_report",
            "producer_node_id": "verifier-1",
            "record_id": "verification-1",
            "record_kind": "verification",
            "schema": "VerificationReport",
            "value": {
                "outcome": "passed",
                "grades": [{"requirement_id": "R-1", "grade": "A"}],
            },
        }
    ]


@pytest.mark.asyncio
async def test_read_run_light_preserves_projection_fields_without_heavy_payloads(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "store-light"
    large_payload = [{"path": f".venv/file-{index}.py"} for index in range(1000)]

    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(
                run_id,
                0,
                [
                    _event(
                        "evt-light-1",
                        run_id,
                        "node_created",
                        {
                            "node_id": "worker-1",
                            "kind": "worker",
                            "state": "planned",
                            "task_region_id": "step/task",
                            "resource_claims": [{"mode": "write", "scope": "repo"}],
                        },
                    ),
                    _event(
                        "evt-light-2",
                        run_id,
                        "output_record_accepted",
                        {
                            "record_id": "candidate-1",
                            "record_kind": "output",
                            "record_type": "candidate",
                            "producer_node_id": "worker-1",
                            "port": "candidate",
                            "schema": "ImplementationCandidate",
                            "candidate_id": "candidate-1",
                            "task_region_id": "step/task",
                            "attempt_number": 1,
                            "value": {"summary": "candidate"},
                            "payload": {"body": large_payload},
                        },
                    ),
                    _event(
                        "evt-light-3",
                        run_id,
                        "callback_accepted",
                        {
                            "node_id": "worker-1",
                            "lease_id": "lease-1",
                            "payload": {"output_records": large_payload},
                        },
                    ),
                    _event(
                        "evt-light-4",
                        run_id,
                        "input_bound",
                        {
                            "edge_id": "edge-candidate",
                            "to_node_id": "verifier-1",
                            "to_port": "candidate_under_test",
                            "record_ids": ["candidate-1"],
                            "bound_at_position": 2,
                        },
                    ),
                    _event(
                        "evt-light-edge",
                        run_id,
                        "edge_created",
                        {
                            "edge_id": "edge-candidate",
                            "from_node_id": "worker-1",
                            "from_port": "candidate",
                            "to_node_id": "verifier-1",
                            "to_port": "candidate_under_test",
                            "binding_policy": "bind_latest",
                            "freshness_policy": "latest_only",
                            "prompt_hydration_policy": "artifact_reference",
                            "metadata": {"purpose": "verify candidate"},
                        },
                    ),
                    _event(
                        "evt-light-5",
                        run_id,
                        "output_record_accepted",
                        {
                            "record_id": "check-result-1",
                            "record_kind": "output",
                            "record_type": "check_result",
                            "producer_node_id": "check-1",
                            "port": "check_result",
                            "schema": "CheckResult",
                            "candidate_id": "candidate-check-1",
                            "task_region_id": "step/task",
                            "value": {
                                "status": "passed",
                                "classification": "passed",
                            },
                            "payload": {"body": large_payload},
                        },
                    ),
                ],
            )

    async with session_factory() as session:
        events = await GraphEventStore(session).read_run_light(run_id)

    assert [event.event_id for event in events] == [
        "evt-light-1",
        "evt-light-2",
        "evt-light-3",
        "evt-light-4",
        "evt-light-edge",
        "evt-light-5",
    ]
    assert events[0].payload == {
        "kind": "worker",
        "node_id": "worker-1",
        "resource_claims": [{"mode": "write", "scope": "repo"}],
        "state": "planned",
        "task_region_id": "step/task",
    }
    assert events[1].payload == {
        "candidate_id": "candidate-1",
        "attempt_number": 1,
        "port": "candidate",
        "producer_node_id": "worker-1",
        "record_id": "candidate-1",
        "record_kind": "output",
        "record_type": "candidate",
        "schema": "ImplementationCandidate",
        "task_region_id": "step/task",
    }
    assert events[2].payload == {
        "execution_id": "execution-1",
        "lease_generation": 1,
        "lease_id": "lease-1",
        "node_id": "worker-1",
        "reason": "accepted",
    }
    assert events[3].payload == {
        "bound_at_position": 2,
        "edge_id": "edge-candidate",
        "record_ids": ["candidate-1"],
        "to_node_id": "verifier-1",
        "to_port": "candidate_under_test",
    }
    assert events[4].payload == {
        "binding_policy": "bind_latest",
        "edge_id": "edge-candidate",
        "freshness_policy": "latest_only",
        "from_node_id": "worker-1",
        "from_port": "candidate",
        "metadata": {"purpose": "verify candidate"},
        "prompt_hydration_policy": "artifact_reference",
        "to_node_id": "verifier-1",
        "to_port": "candidate_under_test",
    }
    assert events[5].payload == {
        "attempt_number": 0,
        "candidate_id": "candidate-check-1",
        "classification": "passed",
        "port": "check_result",
        "producer_node_id": "check-1",
        "record_id": "check-result-1",
        "record_kind": "output",
        "record_type": "check_result",
        "schema": "CheckResult",
        "status": "passed",
        "task_region_id": "step/task",
    }
    assert all("value" not in event.payload for event in events)
    assert all("payload" not in event.payload for event in events)
