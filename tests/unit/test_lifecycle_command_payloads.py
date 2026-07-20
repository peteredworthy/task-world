"""Strict lifecycle command payload and registry coverage."""

import inspect
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from orchestrator.graph import Actor, ActorKind
from orchestrator.graph.command_models import (
    CompleteCommand,
    GraphCommandContext,
    RecordHeartbeatCommand,
)
from orchestrator.graph.commands import COMMAND_SPECS


EXPECTED_COMMANDS = {
    "accept_run",
    "start",
    "pause",
    "resume",
    "cancel",
    "complete",
    "fail",
    "record_heartbeat",
    "seed_compiled_events",
    "schedule_tick",
    "reconcile",
    "submit_callback",
    "submit_patch",
    "acknowledge_start",
    "agent_died",
    "raise_appeal",
    "record_decision",
    "record_gatekeeper_verdicts",
    "record_node_usage",
    "record_requirement_revision",
    "record_support_evidence",
    "evaluate_join",
    "evaluate_final_gate",
    "record_cleanup_applied",
}


def test_command_registry_has_exactly_24_strict_models() -> None:
    assert set(COMMAND_SPECS) == EXPECTED_COMMANDS
    assert len(COMMAND_SPECS) == 24
    assert all(
        spec.payload_model.model_config["extra"] == "forbid" for spec in COMMAND_SPECS.values()
    )


def test_each_registered_handler_accepts_its_concrete_payload_model() -> None:
    for command_type, spec in COMMAND_SPECS.items():
        payload_annotation = get_type_hints(spec.handler)[
            list(inspect.signature(spec.handler).parameters)[3]
        ]
        assert payload_annotation is spec.payload_model, command_type


def test_graph_command_context_owns_runtime_and_actor_provenance() -> None:
    context = GraphCommandContext(
        run_id="run-1",
        current_graph_position=7,
        actor=Actor(kind=ActorKind.HUMAN, role="operator"),
    )

    assert context.run_id == "run-1"
    assert context.current_graph_position == 7
    assert context.actor is not None and context.actor.role == "operator"


@pytest.mark.parametrize("field", ["run_id", "_current_graph_position", "actor_role"])
def test_lifecycle_payload_rejects_context_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        CompleteCommand.model_validate({field: "unexpected"})


@pytest.mark.parametrize("value", [True, "4"])
def test_heartbeat_integer_fields_are_strict(value: object) -> None:
    with pytest.raises(ValidationError):
        RecordHeartbeatCommand.model_validate({"lease_id": "lease-1", "generation": value})


def test_heartbeat_requires_lease_identity() -> None:
    with pytest.raises(ValidationError):
        RecordHeartbeatCommand.model_validate({})
