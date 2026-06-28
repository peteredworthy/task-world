"""Unit tests for the run evidence digest presenter."""

from typing import Any

from orchestrator.api import build_run_evidence_digest_response
from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.config.models import RoutineConfig
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.state import Attempt, ModelTokenUsage
from orchestrator.state.factory import create_run_from_routine


def _routine() -> RoutineConfig:
    return RoutineConfig.model_validate(
        {
            "id": "evidence-digest-unit",
            "name": "Evidence Digest Unit",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Step 1",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Task Alpha",
                            "task_context": "Do not expose this prompt text.",
                            "verifier": {"rubric": [{"id": "req-1", "text": "Pass."}]},
                        },
                        {
                            "id": "task-2",
                            "title": "Task Beta",
                            "verifier": {"rubric": [{"id": "req-2", "text": "Pass."}]},
                        },
                        {
                            "id": "task-3",
                            "title": "Task Gamma",
                            "verifier": {"rubric": [{"id": "req-3", "text": "Pass."}]},
                        },
                    ],
                }
            ],
        }
    )


def _event(event_type: str, payload: dict[str, Any], position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"{event_type}-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )


def _run_with_metrics() -> tuple[Any, str, str]:
    run = create_run_from_routine(_routine(), repo_name="repo-1", source_branch="main")
    run.status = RunStatus.PAUSED
    run.pause_reason = "manual_gate"
    run.last_error = "Graph paused for inspection"
    run.execution_mode = "graph"

    step = run.steps[0]
    step.tasks[0].status = TaskStatus.PENDING_USER_ACTION
    step.tasks[0].pending_action_type = "clarification"
    step.tasks[1].status = TaskStatus.COMPLETED
    step.tasks[2].status = TaskStatus.FAILED

    attempt = Attempt(attempt_num=1)
    attempt.metrics.duration_ms = 1234
    attempt.metrics.num_actions = 7
    attempt.token_usage_by_model = [
        ModelTokenUsage(
            model="gpt-4o",
            input_tokens=10,
            output_tokens=20,
            cache_read_tokens=3,
            cache_creation_tokens=2,
            cost_per_m_input=1.0,
            cost_per_m_output=2.0,
            cost_per_m_cache_read=3.0,
            cost_per_m_cache_creation=4.0,
        )
    ]
    step.tasks[0].attempts = [attempt]

    return run, step.id, step.tasks[0].id


def _graph_events(step_id: str, task_id: str) -> list[EventEnvelope]:
    return [
        _event(
            "node_created",
            {
                "node_id": "node-a",
                "kind": "worker",
                "role": "builder",
                "state": "running",
                "title": "Task Alpha worker",
                "task_id": task_id,
                "task_region_id": f"{step_id}/{task_id}",
            },
            1,
        ),
        _event(
            "output_record_accepted",
            {
                "record_id": "output-1",
                "record_kind": "output",
                "producer_node_id": "node-a",
                "summary": "output summary",
            },
            2,
        ),
        _event(
            "file_state_accepted",
            {
                "record_id": "file-1",
                "producer_node_id": "node-a",
                "snapshot_id": "snapshot-1",
                "tracked": [{"path": "src/app.py", "classification": "source"}],
            },
            3,
        ),
        _event(
            "node_created",
            {
                "node_id": "node-b",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
                "title": "Task Beta worker",
                "task_id": f"{task_id}-beta",
            },
            4,
        ),
        _event(
            "node_deferred",
            {"node_id": "node-b", "reason": "resource_conflict:write:write"},
            5,
        ),
        _event(
            "node_created",
            {
                "node_id": "node-c",
                "kind": "gate",
                "role": "approval",
                "state": "planned",
                "title": "Gate node",
            },
            6,
        ),
        _event(
            "node_deferred",
            {"node_id": "node-c", "reason": "gate_not_approved:gate-c"},
            7,
        ),
        _event(
            "node_created",
            {
                "node_id": "node-review",
                "kind": "review",
                "state": "blocked",
                "title": "Review node",
                "reason": "final invariant blocked",
            },
            8,
        ),
    ]


def test_build_run_evidence_digest_response_hides_evidence_and_limits_nodes() -> None:
    run, step_id, task_id = _run_with_metrics()
    events = _graph_events(step_id, task_id)

    digest = build_run_evidence_digest_response(
        run,
        events,
        pending_actions=[{"action_type": "clarification", "task_id": task_id}],
        max_nodes=2,
        include_node_evidence=False,
    )

    assert digest.run_id == run.id
    assert digest.status == "paused"
    assert digest.execution_mode == "graph"
    assert digest.is_graph_backed is True
    assert digest.run_summary.routine_id == "evidence-digest-unit"
    assert digest.run_summary.repo_name == "repo-1"
    assert digest.run_summary.step_count == 1
    assert digest.run_summary.task_count == 3
    assert digest.run_summary.task_status_counts == {
        "pending_user_action": 1,
        "completed": 1,
        "failed": 1,
    }
    assert digest.run_summary.pause_reason == "manual_gate"
    assert digest.run_summary.last_error == "Graph paused for inspection"
    assert digest.blockers == [
        "pause_reason:manual_gate",
        "last_error:Graph paused for inspection",
        "scheduler:blocked:node-review:blocked",
        "scheduler:waiting_resources:node-b:resource_conflict:write:write",
        "scheduler:waiting_gates:node-c:gate_not_approved:gate-c",
        "graph_review:node-review: final invariant blocked",
        "pending_action:clarification",
    ]
    assert digest.scheduler.model_dump() == {
        "graph_event_count": 8,
        "ready_count": 0,
        "blocked_count": 1,
        "waiting_resource_count": 1,
        "waiting_gate_count": 1,
        "active_lease_count": 0,
        "suspended_lease_count": 0,
    }
    assert [node.node_id for node in digest.representative_nodes] == ["node-a", "node-b"]
    assert all(node.evidence_summary is None for node in digest.representative_nodes)
    assert digest.representative_nodes[0].blockers == []
    assert digest.representative_nodes[1].blockers == [
        "scheduler:waiting_resources:resource_conflict:write:write"
    ]
    assert digest.metrics.total_tokens_read == 10
    assert digest.metrics.total_tokens_write == 20
    assert digest.metrics.total_tokens_cache == 5
    assert digest.metrics.total_duration_ms == 1234
    assert digest.metrics.total_num_actions == 7
    assert digest.metrics.token_usage_by_model_count == 1
    assert digest.metrics.estimated_cost_usd is not None


def test_build_run_evidence_digest_response_includes_sanitized_evidence() -> None:
    run, step_id, task_id = _run_with_metrics()
    events = _graph_events(step_id, task_id)

    digest = build_run_evidence_digest_response(
        run,
        events,
        pending_actions=[],
        max_nodes=3,
        include_node_evidence=True,
    )

    assert digest.representative_nodes[0].evidence_summary is not None
    assert "Do not expose this prompt text" not in digest.representative_nodes[0].evidence_summary
    assert digest.representative_nodes[0].evidence_summary.startswith("state=running")
    assert digest.representative_nodes[0].title == "Task Alpha worker"
    assert digest.representative_nodes[0].role == "builder"


def test_build_run_evidence_digest_response_handles_legacy_run() -> None:
    run = create_run_from_routine(_routine(), repo_name="repo-legacy", source_branch="main")
    digest = build_run_evidence_digest_response(run, [])

    assert digest.is_graph_backed is False
    assert digest.blockers == []
    assert digest.scheduler.model_dump() == {
        "graph_event_count": 0,
        "ready_count": 0,
        "blocked_count": 0,
        "waiting_resource_count": 0,
        "waiting_gate_count": 0,
        "active_lease_count": 0,
        "suspended_lease_count": 0,
    }
    assert digest.representative_nodes == []
