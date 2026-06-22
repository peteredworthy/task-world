from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.db import EventV2Model, create_engine, create_session_factory, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore, StaleProjectionError
from orchestrator.graph_runtime.store import graph_aggregate_id


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
        payload=payload,
    )


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
                "verdict": "passed",
                "value": {
                    "grades": [
                        {
                            "requirement_id": "R-1",
                            "grade": "A",
                            "reason": "satisfied",
                        }
                    ]
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
                "record_kind": "graph_record",
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
        "grades": [{"requirement_id": "R-1", "grade": "A", "reason": "satisfied"}]
    }

    check_result = stored[3].payload
    assert check_result["record_type"] == "check_result"
    assert check_result["schema_version"] == 1
    assert check_result["producer_port"] == "check_result"
    assert check_result["run_id"] == run_id
    assert check_result["created_at"] == "2026-01-01T00:00:00+00:00"
    assert check_result["graph_position"] == 4
    assert check_result["payload"] == {
        "status": "passed",
        "classification": "passed",
        "command_id": "unit-check",
    }

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
                            "large_irrelevant_field": large_payload,
                        },
                    ),
                ],
            )

    async with session_factory() as session:
        summaries = await GraphEventStore(session).read_run_summaries(run_id)

    assert [summary.event_id for summary in summaries] == ["evt-summary-1", "evt-summary-2"]
    assert summaries[0].payload == {"lease_id": "lease-1", "node_id": "worker-1"}
    assert summaries[1].payload == {
        "kind": "worker",
        "node_id": "worker-1",
        "state": "planned",
    }


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
                            "value": {"body": large_payload},
                        },
                    ),
                    _event(
                        "evt-light-2",
                        run_id,
                        "output_record_accepted",
                        {
                            "record_id": "candidate-1",
                            "record_kind": "output",
                            "producer_node_id": "worker-1",
                            "port": "candidate",
                            "candidate_id": "candidate-1",
                            "task_region_id": "step/task",
                            "value": {"body": large_payload},
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
                        "evt-light-5",
                        run_id,
                        "output_record_accepted",
                        {
                            "record_id": "check-result-1",
                            "record_kind": "output",
                            "record_type": "check_result",
                            "producer_node_id": "check-1",
                            "port": "check_result",
                            "candidate_id": "candidate-check-1",
                            "task_region_id": "step/task",
                            "value": {
                                "status": "passed",
                                "classification": "passed",
                                "body": large_payload,
                            },
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
        "port": "candidate",
        "producer_node_id": "worker-1",
        "record_id": "candidate-1",
        "record_kind": "output",
        "record_type": "candidate",
        "task_region_id": "step/task",
    }
    assert events[2].payload == {"lease_id": "lease-1", "node_id": "worker-1"}
    assert events[3].payload == {
        "bound_at_position": 2,
        "edge_id": "edge-candidate",
        "record_ids": ["candidate-1"],
        "to_node_id": "verifier-1",
        "to_port": "candidate_under_test",
    }
    assert events[4].payload == {
        "candidate_id": "candidate-check-1",
        "classification": "passed",
        "port": "check_result",
        "producer_node_id": "check-1",
        "record_id": "check-result-1",
        "record_kind": "output",
        "record_type": "check_result",
        "status": "passed",
        "task_region_id": "step/task",
    }
    assert all("value" not in event.payload for event in events)
    assert all("payload" not in event.payload for event in events)
