"""Graph projection read-only API endpoints."""

from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query

from orchestrator.api.deps import get_graph_store
from orchestrator.api.schemas.base import ApiModel
from orchestrator.graph import (
    EventEnvelope,
    project_decision_view,
    project_leases,
    project_lease_view,
    project_node_metadata,
    project_node_states,
    project_ready_nodes,
    project_residue_report,
    project_gatekeeper_report,
    project_run_state,
    project_scheduler_view,
    project_task_states,
)
from orchestrator.graph_runtime.store import GraphEventStore, GraphEventSummary

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


class PendingGateDecisionResponse(ApiModel):
    node_id: str
    gate_type: str
    prompt: str | None = None


class AppealDecisionResponse(ApiModel):
    node_id: str
    state: str
    outcome: str | None = None


class ReviewReadinessResponse(ApiModel):
    ready: bool
    blockers: list[str]


class DecisionViewResponse(ApiModel):
    run_id: str
    event_count: int
    pending_gates: list[PendingGateDecisionResponse]
    appeals: list[AppealDecisionResponse]
    review: ReviewReadinessResponse


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


class FileStatePathResponse(ApiModel):
    path: str
    classification: str | None = None
    reason: str | None = None
    source: str | None = None
    matched_rule: str | None = None
    needs_gatekeeper: bool = False


class FileStateGatekeeperVerdictResponse(ApiModel):
    path: str
    verdict: str
    classification: str | None = None
    rationale: str | None = None
    confidence: float | None = None
    model_id: str | None = None


class FileStateDiffSummaryResponse(ApiModel):
    files_changed: int
    additions: int | None = None
    deletions: int | None = None


class FileStateBoundaryResponse(ApiModel):
    record_id: str
    node_id: str | None = None
    snapshot_id: str
    snapshot_type: str
    verdict: str | None = None
    classification_counts: dict[str, int]
    captured_paths: list[FileStatePathResponse]
    rejected_paths: list[FileStatePathResponse]
    gatekeeper_verdicts: list[FileStateGatekeeperVerdictResponse]
    diff_summary: FileStateDiffSummaryResponse | None = None


class FileStateNodeReportResponse(ApiModel):
    node_id: str
    boundaries: list[FileStateBoundaryResponse]


class FileStateReportResponse(ApiModel):
    run_id: str
    event_count: int
    nodes: list[FileStateNodeReportResponse]
    gatekeeper: dict[str, Any] | None = None


def _event_to_response(
    event: EventEnvelope,
    *,
    payload_mode: Literal["full", "summary"] = "full",
) -> GraphEventResponse:
    return GraphEventResponse(
        event_id=event.event_id,
        event_type=event.event_type,
        run_id=event.run_id,
        position=event.position,
        timestamp=event.timestamp.isoformat(),
        payload=_event_payload(event, payload_mode=payload_mode),
    )


def _summary_to_response(event: GraphEventSummary) -> GraphEventResponse:
    return GraphEventResponse(
        event_id=event.event_id,
        event_type=event.event_type,
        run_id=event.run_id,
        position=event.position,
        timestamp=event.timestamp,
        payload=_summary_payload(event.payload),
    )


def _event_payload(
    event: EventEnvelope,
    *,
    payload_mode: Literal["full", "summary"],
) -> dict[str, Any]:
    payload = dict(event.payload)
    if payload_mode == "full":
        return payload
    return _summary_payload(payload)


def _summary_payload(payload: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "accepted_patches",
        "actor_role",
        "blocker",
        "blockers",
        "command_type",
        "execution_id",
        "generation",
        "grade",
        "graph_verifier_grades",
        "kind",
        "lease_generation",
        "lease_id",
        "new_state",
        "node_id",
        "node_kind",
        "patch_id",
        "patch_ops",
        "patch_rejection_reasons",
        "producer_node_id",
        "proposed_by_node_id",
        "reason",
        "rejected_patches",
        "rejection_reason",
        "role",
        "state",
        "task_region_id",
        "tokens",
        "tokens_by_node",
        "tokens_by_node_kind",
    }
    summarized = {key: value for key, value in payload.items() if key in keys}
    ops = payload.get("ops") or payload.get("operations")
    if isinstance(ops, list):
        summarized["patch_ops"] = len(cast(list[Any], ops))
    value = payload.get("value")
    if isinstance(value, dict):
        typed_value = cast(dict[str, Any], value)
        grades = typed_value.get("grades")
        if grades is not None:
            summarized["value"] = {"grades": grades}
    grades = payload.get("grades")
    if grades is not None:
        summarized["grades"] = grades
    return summarized


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


