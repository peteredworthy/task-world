"""Architecture and fail-closed boundaries for graph runtime event consumers."""

from __future__ import annotations

from importlib import import_module

import pytest

from orchestrator.graph import (
    Actor,
    ActorKind,
    FakeClock,
    HydratedEvent,
    NodeCreatedPayload,
    StoredEventEnvelope,
    build_graph_catalog,
)
from orchestrator.graph_runtime.dispatch import _callback_conflict_reason
from orchestrator.graph_runtime.prompts import _planner_deferred_reasons
from orchestrator.graph_runtime.store import _is_callback_history_event


def _event(event_type: str, payload: dict[str, object]) -> HydratedEvent:
    return (
        build_graph_catalog()
        .resolve_event(event_type)
        .hydrate(
            StoredEventEnvelope(
                event_id=f"{event_type}-1",
                run_id="run-1",
                position=1,
                event_type=event_type,
                payload_schema_generation=2,
                actor=Actor(kind=ActorKind.CONTROLLER),
                timestamp=FakeClock().now(),
                payload=payload,
            )
        )
    )


@pytest.mark.parametrize(
    "module_name",
    (
        "orchestrator.graph_runtime.dispatch",
        "orchestrator.graph_runtime.controller",
        "orchestrator.graph_runtime.prompts",
        "orchestrator.graph_runtime.store",
        "orchestrator.graph_runtime.outbox",
        "orchestrator.graph_runtime.seeding",
        "orchestrator.graph_runtime.file_state",
        "orchestrator.graph_runtime.gatekeeper",
    ),
)
def test_runtime_domain_modules_do_not_alias_json_event_payload_reader(module_name: str) -> None:
    """Runtime decisions must consume strict payload classes, not JSON views."""
    assert "event_payload_json" not in vars(import_module(module_name))


def test_dispatch_rejection_decision_fails_closed_for_wrong_payload_class() -> None:
    event = _event(
        "command_rejected",
        {"command_type": "submit_callback", "reason": "rejected"},
    )
    mismatched = event.model_copy(
        update={"payload": NodeCreatedPayload(node_id="node-1", kind="worker")}
    )

    with pytest.raises(TypeError, match="command_rejected event has an unexpected payload type"):
        _callback_conflict_reason([mismatched])


def test_prompt_deferred_reason_decision_fails_closed_for_wrong_payload_class() -> None:
    event = _event("node_deferred", {"node_id": "node-1", "reason": "waiting"})
    mismatched = event.model_copy(
        update={"payload": NodeCreatedPayload(node_id="node-1", kind="worker")}
    )

    with pytest.raises(TypeError, match="node_deferred event has an unexpected payload type"):
        _planner_deferred_reasons([mismatched])


def test_store_callback_history_decision_fails_closed_for_wrong_payload_class() -> None:
    event = _event(
        "node_state_changed",
        {"node_id": "node-1", "new_state": "running", "trigger": "runtime_start_acknowledged"},
    )
    mismatched = event.model_copy(
        update={"payload": NodeCreatedPayload(node_id="node-1", kind="worker")}
    )

    with pytest.raises(TypeError, match="node_state_changed event has an unexpected payload type"):
        _is_callback_history_event(mismatched)
