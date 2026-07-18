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
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    GraphProjection,
    project_final_invariant_blockers,
    project_node_states,
    project_run_state,
    project_task_states,
)
from orchestrator.graph_runtime import GraphEventStore
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
                "blockers": ["waiting-for-input"],
                "graph_verifier_grades": {"req-1": "pass"},
                "tokens_by_node": {"worker-1": 30},
                "tokens_by_node_kind": {"worker": 30},
                "operations": [{"op": "replace"}, {"op": "add"}],
            },
        ),
        _event(
            "evt-output",
            run_id,
            "output_record_accepted",
            {
                "record_id": "record-1",
                "record_kind": "output",
                "record_type": "fan_out_inputs",
                "producer_node_id": "worker-1",
                "port": "result",
                "schema": "TestRecord",
                "value": {"large": "x" * 1024},
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
                "task_region_id": "origin",
                "candidate_id": "cand-origin",
                "attempt_number": 1,
                "producer_node_id": "worker-origin",
                "record_id": "cand-origin",
                "record_kind": "output",
                "record_type": "candidate",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "value": {"summary": "origin candidate"},
            },
        ),
        _event(
            "evt-origin-failed",
            run_id,
            "verification_failed",
            _verification_payload("cand-origin", "failed"),
        ),
        _event(
            "evt-corrective-candidate",
            run_id,
            "output_record_accepted",
            {
                "task_region_id": "corrective",
                "candidate_id": "cand-fix",
                "attempt_number": 1,
                "producer_node_id": "worker-fix",
                "record_id": "cand-fix",
                "record_kind": "output",
                "record_type": "candidate",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "supersedes_task_region_id": "origin",
                "value": {"summary": "corrective candidate"},
            },
        ),
        _event(
            "evt-corrective-passed",
            run_id,
            "verification_passed",
            _verification_payload("cand-fix", "passed"),
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
            "record_type": "file_state",
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
            "task_region_id": task_region_id,
            "candidate_id": candidate_id,
            "attempt_number": attempt_number,
            "record_id": candidate_id,
            "record_kind": "output",
            "record_type": "candidate",
            "producer_node_id": f"worker-{candidate_id}",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "value": {"summary": f"candidate {candidate_id}"},
        },
    )


def _verification_payload(candidate_id: str, outcome: str) -> dict[str, Any]:
    return {
        "node_id": f"verifier-{candidate_id}",
        "verifier_node_id": f"verifier-{candidate_id}",
        "candidate_id": candidate_id,
        "record_id": f"verification-{candidate_id}",
        "outcome": outcome,
        "evidence": [],
        "value": {"outcome": outcome, "grades": []},
    }


