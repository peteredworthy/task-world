from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import (
    EventV2Model,
    GraphEventSummaryModel,
    GraphProjectionSnapshotModel,
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope, project_task_states
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.graph_runtime.store import graph_aggregate_id
from orchestrator.graph import build_graph_catalog


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
        payload={"record": payload}
        if event_type == "output_record_accepted"
        and not (isinstance(payload, dict) and "record" in payload)
        else payload,
    )


def _sample_events(run_id: str) -> list[EventEnvelope]:
    return [
        _event("evt-active", run_id, "run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "evt-worker",
            run_id,
            "node_created",
            {
                "node_id": "worker-1",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "evt-ready",
            run_id,
            "node_state_changed",
            {
                "node_id": "worker-1",
                "new_state": "ready",
            },
        ),
        _event(
            "evt-patch-summary",
            run_id,
            "graph_patch_accepted",
            {
                "patch_id": "patch-summary",
                "diagnostics": {
                    "blockers": ["waiting-for-input"],
                    "graph_verifier_grades": {"req-1": "pass"},
                    "tokens_by_node": {"worker-1": 30},
                    "tokens_by_node_kind": {"worker": 30},
                },
                "ops": [{"op": "replace"}, {"op": "add"}],
                "base_graph_position": -1,
                "actor_role": "planner",
                "proposed_by_node_id": "planner-test",
                "successor_planner_node_ids": [],
            },
        ),
        _event(
            "evt-output",
            run_id,
            "output_record_accepted",
            {
                "record": {
                    "record_id": "record-1",
                    "record_kind": "output",
                    "record_type": "candidate",
                    "producer_node_id": "worker-1",
                    "port": "candidate",
                    "candidate_id": "record-1",
                    "value": {"summary": "x" * 1024},
                    "schema": "ImplementationCandidate",
                }
            },
        ),
    ]


def _corrective_supersession_events(run_id: str) -> list[EventEnvelope]:
    return [
        _event("evt-active", run_id, "run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "evt-origin-candidate",
            run_id,
            "output_record_accepted",
            {
                "record": {
                    "task_region_id": "origin",
                    "candidate_id": "cand-origin",
                    "attempt_number": 1,
                    "producer_node_id": "worker-origin",
                    "record_id": "cand-origin",
                    "record_kind": "output",
                    "record_type": "candidate",
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "value": {"summary": "test candidate"},
                }
            },
        ),
        _event(
            "evt-origin-failed",
            run_id,
            "verification_failed",
            {"candidate_id": "cand-origin"},
        ),
        _event(
            "evt-corrective-candidate",
            run_id,
            "output_record_accepted",
            {
                "record": {
                    "task_region_id": "corrective",
                    "candidate_id": "cand-fix",
                    "attempt_number": 1,
                    "producer_node_id": "worker-fix",
                    "record_id": "cand-fix",
                    "record_kind": "output",
                    "record_type": "candidate",
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "supersedes_task_region_ids": ["origin"],
                    "value": {"summary": "test candidate"},
                }
            },
        ),
        _event(
            "evt-corrective-passed",
            run_id,
            "verification_passed",
            {"candidate_id": "cand-fix"},
        ),
        _event(
            "evt-corrective-file-state",
            run_id,
            "file_state_accepted",
            {
                "record_id": "file-state-cand-fix",
                "record_kind": "file_state",
                "record_type": "file_state",
                "task_region_id": "corrective",
                "candidate_id": "cand-fix",
                "snapshot_id": "snapshot-cand-fix",
                "base_snapshot_id": "S0",
                "verdict": "captured",
                "producer_node_id": "worker-fix",
                "port": "file_state",
                "schema": "FileStateRecord",
            },
        ),
    ]


def _file_state_event(
    event_id: str,
    run_id: str,
    task_region_id: str,
    candidate_id: str,
) -> EventEnvelope:
    return _event(
        event_id,
        run_id,
        "file_state_accepted",
        {
            "record_id": f"file-state-{candidate_id}",
            "record_kind": "file_state",
            "producer_node_id": f"worker-{candidate_id}",
            "port": "file_state",
            "schema": "FileStateRecord",
            "snapshot_id": f"snapshot-{candidate_id}",
            "base_snapshot_id": "S0",
            "task_region_id": task_region_id,
            "candidate_id": candidate_id,
            "verdict": "captured",
        },
    )


def _candidate_event(
    event_id: str,
    run_id: str,
    task_region_id: str,
    candidate_id: str,
    attempt_number: int = 1,
) -> EventEnvelope:
    return _event(
        event_id,
        run_id,
        "output_record_accepted",
        {
            "record": {
                "task_region_id": task_region_id,
                "candidate_id": candidate_id,
                "attempt_number": attempt_number,
                "record_id": candidate_id,
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": f"worker-{candidate_id}",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "test candidate"},
            }
        },
    )


def _task_state_parity_cases(run_id: str) -> dict[str, list[EventEnvelope]]:
    return {
        "accepted": [
            _candidate_event("accepted-candidate", run_id, "accepted", "cand-accepted"),
            _event(
                "accepted-verification",
                run_id,
                "verification_passed",
                {"candidate_id": "cand-accepted"},
            ),
            _file_state_event(
                "accepted-file-state",
                run_id,
                "accepted",
                "cand-accepted",
            ),
        ],
        "accepted_with_gate": [
            _event(
                "gate-node",
                run_id,
                "node_created",
                {
                    "node_id": "gate-accepted",
                    "kind": "gate",
                    "task_region_id": "accepted_with_gate",
                },
            ),
            _candidate_event(
                "gate-candidate",
                run_id,
                "accepted_with_gate",
                "cand-accepted-with-gate",
            ),
            _event(
                "gate-verification",
                run_id,
                "verification_passed",
                {"candidate_id": "cand-accepted-with-gate"},
            ),
            _file_state_event(
                "gate-file-state",
                run_id,
                "accepted_with_gate",
                "cand-accepted-with-gate",
            ),
            _event(
                "gate-decision",
                run_id,
                "approval_decision_recorded",
                {
                    "node_id": "gate-accepted",
                    "decision": "approved",
                },
            ),
        ],
        "needs_revision": [
            _candidate_event("revision-candidate", run_id, "needs_revision", "cand-revision"),
            _event(
                "revision-verification",
                run_id,
                "verification_failed",
                {"candidate_id": "cand-revision"},
            ),
        ],
        "blocked_invalid_test": [
            _candidate_event(
                "invalid-test-candidate",
                run_id,
                "blocked_invalid_test",
                "cand-invalid-test",
            ),
            _event(
                "invalid-test-verification",
                run_id,
                "verification_failed",
                {"candidate_id": "cand-invalid-test"},
            ),
            _event(
                "invalid-test-oversight",
                run_id,
                "oversight_decision_recorded",
                {
                    "task_region_id": "blocked_invalid_test",
                    "candidate_id": "cand-invalid-test",
                    "appeal_type": "invalid_test",
                    "decision": "accepted",
                },
            ),
        ],
        "blocked_environment": [
            _candidate_event(
                "environment-candidate",
                run_id,
                "blocked_environment",
                "cand-environment",
            ),
            _event(
                "environment-failure",
                run_id,
                "environment_failure_accepted",
                {"task_region_id": "blocked_environment", "reason": "tool_unavailable"},
            ),
        ],
        "in_progress": [
            _event(
                "in-progress-node",
                run_id,
                "node_created",
                {
                    "node_id": "worker-in-progress",
                    "kind": "worker",
                    "task_region_id": "in_progress",
                },
            ),
            _event(
                "in-progress-lease",
                run_id,
                "lease_granted",
                {
                    "node_id": "worker-in-progress",
                    "lease_id": "lease-in-progress",
                    "generation": 0,
                    "execution_id": "exec-in-progress",
                    "base_snapshot_id": "S0",
                    "expires_at": "2026-01-01T00:05:00+00:00",
                    "resource_claims": [],
                },
            ),
        ],
        "pending": [
            _event(
                "pending-node",
                run_id,
                "node_created",
                {
                    "node_id": "worker-pending",
                    "kind": "worker",
                    "task_region_id": "pending",
                },
            )
        ],
    }


async def _count_model(session: AsyncSession, model: type[Any], run_id: str) -> int:
    result = await session.scalar(
        select(func.count()).select_from(model).where(model.run_id == run_id)
    )
    return int(result or 0)


@pytest.mark.asyncio
async def test_append_keeps_graph_read_models_synchronized(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "read-model-sync"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(run_id, 0, _sample_events(run_id))

    async with session_factory() as session:
        store = GraphEventStore(
            session,
            build_graph_catalog(),
        )
        summaries = await store.read_run_summaries(run_id)
        snapshot = await store.read_projection_snapshot(run_id)

    assert [summary.position for summary in summaries] == [1, 2, 3, 4, 5]
    assert summaries[2].payload == {
        "node_id": "worker-1",
        "new_state": "ready",
    }
    assert summaries[3].payload == {
        "patch_id": "patch-summary",
        "actor_role": "planner",
        "proposed_by_node_id": "planner-test",
        "blockers": ["waiting-for-input"],
        "graph_verifier_grades": {"req-1": "pass"},
        "tokens_by_node": {"worker-1": 30},
        "tokens_by_node_kind": {"worker": 30},
        "patch_ops": 2,
    }
    assert summaries[4].payload == {
        "producer_node_id": "worker-1",
        "record_id": "record-1",
        "record_kind": "output",
        "port": "candidate",
    }
    assert snapshot is not None
    assert snapshot.position == 5
    assert snapshot.run_state == "active"
    assert snapshot.node_states == {"worker-1": "ready"}
    assert snapshot.ready_nodes == ["worker-1"]


@pytest.mark.asyncio
async def test_graph_read_models_roll_back_with_event_append(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "read-model-rollback"
    async with session_factory() as session:
        transaction = await session.begin()
        await GraphEventStore(
            session,
            build_graph_catalog(),
        ).append_events(run_id, 0, _sample_events(run_id))
        await transaction.rollback()

    async with session_factory() as session:
        event_count = await session.scalar(
            select(func.count())
            .select_from(EventV2Model)
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
        )
        summary_count = await _count_model(session, GraphEventSummaryModel, run_id)
        snapshot_count = await _count_model(session, GraphProjectionSnapshotModel, run_id)

    assert event_count == 0
    assert summary_count == 0
    assert snapshot_count == 0


@pytest.mark.asyncio
async def test_graph_read_models_are_rebuildable_and_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "read-model-rebuild"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(run_id, 0, _sample_events(run_id))

    async with session_factory() as session:
        store = GraphEventStore(
            session,
            build_graph_catalog(),
        )
        before_summaries = await store.read_run_summaries(run_id)
        before_snapshot = await store.read_projection_snapshot(run_id)
        await store.delete_read_models(run_id)
        await session.commit()

    async with session_factory() as session:
        event_count = await session.scalar(
            select(func.count())
            .select_from(EventV2Model)
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
        )
        assert event_count == 5
        assert await _count_model(session, GraphEventSummaryModel, run_id) == 0
        assert await _count_model(session, GraphProjectionSnapshotModel, run_id) == 0

    async with session_factory() as session:
        store = GraphEventStore(
            session,
            build_graph_catalog(),
        )
        rebuilt_snapshot = await store.rebuild_read_models(run_id)
        first_rebuild_summaries = await store.read_run_summaries(run_id)
        await store.rebuild_read_models(run_id)
        second_rebuild_summaries = await store.read_run_summaries(run_id)
        await session.commit()

    assert before_snapshot is not None
    assert rebuilt_snapshot is not None
    assert rebuilt_snapshot.position == before_snapshot.position
    assert rebuilt_snapshot.node_states == before_snapshot.node_states
    assert [summary.payload for summary in first_rebuild_summaries] == [
        summary.payload for summary in before_summaries
    ]
    assert [summary.payload for summary in second_rebuild_summaries] == [
        summary.payload for summary in before_summaries
    ]


@pytest.mark.asyncio
async def test_projection_read_model_preserves_corrective_supersession_task_states(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "read-model-corrective-supersession"
    events = _corrective_supersession_events(run_id)
    expected_task_states = project_task_states(build_graph_catalog(), events)

    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(run_id, 0, events)

    async with session_factory() as session:
        store = GraphEventStore(
            session,
            build_graph_catalog(),
        )
        snapshot_before_rebuild = await store.read_projection_snapshot(run_id)
        await store.delete_read_models(run_id)
        await session.commit()

    async with session_factory() as session:
        store = GraphEventStore(
            session,
            build_graph_catalog(),
        )
        compact_projection_events = await store.read_run_projection(run_id)
        rebuilt_snapshot = await store.rebuild_read_models(run_id)
        await session.commit()

    assert expected_task_states == {"corrective": "accepted", "origin": "accepted"}
    assert (
        project_task_states(build_graph_catalog(), compact_projection_events)
        == expected_task_states
    )
    assert snapshot_before_rebuild is not None
    assert snapshot_before_rebuild.task_states == expected_task_states
    assert rebuilt_snapshot is not None
    assert rebuilt_snapshot.task_states == expected_task_states


@pytest.mark.asyncio
async def test_projection_read_model_preserves_task_state_matrix(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "read-model-task-state-matrix"
    cases = _task_state_parity_cases(run_id)
    events = [
        _event("matrix-active", run_id, "run_lifecycle_changed", {"to_state": "active"}),
        *(event for case_events in cases.values() for event in case_events),
    ]
    expected_task_states = {
        task_region_id: ("accepted" if task_region_id == "accepted_with_gate" else task_region_id)
        for task_region_id in cases
    }

    assert project_task_states(build_graph_catalog(), events) == expected_task_states

    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(run_id, 0, events)

    async with session_factory() as session:
        store = GraphEventStore(
            session,
            build_graph_catalog(),
        )
        snapshot_before_rebuild = await store.read_projection_snapshot(run_id)
        await store.delete_read_models(run_id)
        await session.commit()

    async with session_factory() as session:
        store = GraphEventStore(
            session,
            build_graph_catalog(),
        )
        compact_projection_events = await store.read_run_projection(run_id)
        rebuilt_snapshot = await store.rebuild_read_models(run_id)
        await session.commit()

    assert (
        project_task_states(build_graph_catalog(), compact_projection_events)
        == expected_task_states
    )
    assert snapshot_before_rebuild is not None
    assert snapshot_before_rebuild.task_states == expected_task_states
    assert rebuilt_snapshot is not None
    assert rebuilt_snapshot.task_states == expected_task_states


@pytest.mark.asyncio
async def test_graph_event_summaries_are_paged_from_read_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "read-model-paging"
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(
                session,
                build_graph_catalog(),
            ).append_events(run_id, 0, _sample_events(run_id))

    async with session_factory() as session:
        store = GraphEventStore(
            session,
            build_graph_catalog(),
        )
        first_page = await store.read_run_summaries(run_id, from_position=1, limit=2)
        second_page = await store.read_run_summaries(run_id, from_position=3, limit=2)

    assert [summary.position for summary in first_page] == [1, 2]
    assert [summary.position for summary in second_page] == [3, 4]
