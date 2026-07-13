from __future__ import annotations

import ast
from pathlib import Path

from orchestrator.graph.events.lifecycle import COMMAND_REJECTED, CommandRejectedPayload
from orchestrator.graph.models import Actor, ActorKind
from orchestrator.graph.specifications import CommandExecutionContext, HydratedEvent
from tests.graph_command_support import (
    FakeClock,
    SequentialIdGenerator,
    build_graph_command_dependencies,
)
from orchestrator.graph import build_graph_catalog


COMMAND_MODULES = (
    Path("src/orchestrator/graph/commands/__init__.py"),
    Path("src/orchestrator/graph/commands/lifecycle.py"),
    Path("src/orchestrator/graph/commands/callbacks.py"),
)


def test_task2_command_modules_have_no_raw_event_round_trip() -> None:
    forbidden_names = {"_strict_event", "StoredEventEnvelope"}
    forbidden_attributes = {"hydrate", "model_validate"}

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
        assert not attributes & forbidden_attributes, path
        assert "EventEnvelope" not in envelope_calls, path


def test_typed_event_creator_returns_hydrated_events_with_ordered_unique_metadata() -> None:
    from orchestrator.graph.commands.event_creator import TypedEventCreator

    context = CommandExecutionContext(
        run_id="run-1",
        current_position=7,
        clock=FakeClock(),
        id_generator=SequentialIdGenerator(),
        actor=Actor(kind=ActorKind.CONTROLLER),
        events=(),
        future_effects=build_graph_command_dependencies(
            catalog=build_graph_catalog()
        ).future_effects,
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