def _july_4_supersession_incident_events(run_id: str) -> list[EventEnvelope]:
    return [
        _event("incident-active", run_id, "run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "incident-origin-worker",
            run_id,
            "node_created",
            {
                "node_id": "worker-origin",
                "kind": "worker",
                "role": "builder",
                "state": "completed",
                "task_region_id": "origin",
            },
        ),
        _candidate_event("incident-origin-candidate", run_id, "origin", "candidate-origin"),
        _event(
            "incident-origin-verifier",
            run_id,
            "node_created",
            {
                "node_id": "verifier-origin",
                "kind": "verifier",
                "role": "verifier",
                "state": "failed",
                "task_region_id": "origin",
            },
        ),
        _event(
            "incident-origin-failed",
            run_id,
            "verification_failed",
            {
                **_verification_payload("candidate-origin", "failed"),
                "node_id": "verifier-origin",
                "verifier_node_id": "verifier-origin",
            },
        ),
        _event(
            "incident-gap-planner",
            run_id,
            "node_created",
            {
                "node_id": "gap-planner-recovery",
                "kind": "gap_planner",
                "role": "gap_planner",
                "state": "completed",
            },
        ),
        _event(
            "incident-gap-classified",
            run_id,
            "output_record_accepted",
            {
                "record_id": "classified-gap-recovery",
                "record_kind": "output",
                "record_type": "classified_gap",
                "producer_node_id": "gap-planner-recovery",
                "port": "classified_gap",
                "schema": "GapClassification",
                "value": {
                    "milestone_kind": "gap_analysis",
                    "classification": "corrective_work_required",
                    "source": "incident_reconstruction",
                    "task_region_id": "origin",
                    "attempt_number": 1,
                },
            },
        ),
        _event(
            "incident-corrective-worker",
            run_id,
            "node_created",
            {
                "node_id": "worker-corrective",
                "kind": "worker",
                "role": "fixer",
                "state": "completed",
                "task_region_id": "corrective",
            },
        ),
        _event(
            "incident-corrective-candidate",
            run_id,
            "output_record_accepted",
            {
                "task_region_id": "corrective",
                "candidate_id": "candidate-corrective",
                "attempt_number": 1,
                "producer_node_id": "worker-corrective",
                "record_id": "candidate-corrective",
                "record_kind": "output",
                "record_type": "candidate",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "supersedes_task_region_id": "origin",
                "value": {"summary": "repair origin candidate"},
            },
        ),
        _event(
            "incident-corrective-verifier",
            run_id,
            "node_created",
            {
                "node_id": "verifier-corrective",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "task_region_id": "corrective",
            },
        ),
        _event(
            "incident-corrective-passed",
            run_id,
            "verification_passed",
            {
                **_verification_payload("candidate-corrective", "passed"),
                "node_id": "verifier-corrective",
                "verifier_node_id": "verifier-corrective",
            },
        ),
        _file_state_event(
            "incident-corrective-file-state",
            run_id,
            "corrective",
            "candidate-corrective",
        ),
        _event(
            "incident-final-gate",
            run_id,
            "node_created",
            {
                "node_id": "final-gate-incident",
                "kind": "final_gate",
                "role": "final_gate",
                "state": "completed",
            },
        ),
        _event(
            "incident-completion-decision",
            run_id,
            "output_record_accepted",
            {
                "record_id": "completion-decision-incident",
                "record_kind": "output",
                "record_type": "completion_decision",
                "producer_node_id": "final-gate-incident",
                "port": "completion_decision",
                "schema": "CompletionDecision",
                "value": {"status": "passed", "blockers": []},
                "provenance": {"source": "final_gate_evaluated"},
            },
        ),
        _event(
            "incident-completed",
            run_id,
            "run_lifecycle_changed",
            {"from_state": "active", "to_state": "completed"},
        ),
    ]


def _incident_projection_outcome(
    events: list[EventEnvelope],
    projection: GraphProjection | None = None,
) -> dict[str, object]:
    return {
        "task_states": project_task_states(events, projection=projection),
        "final_gate_state": project_node_states(events, projection=projection).get(
            "final-gate-incident"
        ),
        "final_blockers": project_final_invariant_blockers(events, projection=projection),
        "run_state": project_run_state(events, projection=projection),
    }


