"""Executable scenario fixture harness for graph event slices."""

from dataclasses import dataclass, field
from typing import Any, cast

from orchestrator.graph.clock import FakeClock, SequentialIdGenerator
from orchestrator.graph.models import Actor, ActorKind, EventEnvelope
from orchestrator.graph.projections import initial_projection, reduce_event
from orchestrator.graph.store import InMemoryEventStore


@dataclass(frozen=True)
class ScenarioResult:
    scenario_name: str
    passed: bool
    events_produced: list[EventEnvelope]
    projection_snapshot: dict[str, str]
    failures: list[str] = field(default_factory=lambda: [])


def run_scenario(
    scenario: dict[str, Any],
    store: InMemoryEventStore,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> ScenarioResult:
    run_id = str(scenario.get("run_id", "run-1"))
    scenario_name = str(scenario.get("name", "unnamed"))
    failures: list[str] = []

    for event_type, payload in _event_specs(scenario.get("given_events", [])):
        store.append(_make_event(run_id, event_type, payload, clock, id_gen))

    when_command = scenario.get("when_command")
    if when_command is not None:
        command_type, command_payload = _single_mapping("when_command", when_command)
        store.append(
            _make_event(
                run_id,
                "command_recorded",
                {"command_type": command_type, **command_payload},
                clock,
                id_gen,
            )
        )

    events = store.read_from(run_id)
    failures.extend(_check_then_events(scenario.get("then_events", []), events))

    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    projection_snapshot: dict[str, str] = {}
    if projection["run_state"] is not None:
        projection_snapshot["run_state"] = projection["run_state"]
    projection_snapshot.update(projection["node_states"])
    projection_snapshot.update(projection["task_states"])
    for lease_id, lease in projection["leases"].items():
        state = lease.get("state", "")
        projection_snapshot[lease_id] = state if isinstance(state, str) else ""
    failures.extend(
        _check_then_projection(scenario.get("then_projection", {}), projection_snapshot)
    )

    return ScenarioResult(
        scenario_name=scenario_name,
        passed=not failures,
        events_produced=events,
        projection_snapshot=projection_snapshot,
        failures=failures,
    )


def _make_event(
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> EventEnvelope:
    return EventEnvelope(
        event_id=id_gen.next_id("event"),
        run_id=run_id,
        position=-1,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=clock.now(),
        payload=payload,
    )


def _event_specs(raw_events: Any) -> list[tuple[str, dict[str, Any]]]:
    specs: list[tuple[str, dict[str, Any]]] = []
    for raw_event in raw_events:
        if isinstance(raw_event, str):
            specs.append((raw_event, {}))
            continue
        event_type, payload = _single_mapping("event", raw_event)
        specs.append((event_type, payload))
    return specs


def _single_mapping(label: str, value: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(value, dict) or len(cast(dict[str, Any], value)) != 1:
        msg = f"{label} must be a single-key mapping"
        raise ValueError(msg)
    typed: dict[str, Any] = cast(dict[str, Any], value)
    event_type, payload = next(iter(typed.items()))
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        msg = f"{label} payload for {event_type} must be a mapping"
        raise ValueError(msg)
    return event_type, cast(dict[str, Any], payload)


def _check_then_events(then_events: Any, events: list[EventEnvelope]) -> list[str]:
    failures: list[str] = []
    for event_type, expected_payload in _event_specs(then_events):
        matches = [event for event in events if event.event_type == event_type]
        if not matches:
            failures.append(f"Missing expected event: {event_type}")
            continue
        if expected_payload and not any(
            _payload_matches(event.payload, expected_payload) for event in matches
        ):
            failures.append(
                f"Payload mismatch for event {event_type}: expected fields {expected_payload}"
            )
    return failures


def _payload_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(actual.get(key) == value for key, value in expected.items())


def _check_then_projection(then_projection: Any, projection_snapshot: dict[str, str]) -> list[str]:
    if then_projection is None:
        return []
    if not isinstance(then_projection, dict):
        return ["then_projection must be a mapping"]

    failures: list[str] = []
    typed_proj = cast(dict[str, Any], then_projection)
    for key, expected_value in typed_proj.items():
        actual_value = projection_snapshot.get(str(key))
        if actual_value != expected_value:
            failures.append(
                f"Projection mismatch for {key}: expected {expected_value}, got {actual_value}"
            )
    return failures
