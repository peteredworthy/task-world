from __future__ import annotations

import json

import pytest
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.config.models import RoutineConfig
from orchestrator.db import (
    EventV2Model,
    GraphEventSummaryModel,
    GraphNodeDetailSummaryModel,
    GraphProjectionSnapshotModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    SequentialIdGenerator,
    build_projection,
    project_leases,
    project_decision_view_from_projection,
    project_scheduler_view,
    projection_to_checkpoint,
)
from orchestrator.graph_runtime import GraphController, GraphEventStore, seed_run
from orchestrator.graph_runtime import GraphReadModelUnavailable
from orchestrator.graph_runtime import store
from orchestrator.graph_runtime.store import graph_aggregate_id
from tests.unit.graph_test_utils import canonical_event_payload

pytestmark = pytest.mark.slow


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    value = create_engine(":memory:")
    await init_db(value)
    yield value
    await value.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "graph-read-contract",
            "name": "Graph read contract",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [{"id": "task-1", "title": "Task 1"}],
                }
            ],
        }
    )


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _event(event_type: str, payload: dict[str, object], *, index: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{index:03d}",
        run_id="placeholder",
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )


async def _compact_bytes(session: AsyncSession, run_id: str) -> dict[str, tuple[bytes, ...]]:
    event_rows = list(
        (
            await session.execute(
                select(GraphEventSummaryModel)
                .where(GraphEventSummaryModel.run_id == run_id)
                .order_by(GraphEventSummaryModel.position)
            )
        ).scalars()
    )
    snapshot = await session.get(GraphProjectionSnapshotModel, run_id)
    assert snapshot is not None
    node_rows = list(
        (
            await session.execute(
                select(GraphNodeDetailSummaryModel)
                .where(GraphNodeDetailSummaryModel.run_id == run_id)
                .order_by(GraphNodeDetailSummaryModel.node_id)
            )
        ).scalars()
    )
    return {
        "events_summary": tuple(_json_bytes(row.payload) for row in event_rows),
        "graph": (
            _json_bytes(
                {
                    "node_states": snapshot.node_states,
                    "task_states": snapshot.task_states,
                    "leases": snapshot.leases,
                    "ready_nodes": snapshot.ready_nodes,
                    "scheduler": snapshot.scheduler,
                    "lease_view": snapshot.lease_view,
                    "decisions": snapshot.decisions,
                }
            ),
        ),
        "node_detail": tuple(
            _json_bytes(
                {
                    "input_ports": row.input_ports,
                    "output_records": row.output_records,
                    "file_state_records": row.file_state_records,
                    "leases": row.leases,
                    "active_lease": row.active_lease,
                    "callback_history": row.callback_history,
                    "events": row.events,
                    "prompt_summary": row.prompt_summary,
                }
            )
            for row in node_rows
        ),
    }