def _task_state_parity_cases(run_id: str) -> dict[str, list[EventEnvelope]]:
    return {
        "accepted": [
            _candidate_event("accepted-candidate", run_id, "accepted", "cand-accepted"),
            _event(
                "accepted-verification",
                run_id,
                "verification_passed",
                _verification_payload("cand-accepted", "passed"),
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
                _verification_payload("cand-accepted-with-gate", "passed"),
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
                _verification_payload("cand-revision", "failed"),
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
                _verification_payload("cand-invalid-test", "failed"),
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
                "output_record_accepted",
                {
                    "record_id": "check-environment",
                    "task_region_id": "blocked_environment",
                    "record_kind": "output",
                    "record_type": "check_result",
                    "producer_node_id": "check-environment",
                    "port": "check_result",
                    "schema": "CheckResult",
                    "candidate_id": "cand-environment",
                    "attempt_number": 0,
                    "value": {
                        "status": "failed",
                        "classification": "tool_unavailable",
                        "command_id": "environment-check",
                        "command_text": "environment check",
                        "command": {},
                        "worktree_path": "/worktree",
                        "base_snapshot_id": "S0",
                        "execution_id": "environment-check-execution",
                        "duration_ms": 0,
                        "stdout_tail": "",
                        "stderr_tail": "",
                        "stdout_truncated": False,
                        "stderr_truncated": False,
                        "timeout_seconds": 1.0,
                        "environment_policy": {},
                    },
                },
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
                {"node_id": "worker-in-progress", "lease_id": "lease-in-progress"},
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
            await GraphEventStore(session).append_events(run_id, 0, _sample_events(run_id))

    async with session_factory() as session:
        store = GraphEventStore(session)
        summaries = await store.read_run_summaries(run_id)
        snapshot = await store.read_projection_snapshot(run_id)

    assert [summary.position for summary in summaries] == [1, 2, 3, 4]
    assert summaries[2].payload == {
        "node_id": "worker-1",
        "new_state": "ready",
        "blockers": ["waiting-for-input"],
        "graph_verifier_grades": {"req-1": "pass"},
        "tokens_by_node": {"worker-1": 30},
        "tokens_by_node_kind": {"worker": 30},
        "patch_ops": 2,
    }
    assert summaries[-1].payload == {
        "producer_node_id": "worker-1",
        "record_id": "record-1",
        "record_kind": "output",
        "port": "result",
    }
    assert snapshot is not None
    assert snapshot.position == 4
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
        await GraphEventStore(session).append_events(run_id, 0, _sample_events(run_id))
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
            await GraphEventStore(session).append_events(run_id, 0, _sample_events(run_id))

    async with session_factory() as session:
        store = GraphEventStore(session)
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
        assert event_count == 4
        assert await _count_model(session, GraphEventSummaryModel, run_id) == 0
        assert await _count_model(session, GraphProjectionSnapshotModel, run_id) == 0

    async with session_factory() as session:
        store = GraphEventStore(session)
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
    expected_task_states = project_task_states(events)

    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, events)

    async with session_factory() as session:
        store = GraphEventStore(session)
        snapshot_before_rebuild = await store.read_projection_snapshot(run_id)
        await store.delete_read_models(run_id)
        await session.commit()

    async with session_factory() as session:
        store = GraphEventStore(session)
        compact_projection_events = await store.read_run_projection(run_id)
        rebuilt_snapshot = await store.rebuild_read_models(run_id)
        await session.commit()

    assert expected_task_states == {"corrective": "accepted", "origin": "accepted"}
    assert project_task_states(compact_projection_events) == expected_task_states
    assert snapshot_before_rebuild is not None
    assert snapshot_before_rebuild.task_states == expected_task_states
    assert rebuilt_snapshot is not None
    assert rebuilt_snapshot.task_states == expected_task_states


@pytest.mark.asyncio
async def test_july_4_incident_replay_preserves_supersession_and_completion_parity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    run_id = "july-4-supersession-incident"
    events = _july_4_supersession_incident_events(run_id)
    expected = {
        "task_states": {"corrective": "accepted", "origin": "accepted"},
        "final_gate_state": "completed",
        "final_blockers": [],
        "run_state": "completed",
    }

    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, events)

    async with session_factory() as session:
        store = GraphEventStore(session)
        full_events = await store.read_run(run_id)
        compact_events = await store.read_run_projection(run_id)
        checkpoint = await store.read_projection_checkpoint(run_id)
        await store.delete_read_models(run_id)
        await session.commit()

    async with session_factory() as session:
        store = GraphEventStore(session)
        await store.rebuild_read_models(run_id)
        rebuilt_checkpoint = await store.read_projection_checkpoint(run_id)
        await session.commit()

    assert checkpoint is not None
    assert rebuilt_checkpoint is not None
    assert _incident_projection_outcome(full_events) == expected
    assert _incident_projection_outcome(compact_events) == expected
    assert _incident_projection_outcome([], checkpoint.projection) == expected
    assert _incident_projection_outcome([], rebuilt_checkpoint.projection) == expected


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

    assert project_task_states(events) == expected_task_states

    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, events)

    async with session_factory() as session:
        store = GraphEventStore(session)
        snapshot_before_rebuild = await store.read_projection_snapshot(run_id)
        await store.delete_read_models(run_id)
        await session.commit()

    async with session_factory() as session:
        store = GraphEventStore(session)
        compact_projection_events = await store.read_run_projection(run_id)
        rebuilt_snapshot = await store.rebuild_read_models(run_id)
        await session.commit()

    assert project_task_states(compact_projection_events) == expected_task_states
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
            await GraphEventStore(session).append_events(run_id, 0, _sample_events(run_id))

    async with session_factory() as session:
        store = GraphEventStore(session)
        first_page = await store.read_run_summaries(run_id, from_position=1, limit=2)
        second_page = await store.read_run_summaries(run_id, from_position=3, limit=2)

    assert [summary.position for summary in first_page] == [1, 2]
    assert [summary.position for summary in second_page] == [3, 4]
