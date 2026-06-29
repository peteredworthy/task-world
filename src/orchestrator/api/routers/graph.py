"""Graph projection API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api.deps import get_graph_store, get_session_factory, get_workflow_service
from orchestrator.api.schemas.base import ApiModel
from orchestrator.config import RunStatus
from orchestrator.graph import (
    EventEnvelope,
    check_command_reference,
    project_final_invariant_blockers,
    project_graph_patch_attempts,
    node_contract_summary,
    project_decision_view,
    project_graph_topology,
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
from orchestrator.graph_runtime import GraphController, StaleProjectionError
from orchestrator.graph_runtime.store import (
    GraphEventStore,
    GraphEventSummary,
    GraphNodeDetailSummary,
)
from orchestrator.state import RunNotFoundError

router = APIRouter(prefix="/api/runs", tags=["graph"])

_NODE_DETAIL_MAX_TEXT_CHARS = 1_000_000
_NODE_DETAIL_MAX_LIST_ITEMS = 200


class _ApiGraphClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class _ApiGraphIdGenerator:
    def next_id(self, prefix: str = "") -> str:
        return f"{prefix}-{uuid4().hex}"


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


class GraphTopologyNodeResponse(ApiModel):
    node_id: str
    kind: str | None = None
    role: str | None = None
    state: str | None = None
    contract: dict[str, Any] | None = None


class GraphTopologyBoundRecordResponse(ApiModel):
    record_id: str
    record_type: str | None = None
    record_kind: str | None = None
    schema_: str | None = Field(default=None, alias="schema")
    producer_node_id: str | None = None
    producer_port: str | None = None
    position: int | None = None


class GraphTopologyBindingResponse(ApiModel):
    edge_id: str | None = None
    to_node_id: str | None = None
    to_port: str | None = None
    record_ids: list[str]
    bound_at_position: int | None = None
    record_bound_positions: dict[str, int] | None = None
    binding_policy: str | None = None
    trigger: str | None = None


class GraphTopologyEdgeResponse(ApiModel):
    edge_id: str
    from_node_id: str
    from_port: str
    to_node_id: str
    to_port: str
    required: bool
    dependency_type: str
    accepted_record_selector: dict[str, Any] | None = None
    metadata: dict[str, Any]
    source_port_contract: dict[str, Any] | None = None
    target_port_contract: dict[str, Any] | None = None
    record_types: list[str]
    binding: GraphTopologyBindingResponse | None = None
    bound_records: list[GraphTopologyBoundRecordResponse]


class GraphTopologyResponse(ApiModel):
    run_id: str
    event_count: int
    nodes: list[GraphTopologyNodeResponse]
    edges: list[GraphTopologyEdgeResponse]


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
    options: list[str] | None = None
    default_option: str | None = None
    consequence_summary: str | None = None
    expires_at: str | None = None
    requested_authority: list[str] | None = None
    target_node_id: str | None = None
    target_region_id: str | None = None


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


class RecordGraphDecisionRequest(ApiModel):
    decision_type: Literal["approval", "authority", "oversight"]
    node_id: str = Field(min_length=1, max_length=200)
    decision: str = Field(min_length=1, max_length=64)
    decider: dict[str, Any] | str
    scope: dict[str, Any] | None = None
    expires_at: str | None = None
    reason: str | None = None
    record_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_decision_request(self) -> "RecordGraphDecisionRequest":
        valid_by_type = {
            "approval": {"approved", "rejected", "deferred", "defer"},
            "authority": {"granted", "denied", "deferred", "grant", "deny", "defer"},
            "oversight": {"accepted", "rejected", "invalid_test_accepted"},
        }
        valid = valid_by_type[self.decision_type]
        if self.decision not in valid:
            options = ", ".join(sorted(valid))
            raise ValueError(f"decision for {self.decision_type} must be one of: {options}")
        if isinstance(self.decider, str):
            if not self.decider:
                raise ValueError("decider must be a non-empty string or an actor object")
            return self
        if not isinstance(self.decider.get("kind"), str) or not self.decider["kind"]:
            raise ValueError("decider actor object must include a non-empty kind")
        return self


class RecordGraphDecisionResponse(ApiModel):
    run_id: str
    graph_position: int
    events: list[GraphEventResponse]
    decision_view: DecisionViewResponse


class SchedulerViewResponse(ApiModel):
    run_id: str
    event_count: int
    scheduler: SchedulerViewResponseBody
    leases: LeaseViewResponse


def _empty_dict_items() -> list[dict[str, Any]]:
    return []


def _empty_str_items() -> list[str]:
    return []


class NodeDetailResponse(ApiModel):
    run_id: str
    node_id: str
    kind: str | None
    role: str | None
    state: str | None
    task_region_id: str | None = None
    contract: dict[str, Any] | None = None
    resource_claims: list[dict[str, Any]] = Field(default_factory=_empty_dict_items)
    allowed_actions: list[str] = Field(default_factory=_empty_str_items)
    preconditions: list[str] = Field(default_factory=_empty_str_items)
    command_definition: dict[str, Any] | None = None
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


class GraphPatchAttemptResponse(ApiModel):
    patch_id: str
    proposed_by_node_id: str | None = None
    base_graph_position: int | None = None
    current_graph_position: int
    status: Literal["accepted", "rejected"]
    rejection_reason: str | None = None
    diagnostics: dict[str, Any] | None = None
    read_set_diff: dict[str, Any] | None = None
    accepted_event_id: str | None = None
    accepted_position: int | None = None
    rejected_event_id: str | None = None
    rejected_position: int | None = None
    created_node_ids: list[str] = Field(default_factory=list)
    created_edge_ids: list[str] = Field(default_factory=list)


class GraphPatchAttemptsResponse(ApiModel):
    run_id: str
    current_graph_position: int
    attempts: list[GraphPatchAttemptResponse]


class FinalInvariantBlockerResponse(ApiModel):
    kind: str
    reason: str
    node_id: str | None = None
    edge_id: str | None = None
    to_port: str | None = None
    proposal_id: str | None = None
    requirement_id: str | None = None
    revision_id: str | None = None
    task_region_id: str | None = None
    state: str | None = None
    support_ids: list[str] | None = None


class FinalInvariantBlockersResponse(ApiModel):
    run_id: str
    event_count: int
    blockers: list[FinalInvariantBlockerResponse]


class GraphRegionResponse(ApiModel):
    task_region_id: str
    state: str
    blockers: list[FinalInvariantBlockerResponse]


class GraphRegionsResponse(ApiModel):
    run_id: str
    event_count: int
    regions: list[GraphRegionResponse]


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
        "allowed_actions",
        "authority",
        "blocker",
        "blockers",
        "command_type",
        "command_definition",
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
        "port",
        "producer_node_id",
        "preconditions",
        "proposed_by_node_id",
        "reason",
        "record_id",
        "record_kind",
        "rejected_patches",
        "rejection_reason",
        "resource_claims",
        "role",
        "state",
        "task_region_id",
        "to_state",
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


def build_graph_projection_response_from_snapshot(
    run_id: str,
    snapshot: Any | None,
) -> GraphProjectionResponse:
    if snapshot is None:
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
        event_count=int(snapshot.position),
        run_state=cast(str | None, snapshot.run_state),
        node_states=cast(dict[str, str], snapshot.node_states),
        task_states=cast(dict[str, str], snapshot.task_states),
        leases=cast(dict[str, dict[str, Any]], snapshot.leases),
        ready_nodes=cast(list[str], snapshot.ready_nodes),
    )


def _graph_api_run_state(
    projected_run_state: str | None,
    run_status: RunStatus | None,
) -> str | None:
    if projected_run_state is None or run_status is None:
        return projected_run_state
    if run_status in {
        RunStatus.PAUSED,
        RunStatus.STOPPING,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
    }:
        return run_status.value
    return projected_run_state


def build_graph_topology_response(
    run_id: str,
    events: list[EventEnvelope],
) -> GraphTopologyResponse:
    if not events:
        return GraphTopologyResponse(run_id=run_id, event_count=0, nodes=[], edges=[])

    topology = project_graph_topology(events)
    return GraphTopologyResponse(
        run_id=run_id,
        event_count=max(event.position for event in events),
        nodes=[
            GraphTopologyNodeResponse(**cast(dict[str, Any], node)) for node in topology["nodes"]
        ],
        edges=[
            GraphTopologyEdgeResponse(**cast(dict[str, Any], edge)) for edge in topology["edges"]
        ],
    )


def build_graph_patch_attempts_response(
    run_id: str,
    events: list[EventEnvelope],
    *,
    current_graph_position: int | None = None,
) -> GraphPatchAttemptsResponse:
    if current_graph_position is None:
        current_graph_position = max((event.position for event in events), default=0)
    attempts = project_graph_patch_attempts(
        events,
        run_id=run_id,
        current_graph_position=current_graph_position,
    )
    return GraphPatchAttemptsResponse(
        run_id=run_id,
        current_graph_position=current_graph_position,
        attempts=[GraphPatchAttemptResponse(**entry) for entry in attempts["attempts"]],
    )


def build_final_invariant_blockers_response(
    run_id: str,
    events: list[EventEnvelope],
) -> FinalInvariantBlockersResponse:
    return FinalInvariantBlockersResponse(
        run_id=run_id,
        event_count=max((event.position for event in events), default=0),
        blockers=[
            FinalInvariantBlockerResponse(**cast(dict[str, Any], blocker))
            for blocker in project_final_invariant_blockers(events)
        ],
    )


def build_graph_regions_response(
    run_id: str,
    events: list[EventEnvelope],
) -> GraphRegionsResponse:
    if not events:
        return GraphRegionsResponse(run_id=run_id, event_count=0, regions=[])
    task_states = project_task_states(events)
    blockers = project_final_invariant_blockers(events)
    blockers_by_region: dict[str, list[FinalInvariantBlockerResponse]] = {}
    for blocker in blockers:
        task_region_id = blocker.get("task_region_id")
        if not isinstance(task_region_id, str) or not task_region_id:
            continue
        blockers_by_region.setdefault(task_region_id, []).append(
            FinalInvariantBlockerResponse(**cast(dict[str, Any], blocker))
        )
    region_ids = sorted(set(task_states) | set(blockers_by_region))
    return GraphRegionsResponse(
        run_id=run_id,
        event_count=max(event.position for event in events),
        regions=[
            GraphRegionResponse(
                task_region_id=region_id,
                state=task_states.get(region_id, "blocked"),
                blockers=blockers_by_region.get(region_id, []),
            )
            for region_id in region_ids
        ],
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


def build_scheduler_view_response_from_snapshot(
    run_id: str,
    snapshot: Any | None,
) -> SchedulerViewResponse:
    if snapshot is None:
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
    scheduler_view = cast(dict[str, Any], snapshot.scheduler)
    lease_view = cast(dict[str, Any], snapshot.lease_view)
    return SchedulerViewResponse(
        run_id=run_id,
        event_count=int(snapshot.position),
        scheduler=SchedulerViewResponseBody(
            ready=cast(list[str], scheduler_view.get("ready", [])),
            blocked=[
                SchedulerBlockedNodeResponse(**entry)
                for entry in cast(list[dict[str, Any]], scheduler_view.get("blocked", []))
            ],
            waiting_resources=[
                SchedulerBlockedNodeResponse(**entry)
                for entry in cast(
                    list[dict[str, Any]],
                    scheduler_view.get("waiting_resources", []),
                )
            ],
            waiting_gates=[
                SchedulerBlockedNodeResponse(**entry)
                for entry in cast(list[dict[str, Any]], scheduler_view.get("waiting_gates", []))
            ],
        ),
        leases=LeaseViewResponse(
            active=[
                LeaseViewEntryResponse(**entry)
                for entry in cast(list[dict[str, Any]], lease_view.get("active", []))
            ],
            suspended=[
                LeaseViewEntryResponse(**entry)
                for entry in cast(list[dict[str, Any]], lease_view.get("suspended", []))
            ],
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


def build_decision_view_response_from_snapshot(
    run_id: str,
    snapshot: Any | None,
) -> DecisionViewResponse:
    if snapshot is None:
        return DecisionViewResponse(
            run_id=run_id,
            event_count=0,
            pending_gates=[],
            appeals=[],
            review=ReviewReadinessResponse(ready=False, blockers=[]),
        )
    view = cast(dict[str, Any], snapshot.decisions)
    return DecisionViewResponse(
        run_id=run_id,
        event_count=int(snapshot.position),
        pending_gates=[
            PendingGateDecisionResponse(**entry)
            for entry in cast(list[dict[str, Any]], view.get("pending_gates", []))
        ],
        appeals=[
            AppealDecisionResponse(**entry)
            for entry in cast(list[dict[str, Any]], view.get("appeals", []))
        ],
        review=ReviewReadinessResponse(
            **cast(dict[str, Any], view.get("review", {"ready": False, "blockers": []}))
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
        rejected_count = len(cast(list[Any], rejected_paths))
        summary["rejected_paths"] = rejected_count
        summary["total_paths"] = int(summary["total_paths"]) + rejected_count
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
        task_region_id=cast(str | None, metadata.get("task_region_id")),
        contract=cast(dict[str, Any] | None, metadata.get("contract")),
        resource_claims=cast(list[dict[str, Any]], metadata.get("resource_claims", [])),
        allowed_actions=cast(list[str], metadata.get("allowed_actions", [])),
        preconditions=cast(list[str], metadata.get("preconditions", [])),
        command_definition=cast(dict[str, Any] | None, metadata.get("command_definition")),
        input_ports=cast(dict[str, list[str]], metadata.get("input_ports", {})),
        output_records=output_records,
        file_state_records=file_state_records,
        active_lease=active_lease,
        callback_history=[
            _event_to_response(event, payload_mode=payload_mode) for event in callback_history
        ],
        events=[_event_to_response(event, payload_mode=payload_mode) for event in node_events],
        prompt_summary=_latest_prompt_summary(node_events),
    )


def _latest_prompt_summary(events: list[EventEnvelope]) -> dict[str, Any] | None:
    for event in reversed(events):
        prompt_summary = event.payload.get("prompt_summary")
        if isinstance(prompt_summary, dict):
            return dict(cast(dict[str, Any], prompt_summary))
    return None


def build_node_detail_response_from_summary(
    summary: GraphNodeDetailSummary,
    *,
    full_events: list[EventEnvelope] | None = None,
) -> NodeDetailResponse:
    controls = _node_detail_controls_from_summary(summary)
    response_events = [GraphEventResponse(**event) for event in summary.events]
    callback_history = [GraphEventResponse(**event) for event in summary.callback_history]
    output_records = summary.output_records
    file_state_records = summary.file_state_records
    if full_events is not None:
        response_events = _full_node_event_responses(summary.events, full_events)
        callback_history = _full_node_event_responses(summary.callback_history, full_events)
        output_records = _bounded_node_detail_records(
            _pick_output_records(full_events, summary.node_id)
        )
        file_state_records = _bounded_node_detail_records(
            _pick_file_state_records(full_events, summary.node_id)
        )
    return NodeDetailResponse(
        run_id=summary.run_id,
        node_id=summary.node_id,
        kind=summary.kind,
        role=summary.role,
        state=summary.state,
        task_region_id=summary.task_region_id,
        contract=node_contract_summary(summary.kind, summary.role),
        resource_claims=controls["resource_claims"],
        allowed_actions=controls["allowed_actions"],
        preconditions=controls["preconditions"],
        command_definition=controls["command_definition"],
        input_ports=summary.input_ports,
        output_records=output_records,
        file_state_records=file_state_records,
        active_lease=summary.active_lease,
        callback_history=callback_history,
        events=response_events,
        prompt_summary=summary.prompt_summary,
    )


def _full_node_event_responses(
    compact_events: list[dict[str, Any]],
    full_events: list[EventEnvelope],
) -> list[GraphEventResponse]:
    full_by_position = {event.position: event for event in full_events}
    responses: list[GraphEventResponse] = []
    for compact_event in compact_events:
        position = compact_event.get("position")
        full_event = full_by_position.get(position) if isinstance(position, int) else None
        if full_event is None:
            responses.append(GraphEventResponse(**compact_event))
        else:
            responses.append(_node_detail_full_event_response(full_event))
    return responses


def _node_detail_full_event_response(event: EventEnvelope) -> GraphEventResponse:
    return GraphEventResponse(
        event_id=event.event_id,
        event_type=event.event_type,
        run_id=event.run_id,
        position=event.position,
        timestamp=event.timestamp.isoformat(),
        payload=_node_detail_full_event_payload(event),
    )


def _node_detail_full_event_payload(event: EventEnvelope) -> dict[str, Any]:
    payload = dict(event.payload)
    if event.event_type in {
        "callback_accepted",
        "output_record_accepted",
        "file_state_accepted",
    }:
        return _compact_node_detail_record_payload(payload)
    return payload


def _bounded_node_detail_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], _bounded_node_detail_value(record)) for record in records]


def _bounded_node_detail_value(value: Any) -> Any:
    if isinstance(value, dict):
        bounded: dict[str, Any] = {}
        truncated_fields: list[dict[str, Any]] = []
        for key, child in cast(dict[str, Any], value).items():
            if isinstance(child, str) and len(child) > _NODE_DETAIL_MAX_TEXT_CHARS:
                digest = sha256(child.encode("utf-8")).hexdigest()
                bounded[key] = (
                    child[:_NODE_DETAIL_MAX_TEXT_CHARS]
                    + f"\n...[truncated {len(child) - _NODE_DETAIL_MAX_TEXT_CHARS} chars]"
                )
                truncated_fields.append(
                    {
                        "field": key,
                        "original_length": len(child),
                        "sha256": digest,
                    }
                )
                continue
            if isinstance(child, list):
                child_items = cast(list[Any], child)
                if len(child_items) <= _NODE_DETAIL_MAX_LIST_ITEMS:
                    bounded[key] = _bounded_node_detail_value(child_items)
                    continue
                bounded[key] = [
                    _bounded_node_detail_value(item)
                    for item in child_items[:_NODE_DETAIL_MAX_LIST_ITEMS]
                ]
                truncated_fields.append(
                    {
                        "field": key,
                        "original_length": len(child_items),
                        "retained_items": _NODE_DETAIL_MAX_LIST_ITEMS,
                    }
                )
                continue
            bounded[key] = _bounded_node_detail_value(child)
        if truncated_fields:
            bounded["__truncated_fields"] = truncated_fields
        return bounded
    if isinstance(value, list):
        return [_bounded_node_detail_value(item) for item in cast(list[Any], value)]
    return value


def _compact_node_detail_record_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact_keys = {
        "accepted_patches",
        "attempt_number",
        "base_snapshot_id",
        "candidate_id",
        "created_at",
        "execution_id",
        "generation",
        "graph_position",
        "idempotency_key",
        "lease_generation",
        "lease_id",
        "new_state",
        "node_id",
        "observed_graph_position",
        "payload_hash",
        "port",
        "producer_node_id",
        "producer_port",
        "prompt_summary",
        "record_id",
        "record_kind",
        "record_type",
        "reason",
        "rejected_patches",
        "schema",
        "schema_version",
        "snapshot_id",
        "state",
        "task_region_id",
        "verdict",
    }
    compact = {key: value for key, value in payload.items() if key in compact_keys}
    for records_key in ("output_records", "file_state_records"):
        records = payload.get(records_key)
        if isinstance(records, list):
            compact[records_key] = [
                _compact_node_detail_record_payload(cast(dict[str, Any], record))
                for record in cast(list[Any], records)
                if isinstance(record, dict)
            ]
            compact[f"{records_key}_payload_mode"] = "summary"
    nested_payload = payload.get("payload")
    if isinstance(nested_payload, dict):
        compact["payload"] = _compact_node_detail_record_payload(
            cast(dict[str, Any], nested_payload)
        )
    if "value" in payload and _node_detail_record_value_is_small_control_payload(payload):
        compact["value"] = _bounded_node_detail_value(payload["value"])
    return compact


def _node_detail_record_value_is_small_control_payload(payload: dict[str, Any]) -> bool:
    return payload.get("record_type") in {
        "authority_request_record",
        "decision_request",
    } or payload.get("port") in {
        "authority_request_record",
        "decision_request",
    }


def _compact_event_positions(events: list[dict[str, Any]]) -> list[int]:
    positions: list[int] = []
    seen: set[int] = set()
    for event in events:
        position = event.get("position")
        if not isinstance(position, int) or isinstance(position, bool) or position <= 0:
            continue
        if position in seen:
            continue
        seen.add(position)
        positions.append(position)
    return positions


def _node_detail_controls_from_summary(
    summary: GraphNodeDetailSummary,
) -> dict[str, Any]:
    resource_claims: list[dict[str, Any]] = []
    allowed_actions: list[str] = []
    preconditions: list[str] = []
    command_definition: dict[str, Any] | None = None

    for event in summary.events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        payload = cast(dict[str, Any], payload)
        if payload.get("node_id") != summary.node_id:
            continue
        event_claims = _resource_claims_from_payload(payload)
        if event_claims:
            resource_claims = event_claims
        event_allowed_actions = _string_list_from_payload(
            payload,
            "allowed_actions",
        )
        if event_allowed_actions:
            allowed_actions = event_allowed_actions
        event_preconditions = _string_list_from_payload(
            payload,
            "preconditions",
        )
        if event_preconditions:
            preconditions = event_preconditions
        raw_command_definition = payload.get("command_definition")
        if isinstance(raw_command_definition, dict):
            command_definition = dict(cast(dict[str, Any], raw_command_definition))
        elif summary.kind == "check":
            raw_command_reference = check_command_reference(payload)
            if isinstance(raw_command_reference, dict):
                command_definition = dict(cast(dict[str, Any], raw_command_reference))

    if (
        summary.kind == "check"
        and command_definition is not None
        and "has_command_definition" not in preconditions
    ):
        preconditions = [*preconditions, "has_command_definition"]

    if not resource_claims:
        for lease in summary.leases:
            raw_claims = lease.get("resource_claims")
            if isinstance(raw_claims, list):
                claims = [
                    dict(cast(dict[str, Any], claim))
                    for claim in cast(list[Any], raw_claims)
                    if isinstance(claim, dict)
                ]
                if claims:
                    resource_claims = claims
                    break

    return {
        "resource_claims": resource_claims,
        "allowed_actions": allowed_actions,
        "preconditions": preconditions,
        "command_definition": command_definition,
    }


def _resource_claims_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_claims = payload.get("resource_claims")
    if not isinstance(raw_claims, list):
        authority = payload.get("authority")
        if isinstance(authority, dict):
            raw_claims = cast(dict[str, Any], authority).get("resource_claims")
    if not isinstance(raw_claims, list):
        return []
    return [
        dict(cast(dict[str, Any], claim))
        for claim in cast(list[Any], raw_claims)
        if isinstance(claim, dict)
    ]


def _string_list_from_payload(payload: dict[str, Any], field: str) -> list[str]:
    raw_values = payload.get(field)
    if not isinstance(raw_values, list):
        authority = payload.get("authority")
        if isinstance(authority, dict):
            raw_values = cast(dict[str, Any], authority).get(field)
    if not isinstance(raw_values, list):
        return []
    return [value for value in cast(list[Any], raw_values) if isinstance(value, str)]


@router.get("/{run_id}/graph", response_model=GraphProjectionResponse)
async def get_graph_projection(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
    service: Any = Depends(get_workflow_service),
) -> GraphProjectionResponse:
    snapshot = await graph_store.read_projection_snapshot(run_id)
    await graph_store.commit_read_model_changes()
    response = build_graph_projection_response_from_snapshot(run_id, snapshot)
    projection_events = await graph_store.read_run_projection(run_id)
    projected_task_states = project_task_states(projection_events)
    try:
        run = await service.get_run(run_id)
    except RunNotFoundError:
        return response.model_copy(update={"task_states": projected_task_states})
    return response.model_copy(
        update={
            "run_state": _graph_api_run_state(
                response.run_state,
                cast(RunStatus | None, run.status),
            ),
            "task_states": projected_task_states,
        }
    )


@router.get("/{run_id}/graph/topology", response_model=GraphTopologyResponse)
async def get_graph_topology(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> GraphTopologyResponse:
    events = await graph_store.read_run_light(run_id)
    return build_graph_topology_response(run_id, events)


@router.get("/{run_id}/graph/patches", response_model=GraphPatchAttemptsResponse)
async def get_graph_patch_attempts(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> GraphPatchAttemptsResponse:
    events = await graph_store.read_run(run_id)
    current_graph_position = await graph_store.current_position(run_id)
    return build_graph_patch_attempts_response(
        run_id,
        events,
        current_graph_position=current_graph_position,
    )


@router.get("/{run_id}/graph/final-blockers", response_model=FinalInvariantBlockersResponse)
async def get_graph_final_blockers(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> FinalInvariantBlockersResponse:
    events = await graph_store.read_run_light(run_id)
    return build_final_invariant_blockers_response(run_id, events)


@router.get("/{run_id}/graph/regions", response_model=GraphRegionsResponse)
async def get_graph_regions(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> GraphRegionsResponse:
    events = await graph_store.read_run_light(run_id)
    return build_graph_regions_response(run_id, events)


@router.get("/{run_id}/graph/events", response_model=list[GraphEventResponse])
async def get_graph_events(
    run_id: str,
    from_position: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=2000),
    payload_mode: Literal["summary", "full"] = Query(default="summary"),
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> list[GraphEventResponse]:
    if payload_mode == "summary":
        summaries = await graph_store.read_run_summaries(
            run_id,
            from_position=from_position,
            limit=limit,
        )
        await graph_store.commit_read_model_changes()
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


@router.get(
    "/{run_id}/graph/decisions",
    response_model=DecisionViewResponse,
    response_model_exclude_none=True,
)
async def get_graph_decision_view(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> DecisionViewResponse:
    events = await graph_store.read_run_light(run_id)
    return build_decision_view_response(run_id, events)


@router.post(
    "/{run_id}/graph/decisions",
    response_model=RecordGraphDecisionResponse,
    response_model_exclude_none=True,
)
async def record_graph_decision(
    run_id: str,
    request: RecordGraphDecisionRequest,
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> RecordGraphDecisionResponse:
    current_position = await graph_store.current_position(run_id)
    if current_position == 0:
        raise HTTPException(status_code=404, detail="Graph not found for run")

    controller = GraphController(
        session_factory,
        _ApiGraphClock(),
        _ApiGraphIdGenerator(),
        auto_dispatch=False,
    )
    try:
        result = await controller.handle_command(
            run_id,
            current_position,
            "record_decision",
            request.model_dump(exclude_none=True),
        )
    except StaleProjectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    rejected = [event.payload for event in result.events if event.event_type == "command_rejected"]
    if rejected:
        reason = rejected[-1].get("reason", "decision rejected")
        raise HTTPException(status_code=409, detail=str(reason))

    response_events = list(result.events)
    events = await graph_store.read_run_light(run_id)
    if project_run_state(events) == "active":
        schedule_result = await controller.handle_command(
            run_id,
            result.projection_position,
            "schedule_tick",
            {
                "lease_seconds": 300,
                "max_grants": 0,
                "base_snapshot_id": "routine-snapshot",
            },
        )
        response_events.extend(schedule_result.events)
        events = await graph_store.read_run_light(run_id)
    await graph_store.commit_read_model_changes()
    return RecordGraphDecisionResponse(
        run_id=run_id,
        graph_position=len(events),
        events=[_event_to_response(event) for event in response_events],
        decision_view=build_decision_view_response(run_id, events),
    )


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
    summary = await graph_store.read_node_detail_summary(run_id, node_id)
    if summary is None:
        await graph_store.commit_read_model_changes()
        if await graph_store.current_position(run_id) == 0:
            raise HTTPException(status_code=404, detail="No graph projection found for run")
        raise HTTPException(status_code=404, detail="Graph node not found")
    if payload_mode == "full":
        full_events = await graph_store.read_run_positions(
            run_id,
            _compact_event_positions(summary.events),
        )
        await graph_store.commit_read_model_changes()
        return build_node_detail_response_from_summary(summary, full_events=full_events)
    await graph_store.commit_read_model_changes()
    return build_node_detail_response_from_summary(summary)
