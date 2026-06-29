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
    project_planner_chain,
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
async def test_planner_chain_two_horizons_end_to_end(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path / "planner-flow.db")
    controller = GraphController(
        session_factory, FixedClock(), SequentialIds(), auto_dispatch=False
    )
    run_id = "planner-flow"
    try:
        await _seed_planner_run(controller, run_id, budget=8)
        events = await _read_events(session_factory, run_id)
        events = await _complete_node(session_factory, controller, run_id, "planner-plan", events)
        events = await _command(
            session_factory,
            controller,
            run_id,
            "submit_patch",
            _patch_payload(events, "patch-h1", "planner-plan", _region_ops("h1", "planner-1")),
        )
        events = await _drive_region(session_factory, controller, run_id, events, "h1")

        events = await _schedule_and_complete(
            session_factory,
            controller,
            run_id,
            events,
            "planner-1",
        )
        events = await _command(
            session_factory,
            controller,
            run_id,
            "submit_patch",
            _patch_payload(events, "patch-h2", "planner-1", _region_ops("h2", None)),
        )
        events = await _drive_region(session_factory, controller, run_id, events, "h2")

        assert project_run_state(events) == "completed"
        assert project_planner_chain(events)[-1]["successor_node_id"] is None

        replayed = await _read_events(session_factory, run_id)
        assert project_run_state(replayed) == project_run_state(events)
        assert project_planner_chain(replayed) == project_planner_chain(events)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_budget_exhaustion_routes_to_gate_through_controller(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path / "planner-budget.db")
    controller = GraphController(
        session_factory, FixedClock(), SequentialIds(), auto_dispatch=False
    )
    run_id = "planner-budget"
    try:
        await _seed_planner_run(controller, run_id, budget=1)
        events = await _read_events(session_factory, run_id)
        events = await _complete_node(session_factory, controller, run_id, "planner-plan", events)
        events = await _command(
            session_factory,
            controller,
            run_id,
            "submit_patch",
            _patch_payload(events, "patch-h1", "planner-plan", _region_ops("h1", "planner-1")),
        )
        events = await _drive_region(session_factory, controller, run_id, events, "h1")
        events = await _schedule_and_complete(
            session_factory,
            controller,
            run_id,
            events,
            "planner-1",
        )

        events = await _command(
            session_factory,
            controller,
            run_id,
            "submit_patch",
            _patch_payload(events, "patch-budget", "planner-1", _region_ops("h2", "planner-2")),
        )

        assert any(
            event.event_type == "graph_patch_rejected"
            and event.payload["reason"] == "planner_generation_budget_exhausted"
            for event in events
        )
        assert any(
            event.event_type == "node_created"
            and event.payload.get("role") == "planner_generation_budget_gate"
            for event in events
        )
        assert project_run_state(events) != "completed"
    finally:
        await engine.dispose()


async def _session_factory(
    path: Path,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_engine(path)
    await init_db(engine)
    return engine, create_session_factory(engine)


async def _seed_planner_run(controller: GraphController, run_id: str, *, budget: int) -> None:
    routine = RoutineConfig(
        id="planner",
        name="Planner",
        planner_generation_budget=budget,
        steps=[StepConfig(id="Plan", kind="planner", title="Plan")],
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
    events = await _command(
        session_factory,
        controller,
        run_id,
        "acknowledge_start",
        _start_payload(lease),
    )
    return await _command(
        session_factory,
        controller,
        run_id,
        "submit_callback",
        _callback_payload(node_id, lease, []),
    )


async def _schedule_and_complete(
    session_factory: async_sessionmaker[AsyncSession],
    controller: GraphController,
    run_id: str,
    events: list[EventEnvelope],
    node_id: str,
) -> list[EventEnvelope]:
    return await _complete_node(session_factory, controller, run_id, node_id, events)


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
                    "value": {
                        "grades": [
                            {
                                "requirement_id": "R-1",
                                "grade": "A",
                                "reason": "candidate satisfies requirement",
                            }
                        ]
                    },
                },
                {
                    "record_id": f"summary-{prefix}",
                    "record_kind": "output",
                    "producer_node_id": verifier_id,
                    "port": "region_summary",
                    "schema": "RegionSummary",
                    "value": {
                        "summary": "Verification evidence was summarized for the region.",
                        "source_record_ids": [f"verification-{prefix}"],
                        "lossy": False,
                        "omitted_details": [],
                    },
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
) -> dict[str, Any]:
    return {
        "patch_id": patch_id,
        "proposed_by_node_id": planner_id,
        "base_graph_position": max(event.position for event in events),
        "actor_role": "planner",
        "ops": ops,
    }


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
    generation = int(successor_id.rsplit("-", 1)[1])
    ops.append(
        {
            "op": "create_node",
            "node": {
                "node_id": successor_id,
                "kind": "planner",
                "role": "planner",
                "state": "planned",
                "generation_index": generation,
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
                f"edge-file-{prefix}", worker_id, "file_state", successor_id, "accepted_file_state"
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
