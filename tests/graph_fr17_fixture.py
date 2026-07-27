"""Deterministic FR-17 graph fixture shared by acceptance and golden tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config import AgentRunnerType, RunStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.db import RunModel
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow import WorkflowService
from tests.unit.graph_test_utils import canonical_event_payload


async def create_graph_run(session_factory: async_sessionmaker[AsyncSession], run_id: str) -> None:
    run = create_run_from_routine(
        fr17_routine(), repo_name=f"fr17-repo-{run_id}", source_branch="main"
    )
    run.id = run_id
    run.execution_mode = "graph"
    run.routine_embedded = fr17_routine().model_dump(mode="json", by_alias=True)
    run.agent_runner_type = AgentRunnerType.CODEX_SERVER
    async with session_factory() as session:
        await WorkflowService(session).create_run(run)
        stored = await session.get(RunModel, run_id)
        assert stored is not None
        stored.status = RunStatus.ACTIVE
        await session.commit()


async def seed_less_used_readback_graph(
    session_factory: async_sessionmaker[AsyncSession], run_id: str
) -> None:
    async with session_factory() as session:
        async with session.begin():
            await GraphEventStore(session).append_events(run_id, 0, less_used_events(run_id))


def less_used_events(run_id: str) -> list[EventEnvelope]:
    specs: list[tuple[str, dict[str, Any]]] = [
        ("run_lifecycle_changed", {"from_state": "queued", "to_state": "active"}),
        (
            "node_created",
            {"node_id": "planner-fr17", "kind": "planner", "role": "planner", "state": "completed"},
        ),
        (
            "node_created",
            {
                "node_id": "worker-source",
                "kind": "worker",
                "role": "builder",
                "state": "completed",
                "task_region_id": "task-fr17",
                "resource_claims": [{"mode": "write", "scope": "paths", "paths": ["docs/"]}],
                "allowed_actions": ["submit_records", "raise_appeal"],
            },
        ),
        (
            "node_created",
            {
                "node_id": "recovery-1",
                "kind": "recovery",
                "state": "running",
                "task_region_id": "task-fr17",
                "preconditions": ["failure_record_bound"],
                "command_definition": {
                    "id": "recover-runtime",
                    "cmd": "controller:recover-failed-node",
                    "source": "controller",
                },
            },
        ),
        (
            "node_created",
            {
                "node_id": "review-1",
                "kind": "review",
                "state": "ready",
                "task_region_id": "task-fr17",
                "blocker": "merge_conflicts",
                "allowed_actions": ["record_decision"],
            },
        ),
        ("node_deferred", {"node_id": "review-1", "reason": "merge_conflicts"}),
        (
            "node_created",
            {
                "node_id": "appeal-1",
                "kind": "appeal",
                "state": "completed",
                "task_region_id": "task-fr17",
            },
        ),
        (
            "node_created",
            {
                "node_id": "gate-pending",
                "kind": "human_gate",
                "state": "ready",
                "task_region_id": "task-fr17",
                "gate_type": "human_approval",
                "prompt": "Approve FR-17 pending work?",
            },
        ),
        (
            "node_created",
            {
                "node_id": "gate-decision",
                "kind": "human_gate",
                "state": "ready",
                "task_region_id": "task-fr17",
                "gate_type": "human_approval",
                "prompt": "Approve FR-17 completed readback fixture?",
            },
        ),
        (
            "node_created",
            {
                "node_id": "consumer-1",
                "kind": "worker",
                "role": "builder",
                "state": "ready",
                "task_region_id": "task-fr17",
            },
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-failure-recovery",
                "from_node_id": "worker-source",
                "from_port": "failure_record",
                "to_node_id": "recovery-1",
                "to_port": "failure_record",
                "required": True,
                "dependency_type": "input_binding",
                "binding_policy": "bind_first",
                "freshness_policy": "latest_only",
                "prompt_hydration_policy": "summary",
            },
        ),
        (
            "output_record_accepted",
            {
                "record_id": "failure-record-1",
                "record_kind": "output",
                "record_type": "failure_record",
                "producer_node_id": "worker-source",
                "port": "failure_record",
                "schema": "FailureRecord",
                "value": {
                    "failed_node_id": "worker-source",
                    "phase": "runtime",
                    "error_class": "agent_error",
                    "retryable": True,
                },
            },
        ),
        (
            "input_bound",
            {
                "edge_id": "edge-failure-recovery",
                "to_node_id": "recovery-1",
                "to_port": "failure_record",
                "record_ids": ["failure-record-1"],
                "bound_at_position": 12,
                "trigger": "record_accepted",
            },
        ),
        (
            "lease_granted",
            {
                "node_id": "recovery-1",
                "lease_id": "lease-recovery",
                "generation": 1,
                "execution_id": "exec-recovery",
                "expires_at": "2026-01-01T00:05:00+00:00",
            },
        ),
        (
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
                    "responsible_actor": "recovery-1",
                    "graph_changes": [{"target_node_id": "worker-source"}],
                },
            },
        ),
        (
            "node_state_changed",
            {
                "node_id": "recovery-1",
                "new_state": "completed",
                "trigger": "recovery_plan_recorded",
            },
        ),
        (
            "lease_released",
            {"node_id": "recovery-1", "lease_id": "lease-recovery", "generation": 1},
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-recovery-consumer",
                "from_node_id": "recovery-1",
                "from_port": "recovery_plan",
                "to_node_id": "consumer-1",
                "to_port": "outstanding_failures",
                "required": False,
                "dependency_type": "input_binding",
                "binding_policy": "bind_latest",
                "freshness_policy": "latest_only",
                "prompt_hydration_policy": "full",
            },
        ),
        (
            "input_bound",
            {
                "edge_id": "edge-recovery-consumer",
                "to_node_id": "consumer-1",
                "to_port": "outstanding_failures",
                "record_ids": ["recovery-plan-1"],
                "bound_at_position": 19,
                "trigger": "record_accepted",
            },
        ),
        (
            "output_record_accepted",
            decision_request_record("decision-request-pending", "gate-pending"),
        ),
        (
            "output_record_accepted",
            decision_request_record("decision-request-approved", "gate-decision"),
        ),
        (
            "edge_created",
            {
                "edge_id": "edge-decision-consumer",
                "from_node_id": "gate-decision",
                "from_port": "decision_record",
                "to_node_id": "consumer-1",
                "to_port": "approval",
                "required": False,
                "dependency_type": "input_binding",
                "binding_policy": "bind_latest",
            },
        ),
        (
            "appeal_opened",
            {
                "node_id": "appeal-1",
                "appealed_node_id": "worker-source",
                "candidate_id": "candidate-fr17",
                "task_region_id": "task-fr17",
                "appeal_type": "invalid_test",
            },
        ),
        (
            "oversight_decision_recorded",
            {
                "node_id": "oversight-1",
                "appeal_node_id": "appeal-1",
                "appealed_node_id": "worker-source",
                "candidate_id": "candidate-fr17",
                "task_region_id": "task-fr17",
                "appeal_type": "invalid_test",
                "decision": "rejected",
            },
        ),
        (
            "graph_patch_rejected",
            {
                "patch_id": "patch-fr17-rejected",
                "proposed_by_node_id": "planner-fr17",
                "base_graph_position": 3,
                "current_graph_position": 25,
                "actor_role": "planner",
                "reason": "invalid macro expansion for FR-17 fixture",
                "diagnostics": {"macro": "create_join", "valid": False},
                "created_node_ids": [],
                "created_edge_ids": [],
            },
        ),
    ]
    return [
        event(run_id, event_type, payload, position)
        for position, (event_type, payload) in enumerate(specs, 1)
    ]


def decision_request_record(record_id: str, node_id: str) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "record_kind": "graph_record",
        "record_type": "decision_request",
        "producer_node_id": node_id,
        "port": "decision_request",
        "schema": "DecisionRequest",
        "value": {
            "decision_type": "approval",
            "options": ["approved", "rejected"],
            "default_option": "rejected",
            "consequence_summary": "FR-17 acceptance fixture.",
        },
    }


def event(run_id: str, event_type: str, payload: dict[str, Any], position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"fr17-event-{position}",
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )


def fr17_routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "fr17-acceptance",
            "name": "FR-17 Acceptance",
            "execution_mode": "graph",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Readback fixture",
                            "task_context": "Exercise less-used graph readbacks.",
                            "requirements": [{"id": "req-1", "desc": "Readbacks are coherent."}],
                            "verifier": {"rubric": [{"id": "req-1", "text": "Coherent."}]},
                        }
                    ],
                }
            ],
        }
    )
