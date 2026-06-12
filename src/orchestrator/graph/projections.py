"""Pure graph projections for scenario fixtures."""

from typing import Any, TypedDict

from orchestrator.graph.models import EventEnvelope


class GraphProjection(TypedDict):
    run_state: str | None
    node_states: dict[str, str]
    task_states: dict[str, str]
    leases: dict[str, dict[str, Any]]
    ready_nodes: list[str]


def initial_projection() -> GraphProjection:
    return {
        "run_state": None,
        "node_states": {},
        "task_states": {},
        "leases": {},
        "ready_nodes": [],
    }


def reduce_event(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    next_state: GraphProjection = {
        "run_state": state["run_state"],
        "node_states": dict(state["node_states"]),
        "task_states": dict(state["task_states"]),
        "leases": {lease_id: dict(lease) for lease_id, lease in state["leases"].items()},
        "ready_nodes": list(state["ready_nodes"]),
    }

    if event.event_type == "run_lifecycle_changed":
        to_state = event.payload.get("to_state")
        if isinstance(to_state, str):
            next_state["run_state"] = to_state
    elif event.event_type == "node_created":
        node_id = event.payload.get("node_id")
        node_state = event.payload.get("state")
        if isinstance(node_id, str) and isinstance(node_state, str):
            next_state["node_states"][node_id] = node_state
    elif event.event_type == "node_state_changed":
        node_id = event.payload.get("node_id")
        new_state = event.payload.get("new_state")
        if isinstance(node_id, str) and isinstance(new_state, str):
            next_state["node_states"][node_id] = new_state
    elif event.event_type == "lease_granted":
        lease_id = event.payload.get("lease_id")
        node_id = event.payload.get("node_id")
        generation = event.payload.get("generation")
        if isinstance(lease_id, str) and isinstance(node_id, str):
            lease: dict[str, Any] = {
                "lease_id": lease_id,
                "node_id": node_id,
                "state": "active",
            }
            if isinstance(generation, int):
                lease["generation"] = generation
            next_state["leases"][lease_id] = lease
    elif event.event_type in {
        "lease_suspended",
        "lease_revoked",
        "lease_expired",
        "lease_released",
    }:
        lease_id = event.payload.get("lease_id")
        if isinstance(lease_id, str):
            lease = dict(next_state["leases"].get(lease_id, {"lease_id": lease_id}))
            lease["state"] = event.event_type.removeprefix("lease_")
            next_state["leases"][lease_id] = lease

    next_state["ready_nodes"] = _ready_nodes(next_state["node_states"])
    return next_state


def project_run_state(events: list[EventEnvelope]) -> str | None:
    return _project(events)["run_state"]


def project_node_states(events: list[EventEnvelope]) -> dict[str, str]:
    return _project(events)["node_states"]


def project_task_states(events: list[EventEnvelope]) -> dict[str, str]:
    return _project(events)["task_states"]


def project_leases(events: list[EventEnvelope]) -> dict[str, dict[str, Any]]:
    return _project(events)["leases"]


def project_ready_nodes(events: list[EventEnvelope]) -> list[str]:
    return _project(events)["ready_nodes"]


def _project(events: list[EventEnvelope]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def _ready_nodes(node_states: dict[str, str]) -> list[str]:
    return [node_id for node_id, node_state in node_states.items() if node_state == "ready"]
