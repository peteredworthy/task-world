"""Graph projection read-only API endpoints."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query

from orchestrator.api.deps import get_graph_store
from orchestrator.api.schemas.base import ApiModel
from orchestrator.graph import EventEnvelope
from orchestrator.graph.projections import (
    project_leases,
    project_node_states,
    project_ready_nodes,
    project_run_state,
    project_task_states,
)
from orchestrator.graph_runtime.store import GraphEventStore

router = APIRouter(prefix="/api/runs", tags=["graph"])


class GraphEventResponse(ApiModel):
    event_id: str
    event_type: str
    run_id: str
    position: int
    timestamp: str
    payload: dict[str, Any]


class GraphProjectionResponse(ApiModel):
    run_id: str
    event_count: int
    run_state: str | None
    node_states: dict[str, str]
    task_states: dict[str, str]
    leases: dict[str, dict[str, Any]]
    ready_nodes: list[str]


class NodeDetailResponse(ApiModel):
    run_id: str
    node_id: str
    state: str | None
    output_records: list[dict[str, Any]]
    file_state_records: list[dict[str, Any]]
    active_lease: dict[str, Any] | None
    events: list[GraphEventResponse]


def _event_to_response(event: EventEnvelope) -> GraphEventResponse:
    return GraphEventResponse(
        event_id=event.event_id,
        event_type=event.event_type,
        run_id=event.run_id,
        position=event.position,
        timestamp=event.timestamp.isoformat(),
        payload=dict(event.payload),
    )


def build_graph_projection_response(
    run_id: str,
    events: list[EventEnvelope],
) -> GraphProjectionResponse:
    if not events:
        return GraphProjectionResponse(
            run_id=run_id,
            event_count=0,
            run_state=None,
            node_states={},
            task_states={},
            leases={},
            ready_nodes=[],
        )

    return GraphProjectionResponse(
        run_id=run_id,
        event_count=max(event.position for event in events),
        run_state=project_run_state(events),
        node_states=project_node_states(events),
        task_states=project_task_states(events),
        leases=project_leases(events),
        ready_nodes=project_ready_nodes(events),
    )


def _payload_has_node_value(value: Any, node_id: str) -> bool:
    if value == node_id:
        return True
    if isinstance(value, dict):
        return any(
            _payload_has_node_value(v, node_id) for v in cast(dict[str, Any], value).values()
        )
    if isinstance(value, (list, tuple)):
        return any(_payload_has_node_value(item, node_id) for item in cast(list[Any], value))
    return False


def _node_events_filter(event: EventEnvelope, node_id: str) -> bool:
    return _payload_has_node_value(event.payload, node_id)


def _pick_output_records(events: list[EventEnvelope], node_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in events:
        if event.event_type != "output_record_accepted":
            continue
        payload = event.payload
        if not isinstance(payload.get("record_kind"), str):
            continue
        if payload.get("record_kind") != "output":
            continue
        if payload.get("producer_node_id") != node_id:
            continue
        records.append(dict(payload))
    return records


def _pick_file_state_records(events: list[EventEnvelope], node_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in events:
        if event.event_type != "file_state_accepted":
            continue
        payload = event.payload
        if payload.get("producer_node_id") != node_id:
            continue
        records.append(dict(payload))
    return records


def _active_lease_for_node(
    leases: dict[str, dict[str, Any]], node_id: str
) -> dict[str, Any] | None:
    active: dict[str, Any] | None = None
    for lease in leases.values():
        if lease.get("node_id") != node_id:
            continue
        if lease.get("state") == "active":
            return dict(lease)
        if active is None:
            active = dict(lease)
    return active


def build_node_detail_response(
    run_id: str,
    node_id: str,
    events: list[EventEnvelope],
) -> NodeDetailResponse | None:
    node_events = [event for event in events if _node_events_filter(event, node_id)]
    if not node_events:
        return None

    node_states = project_node_states(events)
    leases = project_leases(events)
    state = node_states.get(node_id)
    output_records = _pick_output_records(events, node_id)
    file_state_records = _pick_file_state_records(events, node_id)
    active_lease = _active_lease_for_node(leases, node_id)

    return NodeDetailResponse(
        run_id=run_id,
        node_id=node_id,
        state=state,
        output_records=output_records,
        file_state_records=file_state_records,
        active_lease=active_lease,
        events=[_event_to_response(event) for event in node_events],
    )


@router.get("/{run_id}/graph", response_model=GraphProjectionResponse)
async def get_graph_projection(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> GraphProjectionResponse:
    events = await graph_store.read_run(run_id)
    if not events:
        return GraphProjectionResponse(
            run_id=run_id,
            event_count=0,
            run_state=None,
            node_states={},
            task_states={},
            leases={},
            ready_nodes=[],
        )
    return build_graph_projection_response(run_id, events)


@router.get("/{run_id}/graph/events", response_model=list[GraphEventResponse])
async def get_graph_events(
    run_id: str,
    from_position: int = Query(default=0, ge=0),
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> list[GraphEventResponse]:
    events = await graph_store.read_run(run_id, from_position=from_position)
    return [_event_to_response(event) for event in events]


@router.get("/{run_id}/graph/nodes/{node_id}", response_model=NodeDetailResponse)
async def get_graph_node_detail(
    run_id: str,
    node_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> NodeDetailResponse:
    events = await graph_store.read_run(run_id)
    if not events:
        raise HTTPException(status_code=404, detail="No graph projection found for run")

    detail = build_node_detail_response(run_id, node_id, events)
    if detail is None:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return detail
