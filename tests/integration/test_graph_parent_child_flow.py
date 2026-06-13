from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from orchestrator.config.models import RoutineConfig, StepConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    EventEnvelope,
    compile_routine,
    project_decision_view,
    project_planner_chain,
    project_planner_session,
    project_run_state,
)
from orchestrator.graph_runtime import GraphController, GraphEventStore


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class SequentialIds:
    def __init__(self) -> None:
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{prefix}-{self._next}"
        self._next += 1
        return value


@pytest.mark.asyncio
async def test_two_child_parent_runs_as_one_graph_run(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path / "parent-child-flow.db")
    controller = GraphController(
        session_factory, FixedClock(), SequentialIds(), auto_dispatch=False
    )
    run_id = "parent-child-flow"
    try:
        await _seed_parent_child_run(controller, run_id)
        events = await _read_events(session_factory, run_id)
        events = await _complete_node(session_factory, controller, run_id, "planner-parent", events)
        events = await _command(
            session_factory,
            controller,
            run_id,
            "submit_patch",
            _patch_payload(
                events,
                "patch-child-one",
                "planner-parent",
                _region_ops("one", "planner-child-two"),
                carryover_record_id="summary-one",
            ),
        )
        events = await _drive_region(session_factory, controller, run_id, events, "one")

        assert project_run_state(events) == "active"
        events = await _complete_node(
            session_factory, controller, run_id, "planner-child-two", events
        )
        events = await _command(
            session_factory,
            controller,
            run_id,
            "submit_patch",
            _patch_payload(
                events,
                "patch-child-two",
                "planner-child-two",
                _region_ops("two", None),
            ),
        )
        events = await _drive_region(session_factory, controller, run_id, events, "two")

        assert project_run_state(events) == "completed"
        assert [entry["region_label"] for entry in project_planner_chain(events)] == [
            "child-one",
            "child-two",
        ]
        assert project_planner_session(events)["carryover_record_id"] == "summary-one"
        assert {event.run_id for event in events} == {run_id}
        assert not any(_contains_legacy_child_artifact(event.payload) for event in events)

        replayed = await _read_events(session_factory, run_id)
        assert project_run_state(replayed) == project_run_state(events)
        assert project_planner_chain(replayed) == project_planner_chain(events)
        assert project_planner_session(replayed) == project_planner_session(events)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_child_oversight_maps_to_in_chain_appeal(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path / "parent-child-appeal.db")
    controller = GraphController(
        session_factory, FixedClock(), SequentialIds(), auto_dispatch=False
    )
    run_id = "parent-child-appeal"
    try:
        await _seed_parent_child_run(controller, run_id)
        events = await _read_events(session_factory, run_id)
        events = await _complete_node(session_factory, controller, run_id, "planner-parent", events)
        events = await _command(
            session_factory,
            controller,
            run_id,
            "submit_patch",
            _patch_payload(
                events,
                "patch-child-appeal",
                "planner-parent",
                [
                    *_region_ops("one", None),
                    {
                        "op": "create_appeal",
                        "node_id": "appeal-child-one",
                        "kind": "appeal",
                        "state": "planned",
                        "appealed_node_id": "verifier-one",
                        "appeal_type": "invalid_test",
                        "task_region_id": "region-one",
                    },
                ],
            ),
        )

        projection = project_decision_view(events)
        assert projection["appeals"] == [
            {"node_id": "appeal-child-one", "state": "planned", "outcome": None}
        ]
        assert {event.run_id for event in events} == {run_id}
        assert not any(_contains_legacy_child_artifact(event.payload) for event in events)
    finally:
        await engine.dispose()