def build_decision_view_response(
    run_id: str,
    events: list[EventEnvelope],
) -> DecisionViewResponse:
    if not events:
        return DecisionViewResponse(
            run_id=run_id,
            event_count=0,
            pending_gates=[],
            appeals=[],
            review=ReviewReadinessResponse(ready=False, blockers=[]),
        )

    view = project_decision_view(events)
    return DecisionViewResponse(
        run_id=run_id,
        event_count=max(event.position for event in events),
        pending_gates=[PendingGateDecisionResponse(**entry) for entry in view["pending_gates"]],
        appeals=[AppealDecisionResponse(**entry) for entry in view["appeals"]],
        review=ReviewReadinessResponse(**view["review"]),
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


def _path_text(entry: dict[str, Any]) -> str | None:
    path = entry.get("path")
    return path if isinstance(path, str) else None


def _record_path_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("classifications", "residue", "tracked", "untracked", "ignored", "external"):
        raw_entries = record.get(key)
        if not isinstance(raw_entries, list):
            continue
        for raw_entry in cast(list[Any], raw_entries):
            if not isinstance(raw_entry, dict):
                continue
            entry = dict(cast(dict[str, Any], raw_entry))
            path = _path_text(entry)
            if path is None or path in seen:
                continue
            seen.add(path)
            entries.append(entry)
    return entries


def _rejected_path_entries(record: dict[str, Any]) -> list[FileStatePathResponse]:
    raw_entries = record.get("rejected_paths")
    if not isinstance(raw_entries, list):
        return []
    entries: list[FileStatePathResponse] = []
    for raw_entry in cast(list[Any], raw_entries):
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, Any], raw_entry)
        path = _path_text(entry)
        if path is None:
            continue
        reason = entry.get("reason") or entry.get("matched_rule") or entry.get("policy")
        entries.append(
            FileStatePathResponse(
                path=path,
                classification=cast(str | None, entry.get("classification")),
                reason=cast(str | None, reason),
                source=cast(str | None, entry.get("source")),
                matched_rule=cast(str | None, entry.get("matched_rule")),
                needs_gatekeeper=entry.get("needs_gatekeeper") is True,
            )
        )
    return entries


def _residue_by_record_path(
    residue_report: dict[str, list[dict[str, Any]]],
) -> dict[tuple[str, str], dict[str, Any]]:
    by_record: dict[tuple[str, str], dict[str, Any]] = {}
    for path, entries in residue_report.items():
        for entry in entries:
            record_id = entry.get("record_id")
            if isinstance(record_id, str):
                by_record[(record_id, path)] = entry
    return by_record


def _gatekeeper_verdicts_by_record(
    events: list[EventEnvelope],
) -> dict[str, list[FileStateGatekeeperVerdictResponse]]:
    by_record: dict[str, list[FileStateGatekeeperVerdictResponse]] = {}
    for event in events:
        if event.event_type != "gatekeeper_verdict_recorded":
            continue
        record_id = event.payload.get("file_state_record_id")
        verdicts = event.payload.get("verdicts")
        if not isinstance(record_id, str) or not isinstance(verdicts, list):
            continue
        for raw_verdict in cast(list[Any], verdicts):
            if not isinstance(raw_verdict, dict):
                continue
            verdict = cast(dict[str, Any], raw_verdict)
            path = verdict.get("path")
            if not isinstance(path, str):
                continue
            classification = cast(str | None, verdict.get("classification"))
            by_record.setdefault(record_id, []).append(
                FileStateGatekeeperVerdictResponse(
                    path=path,
                    verdict="reject" if classification == "secret" else "allow",
                    classification=classification,
                    rationale=cast(str | None, verdict.get("rationale")),
                    confidence=cast(float | None, verdict.get("confidence")),
                    model_id=cast(str | None, verdict.get("model_id")),
                )
            )
    return by_record


def _snapshot_type(record: dict[str, Any]) -> str:
    git = record.get("git")
    if isinstance(git, dict) and isinstance(cast(dict[str, Any], git).get("commit_sha"), str):
        return "git_commit"
    return "manifest"


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _diff_summary(
    record: dict[str, Any],
    captured_paths: list[FileStatePathResponse],
) -> FileStateDiffSummaryResponse | None:
    if _snapshot_type(record) != "git_commit":
        return None
    raw_summary: Any = record.get("diff_summary")
    git = record.get("git")
    if raw_summary is None and isinstance(git, dict):
        raw_summary = cast(dict[str, Any], git).get("diff_summary")
    if isinstance(raw_summary, dict):
        summary = cast(dict[str, Any], raw_summary)
        files_changed = _optional_int(summary.get("files_changed")) or len(captured_paths)
        return FileStateDiffSummaryResponse(
            files_changed=files_changed,
            additions=_optional_int(summary.get("additions")),
            deletions=_optional_int(summary.get("deletions")),
        )
    return FileStateDiffSummaryResponse(files_changed=len(captured_paths))


