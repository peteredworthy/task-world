"""Integration tests for graph compatibility projection endpoints."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from orchestrator.api import append_requeue_audit_event
from orchestrator.config import RunStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.db import (
    EventV2Model,
    GraphEventSummaryModel,
    GraphOutboxModel,
    GraphProjectionSnapshotModel,
    RunModel,
)
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock, PatchCommandContext
from orchestrator.graph.commands import IdGenerator
from orchestrator.state.factory import create_run_from_routine
from orchestrator.db.access.mutations import save_run
from orchestrator.graph_runtime import (
    GraphController,
    GraphEventStore,
    OutboxDispatcher,
    OutboxItem,
    seed_run,
)
from tests.unit.graph_test_utils import canonical_event_payload


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "graph-api-test",
            "name": "Graph API Test Routine",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Do one thing",
                            "task_context": "Exercise graph projections.",
                            "verifier": {
                                "rubric": [
                                    {
                                        "id": "req-1",
                                        "text": "The implementation is correct.",
                                    }
                                ]
                            },
                        }
                    ],
                }
            ],
        }
    )


def _event(event_type: str, payload: dict[str, Any]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{uuid4().hex}",
        run_id="placeholder",
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=canonical_event_payload(event_type, payload),
    )


class _RunSeedIdGenerator:
    def __init__(self, run_id: str) -> None:
        self._run_id = run_id.replace("-", "")
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{self._run_id}-{prefix}-{self._next}"
        self._next += 1
        return value


class _RecordingOutboxExecutor:
    def __init__(self) -> None:
        self.event_ids: list[str] = []

    async def dispatch(self, item: OutboxItem) -> None:
        self.event_ids.append(item.event_id)


class _AlwaysFailingOutboxExecutor:
    def __init__(self) -> None:
        self.event_ids: list[str] = []

    async def dispatch(self, item: OutboxItem) -> None:
        self.event_ids.append(item.event_id)
        raise RuntimeError("agent dispatch exploded")


async def _save_manual_graph_run(app: Any, run_id: str) -> None:
    run = create_run_from_routine(
        _routine(),
        repo_name=f"graph-api-manual-repo-{run_id}",
        source_branch="main",
    )
    run.id = run_id
    run.execution_mode = "graph"
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await save_run(session, run)
        await session.commit()


async def _seed_graph_run(
    app: Any,
    run_id: str,
) -> None:
    clock = FakeClock()
    id_gen: IdGenerator = _RunSeedIdGenerator(run_id)
    routine = _routine()
    repo_name = "graph-api-test-repo"

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory

    # Seed the projection from compiled routine topology.
    seed = await seed_run(
        session_factory,
        routine,
        run_id=run_id,
        clock=clock,
        id_gen=id_gen,
    )
    assert seed.projection_position > 0

    # Append lifecycle ticks directly through the controller so projection mirrors
    # existing graph-runner execution flow.
    controller = GraphController(session_factory, clock, id_gen, auto_dispatch=False)
    accepted = await controller.handle_command(run_id, seed.projection_position, "accept_run")
    started = await controller.handle_command(run_id, accepted.projection_position, "start")
    await controller.handle_command(
        run_id,
        started.projection_position,
        "schedule_tick",
        {"max_grants": 1, "lease_seconds": 60},
    )

    run = create_run_from_routine(routine, repo_name=repo_name, source_branch="main")
    run.id = run_id
    async with session_factory() as session:
        await save_run(session, run)
        await session.commit()


async def _seed_control_topology_graph_run(app: Any, run_id: str) -> None:
    await _save_manual_graph_run(app, run_id)
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "worker-control",
                "kind": "worker",
                "role": "builder",
                "state": "completed",
                "task_region_id": "task-1",
                "command_definition": {
                    "id": "worker-command",
                    "cmd": "uv run pytest tests/unit/test_graph_scheduler_view.py -q",
                    "source": "test",
                },
            },
        ),
        _event(
            "node_authority_changed",
            {
                "node_id": "worker-control",
                "authority": {
                    "resource_claims": [{"mode": "write", "scope": "paths", "paths": ["src/"]}],
                    "allowed_actions": ["submit", "record_heartbeat"],
                    "preconditions": ["candidate_bound", "no_active_conflicts"],
                },
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-control",
                "kind": "verifier",
                "role": "verifier",
                "state": "ready",
                "task_region_id": "task-1",
            },
        ),
        _event(
            "edge_created",
            {
                "edge_id": "edge-control-candidate",
                "from_node_id": "worker-control",
                "from_port": "candidate",
                "to_node_id": "verifier-control",
                "to_port": "candidate_under_test",
                "required": True,
                "dependency_type": "input_binding",
                "binding_policy": "bind_latest",
                "freshness_policy": "latest_only",
                "prompt_hydration_policy": "artifact_reference",
                "metadata": {"purpose": "verify bound candidate"},
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "candidate-control",
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-control",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": "candidate-control",
                "value": {"summary": "control readback candidate"},
            },
        ),
        _event(
            "input_bound",
            {
                "edge_id": "edge-control-candidate",
                "to_node_id": "verifier-control",
                "to_port": "candidate_under_test",
                "record_ids": ["candidate-control"],
                "bound_at_position": 0,
                "trigger": "record_accepted",
            },
        ),
    ]
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()


async def _seed_callback_lifecycle_graph_run(app: Any, run_id: str) -> None:
    await _save_manual_graph_run(app, run_id)
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {"node_id": "worker-callback", "kind": "worker", "state": "running"},
        ),
        _event(
            "lease_granted",
            {
                "node_id": "worker-callback",
                "lease_id": "lease-callback",
                "generation": 1,
                "execution_id": "exec-callback",
                "expires_at": "2026-01-01T00:01:00+00:00",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "artifact-callback",
                "record_kind": "graph_record",
                "record_type": "artifact_reference",
                "producer_node_id": "worker-callback",
                "port": "artifact",
                "schema": "ContextArtifact",
                "value": {
                    "artifact_id": "stdout",
                    "artifact_type": "agent_output",
                    "uri": "artifacts/stdout.txt",
                },
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "failure-callback",
                "record_kind": "graph_record",
                "record_type": "failure_record",
                "producer_node_id": "worker-callback",
                "port": "failure_record",
                "schema": "FailureRecord",
                "value": {
                    "failed_node_id": "worker-callback",
                    "phase": "runtime",
                    "error_class": "agent_error",
                    "retryable": True,
                },
            },
        ),
    ]
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()

    controller = GraphController(
        session_factory,
        FakeClock(),
        _RunSeedIdGenerator(run_id),
        auto_dispatch=False,
    )
    heartbeat = await controller.handle_command(
        run_id,
        len(events),
        "record_heartbeat",
        {
            "lease_id": "lease-callback",
            "node_id": "worker-callback",
            "generation": 1,
            "ttl_seconds": 120,
        },
    )
    await controller.handle_command(run_id, heartbeat.projection_position, "cancel")


async def _seed_rejected_patch_graph_run(app: Any, run_id: str) -> None:
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    controller = GraphController(
        session_factory,
        FakeClock(),
        _RunSeedIdGenerator(run_id),
        auto_dispatch=False,
    )
    await controller.handle_command(
        run_id,
        0,
        "submit_patch",
        {
            "patch_id": "patch-bad-request",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "gate-review",
                        "kind": "human_gate",
                        "state": "planned",
                        "decision_request": {
                            "decision_type": "approval",
                            "options": ["approve"],
                            "default_option": "reject",
                            "consequence_summary": "Review graph expansion.",
                        },
                    },
                }
            ],
        },
        context=PatchCommandContext(
            run_id=run_id,
            current_graph_position=0,
            proposed_by_node_id="planner-1",
            actor_role="planner",
        ),
    )


async def _seed_worker_verifier_cycle(app: Any, run_id: str) -> None:
    await _seed_graph_run(app, run_id)

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    clock = FakeClock()
    id_gen: IdGenerator = _RunSeedIdGenerator(run_id)
    controller = GraphController(session_factory, clock, id_gen, auto_dispatch=False)
    async with session_factory() as session:
        events = await GraphEventStore(session).read_run(run_id)
    position = max(event.position for event in events)
    worker_lease = next(event for event in events if event.event_type == "lease_granted")
    worker_node = str(worker_lease.payload["node_id"])
    worker_created = next(
        event
        for event in events
        if event.event_type == "node_created" and event.payload.get("node_id") == worker_node
    )
    candidate_id = str(worker_created.payload["candidate_id"])
    task_region_id = str(worker_created.payload["task_region_id"])
    attempt_number = int(worker_created.payload["attempt_number"])

    acknowledged = await controller.handle_command(
        run_id,
        position,
        "acknowledge_start",
        {
            "node_id": worker_node,
            "lease_id": worker_lease.payload["lease_id"],
            "lease_generation": worker_lease.payload["generation"],
            "execution_id": worker_lease.payload["execution_id"],
        },
    )
    completed_worker = await controller.handle_command(
        run_id,
        acknowledged.projection_position,
        "submit_callback",
        {
            "node_id": worker_node,
            "execution_id": worker_lease.payload["execution_id"],
            "lease_id": worker_lease.payload["lease_id"],
            "lease_generation": worker_lease.payload["generation"],
            "base_snapshot_id": worker_lease.payload["base_snapshot_id"],
            "observed_graph_position": acknowledged.projection_position,
            "idempotency_key": f"callback-{worker_node}",
            "payload": {
                "payload_hash": f"hash-{worker_node}",
                "output_records": [
                    {
                        "record_id": candidate_id,
                        "record_kind": "output",
                        "producer_node_id": worker_node,
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "candidate_id": candidate_id,
                        "task_region_id": task_region_id,
                        "attempt_number": attempt_number,
                        "value": {"summary": "worker output"},
                    },
                    {
                        "record_id": f"fs-{worker_node}",
                        "record_kind": "file_state",
                        "snapshot_id": f"snapshot-{worker_node}",
                        "producer_node_id": worker_node,
                        "verdict": "captured",
                        "tracked": [
                            {
                                "path": "src/app.py",
                                "status": "modified",
                                "classification": "source",
                            }
                        ],
                        "residue": [
                            {
                                "path": "tmp/output.log",
                                "classification": "test_artifact",
                                "needs_gatekeeper": False,
                            }
                        ],
                    },
                ],
            },
        },
    )
    scheduled_verifier = await controller.handle_command(
        run_id,
        completed_worker.projection_position,
        "schedule_tick",
        {"max_grants": 1, "lease_seconds": 60},
    )
    verifier_lease = next(
        event for event in scheduled_verifier.events if event.event_type == "lease_granted"
    )
    verifier_node = str(verifier_lease.payload["node_id"])
    acknowledged_verifier = await controller.handle_command(
        run_id,
        scheduled_verifier.projection_position,
        "acknowledge_start",
        {
            "node_id": verifier_node,
            "lease_id": verifier_lease.payload["lease_id"],
            "lease_generation": verifier_lease.payload["generation"],
            "execution_id": verifier_lease.payload["execution_id"],
        },
    )
    await controller.handle_command(
        run_id,
        acknowledged_verifier.projection_position,
        "submit_callback",
        {
            "node_id": verifier_node,
            "execution_id": verifier_lease.payload["execution_id"],
            "lease_id": verifier_lease.payload["lease_id"],
            "lease_generation": verifier_lease.payload["generation"],
            "base_snapshot_id": verifier_lease.payload["base_snapshot_id"],
            "observed_graph_position": acknowledged_verifier.projection_position,
            "idempotency_key": f"callback-{verifier_node}",
            "payload": {
                "payload_hash": f"hash-{verifier_node}",
                "output_records": [
                    {
                        "record_id": f"verification-{candidate_id}",
                        "record_kind": "verification",
                        "producer_node_id": verifier_node,
                        "port": "verification_report",
                        "schema": "VerificationReport",
                        "candidate_id": candidate_id,
                        "outcome": "passed",
                        "evidence": {"summary": "looks good"},
                        "value": {
                            "outcome": "passed",
                            "grades": [
                                {
                                    "requirement_id": "R-1",
                                    "grade": "A",
                                    "reason": "candidate satisfies requirement",
                                }
                            ],
                        },
                    }
                ],
            },
        },
    )


async def test_graph_projection_empty_for_non_graph_run(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"legacy-run-{uuid4().hex[:8]}"
    run = create_run_from_routine(
        _routine(),
        repo_name="graph-api-legacy-repo",
        source_branch="main",
    )
    run.id = run_id
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await save_run(session, run)
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph")
    assert response.status_code == 200
    projection = response.json()
    assert projection["run_id"] == run_id
    assert projection["event_count"] == 0
    assert projection["run_state"] is None
    assert projection["node_states"] == {}
    assert projection["task_states"] == {}
    assert projection["leases"] == {}
    assert projection["ready_nodes"] == []


async def test_graph_health_returns_not_found_for_a_missing_run(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, _app = _shared_app_fixture

    response = await client.get("/api/runs/no-such-run/graph/health")

    assert response.status_code == 404


async def test_graph_health_returns_an_empty_bounded_snapshot_for_a_saved_run(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-health-empty-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)

    response = await client.get(f"/api/runs/{run_id}/graph/health")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": run_id,
        "event_count": 0,
        "run_state": None,
        "status": "empty",
        "counts": {
            "ready": 0,
            "blocked": 0,
            "waiting_resources": 0,
            "waiting_gates": 0,
            "active_leases": 0,
            "suspended_leases": 0,
            "expired_leases": 0,
            "failed_nodes": 0,
            "final_blockers": 0,
            "patches_accepted": 0,
            "patches_rejected": 0,
            "verifier_passed": 0,
            "verifier_failed": 0,
            "pending_gates": 0,
        },
        "failed_nodes": [],
        "expired_leases": [],
        "blockers": [],
        "recent_patch_decisions": [],
        "verifier": {"passed": 0, "failed": 0, "recent": []},
        "pending_gates": [],
        "review_blockers": [],
        "detail_meta": {},
    }


async def test_graph_health_reduces_current_typed_events_to_compact_operator_facts(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-health-populated-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "verifier-expired",
                "kind": "verifier",
                "role": "verifier",
                "state": "planned",
                "task_region_id": "step-1/task-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "review-final",
                "kind": "review",
                "role": "invariant",
                "state": "blocked",
                "task_region_id": "step-1/task-1",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "gate-human",
                "kind": "gate",
                "role": "approval",
                "state": "blocked",
                "gate_type": "human_approval",
                "task_region_id": "step-1/task-1",
            },
        ),
        _event(
            "lease_granted",
            {
                "lease_id": "lease-expired",
                "node_id": "verifier-expired",
                "generation": 1,
                "execution_id": "execution-expired",
                "expires_at": "2026-06-21T12:05:00+00:00",
                "base_snapshot_id": "snapshot-1",
            },
        ),
        _event("lease_expired", {"lease_id": "lease-expired", "node_id": "verifier-expired"}),
        _event(
            "node_state_changed",
            {
                "node_id": "verifier-expired",
                "new_state": "failed",
                "trigger": "lease_expired_without_callback",
                "reason": "lease_expired_without_callback",
            },
        ),
        _event(
            "verification_passed",
            {
                "verifier_node_id": "verifier-pass",
                "candidate_id": "candidate-1",
                "task_region_id": "step-1/task-1",
                "record_id": "verification-pass",
                "value": {"grades": [{"requirement_id": "req-1", "grade": "A", "reason": "met"}]},
            },
        ),
        _event(
            "verification_failed",
            {
                "verifier_node_id": "verifier-expired",
                "candidate_id": "candidate-1",
                "task_region_id": "step-1/task-1",
                "record_id": "verification-failed",
                "value": {
                    "grades": [{"requirement_id": "req-2", "grade": "C", "reason": "not met"}]
                },
            },
        ),
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-accepted",
                "actor_role": "planner",
                "proposed_by_node_id": "planner-1",
                "ops": [{"op": "create_node"}],
            },
        ),
        _event(
            "graph_patch_rejected",
            {
                "patch_id": "patch-rejected",
                "actor_role": "planner",
                "proposed_by_node_id": "planner-1",
                "reason": "read_set_changed",
            },
        ),
        _event(
            "node_deferred",
            {"node_id": "review-final", "reason": "missing_required_input:verification_evidence"},
        ),
        _event(
            "command_rejected",
            {
                "command_type": "complete",
                "reason": "final invariant blockers remain",
                "blockers": [{"node_id": "review-final", "kind": "final_invariant"}],
            },
        ),
    ]
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph/health")

    assert response.status_code == 200
    health = response.json()
    assert health["counts"] == {
        "ready": 0,
        "blocked": 1,
        "waiting_resources": 0,
        "waiting_gates": 1,
        "active_leases": 0,
        "suspended_leases": 0,
        "expired_leases": 1,
        "failed_nodes": 1,
        "final_blockers": 3,
        "patches_accepted": 1,
        "patches_rejected": 1,
        "verifier_passed": 1,
        "verifier_failed": 1,
        "pending_gates": 1,
    }
    assert health["failed_nodes"] == [
        {"node_id": "verifier-expired", "reason": "lease_expired_without_callback"}
    ]
    assert health["expired_leases"] == [
        {
            "lease_id": "lease-expired",
            "node_id": "verifier-expired",
            "reason": "lease_expired_without_callback",
        }
    ]
    assert len(health["blockers"]) == 3
    assert health["verifier"] == {
        "passed": 1,
        "failed": 1,
        "recent": [
            {"node_id": "verifier-pass", "candidate_id": "candidate-1", "verdict": "passed"},
            {"node_id": "verifier-expired", "candidate_id": "candidate-1", "verdict": "failed"},
        ],
    }
    assert health["recent_patch_decisions"] == [
        {"patch_id": "patch-accepted", "decision": "accepted", "reason": None},
        {"patch_id": "patch-rejected", "decision": "rejected", "reason": "read_set_changed"},
    ]
    assert health["pending_gates"] == [{"node_id": "gate-human", "gate_type": "human_approval"}]
    assert health["review_blockers"] == [
        "review-final: missing_required_input:verification_evidence"
    ]
    assert len(response.content) < 4_000


async def test_graph_projection_reflects_seeded_events(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = "graph-seeded-run"

    await _seed_graph_run(app, run_id)

    projection_resp = await client.get(f"/api/runs/{run_id}/graph")
    assert projection_resp.status_code == 200
    projection = projection_resp.json()
    assert projection["event_count"] > 0
    assert projection["run_state"] == "active"
    assert len(projection["node_states"]) > 0
    worker_node = next(
        node_id for node_id in projection["node_states"] if node_id.startswith("worker-")
    )

    events_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")
    assert events_resp.status_code == 200
    all_events = events_resp.json()
    assert len(all_events) == projection["event_count"]

    filter_resp = await client.get(f"/api/runs/{run_id}/graph/events?from_position=2")
    assert filter_resp.status_code == 200
    filtered_events = filter_resp.json()
    assert len(filtered_events) <= len(all_events)
    assert all(event["position"] >= 2 for event in filtered_events)

    summary_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=summary")
    assert summary_resp.status_code == 200
    summary_events = summary_resp.json()
    assert len(summary_events) == len(all_events)
    root_summary = next(
        event for event in summary_events if event["payload"].get("node_id") == "root"
    )
    assert "routine" not in root_summary["payload"]

    invalid_summary_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=compact")
    assert invalid_summary_resp.status_code == 422

    detail_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/{worker_node}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["state"] == projection["node_states"][worker_node]
    assert detail["node_id"] == worker_node

    not_found = await client.get(f"/api/runs/{run_id}/graph/nodes/nonexistent")
    assert not_found.status_code == 404


async def test_graph_final_blockers_surface_failed_outbox_rows(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-failed-outbox-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        async with session.begin():
            session.add(
                GraphOutboxModel(
                    event_id="failed-outbox-event",
                    run_id=run_id,
                    kind="agent_dispatch",
                    payload={"event_id": "failed-outbox-event", "node_id": "worker-1"},
                    status="pending",
                    attempts=0,
                    created_at=now,
                    updated_at=now,
                    next_attempt_at=None,
                    last_error=None,
                )
            )

    dispatcher = OutboxDispatcher(
        session_factory,
        _AlwaysFailingOutboxExecutor(),
        FakeClock(),
        retry_base_seconds=0,
        retry_factor=1,
        retry_jitter_seconds=0,
    )
    assert await dispatcher.dispatch_pending(run_id=run_id) == []

    async with session_factory() as session:
        failed_row = (
            await session.execute(
                select(GraphOutboxModel).where(GraphOutboxModel.event_id == "failed-outbox-event")
            )
        ).scalar_one()
    assert failed_row.status == "failed"
    assert failed_row.attempts == 3
    assert failed_row.last_error == "agent dispatch exploded"

    response = await client.get(f"/api/runs/{run_id}/graph/final-blockers")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    blocker = next(
        item
        for item in body["blockers"]
        if item["kind"] == "failed_outbox_row" and item["outbox_event_id"] == "failed-outbox-event"
    )
    assert blocker["reason"] == (
        f"outbox row failed for run {run_id}: agent_dispatch: agent dispatch exploded"
    )
    assert blocker["state"] == "failed"
    assert blocker["support_ids"] == ["failed-outbox-event"]
    assert blocker["run_id"] == run_id
    assert isinstance(blocker["outbox_id"], int)
    assert blocker["outbox_kind"] == "agent_dispatch"
    assert blocker["outbox_last_error"] == "agent dispatch exploded"
    assert blocker["outbox_attempts"] == 3


async def test_operator_requeues_failed_outbox_row_with_audit_event(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-requeue-outbox-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [_event("run_lifecycle_changed", {"to_state": "active"})],
        )
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        session.add(
            GraphOutboxModel(
                event_id="requeue-outbox-event",
                run_id=run_id,
                kind="agent_dispatch",
                payload={"event_id": "requeue-outbox-event", "node_id": "worker-1"},
                status="failed",
                attempts=3,
                created_at=now,
                updated_at=now,
                next_attempt_at=now,
                last_error="agent dispatch exploded",
            )
        )
        await session.commit()

    response = await client.post(f"/api/runs/{run_id}/graph/outbox/requeue/requeue-outbox-event")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": run_id,
        "event_id": "requeue-outbox-event",
        "status": "pending",
        "attempts": 0,
    }
    async with session_factory() as session:
        row = (
            await session.execute(
                select(GraphOutboxModel).where(GraphOutboxModel.event_id == "requeue-outbox-event")
            )
        ).scalar_one()
    assert row.status == "pending"
    assert row.attempts == 0
    assert row.next_attempt_at is None
    assert row.last_error is None

    events_response = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")
    assert events_response.status_code == 200
    audit_event = next(
        event for event in events_response.json() if event["event_type"] == "outbox_requeued"
    )
    assert audit_event["payload"] == {
        "run_id": run_id,
        "outbox_id": row.outbox_id,
        "event_id": "requeue-outbox-event",
        "kind": "agent_dispatch",
        "previous_status": "failed",
        "previous_attempts": 3,
        "previous_last_error": "agent dispatch exploded",
        "operator": "human-operator",
        "graph_position": audit_event["position"],
    }

    executor = _RecordingOutboxExecutor()
    completed = await OutboxDispatcher(session_factory, executor, FakeClock()).dispatch_pending(
        run_id=run_id
    )
    assert executor.event_ids == ["requeue-outbox-event"]
    assert [item.event_id for item in completed] == ["requeue-outbox-event"]
    async with session_factory() as session:
        completed_row = (
            await session.execute(
                select(GraphOutboxModel).where(GraphOutboxModel.event_id == "requeue-outbox-event")
            )
        ).scalar_one()
    assert completed_row.status == "completed"
    assert completed_row.attempts == 1


async def test_operator_requeue_failed_outbox_row_rejects_invalid_requests(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-requeue-invalid-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [_event("run_lifecycle_changed", {"to_state": "active"})],
        )
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        session.add(
            GraphOutboxModel(
                event_id="pending-outbox-event",
                run_id=run_id,
                kind="agent_dispatch",
                payload={"event_id": "pending-outbox-event", "node_id": "worker-1"},
                status="pending",
                attempts=0,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    missing = await client.post(f"/api/runs/{run_id}/graph/outbox/requeue/missing-event")
    non_failed = await client.post(f"/api/runs/{run_id}/graph/outbox/requeue/pending-outbox-event")
    invalid_run = await client.post(
        "/api/runs/invalid%20run/graph/outbox/requeue/pending-outbox-event"
    )
    invalid_event = await client.post(f"/api/runs/{run_id}/graph/outbox/requeue/invalid%20event")

    assert missing.status_code == 404
    assert missing.json()["detail"] == "Outbox row not found"
    assert non_failed.status_code == 409
    assert non_failed.json()["detail"] == "Outbox row is not failed"
    assert invalid_run.status_code == 422
    assert invalid_event.status_code == 422


async def test_requeue_audit_append_translates_stale_position_to_conflict(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    _client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-requeue-stale-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [
                _event("run_lifecycle_changed", {"to_state": "active"}),
                _event("node_created", {"node_id": "worker-1", "kind": "worker"}),
            ],
        )
        audit_event = EventEnvelope(
            event_id=f"outbox-requeued-{uuid4().hex}",
            run_id=run_id,
            position=-1,
            event_type="outbox_requeued",
            schema_version=1,
            actor=Actor(kind=ActorKind.HUMAN, id="human-operator", role="operator"),
            causation_id="stale-outbox-event",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            payload={"event_id": "stale-outbox-event"},
        )

        try:
            await append_requeue_audit_event(
                GraphEventStore(session),
                run_id=run_id,
                current_position=1,
                audit_event=audit_event,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
            assert "stale graph projection" in str(exc.detail)
        else:
            raise AssertionError("expected stale graph projection conflict")


async def test_operator_graph_patch_endpoint_accepts_human_patch(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-operator-patch-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [_event("run_lifecycle_changed", {"to_state": "active"})],
        )
        await session.commit()

    response = await client.post(
        f"/api/runs/{run_id}/graph/patch",
        json={
            "patch_id": "operator-patch-1",
            "ops": [
                {
                    "op": "create_node",
                    "node": {"node_id": "operator-note", "kind": "artifact"},
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["accepted"] is True
    assert any(event["event_type"] == "graph_patch_accepted" for event in body["events"])
    assert any(
        event["event_type"] == "node_created" and event["payload"]["node_id"] == "operator-note"
        for event in body["events"]
    )


async def test_operator_graph_patch_generates_id_only_when_patch_id_is_omitted(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-operator-patch-generated-id-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [_event("run_lifecycle_changed", {"to_state": "active"})],
        )
        await session.commit()

    response = await client.post(
        f"/api/runs/{run_id}/graph/patch",
        json={"ops": []},
    )

    assert response.status_code == 200
    assert response.json()["patch_id"].startswith("operator-patch-")


@pytest.mark.parametrize(
    "payload",
    [
        {"patch_id": "p", "base_graph_position": "0", "ops": []},
        {"patch_id": "p", "base_graph_position": 0, "carryover_summary": "r"},
        {"patch_id": "p", "base_graph_position": 0, "unknown": True},
        {"patch_id": "", "ops": []},
        {"patch_id": "p" * 201, "ops": []},
        {"patch_id": "not a patch id", "ops": []},
        {"rationale_record_id": "", "ops": []},
        {"rationale_record_id": "r" * 201, "ops": []},
        {"rationale_record_id": "not a rationale id", "ops": []},
        {"base_graph_position": -1, "ops": []},
        {"patch_id": "p"},
    ],
)
async def test_operator_graph_patch_rejects_noncanonical_payload_fields(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
    payload: dict[str, object],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-operator-patch-invalid-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [_event("run_lifecycle_changed", {"to_state": "active"})],
        )
        await session.commit()

    response = await client.post(f"/api/runs/{run_id}/graph/patch", json=payload)

    assert response.status_code == 422


async def test_graph_projection_uses_paused_run_row_as_effective_state(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-paused-effective-{uuid4().hex[:8]}"
    await _seed_graph_run(app, run_id)

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        stored = await session.get(RunModel, run_id)
        assert stored is not None
        stored.status = RunStatus.PAUSED
        stored.pause_reason = "graph_blocked"
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph")
    assert response.status_code == 200
    projection = response.json()
    assert projection["event_count"] > 0
    assert projection["run_state"] == "paused"


async def test_graph_projection_recomputes_task_states_from_events(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-fresh-task-states-{uuid4().hex[:8]}"
    await _seed_graph_run(app, run_id)

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        snapshot = await GraphEventStore(session).read_projection_snapshot(run_id)
        assert snapshot is not None
        snapshot.task_states = {"task-1": "stale"}
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph")
    assert response.status_code == 200
    projection = response.json()
    assert projection["task_states"] != {"task-1": "stale"}
    assert "stale" not in projection["task_states"].values()


async def test_active_graph_execution_readback_uses_bounded_summary_paths(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = "graph-active-readback"

    await _seed_graph_run(app, run_id)

    projection_resp = await client.get(f"/api/runs/{run_id}/graph")
    assert projection_resp.status_code == 200
    projection = projection_resp.json()
    active_leases = [
        lease for lease in projection["leases"].values() if lease.get("state") == "active"
    ]
    assert active_leases
    active_node_id = active_leases[0]["node_id"]

    scheduler_resp = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    events_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=summary")
    node_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/{active_node_id}")

    assert scheduler_resp.status_code == 200
    assert events_resp.status_code == 200
    assert node_resp.status_code == 200

    scheduler = scheduler_resp.json()
    assert any(lease["node_id"] == active_node_id for lease in scheduler["leases"]["active"])

    summary_events = events_resp.json()
    assert len(summary_events) == projection["event_count"]
    assert all("routine" not in event["payload"] for event in summary_events)

    node = node_resp.json()
    assert node["node_id"] == active_node_id
    assert node["active_lease"]["state"] == "active"
    assert "routine" not in str(node["events"])


async def test_graph_projection_routes_recreate_deleted_read_models(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = "graph-read-model-api-rebuild"
    await _seed_graph_run(app, run_id)

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await session.execute(
            delete(GraphEventSummaryModel).where(GraphEventSummaryModel.run_id == run_id)
        )
        await session.execute(
            delete(GraphProjectionSnapshotModel).where(
                GraphProjectionSnapshotModel.run_id == run_id
            )
        )
        await session.commit()

    projection_resp = await client.get(f"/api/runs/{run_id}/graph")
    scheduler_resp = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    decisions_resp = await client.get(f"/api/runs/{run_id}/graph/decisions")

    assert projection_resp.status_code == 200
    assert scheduler_resp.status_code == 200
    assert decisions_resp.status_code == 200
    assert projection_resp.json()["event_count"] > 0
    assert scheduler_resp.json()["event_count"] == projection_resp.json()["event_count"]
    assert decisions_resp.json()["event_count"] == projection_resp.json()["event_count"]

    async with session_factory() as session:
        summary_count = await session.scalar(
            select(func.count())
            .select_from(GraphEventSummaryModel)
            .where(GraphEventSummaryModel.run_id == run_id)
        )
        snapshot_count = await session.scalar(
            select(func.count())
            .select_from(GraphProjectionSnapshotModel)
            .where(GraphProjectionSnapshotModel.run_id == run_id)
        )

    assert summary_count == projection_resp.json()["event_count"]
    assert snapshot_count == 1


async def test_node_detail_returns_inputs_outputs_filestate_callbacks(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = "graph-node-detail-cycle"
    await _seed_worker_verifier_cycle(app, run_id)

    events_resp = await client.get(f"/api/runs/{run_id}/graph/events")
    assert events_resp.status_code == 200
    events = events_resp.json()
    worker_node = next(
        event["payload"]["node_id"]
        for event in events
        if event["event_type"] == "node_created" and event["payload"].get("kind") == "worker"
    )
    verifier_node = next(
        event["payload"]["node_id"]
        for event in events
        if event["event_type"] == "node_created" and event["payload"].get("kind") == "verifier"
    )

    summary_worker_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/{worker_node}")
    assert summary_worker_resp.status_code == 200
    summary_worker = summary_worker_resp.json()
    assert summary_worker["kind"] == "worker"
    assert summary_worker["output_records"]
    assert summary_worker["output_records"][0]["record_id"]
    assert summary_worker["output_records"][0]["port"]
    assert "value" not in summary_worker["output_records"][0]
    assert summary_worker["file_state_records"]
    assert summary_worker["file_state_records"][0]["classification_summary"]["total_paths"] == 0

    summary_verifier_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/{verifier_node}")
    assert summary_verifier_resp.status_code == 200
    summary_verifier = summary_verifier_resp.json()
    assert summary_verifier["input_ports"]["candidate_under_test"] == [
        summary_worker["output_records"][0]["record_id"]
    ]

    worker_resp = await client.get(
        f"/api/runs/{run_id}/graph/nodes/{worker_node}?payload_mode=full"
    )
    assert worker_resp.status_code == 200
    worker = worker_resp.json()
    assert worker["kind"] == "worker"
    assert worker["role"] == "builder"
    assert worker["output_records"]
    assert any(record["record_kind"] == "output" for record in worker["output_records"])
    assert worker["file_state_records"]
    file_state = worker["file_state_records"][0]
    assert file_state["verdict"] == "captured"
    assert file_state["classification_summary"]["total_paths"] == 2
    assert file_state["classification_summary"]["classifications"]["test_artifact"] == 1
    assert worker["active_lease"]["state"] == "released"
    worker_callback_types = [event["event_type"] for event in worker["callback_history"]]
    assert worker_callback_types == ["node_state_changed", "callback_accepted"]
    assert [event["position"] for event in worker["callback_history"]] == sorted(
        event["position"] for event in worker["callback_history"]
    )

    verifier_resp = await client.get(
        f"/api/runs/{run_id}/graph/nodes/{verifier_node}?payload_mode=full"
    )
    assert verifier_resp.status_code == 200
    verifier = verifier_resp.json()
    assert verifier["kind"] == "verifier"
    assert verifier["input_ports"]["candidate_under_test"] == [
        worker["output_records"][0]["record_id"]
    ]
    assert verifier["output_records"]
    assert verifier["output_records"][0]["record_kind"] == "verification"
    verifier_callback_types = [event["event_type"] for event in verifier["callback_history"]]
    assert verifier_callback_types == ["node_state_changed", "callback_accepted"]


async def test_full_node_detail_hydrates_only_target_node_event_rows(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-node-detail-noisy-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)

    events = [
        _event("run_lifecycle_changed", {"to_state": "active"}),
        _event(
            "node_created",
            {
                "node_id": "planner-s-01",
                "kind": "planner",
                "role": "planner",
                "state": "completed",
                "task_region_id": "implementation",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "plan-1",
                "record_kind": "output",
                "producer_node_id": "planner-s-01",
                "port": "plan",
                "schema": "PlannerPacket",
                "value": {"body": "target planner body"},
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "worker-s-01-t-01",
                "kind": "worker",
                "role": "builder",
                "state": "completed",
                "task_region_id": "implementation",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "verifier-corrective-graph-health",
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
                "task_region_id": "corrective",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "check-final-invariant-graph-health",
                "kind": "check",
                "role": "final_check",
                "state": "ready",
                "task_region_id": "final-invariant",
            },
        ),
        _event(
            "node_created",
            {
                "node_id": "noise-worker",
                "kind": "worker",
                "role": "builder",
                "state": "completed",
                "task_region_id": "noise",
            },
        ),
        *[
            _event(
                "output_record_accepted",
                {
                    "record_id": f"noise-{index}",
                    "record_kind": "output",
                    "producer_node_id": "noise-worker",
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "value": {"body": "x" * 4096, "index": index},
                },
            )
            for index in range(40)
        ],
    ]

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()

    async with session_factory() as session:
        noise_position = await session.scalar(
            select(EventV2Model.version)
            .where(EventV2Model.aggregate_id == f"graph:{run_id}")
            .where(EventV2Model.event_type == "output_record_accepted")
            .where(EventV2Model.version > 3)
            .order_by(EventV2Model.version)
            .limit(1)
        )
        assert noise_position is not None
        await session.execute(
            update(EventV2Model)
            .where(EventV2Model.aggregate_id == f"graph:{run_id}")
            .where(EventV2Model.version == noise_position)
            .values(payload="{not-json")
        )
        await session.commit()

    summary_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/planner-s-01")
    assert summary_resp.status_code == 200

    full_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/planner-s-01?payload_mode=full")
    assert full_resp.status_code == 200
    full = full_resp.json()
    assert full["output_records"][0]["value"]["body"] == "target planner body"
    assert all(record["producer_node_id"] == "planner-s-01" for record in full["output_records"])
    assert all(
        event["payload"].get("producer_node_id", "planner-s-01") == "planner-s-01"
        for event in full["events"]
    )
    assert all("value" not in event["payload"] for event in full["events"])


async def test_fresh_control_and_topology_readbacks_preserve_runtime_controls(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-control-topology-{uuid4().hex[:8]}"
    await _seed_control_topology_graph_run(app, run_id)

    node_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/worker-control")
    full_node_resp = await client.get(
        f"/api/runs/{run_id}/graph/nodes/worker-control?payload_mode=full"
    )
    topology_resp = await client.get(f"/api/runs/{run_id}/graph/topology")
    events_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")

    assert node_resp.status_code == 200
    assert full_node_resp.status_code == 200
    assert topology_resp.status_code == 200
    assert events_resp.status_code == 200

    node = node_resp.json()
    full_node = full_node_resp.json()
    expected_controls = {
        "resource_claims": [{"mode": "write", "scope": "paths", "paths": ["src/"]}],
        "allowed_actions": ["submit", "record_heartbeat"],
        "preconditions": ["candidate_bound", "no_active_conflicts"],
        "command_definition": {
            "id": "worker-command",
            "cmd": "uv run pytest tests/unit/test_graph_scheduler_view.py -q",
            "source": "test",
        },
    }
    for key, expected in expected_controls.items():
        assert node[key] == expected
        assert full_node[key] == expected

    topology = topology_resp.json()
    assert topology["event_count"] == len(events_resp.json()) == 7
    edge = next(edge for edge in topology["edges"] if edge["edge_id"] == "edge-control-candidate")
    assert edge["metadata"] == {
        "binding_policy": "bind_latest",
        "freshness_policy": "latest_only",
        "prompt_hydration_policy": "artifact_reference",
        "metadata": {"purpose": "verify bound candidate"},
    }
    assert edge["binding"] == {
        "edge_id": "edge-control-candidate",
        "to_node_id": "verifier-control",
        "to_port": "candidate_under_test",
        "record_ids": ["candidate-control"],
        "bound_at_position": 7,
        "record_bound_positions": {"candidate-control": 7},
        "binding_policy": "bind_latest",
        "trigger": "record_accepted",
    }
    assert edge["bound_records"] == [
        {
            "record_id": "candidate-control",
            "record_type": "candidate",
            "record_kind": "output",
            "schema": "ImplementationCandidate",
            "producer_node_id": "worker-control",
            "producer_port": "candidate",
            "position": 6,
        }
    ]


async def test_callback_lifecycle_readbacks_cover_heartbeat_cancel_artifact_and_failure(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-callback-lifecycle-{uuid4().hex[:8]}"
    await _seed_callback_lifecycle_graph_run(app, run_id)

    graph_resp = await client.get(f"/api/runs/{run_id}/graph")
    scheduler_resp = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    node_resp = await client.get(
        f"/api/runs/{run_id}/graph/nodes/worker-callback?payload_mode=full"
    )
    events_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")

    assert graph_resp.status_code == 200
    assert scheduler_resp.status_code == 200
    assert node_resp.status_code == 200
    assert events_resp.status_code == 200

    graph = graph_resp.json()
    scheduler = scheduler_resp.json()
    node = node_resp.json()
    events = events_resp.json()
    event_types = [event["event_type"] for event in events]

    assert graph["run_state"] == "cancelling"
    assert graph["node_states"]["worker-callback"] == "cancelled"
    assert graph["leases"]["lease-callback"]["state"] == "revoked"
    assert graph["leases"]["lease-callback"]["expires_at"] == "2026-01-01T00:02:00+00:00"
    assert scheduler["leases"] == {"active": [], "suspended": []}
    assert scheduler["scheduler"] == {
        "ready": [],
        "blocked": [],
        "waiting_resources": [],
        "waiting_gates": [],
    }

    assert "heartbeat_recorded" in event_types
    assert "lease_renewed" in event_types
    assert "lease_revoked" in event_types
    assert any(record["record_type"] == "artifact_reference" for record in node["output_records"])
    assert any(record["record_type"] == "failure_record" for record in node["output_records"])
    callback_events = [event["event_type"] for event in node["callback_history"]]
    assert callback_events == []
    node_event_types = [event["event_type"] for event in node["events"]]
    assert "heartbeat_recorded" in node_event_types
    assert "lease_revoked" in node_event_types


async def test_patch_attempt_readback_surfaces_rejected_patch_diagnostics(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-patch-probe-{uuid4().hex[:8]}"
    await _seed_rejected_patch_graph_run(app, run_id)

    patches_resp = await client.get(f"/api/runs/{run_id}/graph/patches")
    events_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=full")

    assert patches_resp.status_code == 200
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert [event["event_type"] for event in events] == ["graph_patch_rejected"]

    body = patches_resp.json()
    assert body["run_id"] == run_id
    assert body["current_graph_position"] == 1
    assert len(body["attempts"]) == 1
    attempt = body["attempts"][0]
    assert attempt["patch_id"] == "patch-bad-request"
    assert attempt["proposed_by_node_id"] == "planner-1"
    assert attempt["base_graph_position"] is None
    assert attempt["current_graph_position"] == 1
    assert attempt["status"] == "rejected"
    assert attempt["rejected_event_id"] == events[0]["event_id"]
    assert attempt["rejected_position"] == 1
    assert attempt["created_node_ids"] == []
    assert attempt["created_edge_ids"] == []
    assert attempt["diagnostics"]["actor_role"] == "planner"
    assert events[0]["payload"]["base_graph_position"] == -1
    assert "invalid_request_record" in attempt["rejection_reason"]
    assert "payload [value_error]" in attempt["rejection_reason"]


async def test_node_detail_404_for_unknown_node(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = "graph-node-detail-404"
    await _seed_graph_run(app, run_id)

    response = await client.get(f"/api/runs/{run_id}/graph/nodes/nonexistent")
    assert response.status_code == 404


async def test_is_graph_backed_flag_in_run_response(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture

    run_id = "graph-backed-flag"
    await _seed_graph_run(app, run_id)

    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["is_graph_backed"] is True

    list_response = await client.get("/api/runs")
    assert list_response.status_code == 200
    runs = list_response.json()["runs"]
    run_entry = next(run for run in runs if run["id"] == run_id)
    assert run_entry["is_graph_backed"] is True


async def test_is_graph_backed_false_for_legacy_run(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"legacy-run-{uuid4().hex[:8]}"
    run = create_run_from_routine(
        _routine(),
        repo_name="graph-api-legacy-repo",
        source_branch="main",
    )
    run.id = run_id
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await save_run(session, run)
        await session.commit()
    response = await client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["is_graph_backed"] is False

    list_response = await client.get("/api/runs")
    assert list_response.status_code == 200
    runs = list_response.json()["runs"]
    run_entry = next(run for run in runs if run["id"] == run_id)
    assert run_entry["is_graph_backed"] is False


async def test_legacy_run_with_workflow_events_is_not_graph_backed(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    """Production legacy runs have workflow events in events_v2 under
    aggregate_id == run_id. Those rows must not 500 the graph projection
    endpoint nor mark the run graph-backed (regression: dogfood run r220)."""
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"legacy-evented-{uuid4().hex[:8]}"
    run = create_run_from_routine(
        _routine(),
        repo_name="graph-api-legacy-repo",
        source_branch="main",
    )
    run.id = run_id
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await save_run(session, run)
        # Simulate the legacy workflow event stream for this run.
        session.add(
            EventV2Model(
                aggregate_id=run_id,
                version=1,
                event_type="run_created",
                payload='{"timestamp": "2026-06-12T00:00:00Z", "run_id": "%s"}' % run_id,
                timestamp="2026-06-12T00:00:00Z",
            )
        )
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph")
    assert response.status_code == 200
    projection = response.json()
    assert projection["event_count"] == 0
    assert projection["run_state"] is None
    assert projection["node_states"] == {}

    detail = await client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["is_graph_backed"] is False

    list_response = await client.get("/api/runs")
    runs = list_response.json()["runs"]
    run_entry = next(run for run in runs if run["id"] == run_id)
    assert run_entry["is_graph_backed"] is False


async def test_graph_events_from_position(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture

    run_id = "graph-events-position"
    await _seed_graph_run(app, run_id)

    response = await client.get(f"/api/runs/{run_id}/graph/events?from_position=2")
    assert response.status_code == 200
    events = response.json()

    # Ensure the endpoint enforces floor-position filtering and ordering.
    assert all(event["position"] >= 2 for event in events)
    assert events == sorted(events, key=lambda item: item["position"])
