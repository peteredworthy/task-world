"""Graph projection read-only API endpoints."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query

from orchestrator.api.deps import get_graph_store
from orchestrator.api.schemas.base import ApiModel
from orchestrator.graph import EventEnvelope
from orchestrator.graph.projections import (
    project_leases,
    project_lease_view,
    project_node_metadata,
    project_node_states,
    project_ready_nodes,
    project_run_state,
    project_scheduler_view,
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


class SchedulerBlockedNodeResponse(ApiModel):
    node_id: str
    reason: str


class SchedulerViewResponseBody(ApiModel):
    ready: list[str]
    blocked: list[SchedulerBlockedNodeResponse]
    waiting_resources: list[SchedulerBlockedNodeResponse]
    waiting_gates: list[SchedulerBlockedNodeResponse]


class LeaseViewEntryResponse(ApiModel):
    lease_id: str
    node_id: str
    generation: int | None = None
    state: str
    execution_id: str | None = None
    expires_at: str | None = None


class LeaseViewResponse(ApiModel):
    active: list[LeaseViewEntryResponse]
    suspended: list[LeaseViewEntryResponse]


class SchedulerViewResponse(ApiModel):
    run_id: str
    event_count: int
    scheduler: SchedulerViewResponseBody
    leases: LeaseViewResponse


class NodeDetailResponse(ApiModel):
    run_id: str
    node_id: str
    kind: str | None
    role: str | None
    state: str | None
    input_ports: dict[str, list[str]]
    output_records: list[dict[str, Any]]
    file_state_records: list[dict[str, Any]]
    active_lease: dict[str, Any] | None
    callback_history: list[GraphEventResponse]
    events: list[GraphEventResponse]
    prompt_summary: dict[str, Any] | None = None


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


def build_scheduler_view_response(
    run_id: str,
    events: list[EventEnvelope],
) -> SchedulerViewResponse:
    if not events:
        return SchedulerViewResponse(
            run_id=run_id,
            event_count=0,
            scheduler=SchedulerViewResponseBody(
                ready=[],
                blocked=[],
                waiting_resources=[],
                waiting_gates=[],
            ),
            leases=LeaseViewResponse(active=[], suspended=[]),
        )

    scheduler_view = project_scheduler_view(events)
    lease_view = project_lease_view(events)
    return SchedulerViewResponse(
        run_id=run_id,
        event_count=max(event.position for event in events),
        scheduler=SchedulerViewResponseBody(
            ready=scheduler_view["ready"],
            blocked=[SchedulerBlockedNodeResponse(**entry) for entry in scheduler_view["blocked"]],
            waiting_resources=[
                SchedulerBlockedNodeResponse(**entry)
                for entry in scheduler_view["waiting_resources"]
            ],
            waiting_gates=[
                SchedulerBlockedNodeResponse(**entry) for entry in scheduler_view["waiting_gates"]
            ],
        ),
        leases=LeaseViewResponse(
            active=[LeaseViewEntryResponse(**entry) for entry in lease_view["active"]],
            suspended=[LeaseViewEntryResponse(**entry) for entry in lease_view["suspended"]],
        ),
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
        if payload.get("record_kind") == "file_state":
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
        record = dict(payload)
        record["classification_summary"] = _classification_summary(record)
        records.append(record)
    return records


def _classification_summary(record: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "verdict": record.get("verdict"),
        "total_paths": 0,
        "needs_gatekeeper": 0,
        "classifications": {},
    }
    class_counts: dict[str, int] = {}
    for key in ("tracked", "untracked", "ignored", "external", "classifications", "residue"):
        entries = record.get(key)
        if not isinstance(entries, list):
            continue
        summary[key] = len(cast(list[Any], entries))
        for raw_entry in cast(list[Any], entries):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, Any], raw_entry)
            summary["total_paths"] = int(summary["total_paths"]) + 1
            if entry.get("needs_gatekeeper") is True:
                summary["needs_gatekeeper"] = int(summary["needs_gatekeeper"]) + 1
            classification = entry.get("classification")
            if isinstance(classification, str):
                class_counts[classification] = class_counts.get(classification, 0) + 1
    rejected_paths = record.get("rejected_paths")
    if isinstance(rejected_paths, list):
        summary["rejected_paths"] = len(cast(list[Any], rejected_paths))
    summary["classifications"] = class_counts
    return summary


def _is_callback_history_event(event: EventEnvelope) -> bool:
    if event.event_type in {
        "callback_accepted",
        "callback_rejected_stale",
        "callback_rejected_conflict",
        "callback_duplicate_returned",
        "agent_died",
    }:
        return True
    return (
        event.event_type == "node_state_changed"
        and event.payload.get("trigger") == "runtime_start_acknowledged"
    )


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
    node_metadata = project_node_metadata(events)
    leases = project_leases(events)
    state = node_states.get(node_id)
    metadata = node_metadata.get(node_id, {})
    output_records = _pick_output_records(events, node_id)
    file_state_records = _pick_file_state_records(events, node_id)
    active_lease = _active_lease_for_node(leases, node_id)
    callback_history = [event for event in node_events if _is_callback_history_event(event)]

    return NodeDetailResponse(
        run_id=run_id,
        node_id=node_id,
        kind=cast(str | None, metadata.get("kind")),
        role=cast(str | None, metadata.get("role")),
        state=state,
        input_ports=cast(dict[str, list[str]], metadata.get("input_ports", {})),
        output_records=output_records,
        file_state_records=file_state_records,
        active_lease=active_lease,
        callback_history=[_event_to_response(event) for event in callback_history],
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


@router.get("/{run_id}/graph/scheduler", response_model=SchedulerViewResponse)
async def get_graph_scheduler_view(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> SchedulerViewResponse:
    events = await graph_store.read_run(run_id)
    return build_scheduler_view_response(run_id, events)


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
