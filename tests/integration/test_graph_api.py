"""Integration tests for graph compatibility projection endpoints."""

import json

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from orchestrator.api import build_expired_lease_rows
from orchestrator.config import RunStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.db import (
    EventV2Model,
    GraphEventSummaryModel,
    GraphNodeDetailSummaryCheckpointModel,
    GraphNodeDetailSummaryModel,
    GraphOutboxModel,
    GraphProjectionSnapshotModel,
    RunModel,
)
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    IdGenerator,
    PatchCommandContext,
    output_record_payloads_view,
)
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

pytestmark = pytest.mark.slow


def test_expired_lease_health_uses_latest_generation_for_each_node() -> None:
    leases = {
        "expired-old": {
            "node_id": "node-1",
            "execution_id": "execution-old",
            "generation": 1,
            "state": "expired",
        },
        "active-new": {
            "node_id": "node-1",
            "execution_id": "execution-new",
            "generation": 2,
            "state": "active",
        },
        "expired-current": {
            "node_id": "node-2",
            "execution_id": "execution-current",
            "generation": 3,
            "state": "expired",
        },
    }

    rows = build_expired_lease_rows(leases, {"node-2": "lease_expired_without_callback"})

    assert [row.model_dump() for row in rows] == [
        {
            "lease_id": "expired-current",
            "node_id": "node-2",
            "reason": "lease_expired_without_callback",
        }
    ]


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
                            "requirements": [
                                {
                                    "id": "req-1",
                                    "desc": "The implementation is correct.",
                                }
                            ],
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
    requirement_id = next(
        record.value.id
        for record in output_record_payloads_view(await controller.read_projection(run_id)).values()
        if record.record_type == "requirement_record"
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
            "complete_node": False,
            "payload": {
                "payload_hash": f"hash-{worker_node}",
                "output_records": [
                    {
                        "record_id": candidate_id,
                        "record_kind": "output",
                        "record_type": "candidate",
                        "producer_node_id": worker_node,
                        "port": "candidate",
                        "schema": "ImplementationCandidate",
                        "candidate_id": candidate_id,
                        "task_region_id": task_region_id,
                        "attempt_number": attempt_number,
                        "value": {"summary": "worker output"},
                    },
                ],
            },
        },
    )
    async with session_factory() as session:
        stored_events = await GraphEventStore(session).append_events(
            run_id,
            completed_worker.projection_position,
            [
                _event(
                    "file_state_accepted",
                    {
                        "record_id": f"fs-{worker_node}",
                        "record_kind": "file_state",
                        "record_type": "file_state",
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
                ),
                _event(
                    "node_state_changed",
                    {
                        "node_id": worker_node,
                        "new_state": "completed",
                        "trigger": "callback_accepted",
                    },
                ),
                _event("lease_released", {"lease_id": worker_lease.payload["lease_id"]}),
            ],
        )
        await session.commit()
    scheduled_verifier = await controller.handle_command(
        run_id,
        stored_events[-1].position,
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
                        "record_type": "verification_report",
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
                                    "requirement_id": requirement_id,
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
    health = response.json()
    assert health["run_id"] == run_id
    assert health["event_count"] == 0
    assert health["status"] == "empty"
    assert health["health_status"] == health["facts_status"] == "complete"
    assert health["unavailable_checks"] == []
    assert all(value == 0 for value in health["counts"].values())
    assert health["detail_meta"] == {}


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
                "value": {
                    "outcome": "passed",
                    "grades": [{"requirement_id": "req-1", "grade": "A", "reason": "met"}],
                },
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
                    "outcome": "failed",
                    "grades": [{"requirement_id": "req-2", "grade": "C", "reason": "not met"}],
                },
            },
        ),
        _event(
            "graph_patch_accepted",
            {
                "patch_id": "patch-accepted",
                "actor_role": "planner",
                "proposed_by_node_id": "planner-1",
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
    assert health["health_status"] == health["facts_status"] == "partial"
    assert health["counts"]["patches_accepted"] == 1
    assert health["counts"]["patches_rejected"] == 1
    assert health["counts"]["verifier_passed"] == 1
    assert health["counts"]["verifier_failed"] == 1
    assert health["counts"]["expired_leases"] is None
    assert "expired_leases" in health["unavailable_checks"]
    assert health["failed_nodes"] == []
    assert health["expired_leases"] == []
    assert health["blockers"] == []
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
    assert health["pending_gates"] == []
    assert health["review_blockers"] == []
    assert len(response.content) < 4_000


@pytest.mark.parametrize(
    "candidate_id",
    [
        pytest.param("candidate-" + ("x" * 1_000), id="ascii-over-budget"),
        pytest.param("候" * 100, id="utf8-over-budget"),
    ],
)
async def test_graph_health_compacts_over_budget_candidate_identities(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
    candidate_id: str,
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-health-candidate-id-{uuid4().hex[:8]}"
    candidate_sha256 = sha256(candidate_id.encode()).hexdigest()
    compact_candidate_id = f"sha256:{candidate_sha256}"
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [
                _event(
                    "verification_passed",
                    {
                        "verifier_node_id": "verifier-1",
                        "candidate_id": candidate_id,
                        "task_region_id": "step-1/task-1",
                        "record_id": "verification-1",
                    },
                )
            ],
        )
        await session.commit()
        live_summary = (
            await session.execute(
                select(GraphEventSummaryModel.payload).where(
                    GraphEventSummaryModel.run_id == run_id
                )
            )
        ).scalar_one()
        assert live_summary["candidate_id"] == compact_candidate_id
        assert live_summary["candidate_id_hashed"] is True
        assert live_summary["candidate_id_original_chars"] == len(candidate_id)
        assert live_summary["candidate_id_original_bytes"] == len(candidate_id.encode())
        assert live_summary["candidate_id_sha256"] == candidate_sha256
        assert candidate_id not in json.dumps(live_summary)

        await session.execute(
            delete(GraphEventSummaryModel).where(GraphEventSummaryModel.run_id == run_id)
        )
        await GraphEventStore(session).ensure_event_summaries(run_id)
        await session.commit()
        rebuilt_summary = (
            await session.execute(
                select(GraphEventSummaryModel.payload).where(
                    GraphEventSummaryModel.run_id == run_id
                )
            )
        ).scalar_one()
        assert rebuilt_summary == live_summary

    response = await client.get(f"/api/runs/{run_id}/graph/health")

    assert response.status_code == 200
    assert response.json()["verifier"] == {
        "passed": 1,
        "failed": 0,
        "recent": [
            {
                "node_id": "verifier-1",
                "candidate_id": compact_candidate_id,
                "candidate_id_hashed": True,
                "candidate_id_original_chars": len(candidate_id),
                "candidate_id_original_bytes": len(candidate_id.encode()),
                "candidate_id_sha256": candidate_sha256,
                "verdict": "passed",
            }
        ],
    }
    assert candidate_id not in response.text


async def test_graph_summary_event_preserves_compact_candidate_identity_metadata(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-summary-candidate-{uuid4().hex[:8]}"
    candidate_id = "candidate-" + ("候" * 1_000)
    candidate_sha256 = sha256(candidate_id.encode()).hexdigest()
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [
                _event(
                    "verification_passed",
                    {
                        "verifier_node_id": "verifier-1",
                        "candidate_id": candidate_id,
                        "task_region_id": "step-1/task-1",
                        "record_id": "verification-1",
                    },
                )
            ],
        )
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=summary")

    assert response.status_code == 200
    payload = response.json()[0]["payload"]
    assert payload["candidate_id"] == f"sha256:{candidate_sha256}"
    assert payload["candidate_id_hashed"] is True
    assert payload["candidate_id_original_chars"] == len(candidate_id)
    assert payload["candidate_id_original_bytes"] == len(candidate_id.encode())
    assert payload["candidate_id_sha256"] == candidate_sha256
    assert candidate_id not in response.text


async def test_graph_summary_event_keeps_persisted_depth_bounded_payload_opaque(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-summary-opaque-{uuid4().hex[:8]}"
    nested_evidence = {
        "level-1": {
            "level-2": {
                "level-3": {"entries": {f"entry-{index:02d}": index for index in range(33)}}
            }
        }
    }
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [
                _event(
                    "verification_passed",
                    {
                        "verifier_node_id": "verifier-opaque",
                        "candidate_id": "candidate-opaque",
                        "task_region_id": "step-1/task-1",
                        "record_id": "verification-opaque",
                        "evidence": [nested_evidence],
                    },
                )
            ],
        )
        await session.commit()
        persisted = (
            await session.execute(
                select(GraphEventSummaryModel.payload).where(
                    GraphEventSummaryModel.run_id == run_id
                )
            )
        ).scalar_one()
    expected = {key: value for key, value in persisted.items() if key != "_graph_read_contract"}

    response = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=summary")

    assert response.status_code == 200
    assert response.json()[0]["payload"] == expected


async def test_graph_health_keeps_hashed_and_literal_candidate_identities_distinct(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-health-candidate-namespace-{uuid4().hex[:8]}"
    long_candidate_id = "candidate-" + ("x" * 1_000)
    candidate_sha256 = sha256(long_candidate_id.encode()).hexdigest()
    compact_candidate_id = f"sha256:{candidate_sha256}"
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [
                _event(
                    "verification_passed",
                    {
                        "verifier_node_id": "verifier-1",
                        "candidate_id": long_candidate_id,
                        "task_region_id": "step-1/task-1",
                        "record_id": "verification-long",
                    },
                ),
                _event(
                    "verification_failed",
                    {
                        "verifier_node_id": "verifier-1",
                        "candidate_id": compact_candidate_id,
                        "task_region_id": "step-1/task-1",
                        "record_id": "verification-literal",
                    },
                ),
            ],
        )
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph/health")

    assert response.status_code == 200
    health = response.json()
    assert health["counts"]["verifier_passed"] == 1
    assert health["counts"]["verifier_failed"] == 1
    assert health["verifier"] == {
        "passed": 1,
        "failed": 1,
        "recent": [
            {
                "node_id": "verifier-1",
                "candidate_id": compact_candidate_id,
                "candidate_id_hashed": True,
                "candidate_id_original_chars": len(long_candidate_id),
                "candidate_id_original_bytes": len(long_candidate_id.encode()),
                "candidate_id_sha256": candidate_sha256,
                "verdict": "passed",
            },
            {
                "node_id": "verifier-1",
                "candidate_id": compact_candidate_id,
                "verdict": "failed",
            },
        ],
    }


async def test_graph_health_rejects_complete_legacy_summary_with_raw_over_budget_candidate(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-health-legacy-candidate-{uuid4().hex[:8]}"
    candidate_id = "candidate-" + ("x" * 1_000)
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [
                _event(
                    "verification_passed",
                    {
                        "verifier_node_id": "verifier-1",
                        "candidate_id": candidate_id,
                        "task_region_id": "step-1/task-1",
                        "record_id": "verification-1",
                    },
                )
            ],
        )
        await session.execute(
            update(GraphEventSummaryModel)
            .where(GraphEventSummaryModel.run_id == run_id)
            .values(
                payload={
                    "verifier_node_id": "verifier-1",
                    "candidate_id": candidate_id,
                    "task_region_id": "step-1/task-1",
                    "record_id": "verification-1",
                }
            )
        )
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph/health")

    assert response.status_code == 200
    health = response.json()
    assert health["health_status"] == health["facts_status"] == "unavailable"
    assert health["counts"]["verifier_passed"] is None
    assert candidate_id not in response.text


async def test_graph_health_reads_only_bounded_compact_details(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-health-bounded-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(
            run_id,
            0,
            [
                _event("graph_patch_accepted", {"patch_id": f"patch-{index:03d}"})
                for index in range(25)
            ],
        )
        await session.commit()

    statements: list[str] = []

    def capture(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: Any,
    ) -> None:
        statements.append(statement.lower())

    engine = app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = await client.get(f"/api/runs/{run_id}/graph/health")
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert response.status_code == 200
    health = response.json()
    assert health["counts"]["patches_accepted"] == 25
    assert len(health["recent_patch_decisions"]) == 20
    assert health["detail_meta"]["recent_patch_decisions"] == {"total": 25, "truncated": True}
    assert [row["patch_id"] for row in health["recent_patch_decisions"]] == [
        f"patch-{index:03d}" for index in range(5, 25)
    ]
    event_reads = [statement for statement in statements if "events_v2" in statement]
    assert event_reads
    assert all("payload" not in statement for statement in event_reads)
    assert not any("graph_projection_snapshots" in statement for statement in statements)

    async with session_factory() as session:
        await session.execute(
            delete(GraphEventSummaryModel).where(GraphEventSummaryModel.run_id == run_id)
        )
        await session.commit()
    stale = await client.get(f"/api/runs/{run_id}/graph/health")
    assert stale.status_code == 200
    stale_health = stale.json()
    assert stale_health["health_status"] == stale_health["facts_status"] == "unavailable"
    assert stale_health["counts"]["patches_accepted"] is None
    assert "compact_event_summaries" in stale_health["unavailable_checks"]


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


async def test_archival_graph_views_page_over_cap_through_http(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    """Topology, blockers, and regions remain complete beyond one API page."""
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-archival-pages-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    events = [
        _event(
            "node_created",
            {
                "node_id": f"check-{index:03d}",
                "kind": "check",
                "role": "check",
                "state": "planned",
                "task_region_id": f"region-{index:03d}",
            },
        )
        for index in range(101)
    ]
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        await GraphEventStore(session).append_events(run_id, 0, events)
        await session.commit()

    for path, collection in (
        ("topology", "nodes"),
        ("final-blockers", "blockers"),
        ("regions", "regions"),
    ):
        first = await client.get(f"/api/runs/{run_id}/graph/{path}")
        assert first.status_code == 200
        first_body = first.json()
        assert len(first.content) <= 262_144
        assert len(first_body[collection]) == 100
        assert first_body["truncated"] is True
        assert first_body["total_known"] > 100
        cursor = first_body["next_cursor"]
        assert cursor is not None

        received = len(first_body[collection])
        while cursor is not None:
            next_page = await client.get(f"/api/runs/{run_id}/graph/{path}?cursor={cursor}")
            assert next_page.status_code == 200
            next_body = next_page.json()
            assert len(next_page.content) <= 262_144
            assert next_body["total_known"] == first_body["total_known"]
            assert next_body[collection]
            received += len(next_body[collection])
            cursor = next_body["next_cursor"]
        assert received == first_body["total_known"]


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


async def test_graph_final_blocker_outbox_cursor_keeps_the_boundary_row(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-failed-outbox-pages-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        async with session.begin():
            session.add_all(
                [
                    GraphOutboxModel(
                        event_id=f"failed-outbox-{index:03d}",
                        run_id=run_id,
                        kind="agent_dispatch",
                        payload={"event_id": f"failed-outbox-{index:03d}"},
                        status="failed",
                        attempts=1,
                        created_at=now,
                        updated_at=now,
                        next_attempt_at=None,
                        last_error="failed",
                    )
                    for index in range(101)
                ]
            )

    first = await client.get(f"/api/runs/{run_id}/graph/final-blockers")
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["blockers"]) == 100
    cursor = first_body["next_cursor"]
    assert isinstance(cursor, str) and cursor.startswith("outbox:")

    second = await client.get(f"/api/runs/{run_id}/graph/final-blockers?cursor={cursor}")
    assert second.status_code == 200
    second_body = second.json()
    assert [blocker["outbox_event_id"] for blocker in second_body["blockers"]] == [
        "failed-outbox-100"
    ]
    assert second_body["next_cursor"] is None


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


async def test_graph_projection_uses_current_snapshot_task_states(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-fresh-task-states-{uuid4().hex[:8]}"
    await _seed_graph_run(app, run_id)

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        snapshot = await GraphEventStore(session).read_projection_snapshot(run_id)
        assert snapshot is not None
        snapshot.task_states = {"task-1": "snapshot-value"}
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph")
    assert response.status_code == 200
    projection = response.json()
    assert projection["task_states"] == {"task-1": "snapshot-value"}


async def test_graph_projection_uses_snapshot_without_replaying_large_history(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-snapshot-read-{uuid4().hex[:8]}"
    await _seed_graph_run(app, run_id)

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        store = GraphEventStore(session)
        position = await store.current_position(run_id)
        history = [_event("run_lifecycle_changed", {"to_state": "active"}) for _ in range(1_000)]
        await store.append_events(run_id, position, history)
        snapshot = await session.get(GraphProjectionSnapshotModel, run_id)
        assert snapshot is not None
        expected_task_states = {"task-z": "blocked", "task-a": "ready"}
        snapshot.task_states = expected_task_states
        await session.commit()

    statements: list[str] = []

    def capture_statements(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: Any,
    ) -> None:
        normalized = statement.lower()
        if "events_v2" in normalized and "select" in normalized:
            statements.append(normalized)

    engine = app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture_statements)
    try:
        response = await client.get(f"/api/runs/{run_id}/graph")
    finally:
        event.remove(engine, "before_cursor_execute", capture_statements)

    assert response.status_code == 200
    body = response.json()
    assert body["task_states"] == expected_task_states
    assert list(body["task_states"]) == list(expected_task_states)
    assert statements
    assert all("max(" in statement for statement in statements)
    assert not any("json_extract" in statement for statement in statements)
    assert not any("order by" in statement for statement in statements)

    empty_run_id = f"graph-empty-read-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, empty_run_id)
    empty_response = await client.get(f"/api/runs/{empty_run_id}/graph")
    assert empty_response.status_code == 200
    assert empty_response.json()["task_states"] == {}


async def _seed_rebuilt_human_gate_read_models(
    app: Any,
    run_id: str,
    *,
    count: int,
    aggregate_pressure: bool = False,
    options: list[str] | None = None,
) -> None:
    await _save_manual_graph_run(app, run_id)
    events = []
    for index in reversed(range(count)):
        payload: dict[str, Any] = {
            "node_id": f"gate-{index:03d}",
            "kind": "human_gate",
            "role": "approval",
            "state": "blocked",
            "gate_type": "human_approval",
            "prompt": (
                f"prompt-{index:03d}-" + ("p" * 4_080) if aggregate_pressure else f"Approve {index}"
            ),
            "blocker": (
                f"blocker-{index:03d}-" + ("b" * 4_080) if aggregate_pressure else "human approval"
            ),
        }
        if aggregate_pressure or (options is not None and index == 0):
            payload["decision_request"] = {
                "decision_type": "approval",
                "options": options if options is not None and index == 0 else ["approve"],
                "default_option": "option-000" if options is not None and index == 0 else "approve",
                "consequence_summary": (
                    f"consequence-{index:03d}-" + ("c" * 4_075)
                    if aggregate_pressure
                    else "Choose one option."
                ),
            }
        events.append(_event("node_created", payload))

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        graph_store = GraphEventStore(session)
        await graph_store.append_events(run_id, 0, events)
        await graph_store.delete_read_models(run_id)
        await graph_store.rebuild_read_models(run_id)
        await session.commit()


async def test_decision_route_cursor_uses_aggregate_pressure_field_prefix(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-gate-pressure-cursor-{uuid4().hex[:8]}"
    await _seed_rebuilt_human_gate_read_models(
        app,
        run_id,
        count=60,
        aggregate_pressure=True,
    )

    response = await client.get(f"/api/runs/{run_id}/graph/decisions")

    assert response.status_code == 200
    body = response.json()
    assert [gate["node_id"] for gate in body["pending_gates"]] == [
        f"gate-{index:03d}" for index in range(30)
    ]
    assert body["truncated"] is True
    assert body["next_cursor"] == "gate-029"
    decisions_meta = body["collection_meta"]["decisions"]
    assert decisions_meta["next_cursor"] == "gate-029"
    assert decisions_meta["fields"]["pending_gates"]["next_cursor"] == "gate-029"


async def test_gate_routes_use_count_capped_field_prefix_cursors(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-gate-count-cursor-{uuid4().hex[:8]}"
    await _seed_rebuilt_human_gate_read_models(app, run_id, count=101)

    scheduler_response = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    decision_response = await client.get(f"/api/runs/{run_id}/graph/decisions")

    assert scheduler_response.status_code == 200
    scheduler = scheduler_response.json()
    assert len(scheduler["scheduler"]["blocked"]) == 100
    assert scheduler["next_cursor"] == "gate-099"
    scheduler_meta = scheduler["collection_meta"]["scheduler"]
    assert scheduler_meta["next_cursor"] == "gate-099"
    assert scheduler_meta["fields"]["blocked"]["next_cursor"] == "gate-099"

    assert decision_response.status_code == 200
    decisions = decision_response.json()
    assert len(decisions["pending_gates"]) == 100
    assert decisions["next_cursor"] == "gate-099"
    decisions_meta = decisions["collection_meta"]["decisions"]
    assert decisions_meta["next_cursor"] == "gate-099"
    assert decisions_meta["fields"]["pending_gates"]["next_cursor"] == "gate-099"


async def test_decision_route_attributes_nested_options_metadata_to_gate_identity(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-gate-options-cursor-{uuid4().hex[:8]}"
    await _seed_rebuilt_human_gate_read_models(
        app,
        run_id,
        count=1,
        options=[f"option-{index:03d}" for index in reversed(range(51))],
    )

    response = await client.get(f"/api/runs/{run_id}/graph/decisions")

    assert response.status_code == 200
    body = response.json()
    assert body["pending_gates"][0]["options"] == [f"option-{index:03d}" for index in range(50)]
    assert body["next_cursor"] == "option-049"
    options_meta = body["collection_meta"]["decisions"]["fields"]["pending_gates.gate-000.options"]
    assert options_meta["owner"] == "decisions.pending_gates.gate-000.options"
    assert options_meta["total_known"] == 51
    assert options_meta["next_cursor"] == "option-049"


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
    assert all("routine" not in event["payload"] for event in node["events"])


async def test_graph_projection_routes_report_deleted_read_models_unavailable(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = "graph-read-model-api-rebuild"
    await _seed_graph_run(app, run_id)

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        current_position = await GraphEventStore(session).current_position(run_id)
        await session.execute(
            delete(GraphEventSummaryModel).where(GraphEventSummaryModel.run_id == run_id)
        )
        await session.execute(
            delete(GraphProjectionSnapshotModel).where(
                GraphProjectionSnapshotModel.run_id == run_id
            )
        )
        await session.commit()

    scheduler_resp = await client.get(f"/api/runs/{run_id}/graph/scheduler")
    decisions_resp = await client.get(f"/api/runs/{run_id}/graph/decisions")
    projection_resp = await client.get(f"/api/runs/{run_id}/graph")
    summary_events_resp = await client.get(f"/api/runs/{run_id}/graph/events?payload_mode=summary")

    for response, read_model in (
        (scheduler_resp, "graph_projection_snapshot"),
        (decisions_resp, "graph_projection_snapshot"),
        (projection_resp, "graph_projection_snapshot"),
        (summary_events_resp, "graph_event_summaries"),
    ):
        assert response.status_code == 503
        assert response.json()["detail"] == {
            "code": "read_model_unavailable",
            "run_id": run_id,
            "read_model": read_model,
            "current_position": current_position,
            "reason": "missing_or_stale",
            "retryable": True,
        }

    async with session_factory() as session:
        assert await session.get(GraphProjectionSnapshotModel, run_id) is None
        count = await session.scalar(
            select(func.count())
            .select_from(GraphEventSummaryModel)
            .where(GraphEventSummaryModel.run_id == run_id)
        )
        assert count == 0


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
                "record_type": "analysis_summary",
                "producer_node_id": "planner-s-01",
                "port": "planning_summary",
                "schema": "AnalysisSummary",
                "value": {
                    "summary": "target planner body",
                    "source_record_ids": [],
                    "lossy": False,
                    "omitted_details": [],
                },
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
                    "record_type": "candidate",
                    "producer_node_id": "noise-worker",
                    "port": "candidate",
                    "schema": "ImplementationCandidate",
                    "candidate_id": f"noise-{index}",
                    "value": {"summary": "x" * 4096},
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
    assert full["output_records"][0]["value"]["summary"] == "target planner body"
    assert all(record["producer_node_id"] == "planner-s-01" for record in full["output_records"])
    assert all(
        event["payload"].get("producer_node_id", "planner-s-01") == "planner-s-01"
        for event in full["events"]
    )
    assert all("value" not in event["payload"] for event in full["events"])


async def test_full_node_detail_uses_summary_owner_contract_for_nested_collections(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-node-detail-shared-owner-{uuid4().hex[:8]}"
    node_id = "verifier-shared-owner"
    grades = [
        {
            "requirement_id": f"requirement-{index:03d}",
            "grade": "A",
            "reason": f"reason-{index:03d}",
        }
        for index in range(201)
    ]
    await _save_manual_graph_run(app, run_id)
    events = [
        _event(
            "node_created",
            {
                "node_id": node_id,
                "kind": "verifier",
                "role": "verifier",
                "state": "completed",
            },
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "verification-shared-owner",
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": node_id,
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": "candidate-shared-owner",
                "outcome": "passed",
                "value": {"outcome": "passed", "grades": grades},
            },
        ),
    ]
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        graph_store = GraphEventStore(session)
        await graph_store.append_events(run_id, 0, events)
        await session.execute(
            delete(GraphNodeDetailSummaryModel).where(GraphNodeDetailSummaryModel.run_id == run_id)
        )
        await graph_store.rebuild_node_detail_summaries(run_id)
        stored_events = await graph_store.read_run(run_id)
        stored_record = next(
            event.payload for event in stored_events if event.event_type == "output_record_accepted"
        )
        assert len(stored_record["value"]["grades"]) == 201
        await session.commit()

    summary_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/{node_id}")
    full_resp = await client.get(f"/api/runs/{run_id}/graph/nodes/{node_id}?payload_mode=full")
    assert summary_resp.status_code == 200
    assert full_resp.status_code == 503
    unavailable = full_resp.json()["detail"]
    assert unavailable["code"] == "read_model_unavailable"
    assert unavailable["reason"] == "full_event_payload_exceeds_byte_cap"
    summary = summary_resp.json()
    summary_value = summary["output_records"][0]["value"]
    assert "__truncated_fields" not in summary_value
    assert len(summary_value["grades"]["value"]) == 50
    assert summary["truncated"] is True
    assert summary["next_cursor"].startswith("sha256:")
    value_meta = summary["collection_meta"]["output_records"]["fields"][
        "verification-shared-owner.value"
    ]
    assert value_meta["truncated"] is True
    assert value_meta["next_cursor"] == summary["next_cursor"]
    assert value_meta["original_bytes"] > 0
    assert len(value_meta["sha256"]) == 64
    assert len(full_resp.content) <= 262_144


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


async def test_node_detail_missing_current_owner_row_is_retryable_without_rebuild(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    """A broken compact row never makes a public GET replay or mutate history."""
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-node-detail-missing-owner-{uuid4().hex[:8]}"
    await _seed_graph_run(app, run_id)

    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        owner_row = (
            await session.execute(
                select(GraphNodeDetailSummaryModel)
                .where(GraphNodeDetailSummaryModel.run_id == run_id)
                .order_by(GraphNodeDetailSummaryModel.node_id)
                .limit(1)
            )
        ).scalar_one()
        node_id = owner_row.node_id
        checkpoint = await session.get(GraphNodeDetailSummaryCheckpointModel, run_id)
        snapshot = await session.get(GraphProjectionSnapshotModel, run_id)
        assert checkpoint is not None
        assert snapshot is not None
        checkpoint_position = checkpoint.position
        snapshot_position = snapshot.position
        await session.execute(
            delete(GraphNodeDetailSummaryModel).where(
                GraphNodeDetailSummaryModel.run_id == run_id,
                GraphNodeDetailSummaryModel.node_id == node_id,
            )
        )
        await session.commit()

    response = await client.get(f"/api/runs/{run_id}/graph/nodes/{node_id}")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "read_model_unavailable",
        "run_id": run_id,
        "read_model": "graph_node_detail_summaries",
        "current_position": checkpoint_position,
        "reason": "missing_owner_row",
        "retryable": True,
    }

    async with session_factory() as session:
        assert (
            await session.get(
                GraphNodeDetailSummaryModel,
                {"run_id": run_id, "node_id": node_id},
            )
            is None
        )
        checkpoint = await session.get(GraphNodeDetailSummaryCheckpointModel, run_id)
        snapshot = await session.get(GraphProjectionSnapshotModel, run_id)
        assert checkpoint is not None
        assert snapshot is not None
        assert checkpoint.position == checkpoint_position
        assert snapshot.position == snapshot_position


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


@pytest.mark.asyncio
async def test_graph_events_have_bounded_consistent_pagination(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-events-pagination-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(
                run_id,
                0,
                [
                    _event(
                        "node_created",
                        {
                            "node_id": f"worker-{position}",
                            "kind": "worker",
                            "state": "planned",
                        },
                    )
                    for position in range(1, 53)
                ],
            )

    default_page = await client.get(f"/api/runs/{run_id}/graph/events")
    assert default_page.status_code == 200
    assert [event["position"] for event in default_page.json()] == list(range(1, 51))
    assert default_page.headers["X-Has-More"] == "true"
    assert default_page.headers["X-Next-Position"] == "51"
    assert default_page.headers["X-Truncated-By-Bytes"] == "false"

    for payload_mode in ("summary", "full"):
        first = await client.get(
            f"/api/runs/{run_id}/graph/events",
            params={"payload_mode": payload_mode, "limit": 2},
        )
        second = await client.get(
            f"/api/runs/{run_id}/graph/events",
            params={
                "payload_mode": payload_mode,
                "limit": 2,
                "from_position": first.headers["X-Next-Position"],
            },
        )
        assert [event["position"] for event in first.json()] == [1, 2]
        assert [event["position"] for event in second.json()] == [3, 4]
        assert first.headers["X-Has-More"] == second.headers["X-Has-More"] == "true"

        final = await client.get(
            f"/api/runs/{run_id}/graph/events",
            params={"payload_mode": payload_mode, "from_position": 52, "limit": 2},
        )
        assert [event["position"] for event in final.json()] == [52]
        assert final.headers["X-Has-More"] == "false"
        assert final.headers["X-Next-Position"] == "null"

        empty = await client.get(
            f"/api/runs/{run_id}/graph/events",
            params={"payload_mode": payload_mode, "from_position": 53, "limit": 2},
        )
        assert empty.json() == []
        assert empty.headers["X-Has-More"] == "false"
        assert empty.headers["X-Next-Position"] == "null"

    for invalid_limit in (0, -1, 101):
        response = await client.get(
            f"/api/runs/{run_id}/graph/events",
            params={"limit": invalid_limit},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_graph_full_events_do_not_decode_payloads_above_the_public_byte_cap(
    _shared_app_fixture: tuple[AsyncClient, Any, Any, Any, Any],
) -> None:
    client, _drain, _, _, app = _shared_app_fixture
    run_id = f"graph-events-oversized-{uuid4().hex[:8]}"
    await _save_manual_graph_run(app, run_id)
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    oversized_value = "x" * 20_000
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(
                run_id,
                0,
                [
                    _event(
                        "callback_accepted",
                        {
                            "node_id": "oversized-node",
                            "payload": {"oversized_value": oversized_value},
                        },
                    )
                ],
            )

    response = await client.get(
        f"/api/runs/{run_id}/graph/events",
        params={"payload_mode": "full", "limit": 1},
    )

    assert response.status_code == 200
    event = response.json()[0]
    assert event["event_id"].startswith("callback_accepted-")
    assert event["payload"] == {}
    assert event["payload_truncated"] is True
    assert event["payload_original_bytes"] > len(oversized_value)
    assert event["payload_sha256"] is None
    assert response.headers["X-Has-More"] == "false"
    assert response.headers["X-Next-Position"] == "null"
