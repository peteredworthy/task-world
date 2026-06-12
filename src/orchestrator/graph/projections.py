"""Minimal graph projections for slice 1.2 scenario fixtures."""

from orchestrator.graph.models import EventEnvelope


def project_node_states(events: list[EventEnvelope]) -> dict[str, str]:
    node_states: dict[str, str] = {}
    for event in events:
        if event.event_type != "node_state_changed":
            continue
        node_id = event.payload.get("node_id")
        new_state = event.payload.get("new_state")
        if isinstance(node_id, str) and isinstance(new_state, str):
            node_states[node_id] = new_state
    return node_states


def project_task_states(events: list[EventEnvelope]) -> dict[str, str]:
    return {}