async def test_compact_rows_are_bounded_before_persistence_and_rebuild_identically(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "graph-read-contract-bounded-rows"
    clock = FakeClock()
    ids = SequentialIdGenerator()
    seed = await seed_run(
        session_factory,
        _routine(),
        run_id=run_id,
        clock=clock,
        id_gen=ids,
    )
    controller = GraphController(session_factory, clock, ids, auto_dispatch=False)
    accepted = await controller.handle_command(run_id, seed.projection_position, "accept_run")
    await controller.handle_command(run_id, accepted.projection_position, "start")

    async with session_factory() as session:
        contracts = getattr(store, "GRAPH_READ_CONTRACTS", None)
        assert contracts is not None, "checked graph read-contract matrix is missing"
        source_before = tuple(
            (
                await session.execute(
                    select(EventV2Model.payload)
                    .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
                    .order_by(EventV2Model.version)
                )
            ).scalars()
        )
        live = await _compact_bytes(session, run_id)
        for owner, rows in live.items():
            budget = contracts[owner].byte_cap
            assert rows
            assert all(len(row) <= budget for row in rows)

        await session.execute(
            delete(GraphEventSummaryModel).where(GraphEventSummaryModel.run_id == run_id)
        )
        await session.execute(
            delete(GraphProjectionSnapshotModel).where(
                GraphProjectionSnapshotModel.run_id == run_id
            )
        )
        await session.execute(
            delete(GraphNodeDetailSummaryModel).where(GraphNodeDetailSummaryModel.run_id == run_id)
        )
        await session.flush()
        await GraphEventStore(session).rebuild_read_models(run_id)
        rebuilt = await _compact_bytes(session, run_id)
        source_after = tuple(
            (
                await session.execute(
                    select(EventV2Model.payload)
                    .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
                    .order_by(EventV2Model.version)
                )
            ).scalars()
        )

    assert rebuilt == live
    assert source_after == source_before


async def test_projection_snapshot_packs_the_entire_owner_row_deterministically(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "graph-read-contract-large-snapshot"
    events = [
        _event(
            "node_created",
            {
                "node_id": f"node-{index:03d}",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "command_definition": {
                    "id": f"command-{index:03d}",
                    "cmd": "x" * 4_096,
                    "source": "test",
                },
            },
            index=index,
        )
        for index in reversed(range(101))
    ]
    events.extend(
        _event(
            "lease_granted",
            {
                "node_id": f"node-{index:03d}",
                "lease_id": f"lease-{index:03d}",
                "generation": 1,
                "execution_id": f"execution-{index:03d}",
                "resource_claims": [
                    {
                        "mode": "read",
                        "scope": f"claim-{claim_index:02d}-" + ("y" * 4_080),
                    }
                    for claim_index in range(32)
                ],
            },
            index=101 + index,
        )
        for index in reversed(range(10))
    )

    async with session_factory() as session:
        graph_store = GraphEventStore(session)
        await graph_store.append_events(run_id, 0, events)
        stored_events = await graph_store.read_run(run_id)
        checkpoint_bytes = _json_bytes(projection_to_checkpoint(build_projection(stored_events)))
        assert len(checkpoint_bytes) > store.GRAPH_RESPONSE_BYTES
        snapshot = await session.get(GraphProjectionSnapshotModel, run_id)
        assert snapshot is not None
        live = (await _compact_bytes(session, run_id))["graph"][0]
        metadata = snapshot.decisions["_graph_read_contract"]

        assert len(live) <= store.GRAPH_RESPONSE_BYTES
        assert list(snapshot.node_states) == [f"node-{index:03d}" for index in range(100)]
        assert metadata["collections"]["node_states"] == {
            "revision": 1,
            "owner": "graph",
            "truncated": True,
            "total_known": 101,
            "next_cursor": "node-099",
            "original_bytes": len(
                _json_bytes({f"node-{index:03d}": "planned" for index in range(101)})
            ),
            "sha256": sha256(
                _json_bytes({f"node-{index:03d}": "planned" for index in range(101)})
            ).hexdigest(),
        }
        assert metadata["checkpoint"] == {
            "truncated": True,
            "original_bytes": len(checkpoint_bytes),
            "sha256": sha256(checkpoint_bytes).hexdigest(),
        }
        retained_lease_ids = list(snapshot.leases)
        assert retained_lease_ids
        assert retained_lease_ids == [
            f"lease-{index:03d}" for index in range(len(retained_lease_ids))
        ]
        lease_meta = metadata["collections"]["leases"]
        expected_lease_bytes = _json_bytes(
            project_leases([], projection=build_projection(stored_events))
        )
        assert lease_meta["truncated"] is True
        assert lease_meta["total_known"] == 10
        assert lease_meta["next_cursor"] == retained_lease_ids[-1]
        assert lease_meta["original_bytes"] == len(expected_lease_bytes)
        assert lease_meta["sha256"] == sha256(expected_lease_bytes).hexdigest()

        await graph_store.delete_read_models(run_id)
        await graph_store.rebuild_read_models(run_id)
        rebuilt = (await _compact_bytes(session, run_id))["graph"][0]

    assert rebuilt == live


async def test_node_detail_packs_the_entire_owner_row_deterministically(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "graph-read-contract-large-node-detail"
    node_id = "node-large"
    events = [
        _event(
            "node_created",
            {"node_id": node_id, "kind": "verifier", "role": "verifier", "state": "ready"},
            index=0,
        )
    ]
    for record_index in reversed(range(3)):
        events.append(
            _event(
                "output_record_accepted",
                {
                    "record_id": f"record-{record_index:03d}",
                    "record_kind": "verification",
                    "record_type": "verification_report",
                    "producer_node_id": node_id,
                    "port": "verification_report",
                    "schema": "VerificationReport",
                    "candidate_id": f"candidate-{record_index:03d}",
                    "value": {
                        "outcome": "passed",
                        "grades": [
                            {
                                "requirement_id": f"req-{grade_index:03d}",
                                "grade": "A",
                                "reason": f"{record_index:03d}-{grade_index:03d}-" + ("x" * 4_080),
                            }
                            for grade_index in range(50)
                        ],
                    },
                },
                index=record_index + 1,
            )
        )

    async with session_factory() as session:
        graph_store = GraphEventStore(session)
        await graph_store.append_events(run_id, 0, events)
        row = await session.get(
            GraphNodeDetailSummaryModel,
            {"run_id": run_id, "node_id": node_id},
        )
        assert row is not None
        live = (await _compact_bytes(session, run_id))["node_detail"][0]
        metadata = row.prompt_summary["_graph_read_contract"]["collections"]["output_records"]

        assert len(live) <= store.GRAPH_RESPONSE_BYTES
        retained_record_ids = [record["record_id"] for record in row.output_records]
        assert retained_record_ids
        assert retained_record_ids == [
            f"record-{index:03d}" for index in range(len(retained_record_ids))
        ]
        assert metadata["truncated"] is True
        assert metadata["total_known"] == 3
        assert metadata["next_cursor"] == retained_record_ids[-1]
        assert metadata["original_bytes"] is None
        assert metadata["sha256"] is None

        await graph_store.delete_read_models(run_id)
        await graph_store.rebuild_read_models(run_id)
        rebuilt = (await _compact_bytes(session, run_id))["node_detail"][0]

    assert rebuilt == live


async def test_snapshot_packs_scheduler_and_decisions_after_other_fields_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "graph-read-contract-large-gates"
    events = [
        _event(
            "node_created",
            {
                "node_id": f"gate-{index:03d}",
                "kind": "human_gate",
                "role": "approval",
                "state": "blocked",
                "gate_type": "human_approval",
                "prompt": f"prompt-{index:03d}-" + ("p" * 4_080),
                "blocker": f"blocker-{index:03d}-" + ("b" * 4_080),
                "decision_request": {
                    "decision_type": "approval",
                    "options": ["approve"],
                    "default_option": "approve",
                    "consequence_summary": f"consequence-{index:03d}-" + ("c" * 4_075),
                },
            },
            index=index,
        )
        for index in reversed(range(60))
    ]

    async with session_factory() as session:
        graph_store = GraphEventStore(session)
        await graph_store.append_events(run_id, 0, events)
        stored_events = await graph_store.read_run(run_id)
        projection = build_projection(stored_events)
        expected_scheduler = dict(project_scheduler_view([], projection=projection))
        expected_decisions = dict(project_decision_view_from_projection(projection))
        assert len(_json_bytes(expected_scheduler)) + len(_json_bytes(expected_decisions)) > (
            store.GRAPH_RESPONSE_BYTES
        )

        row = await session.get(GraphProjectionSnapshotModel, run_id)
        assert row is not None
        live = (await _compact_bytes(session, run_id))["graph"][0]
        metadata = row.decisions["_graph_read_contract"]["collections"]

        assert len(live) <= store.GRAPH_RESPONSE_BYTES
        retained_scheduler_ids = [entry["node_id"] for entry in row.scheduler["blocked"]]
        retained_decision_ids = [entry["node_id"] for entry in row.decisions["pending_gates"]]
        assert retained_scheduler_ids == [
            f"gate-{index:03d}" for index in range(len(retained_scheduler_ids))
        ]
        assert retained_decision_ids == [
            f"gate-{index:03d}" for index in range(len(retained_decision_ids))
        ]
        scheduler_field_meta = metadata["scheduler"]["fields"]["blocked"]
        decision_field_meta = metadata["decisions"]["fields"]["pending_gates"]
        assert scheduler_field_meta["total_known"] == 60
        assert scheduler_field_meta["truncated"] is False
        assert scheduler_field_meta["next_cursor"] is None
        assert scheduler_field_meta["original_bytes"] is None
        assert scheduler_field_meta["sha256"] is None
        assert decision_field_meta["total_known"] == 60
        assert decision_field_meta["truncated"] is True
        assert decision_field_meta["next_cursor"] == retained_decision_ids[-1]
        assert decision_field_meta["original_bytes"] == len(
            _json_bytes(expected_decisions["pending_gates"])
        )
        assert (
            decision_field_meta["sha256"]
            == sha256(_json_bytes(expected_decisions["pending_gates"])).hexdigest()
        )

        await graph_store.delete_read_models(run_id)
        await graph_store.rebuild_read_models(run_id)
        rebuilt = (await _compact_bytes(session, run_id))["graph"][0]

    assert rebuilt == live


async def test_node_detail_packs_large_prompt_summary_after_event_lists_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "graph-read-contract-large-prompt-summary"
    node_id = "node-prompt"
    prompt_summary = {
        f"section-{section:02d}": {
            f"field-{field:02d}": f"{section:02d}-{field:02d}-" + ("x" * 4_086)
            for field in range(32)
        }
        for section in range(32)
    }
    events = [
        _event(
            "node_created",
            {"node_id": node_id, "kind": "worker", "role": "builder", "state": "ready"},
            index=0,
        ),
        _event(
            "lease_granted",
            {
                "node_id": node_id,
                "lease_id": "lease-prompt",
                "generation": 1,
                "execution_id": "execution-prompt",
                "resource_claims": [],
            },
            index=1,
        ),
        _event(
            "node_state_changed",
            {"node_id": node_id, "new_state": "running", "prompt_summary": prompt_summary},
            index=2,
        ),
    ]
    assert len(_json_bytes(prompt_summary)) > 4_000_000

    async with session_factory() as session:
        graph_store = GraphEventStore(session)
        await graph_store.append_events(run_id, 0, events)
        row = await session.get(
            GraphNodeDetailSummaryModel,
            {"run_id": run_id, "node_id": node_id},
        )
        assert row is not None
        active_lease = dict(row.active_lease or {})
        assert active_lease["lease_id"] == "lease-prompt"
        row.events = []
        row.callback_history = []
        store._pack_node_detail_row(row)
        live = (await _compact_bytes(session, run_id))["node_detail"][0]
        contract = row.prompt_summary["_graph_read_contract"]
        metadata = contract["collections"]["prompt_summary"]

        assert len(live) <= store.GRAPH_RESPONSE_BYTES
        assert row.events == []
        assert row.callback_history == []
        assert row.active_lease == active_lease
        assert row.prompt_summary["value"] == {}
        assert row.prompt_summary["truncated"] is True
        assert row.prompt_summary["next_cursor"] == f"sha256:{metadata['sha256']}"
        assert metadata["total_known"] == 32
        assert metadata["truncated"] is True
        assert metadata["next_cursor"] == f"sha256:{metadata['sha256']}"
        assert metadata["original_bytes"] == len(_json_bytes(prompt_summary))
        assert metadata["sha256"] == sha256(_json_bytes(prompt_summary)).hexdigest()

        assert len(live) <= store.GRAPH_RESPONSE_BYTES


async def test_typed_human_gate_collections_retain_one_hundred_entries_and_rebuild(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "graph-read-contract-101-gates"
    events = [
        _event(
            "node_created",
            {
                "node_id": f"gate-{index:03d}",
                "kind": "human_gate",
                "role": "approval",
                "state": "blocked",
                "gate_type": "human_approval",
                "prompt": f"Approve {index}",
                "blocker": "human approval",
            },
            index=index,
        )
        for index in reversed(range(101))
    ]

    async with session_factory() as session:
        graph_store = GraphEventStore(session)
        await graph_store.append_events(run_id, 0, events)
        row = await session.get(GraphProjectionSnapshotModel, run_id)
        assert row is not None
        live = (await _compact_bytes(session, run_id))["graph"][0]

        assert [entry["node_id"] for entry in row.scheduler["blocked"]] == [
            f"gate-{index:03d}" for index in range(100)
        ]
        assert [entry["node_id"] for entry in row.decisions["pending_gates"]] == [
            f"gate-{index:03d}" for index in range(100)
        ]
        collections = row.decisions["_graph_read_contract"]["collections"]
        assert collections["scheduler"]["fields"]["blocked"]["total_known"] == 101
        assert collections["scheduler"]["fields"]["blocked"]["next_cursor"] == "gate-099"
        assert collections["decisions"]["fields"]["pending_gates"]["total_known"] == 101
        assert collections["decisions"]["fields"]["pending_gates"]["next_cursor"] == ("gate-099")

        await graph_store.delete_read_models(run_id)
        await graph_store.rebuild_read_models(run_id)
        rebuilt = (await _compact_bytes(session, run_id))["graph"][0]

    assert rebuilt == live


@pytest.mark.parametrize("contract_key", ("topology", "final_blockers", "regions"))
async def test_legacy_projection_views_refuse_history_beyond_their_bounded_contract(
    session_factory: async_sessionmaker[AsyncSession],
    contract_key: Literal["topology", "final_blockers", "regions"],
) -> None:
    """A request-time presenter cannot silently fold an unbounded history."""
    run_id = f"graph-bounded-{contract_key}"
    events = [
        _event(
            "node_created",
            {"node_id": f"node-{index:03d}", "kind": "worker", "state": "planned"},
            index=index,
        )
        for index in range(101)
    ]

    async with session_factory() as session:
        graph_store = GraphEventStore(session)
        await graph_store.append_events(run_id, 0, events)

        with pytest.raises(GraphReadModelUnavailable, match="history_exceeds_bounded_view_cap"):
            await graph_store.read_current_bounded_projection_history(
                run_id,
                contract_key=contract_key,
            )


async def test_runtime_checkpoint_and_event_window_have_distinct_over_cap_behavior(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Runtime state can use a current checkpoint; history-dependent work cannot.

    This is the execution boundary used by bootstrap, resume, dispatch, and
    recovery.  A caller that still requests event facts, or whose durable
    checkpoint cannot represent the oversized graph, receives a truthful
    unavailable read model instead of an authority-history replay.
    """
    run_id = "graph-runtime-window-over-cap"
    cap = store.GRAPH_READ_CONTRACTS["runtime"].budget.decode_cap
    events = [
        _event(
            "node_created",
            {"node_id": f"node-{index:03d}", "kind": "worker", "state": "planned"},
            index=index,
        )
        for index in range(cap + 1)
    ]

    async with session_factory() as session:
        graph_store = GraphEventStore(session)
        await graph_store.append_events(run_id, 0, events)

        with pytest.raises(GraphReadModelUnavailable, match="recovery_tail_exceeds_bounded_cap"):
            await graph_store.read_bounded_runtime_events(run_id)

        # Lifecycle bootstrap/resume use the same bounded checkpoint contract.
        # A too-large graph is paused for a durable-model repair; it never
        # falls back to a full event log just to inspect run state.
        with pytest.raises(GraphReadModelUnavailable, match="recovery_tail_exceeds_bounded_cap"):
            await graph_store.load_projection_with_tail(run_id)