def _file_state_boundary_response(
    record: dict[str, Any],
    residue_by_path: dict[tuple[str, str], dict[str, Any]],
    gatekeeper_verdicts: dict[str, list[FileStateGatekeeperVerdictResponse]],
) -> FileStateBoundaryResponse | None:
    record_id = record.get("record_id")
    snapshot_id = record.get("snapshot_id")
    if not isinstance(record_id, str) or not isinstance(snapshot_id, str):
        return None

    counts: dict[str, int] = {}
    captured_paths: list[FileStatePathResponse] = []
    for entry in _record_path_entries(record):
        path = _path_text(entry)
        if path is None:
            continue
        residue = residue_by_path.get((record_id, path), {})
        classification = residue.get("classification", entry.get("classification"))
        if isinstance(classification, str):
            counts[classification] = counts.get(classification, 0) + 1
        captured_paths.append(
            FileStatePathResponse(
                path=path,
                classification=cast(str | None, classification),
                reason=cast(str | None, entry.get("reason")),
                source=cast(str | None, residue.get("source", entry.get("source"))),
                matched_rule=cast(
                    str | None,
                    residue.get("matched_rule", entry.get("matched_rule")),
                ),
                needs_gatekeeper=residue.get("needs_gatekeeper", entry.get("needs_gatekeeper"))
                is True,
            )
        )

    rejected_paths = _rejected_path_entries(record)
    for rejected in rejected_paths:
        if rejected.classification is not None:
            counts[rejected.classification] = counts.get(rejected.classification, 0) + 1

    return FileStateBoundaryResponse(
        record_id=record_id,
        node_id=cast(str | None, record.get("producer_node_id")),
        snapshot_id=snapshot_id,
        snapshot_type=_snapshot_type(record),
        verdict=cast(str | None, record.get("verdict")),
        classification_counts={key: counts[key] for key in sorted(counts)},
        captured_paths=captured_paths,
        rejected_paths=rejected_paths,
        gatekeeper_verdicts=gatekeeper_verdicts.get(record_id, []),
        diff_summary=_diff_summary(record, captured_paths),
    )


def build_file_state_report_response(
    run_id: str,
    events: list[EventEnvelope],
) -> FileStateReportResponse:
    if not events:
        return FileStateReportResponse(run_id=run_id, event_count=0, nodes=[], gatekeeper=None)

    residue_report = project_residue_report(events)
    gatekeeper_report = project_gatekeeper_report(events).get(run_id)
    residue_by_path = _residue_by_record_path(residue_report)
    gatekeeper_verdicts = _gatekeeper_verdicts_by_record(events)
    by_node: dict[str, list[FileStateBoundaryResponse]] = {}
    for event in events:
        if event.event_type != "file_state_accepted":
            continue
        boundary = _file_state_boundary_response(
            dict(event.payload),
            residue_by_path,
            gatekeeper_verdicts,
        )
        if boundary is None:
            continue
        node_id = boundary.node_id or "unknown"
        by_node.setdefault(node_id, []).append(boundary)

    return FileStateReportResponse(
        run_id=run_id,
        event_count=max(event.position for event in events),
        nodes=[
            FileStateNodeReportResponse(node_id=node_id, boundaries=boundaries)
            for node_id, boundaries in sorted(by_node.items())
        ],
        gatekeeper=gatekeeper_report,
    )


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
    *,
    payload_mode: Literal["full", "summary"] = "full",
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
        callback_history=[
            _event_to_response(event, payload_mode=payload_mode) for event in callback_history
        ],
        events=[_event_to_response(event, payload_mode=payload_mode) for event in node_events],
    )


@router.get("/{run_id}/graph", response_model=GraphProjectionResponse)
async def get_graph_projection(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> GraphProjectionResponse:
    events = await graph_store.read_run_projection(run_id)
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
    payload_mode: Literal["summary", "full"] = Query(default="summary"),
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> list[GraphEventResponse]:
    if payload_mode == "summary":
        summaries = await graph_store.read_run_summaries(run_id, from_position=from_position)
        return [_summary_to_response(event) for event in summaries]
    events = await graph_store.read_run(run_id, from_position=from_position)
    return [_event_to_response(event) for event in events]


@router.get("/{run_id}/graph/scheduler", response_model=SchedulerViewResponse)
async def get_graph_scheduler_view(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> SchedulerViewResponse:
    events = await graph_store.read_run_light(run_id)
    return build_scheduler_view_response(run_id, events)


@router.get("/{run_id}/graph/decisions", response_model=DecisionViewResponse)
async def get_graph_decision_view(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> DecisionViewResponse:
    events = await graph_store.read_run_light(run_id)
    return build_decision_view_response(run_id, events)


@router.get("/{run_id}/graph/file-state", response_model=FileStateReportResponse)
async def get_graph_file_state_report(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> FileStateReportResponse:
    events = await graph_store.read_run(run_id)
    return build_file_state_report_response(run_id, events)


@router.get("/{run_id}/graph/nodes/{node_id}", response_model=NodeDetailResponse)
async def get_graph_node_detail(
    run_id: str,
    node_id: str,
    payload_mode: Literal["summary", "full"] = Query(default="summary"),
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> NodeDetailResponse:
    if payload_mode == "full":
        events = await graph_store.read_run(run_id)
    else:
        events = await graph_store.read_run_node_detail(run_id)
    if not events:
        raise HTTPException(status_code=404, detail="No graph projection found for run")

    detail = build_node_detail_response(run_id, node_id, events, payload_mode=payload_mode)
    if detail is None:
        raise HTTPException(status_code=404, detail="Graph node not found")
    return detail
