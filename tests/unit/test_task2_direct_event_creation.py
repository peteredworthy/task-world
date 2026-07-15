from __future__ import annotations

import ast
from pathlib import Path

from orchestrator.graph import build_graph_catalog, event_payload_json
from orchestrator.graph.commands.event_creator import TypedEventCreator
from orchestrator.graph.commands.lifecycle import (
    FailureRecordInput,
    RecoveryPlanRecordInput,
    _failure_record_event,
    _recovery_plan_record_event,
)
from orchestrator.graph.events.lifecycle import (
    COMMAND_REJECTED,
    CommandRejectedPayload,
    RuntimeRetryScheduledPayload,
)
from orchestrator.graph.models import Actor, ActorKind
from orchestrator.graph.specifications import CommandExecutionContext, HydratedEvent
from tests.graph_command_support import (
    FakeClock,
    SequentialIdGenerator,
)


COMMAND_MODULES = (
    Path("src/orchestrator/graph/commands/__init__.py"),
    Path("src/orchestrator/graph/commands/lifecycle.py"),
    Path("src/orchestrator/graph/commands/callbacks.py"),
)
LIFECYCLE_MODULE = Path("src/orchestrator/graph/commands/lifecycle.py")


def test_task2_command_modules_have_no_raw_event_round_trip() -> None:
    forbidden_names = {"_strict_event", "StoredEventEnvelope"}

    for path in COMMAND_MODULES:
        tree = ast.parse(path.read_text())
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        envelope_calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not names & forbidden_names, path
        assert "hydrate" not in attributes, path
        assert "EventEnvelope" not in envelope_calls, path


def test_lifecycle_records_use_direct_typed_construction() -> None:
    tree = ast.parse(LIFECYCLE_MODULE.read_text())
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    assert "model_validate" not in attributes


def test_typed_event_creator_returns_hydrated_events_with_ordered_unique_metadata() -> None:
    catalog = build_graph_catalog()
    context = CommandExecutionContext(
        run_id="run-1",
        current_position=7,
        clock=FakeClock(),
        id_generator=SequentialIdGenerator(),
        actor=Actor(kind=ActorKind.CONTROLLER),
        events=(),
        catalog=catalog,
    )
    creator = TypedEventCreator(context)

    first = creator.create(
        COMMAND_REJECTED,
        CommandRejectedPayload(command_type="start", reason="first"),
    )
    second = creator.create(
        COMMAND_REJECTED,
        CommandRejectedPayload(command_type="pause", reason="second"),
    )

    assert isinstance(first, HydratedEvent)
    assert isinstance(second, HydratedEvent)
    assert first.metadata.event_id != second.metadata.event_id
    assert first.metadata.event_id == "event-1"
    assert second.metadata.event_id == "event-2"
    assert first.metadata.position == 8
    assert second.metadata.position == 9
    assert first.metadata.timestamp <= second.metadata.timestamp


def test_lifecycle_direct_failure_record_preserves_record_json() -> None:
    creator = TypedEventCreator(
        CommandExecutionContext(
            run_id="run-1",
            current_position=7,
            clock=FakeClock(),
            id_generator=SequentialIdGenerator(),
            actor=Actor(kind=ActorKind.CONTROLLER),
            events=(),
            catalog=build_graph_catalog(),
        )
    )

    event = _failure_record_event(
        creator,
        FailureRecordInput(
            node_id="worker-1",
            error_class="max_attempts_exhausted",
            lease_id="lease-1",
            execution_id="exec-1",
            generation=2,
            reason="process_exit",
            attempt_number=3,
            max_attempts=3,
        ),
    )

    assert event_payload_json(event)["record"] == {
        "record_id": "failure-worker-1-lease-1",
        "record_kind": "graph_record",
        "record_type": "failure_record",
        "producer_node_id": "worker-1",
        "port": "failure_record",
        "schema": "FailureRecord",
        "value": {
            "failed_node_id": "worker-1",
            "phase": "runtime",
            "error_class": "max_attempts_exhausted",
            "retryable": False,
            "lease_id": "lease-1",
            "execution_id": "exec-1",
            "reason": "process_exit",
            "lease_generation": 2,
            "attempt_number": 3,
            "max_attempts": 3,
        },
    }


def test_lifecycle_direct_recovery_plan_preserves_record_json() -> None:
    creator = TypedEventCreator(
        CommandExecutionContext(
            run_id="run-1",
            current_position=7,
            clock=FakeClock(),
            id_generator=SequentialIdGenerator(),
            actor=Actor(kind=ActorKind.CONTROLLER),
            events=(),
            catalog=build_graph_catalog(),
        )
    )

    event = _recovery_plan_record_event(
        creator,
        RecoveryPlanRecordInput(
            node_id="worker-1",
            retry=RuntimeRetryScheduledPayload(
                node_id="worker-1",
                lease_id="lease-1",
                generation=2,
                policy="v1_requeue_same_node_after_agent_death",
                reason="process_exit",
                retry_after_seconds=60,
                retry_not_before="2026-01-01T00:01:00+00:00",
            ),
            retry_backoff_seconds=60,
        ),
    )

    assert event_payload_json(event)["record"] == {
        "record_id": "recovery-plan-worker-1-lease-1",
        "record_kind": "output",
        "record_type": "recovery_plan",
        "producer_node_id": "worker-1",
        "port": "recovery_plan",
        "schema": "RecoveryPlan",
        "value": {
            "action": "retry",
            "responsible_actor": "controller",
            "graph_changes": [{"op": "set_node_state", "node_id": "worker-1", "state": "blocked"}],
            "reason": "process_exit",
            "retry_after_seconds": 60,
            "retry_not_before": "2026-01-01T00:01:00+00:00",
        },
    }