async def _session_factory(
    path: Path,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_engine(path)
    await init_db(engine)
    return engine, create_session_factory(engine)


async def _seed_parent_child_run(controller: GraphController, run_id: str) -> None:
    routine = RoutineConfig(
        id="parent-child",
        name="Parent Child",
        steps=[
            StepConfig(
                id="Parent",
                kind="planner",
                title="Parent",
                child_routines=[
                    {"routine": "child-one"},
                    {"routine": "child-two"},
                ],
            )
        ],
    )
    compiled = compile_routine(routine, FixedClock(), SequentialIds(), run_id=run_id)
    await controller.handle_command(
        run_id,
        0,
        "seed_compiled_events",
        {"events": [event.model_dump(mode="json") for event in compiled]},
    )
    position = await controller.current_position(run_id)
    result = await controller.handle_command(run_id, position, "accept_run", {})
    result = await controller.handle_command(run_id, result.projection_position, "start", {})
    assert result.projection_position > 0


async def _complete_node(
    session_factory: async_sessionmaker[AsyncSession],
    controller: GraphController,
    run_id: str,
    node_id: str,
    events: list[EventEnvelope],
) -> list[EventEnvelope]:
    events = await _command(
        session_factory,
        controller,
        run_id,
        "schedule_tick",
        {"base_snapshot_id": "snapshot-0", "max_grants": 10},
    )
    lease = next(
        event
        for event in events
        if event.event_type == "lease_granted" and event.payload["node_id"] == node_id
    )
    await _command(session_factory, controller, run_id, "acknowledge_start", _start_payload(lease))
    return await _command(
        session_factory,
        controller,
        run_id,
        "submit_callback",
        _callback_payload(node_id, lease, []),
    )


async def _drive_region(
    session_factory: async_sessionmaker[AsyncSession],
    controller: GraphController,
    run_id: str,
    events: list[EventEnvelope],
    prefix: str,
) -> list[EventEnvelope]:
    worker_id = f"worker-{prefix}"
    verifier_id = f"verifier-{prefix}"
    events = await _command(
        session_factory,
        controller,
        run_id,
        "schedule_tick",
        {"base_snapshot_id": "snapshot-0", "max_grants": 10},
    )
    worker_lease = next(
        event
        for event in events
        if event.event_type == "lease_granted" and event.payload["node_id"] == worker_id
    )
    await _command(
        session_factory,
        controller,
        run_id,
        "acknowledge_start",
        _start_payload(worker_lease),
    )
    events = await _command(
        session_factory,
        controller,
        run_id,
        "submit_callback",
        _callback_payload(
            worker_id,
            worker_lease,
            [
                {
                    "record_id": f"candidate-{prefix}",
                    "record_kind": "output",
                    "producer_node_id": worker_id,
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "candidate_id": f"candidate-{prefix}",
                    "task_region_id": f"region-{prefix}",
                    "attempt_number": 1,
                    "value": {"summary": "done"},
                },
                {
                    "record_id": f"file-state-{prefix}",
                    "record_kind": "file_state",
                    "producer_node_id": worker_id,
                    "snapshot_id": f"snapshot-{prefix}",
                    "base_snapshot_id": "snapshot-0",
                    "port": "file_state",
                },
            ],
        ),
    )

    events = await _command(
        session_factory,
        controller,
        run_id,
        "schedule_tick",
        {"base_snapshot_id": f"snapshot-{prefix}", "max_grants": 10},
    )
    verifier_lease = next(
        event
        for event in events
        if event.event_type == "lease_granted" and event.payload["node_id"] == verifier_id
    )
    await _command(
        session_factory,
        controller,
        run_id,
        "acknowledge_start",
        _start_payload(verifier_lease),
    )
    return await _command(
        session_factory,
        controller,
        run_id,
        "submit_callback",
        _callback_payload(
            verifier_id,
            verifier_lease,
            [
                {
                    "record_id": f"verification-{prefix}",
                    "record_kind": "verification",
                    "candidate_id": f"candidate-{prefix}",
                    "verdict": "passed",
                },
                {
                    "record_id": f"summary-{prefix}",
                    "record_kind": "output",
                    "producer_node_id": verifier_id,
                    "port": "region_summary",
                    "schema": "RegionSummary",
                    "value": {"milestone_kind": "region_summary"},
                },
            ],
        ),
    )


async def _command(
    session_factory: async_sessionmaker[AsyncSession],
    controller: GraphController,
    run_id: str,
    command_type: str,
    payload: dict[str, Any],
) -> list[EventEnvelope]:
    position = await controller.current_position(run_id)
    await controller.handle_command(run_id, position, command_type, payload)
    return await _read_events(session_factory, run_id)


async def _read_events(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
) -> list[EventEnvelope]:
    async with session_factory() as session:
        return await GraphEventStore(session).read_run(run_id)


def _patch_payload(
    events: list[EventEnvelope],
    patch_id: str,
    planner_id: str,
    ops: list[dict[str, Any]],
    *,
    carryover_record_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "patch_id": patch_id,
        "proposed_by_node_id": planner_id,
        "base_graph_position": max(event.position for event in events),
        "actor_role": "planner",
        "ops": ops,
    }
    if carryover_record_id is not None:
        payload["carryover_record_id"] = carryover_record_id
    return payload


def _region_ops(prefix: str, successor_id: str | None) -> list[dict[str, Any]]:
    worker_id = f"worker-{prefix}"
    verifier_id = f"verifier-{prefix}"
    candidate_id = f"candidate-{prefix}"
    ops: list[dict[str, Any]] = [
        {
            "op": "create_node",
            "node": {
                "node_id": worker_id,
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "task_region_id": f"region-{prefix}",
                "attempt_number": 1,
                "candidate_id": candidate_id,
            },
        },
        {
            "op": "create_node",
            "node": {
                "node_id": verifier_id,
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "task_region_id": f"region-{prefix}",
                "attempt_number": 1,
                "candidate_id": candidate_id,
            },
        },
        {
            "op": "create_edge",
            "edge_id": f"edge-candidate-{prefix}",
            "from_node_id": worker_id,
            "from_port": "candidate",
            "to_node_id": verifier_id,
            "to_port": "candidate_under_test",
        },
    ]
    if successor_id is None:
        return ops
    ops.append(
        {
            "op": "create_node",
            "node": {
                "node_id": successor_id,
                "kind": "planner",
                "role": "planner",
                "state": "planned",
                "generation_index": 1,
                "inputs": [
                    {"port": "region_summary", "direction": "input", "required": True},
                    {"port": "accepted_file_state", "direction": "input", "required": True},
                ],
            },
        }
    )
    ops.extend(
        [
            _selector_edge(
                f"edge-summary-{prefix}",
                verifier_id,
                "region_summary",
                successor_id,
                "region_summary",
            ),
            _selector_edge(
                f"edge-file-{prefix}",
                worker_id,
                "file_state",
                successor_id,
                "accepted_file_state",
            ),
        ]
    )
    return ops


def _selector_edge(
    edge_id: str,
    from_node_id: str,
    from_port: str,
    to_node_id: str,
    to_port: str,
) -> dict[str, Any]:
    return {
        "op": "create_edge",
        "edge_id": edge_id,
        "from_node_id": from_node_id,
        "from_port": from_port,
        "to_node_id": to_node_id,
        "to_port": to_port,
        "accepted_record_selector": {"record_kinds": [to_port]},
    }


def _start_payload(lease: EventEnvelope) -> dict[str, Any]:
    return {
        "node_id": lease.payload["node_id"],
        "execution_id": lease.payload["execution_id"],
        "lease_id": lease.payload["lease_id"],
        "lease_generation": lease.payload["generation"],
    }


def _callback_payload(
    node_id: str,
    lease: EventEnvelope,
    output_records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "execution_id": lease.payload["execution_id"],
        "lease_id": lease.payload["lease_id"],
        "lease_generation": lease.payload["generation"],
        "base_snapshot_id": lease.payload["base_snapshot_id"],
        "observed_graph_position": lease.position,
        "idempotency_key": f"callback-{node_id}-{lease.position}",
        "payload": {
            "payload_hash": f"hash-{node_id}-{lease.position}",
            "output_records": output_records,
        },
    }


def _contains_legacy_child_artifact(payload: dict[str, Any]) -> bool:
    legacy_terms = {
        "child_run_id",
        "parent_run_id",
        "worktree_path",
        "child_worktree_path",
        "merge_step",
        "merge_commit",
    }
    return any(term in payload for term in legacy_terms) or payload.get("kind") == "merge"
