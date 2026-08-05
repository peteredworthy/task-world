"""Graph projection API endpoints."""

from __future__ import annotations

import json

from datetime import datetime, timezone
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Annotated, Any, Iterable, Literal, NoReturn, TypedDict, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api.deps import (
    get_artifact_store_resolver,
    get_global_config,
    get_graph_store,
    get_run_repository,
    get_session_factory,
    get_workflow_service,
)
from orchestrator.artifacts import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactStoreResolver,
    StoredArtifactRef,
)
from orchestrator.api.schemas.base import ApiModel
from orchestrator.config import GlobalConfig, RunStatus
from orchestrator.db import GraphOutboxModel, RunRepository
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    GraphCommandContext,
    PatchCommandFields,
    PatchCommandContext,
    PendingGateDecision,
    RecordSelector,
    RecordDecisionCommand,
    build_projection,
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
    project_gatekeeper_report,
    project_run_state,
    project_scheduler_view,
    project_task_states,
)
from orchestrator.graph_runtime import (
    GRAPH_READ_CONTRACTS,
    GraphController,
    GraphExpectedPositionMismatch,
    GraphPatchAttemptPage,
    GraphReadModelUnavailable,
    StaleProjectionError,
    bound_graph_json,
    bound_node_detail_owner,
)
from orchestrator.graph_runtime.store import (
    BoundedFullGraphEvent,
    BoundedGraphHealth,
    GraphEventStore,
    GraphEventSummary,
    GraphNodeDetailSummary,
    GRAPH_FIXED_VIEW_ITEMS,
    MAX_FILE_STATE_GATEKEEPER_FACTS_PER_BOUNDARY,
    PydanticCollectionContract,
)
from orchestrator.state import RunNotFoundError

router = APIRouter(prefix="/api/runs", tags=["graph"])

_GRAPH_HEALTH_MAX_DETAILS = 20
_GRAPH_IDENTIFIER_PATTERN = r"^[A-Za-z0-9_.:-]+$"
DEFAULT_GRAPH_EVENT_LIMIT = 50
MAX_GRAPH_EVENT_LIMIT = 100
DEFAULT_FILE_STATE_PAGE_LIMIT = 20
MAX_FILE_STATE_PAGE_LIMIT = 100
DEFAULT_FILE_STATE_PATH_LIMIT = 50
MAX_FILE_STATE_PATH_LIMIT = 200
DEFAULT_GRAPH_PATCH_ATTEMPT_LIMIT = 25
MAX_GRAPH_PATCH_ATTEMPT_LIMIT = 100
MAX_GRAPH_PATCH_LIST_ITEMS = 50
MAX_GRAPH_PATCH_TEXT_CHARS = 4_000
MAX_GRAPH_PATCH_JSON_DEPTH = 8
MAX_GRAPH_PATCH_JSON_MAPPING_ENTRIES = 50
MAX_GRAPH_PATCH_JSON_SEQUENCE_ITEMS = 50
MAX_GRAPH_PATCH_PAYLOAD_CHARS = 20_000
MAX_GRAPH_PATCH_JSON_KEY_CHARS = 200
_GRAPH_READ_CONTRACT_KEY = "_graph_read_contract"
_ARCHIVAL_READ_CONTRACT_KEY = "_graph_archival_read_contract"
_FINAL_BLOCKER_OUTBOX_CURSOR_PREFIX = "outbox:"
_GRAPH_RESPONSE_BYTES = 262_144
_FINAL_BLOCKER_OUTBOX_STRING_BYTES = 512

GraphIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=200, pattern=_GRAPH_IDENTIFIER_PATTERN),
]
ArtifactHash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
DecisionNodeIdentifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^\S+$")]
DecisionValue = Annotated[str, Field(min_length=1, max_length=64)]
NonEmptyString = Annotated[str, Field(min_length=1, pattern=r".*\S.*")]


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
    payload_truncated: bool = False
    payload_original_bytes: int | None = None
    payload_sha256: str | None = None


class GraphReadPageMetadataResponse(ApiModel):
    owner: str | None = None
    truncated: bool = False
    total_known: int = 0
    next_cursor: str | int | None = None
    original_bytes: int | None = None
    sha256: str | None = None
    fields: dict[str, GraphReadPageMetadataResponse] = Field(default_factory=dict)


def _raise_read_model_unavailable(error: GraphReadModelUnavailable) -> NoReturn:
    raise HTTPException(
        status_code=503,
        detail={
            "code": "read_model_unavailable",
            "run_id": error.run_id,
            "read_model": error.owner_read_model_name,
            "current_position": error.current_position,
            "reason": error.reason,
            "retryable": True,
        },
    ) from error


def _raise_expected_position_mismatch(error: GraphExpectedPositionMismatch) -> NoReturn:
    """Tell a multi-view client to abandon its obsolete graph anchor."""
    raise HTTPException(
        status_code=409,
        detail={
            "code": "expected_position_mismatch",
            "run_id": error.run_id,
            "expected_position": error.expected_position,
            "current_position": error.current_position,
            "retryable": True,
        },
    ) from error


class _BoundedPayloadMetadata(TypedDict):
    truncated: bool
    original_bytes: int | None
    sha256: str | None


class GraphProjectionResponse(ApiModel):
    run_id: str
    event_count: int
    run_state: str | None
    node_states: dict[str, str]
    task_states: dict[str, str]
    leases: dict[str, dict[str, Any]]
    ready_nodes: list[str]
    truncated: bool = False
    total_known: int = 0
    next_cursor: str | int | None = None
    collection_meta: dict[str, GraphReadPageMetadataResponse] = Field(default_factory=dict)


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
    from_node_kind: str | None = None
    from_node_role: str | None = None
    from_port: str
    to_node_id: str
    to_port: str
    required: bool
    dependency_type: str
    accepted_record_selector: RecordSelector | None = None
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
    truncated: bool = False
    total_known: int = 0
    next_cursor: str | int | None = None
    partial: bool = False
    collection_meta: dict[str, GraphReadPageMetadataResponse] = Field(default_factory=dict)


class SchedulerBlockedNodeResponse(ApiModel):
    node_id: str
    reason: str


class SchedulerViewResponseBody(ApiModel):
    ready: Annotated[list[str], PydanticCollectionContract("list", 100, "self")]
    blocked: Annotated[
        list[SchedulerBlockedNodeResponse],
        PydanticCollectionContract("list", 100, "node_id"),
    ]
    waiting_resources: Annotated[
        list[SchedulerBlockedNodeResponse],
        PydanticCollectionContract("list", 100, "node_id"),
    ]
    waiting_gates: Annotated[
        list[SchedulerBlockedNodeResponse],
        PydanticCollectionContract("list", 100, "node_id"),
    ]


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
    options: Annotated[list[str] | None, PydanticCollectionContract("list", 50, "self")] = None
    default_option: str | None = None
    consequence_summary: str | None = None
    expires_at: str | None = None
    requested_authority: Annotated[
        list[str] | None, PydanticCollectionContract("list", 50, "self")
    ] = None
    target_node_id: str | None = None
    target_region_id: str | None = None


class AppealDecisionResponse(ApiModel):
    node_id: str
    state: str
    outcome: str | None = None


class ReviewReadinessResponse(ApiModel):
    ready: bool
    blockers: Annotated[list[str], PydanticCollectionContract("list", 100, "self")]


class DecisionViewResponse(ApiModel):
    run_id: str
    event_count: int
    pending_gates: Annotated[
        list[PendingGateDecisionResponse],
        PydanticCollectionContract("list", 100, "node_id"),
    ]
    appeals: Annotated[
        list[AppealDecisionResponse],
        PydanticCollectionContract("list", 100, "node_id"),
    ]
    review: ReviewReadinessResponse
    truncated: bool = False
    total_known: int = 0
    next_cursor: str | int | None = None
    collection_meta: dict[str, GraphReadPageMetadataResponse] = Field(default_factory=dict)


class RecordGraphDecisionRequest(RecordDecisionCommand):
    """HTTP ingress reuses the strict domain decision command schema."""

    node_id: DecisionNodeIdentifier
    decision: DecisionValue
    decider: Actor | NonEmptyString
    record_id: DecisionNodeIdentifier | None = None


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
    truncated: bool = False
    total_known: int = 0
    next_cursor: str | int | None = None
    collection_meta: dict[str, GraphReadPageMetadataResponse] = Field(default_factory=dict)


class GraphHealthCountsResponse(ApiModel):
    ready: int | None
    blocked: int | None
    waiting_resources: int | None
    waiting_gates: int | None
    active_leases: int | None
    suspended_leases: int | None
    expired_leases: int | None
    failed_nodes: int | None
    final_blockers: int | None
    patches_accepted: int | None
    patches_rejected: int | None
    verifier_passed: int | None
    verifier_failed: int | None
    pending_gates: int | None


class GraphHealthFailedNodeResponse(ApiModel):
    node_id: str
    reason: str


class GraphHealthExpiredLeaseResponse(ApiModel):
    lease_id: str
    node_id: str
    reason: str


class GraphHealthBlockerResponse(ApiModel):
    node_id: str
    kind: str
    reason: str


class GraphHealthPatchDecisionResponse(ApiModel):
    patch_id: str
    decision: Literal["accepted", "rejected"]
    reason: str | None = None


class GraphHealthVerifierResultResponse(ApiModel):
    node_id: str
    candidate_id: str
    candidate_id_hashed: bool | None = Field(default=None, exclude_if=lambda value: value is None)
    candidate_id_original_chars: int | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    candidate_id_original_bytes: int | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    candidate_id_sha256: str | None = Field(default=None, exclude_if=lambda value: value is None)
    verdict: Literal["passed", "failed"]


class GraphHealthVerifierResponse(ApiModel):
    passed: int | None
    failed: int | None
    recent: list[GraphHealthVerifierResultResponse]


class GraphHealthPendingGateResponse(ApiModel):
    node_id: str
    gate_type: str


class GraphHealthResponse(ApiModel):
    run_id: str
    event_count: int
    run_state: str | None
    status: str
    health_status: Literal["partial", "complete", "unavailable"]
    facts_status: Literal["partial", "complete", "unavailable"]
    unavailable_checks: list[str]
    section_status: dict[str, Literal["partial", "complete", "unavailable"]]
    counts: GraphHealthCountsResponse
    failed_nodes: list[GraphHealthFailedNodeResponse]
    expired_leases: list[GraphHealthExpiredLeaseResponse]
    blockers: list[GraphHealthBlockerResponse]
    recent_patch_decisions: list[GraphHealthPatchDecisionResponse]
    verifier: GraphHealthVerifierResponse
    pending_gates: list[GraphHealthPendingGateResponse]
    review_blockers: list[str]
    detail_meta: dict[str, dict[str, int | bool]]


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
    truncated: bool = False
    total_known: int = 0
    next_cursor: str | int | None = None
    collection_meta: dict[str, GraphReadPageMetadataResponse] = Field(default_factory=dict)


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
    # Source-entry counts are not unique-path counts: producer payloads may
    # repeat a path across classification/residue source arrays.
    captured_source_entries_total: int
    captured_paths_truncated: bool
    rejected_paths: list[FileStatePathResponse]
    rejected_source_entries_total: int
    rejected_paths_truncated: bool
    gatekeeper_verdicts: list[FileStateGatekeeperVerdictResponse]
    gatekeeper_verdicts_total: int | None
    gatekeeper_verdicts_truncated: bool
    gatekeeper_facts_total: int
    gatekeeper_facts_truncated: bool
    diff_summary: FileStateDiffSummaryResponse | None = None
    diff_summary_available: bool = False


class FileStateNodeReportResponse(ApiModel):
    node_id: str
    boundaries: list[FileStateBoundaryResponse]


class FileStateReportResponse(ApiModel):
    run_id: str
    """Number of matching canonical events in this page, not total graph history."""
    event_count: int
    from_position: int
    has_more: bool
    next_position: int | None = None
    path_limit: int
    nodes: list[FileStateNodeReportResponse]
    """Gatekeeper summary for this page only; it is never represented as global state."""
    gatekeeper_scope: Literal["page"] = "page"
    gatekeeper_metrics_truncated: bool = False
    orphan_gatekeeper_fact_count: int = 0
    gatekeeper: dict[str, Any] | None = None


class GraphPatchIdentifierTruncationResponse(ApiModel):
    index: int
    original_chars: int
    sha256: str


class GraphPatchNestedIdentifierTruncationResponse(ApiModel):
    path: str
    original_chars: int
    sha256: str


class GraphPatchAttemptResponse(ApiModel):
    patch_id: str
    patch_id_truncated: bool = False
    patch_id_original_chars: int | None = None
    patch_id_sha256: str | None = None
    proposed_by_node_id: str | None = None
    proposed_by_node_id_truncated: bool = False
    proposed_by_node_id_original_chars: int | None = None
    proposed_by_node_id_sha256: str | None = None
    base_graph_position: int | None = None
    current_graph_position: int
    status: Literal["proposed", "accepted", "rejected", "superseded"]
    rejection_reason: str | None = None
    diagnostics: dict[str, Any] | None = None
    read_set_diff: dict[str, Any] | None = None
    accepted_event_id: str | None = None
    accepted_position: int | None = None
    rejected_event_id: str | None = None
    rejected_position: int | None = None
    created_node_ids: list[str] = Field(default_factory=list)
    created_node_ids_total: int = 0
    created_node_ids_truncated: bool = False
    created_node_id_truncations: list[GraphPatchIdentifierTruncationResponse] = Field(
        default_factory=lambda: list[GraphPatchIdentifierTruncationResponse]()
    )
    created_edge_ids: list[str] = Field(default_factory=list)
    created_edge_ids_total: int = 0
    created_edge_ids_truncated: bool = False
    created_edge_id_truncations: list[GraphPatchIdentifierTruncationResponse] = Field(
        default_factory=lambda: list[GraphPatchIdentifierTruncationResponse]()
    )
    operations: list[dict[str, Any]] = []
    operations_total: int = 0
    operations_truncated: bool = False
    requirements: list[Any] = Field(default_factory=list)
    requirements_total: int = 0
    requirements_truncated: bool = False
    reasons: list[str] = Field(default_factory=list)
    reasons_total: int = 0
    reasons_truncated: bool = False
    evidence: list[Any] = Field(default_factory=list)
    evidence_total: int = 0
    evidence_truncated: bool = False
    text_truncated: bool = False
    max_text_chars: int = MAX_GRAPH_PATCH_TEXT_CHARS
    payload_truncated: bool = False
    payload_truncation_reasons: list[str] = Field(default_factory=list)
    nested_identifier_truncations: list[GraphPatchNestedIdentifierTruncationResponse] = Field(
        default_factory=lambda: list[GraphPatchNestedIdentifierTruncationResponse]()
    )
    nested_identifier_truncations_truncated: bool = False


class GraphPatchAttemptsResponse(ApiModel):
    run_id: str
    current_graph_position: int
    attempts: list[GraphPatchAttemptResponse]
    has_more: bool
    next_position: int | None = None
    limit: int
    orphan_outcome_count: int = 0
    capped_fact_count: int = 0
    partial: bool = False


class SubmitGraphPatchRequest(PatchCommandFields):
    """HTTP ingress composes the strict shared graph patch fields."""

    patch_id: GraphIdentifier | None = None
    base_graph_position: int | None = Field(default=None, ge=0)
    ops: list[dict[str, Any]] = Field(...)
    rationale_record_id: GraphIdentifier | None = None


class SubmitGraphPatchResponse(ApiModel):
    run_id: str
    graph_position: int
    accepted: bool
    patch_id: str
    events: list[GraphEventResponse]


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
    run_id: str | None = None
    outbox_id: int | None = None
    outbox_event_id: str | None = None
    outbox_kind: str | None = None
    outbox_last_error: str | None = None
    outbox_attempts: int | None = None


class FinalInvariantBlockersResponse(ApiModel):
    run_id: str
    event_count: int
    blockers: list[FinalInvariantBlockerResponse]
    truncated: bool = False
    total_known: int = 0
    next_cursor: str | int | None = None
    partial: bool = False
    collection_meta: dict[str, GraphReadPageMetadataResponse] = Field(default_factory=dict)


class GraphRegionResponse(ApiModel):
    task_region_id: str
    state: str
    blockers: list[FinalInvariantBlockerResponse]


class GraphRegionsResponse(ApiModel):
    run_id: str
    event_count: int
    regions: list[GraphRegionResponse]
    truncated: bool = False
    total_known: int = 0
    next_cursor: str | int | None = None
    partial: bool = False
    collection_meta: dict[str, GraphReadPageMetadataResponse] = Field(default_factory=dict)


def _unpack_archival_items(
    items: Iterable[dict[str, Any]],
    *,
    identity_fields: tuple[str, ...],
) -> tuple[list[dict[str, Any]], bool, dict[str, GraphReadPageMetadataResponse]]:
    """Remove storage-only archival metadata and expose it truthfully at the API boundary."""
    unpacked: list[dict[str, Any]] = []
    partial = False
    metadata: dict[str, GraphReadPageMetadataResponse] = {}
    for index, raw_item in enumerate(items, start=1):
        item = dict(raw_item)
        raw_contract = item.pop(_ARCHIVAL_READ_CONTRACT_KEY, None)
        identity = next(
            (
                item[field]
                for field in identity_fields
                if isinstance(item.get(field), str) and item[field]
            ),
            f"entry-{index}",
        )
        if isinstance(raw_contract, dict):
            typed_contract = cast(dict[str, object], raw_contract)
        else:
            typed_contract = None
        if typed_contract is not None and typed_contract.get("partial") is True:
            partial = True
            raw_fields = typed_contract.get("fields")
            if isinstance(raw_fields, dict):
                prefix = str(identity)
                for path, value in cast(dict[str, object], raw_fields).items():
                    if isinstance(value, dict):
                        metadata[f"{prefix}:{path}"] = GraphReadPageMetadataResponse(
                            **cast(dict[str, Any], value)
                        )
        unpacked.append(item)
    return unpacked, partial, metadata


def _event_to_response(
    event: EventEnvelope,
    *,
    payload_mode: Literal["full", "summary"] = "full",
) -> GraphEventResponse:
    payload, metadata = _bounded_rendered_payload(
        _event_payload(event, payload_mode=payload_mode),
        contract_key="events_full" if payload_mode == "full" else "events_summary",
    )
    return GraphEventResponse(
        event_id=event.event_id,
        event_type=event.event_type,
        run_id=event.run_id,
        position=event.position,
        timestamp=event.timestamp.isoformat(),
        payload=payload,
        payload_truncated=metadata["truncated"],
        payload_original_bytes=metadata["original_bytes"],
        payload_sha256=metadata["sha256"],
    )


def _bounded_full_event_to_response(event: BoundedFullGraphEvent) -> GraphEventResponse:
    """Render a selected full-event row without ever decoding an oversized body."""
    if event.payload_json is None:
        return GraphEventResponse(
            event_id=event.event_id,
            event_type=event.event_type,
            run_id=event.run_id,
            position=event.position,
            timestamp=event.timestamp,
            payload={},
            payload_truncated=True,
            payload_original_bytes=event.payload_original_bytes,
            payload_sha256=None,
        )
    payload = json.loads(event.payload_json)
    if not isinstance(payload, dict):
        # Stored graph envelopes always have object payloads.  Do not turn a
        # malformed legacy row into an unbounded/error-prone request decode.
        return GraphEventResponse(
            event_id=event.event_id,
            event_type=event.event_type,
            run_id=event.run_id,
            position=event.position,
            timestamp=event.timestamp,
            payload={},
            payload_truncated=True,
            payload_original_bytes=event.payload_original_bytes,
            payload_sha256=None,
        )
    bounded, metadata = _bounded_rendered_payload(
        cast(dict[str, Any], payload), contract_key="events_full"
    )
    return GraphEventResponse(
        event_id=event.event_id,
        event_type=event.event_type,
        run_id=event.run_id,
        position=event.position,
        timestamp=event.timestamp,
        payload=bounded,
        payload_truncated=metadata["truncated"],
        payload_original_bytes=metadata["original_bytes"],
        payload_sha256=metadata["sha256"],
    )


def _summary_to_response(event: GraphEventSummary) -> GraphEventResponse:
    stored_metadata = event.payload.get(_GRAPH_READ_CONTRACT_KEY)
    canonical_payload = {
        key: value for key, value in event.payload.items() if key != _GRAPH_READ_CONTRACT_KEY
    }
    metadata = _BoundedPayloadMetadata(
        truncated=False,
        original_bytes=None,
        sha256=None,
    )
    if isinstance(stored_metadata, dict):
        typed_stored = cast(dict[str, Any], stored_metadata)
        if typed_stored.get("truncated") is True:
            original_bytes = typed_stored.get("original_bytes")
            digest = typed_stored.get("sha256")
            metadata = _BoundedPayloadMetadata(
                truncated=True,
                original_bytes=original_bytes if isinstance(original_bytes, int) else None,
                sha256=digest if isinstance(digest, str) else None,
            )
    return GraphEventResponse(
        event_id=event.event_id,
        event_type=event.event_type,
        run_id=event.run_id,
        position=event.position,
        timestamp=event.timestamp,
        payload=canonical_payload,
        payload_truncated=metadata["truncated"],
        payload_original_bytes=metadata["original_bytes"],
        payload_sha256=metadata["sha256"],
    )


def _bounded_rendered_payload(
    payload: dict[str, Any],
    *,
    contract_key: Literal["events_summary", "events_full"],
) -> tuple[dict[str, Any], _BoundedPayloadMetadata]:
    contract = GRAPH_READ_CONTRACTS[contract_key]
    result = bound_graph_json(payload, contract.budget)
    bounded = cast(dict[str, Any], result["value"])
    rendered_cap = contract.budget.rendered_payload_byte_cap or 16_384
    rendered = json.dumps(
        bounded,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if len(rendered) <= rendered_cap:
        original_bytes = result["original_bytes"]
        digest = result["sha256"]
        return bounded, {
            "truncated": result["truncated"] is True,
            "original_bytes": original_bytes if isinstance(original_bytes, int) else None,
            "sha256": digest if isinstance(digest, str) else None,
        }
    original = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    identity_keys = (
        "candidate_id",
        "candidate_id_hashed",
        "candidate_id_original_chars",
        "candidate_id_original_bytes",
        "candidate_id_sha256",
        "node_id",
        "verifier_node_id",
        "patch_id",
        "record_id",
    )
    return (
        {key: bounded[key] for key in identity_keys if key in bounded},
        {
            "truncated": True,
            "original_bytes": len(original),
            "sha256": sha256(original).hexdigest(),
        },
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
        "outcome",
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
            value_summary: dict[str, Any] = {"grades": grades}
            outcome = typed_value.get("outcome")
            if isinstance(outcome, str):
                value_summary["outcome"] = outcome
            summarized["value"] = value_summary
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

    # Fold once and reuse across every view below, instead of each project_*
    # call re-folding the full event stream from scratch.
    projection = build_projection(events)
    return GraphProjectionResponse(
        run_id=run_id,
        event_count=max(event.position for event in events),
        run_state=project_run_state(events, projection=projection),
        node_states=project_node_states(events, projection=projection),
        task_states=project_task_states(events, projection=projection),
        leases=project_leases(events, projection=projection),
        ready_nodes=project_ready_nodes(events, projection=projection),
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
    collection_meta, page_meta = _snapshot_page_metadata(
        snapshot,
        ("node_states", "task_states", "leases", "ready_nodes"),
    )
    return GraphProjectionResponse(
        run_id=run_id,
        event_count=int(snapshot.position),
        run_state=cast(str | None, snapshot.run_state),
        node_states=cast(dict[str, str], snapshot.node_states),
        task_states=cast(dict[str, str], snapshot.task_states),
        leases=cast(dict[str, dict[str, Any]], snapshot.leases),
        ready_nodes=cast(list[str], snapshot.ready_nodes),
        collection_meta=collection_meta,
        **page_meta,
    )


def _snapshot_page_metadata(
    snapshot: Any,
    fields: tuple[str, ...],
) -> tuple[dict[str, GraphReadPageMetadataResponse], dict[str, Any]]:
    raw_decisions: Any = snapshot.decisions
    decisions = cast(dict[str, Any], raw_decisions) if isinstance(raw_decisions, dict) else {}
    raw_contract = decisions.get(_GRAPH_READ_CONTRACT_KEY)
    typed_contract = cast(dict[str, Any], raw_contract) if isinstance(raw_contract, dict) else {}
    candidate_collections = typed_contract.get("collections", {})
    raw_collections = (
        cast(dict[str, Any], candidate_collections)
        if isinstance(candidate_collections, dict)
        else {}
    )
    metadata: dict[str, GraphReadPageMetadataResponse] = {}
    for name in fields:
        raw = raw_collections.get(name)
        item = _read_page_metadata(raw)
        if item is None:
            continue
        metadata[name] = item
    truncated = any(item.truncated for item in metadata.values())
    next_cursor = _route_metadata_cursor(metadata)
    return metadata, {
        "truncated": truncated,
        "total_known": max((item.total_known for item in metadata.values()), default=0),
        "next_cursor": next_cursor,
    }


def _read_page_metadata(value: Any) -> GraphReadPageMetadataResponse | None:
    if not isinstance(value, dict):
        return None
    raw = cast(dict[str, Any], value)
    total_known = raw.get("total_known")
    cursor = raw.get("next_cursor")
    raw_fields = raw.get("fields")
    fields = {
        name: item
        for name, field_value in (
            cast(dict[str, Any], raw_fields).items() if isinstance(raw_fields, dict) else ()
        )
        if (item := _read_page_metadata(field_value)) is not None
    }
    field_cursor = _route_metadata_cursor(fields)
    owner = raw.get("owner")
    original_bytes = raw.get("original_bytes")
    digest = raw.get("sha256")
    return GraphReadPageMetadataResponse(
        owner=owner if isinstance(owner, str) else None,
        truncated=raw.get("truncated") is True,
        total_known=total_known if isinstance(total_known, int) else 0,
        next_cursor=(
            field_cursor
            if field_cursor is not None
            else cursor
            if isinstance(cursor, (str, int))
            else None
        ),
        original_bytes=original_bytes if isinstance(original_bytes, int) else None,
        sha256=digest if isinstance(digest, str) else None,
        fields=fields,
    )


def _route_metadata_cursor(
    metadata: dict[str, GraphReadPageMetadataResponse],
) -> str | int | None:
    cursors = [
        (path, item.next_cursor)
        for path, item in sorted(metadata.items())
        if item.truncated and item.next_cursor is not None
    ]
    if not cursors:
        return None
    unique = {cursor for _, cursor in cursors}
    if len(unique) == 1:
        return cursors[0][1]
    encoded = json.dumps(cursors, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"aggregate:sha256:{sha256(encoded.encode()).hexdigest()}"


def _contains_partial_graph_contract(value: Any) -> bool:
    """Detect truthful nested truncation already embedded by bounded owners."""
    if isinstance(value, dict):
        mapping = cast(dict[str, Any], value)
        if mapping.get("truncated") is True:
            return True
        contract = mapping.get("_graph_read_contract")
        if isinstance(contract, dict):
            typed_contract = cast(dict[str, Any], contract)
            if typed_contract.get("partial") is True or typed_contract.get("truncated") is True:
                return True
        return any(_contains_partial_graph_contract(item) for item in mapping.values())
    if isinstance(value, list):
        return any(_contains_partial_graph_contract(item) for item in cast(list[Any], value))
    return False


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
        RunStatus.CANCELLED,
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


def build_graph_topology_response_from_projection(
    run_id: str,
    projection: Any,
    *,
    event_count: int,
    cursor: int = 0,
    limit: int = GRAPH_FIXED_VIEW_ITEMS,
) -> GraphTopologyResponse:
    """Page the topology owned by the durable projection checkpoint.

    The flattened, typed ordering makes the cursor stable across a request:
    nodes precede edges and each group is lexical.  This is intentionally not
    a history fallback; the projection is advanced with every graph append.
    """
    topology = project_graph_topology([], projection=projection)
    entries: list[tuple[str, dict[str, Any]]] = [
        ("node", cast(dict[str, Any], node)) for node in topology["nodes"]
    ] + [("edge", cast(dict[str, Any], edge)) for edge in topology["edges"]]
    page = entries[cursor : cursor + limit]
    next_cursor = cursor + len(page) if cursor + len(page) < len(entries) else None
    return GraphTopologyResponse(
        run_id=run_id,
        event_count=event_count,
        nodes=[GraphTopologyNodeResponse(**item) for kind, item in page if kind == "node"],
        edges=[GraphTopologyEdgeResponse(**item) for kind, item in page if kind == "edge"],
        truncated=next_cursor is not None,
        total_known=len(entries),
        next_cursor=next_cursor,
    )


def build_graph_topology_response_from_view(
    run_id: str, view: dict[str, Any], *, event_count: int, cursor: int, limit: int
) -> GraphTopologyResponse:
    nodes = [cast(dict[str, Any], item) for item in view.get("nodes", []) if isinstance(item, dict)]
    edges = [cast(dict[str, Any], item) for item in view.get("edges", []) if isinstance(item, dict)]
    entries = [("node", item) for item in nodes] + [("edge", item) for item in edges]
    page = entries[cursor : cursor + limit]
    next_cursor = cursor + len(page) if cursor + len(page) < len(entries) else None
    return GraphTopologyResponse(
        run_id=run_id,
        event_count=event_count,
        nodes=[GraphTopologyNodeResponse(**item) for kind, item in page if kind == "node"],
        edges=[GraphTopologyEdgeResponse(**item) for kind, item in page if kind == "edge"],
        truncated=next_cursor is not None,
        total_known=len(entries),
        next_cursor=next_cursor,
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
        has_more=False,
        limit=DEFAULT_GRAPH_PATCH_ATTEMPT_LIMIT,
    )


def build_bounded_graph_patch_attempts_response(
    run_id: str,
    page: GraphPatchAttemptPage,
    *,
    current_graph_position: int,
    limit: int,
) -> GraphPatchAttemptsResponse:
    attempts = [
        _bounded_patch_attempt(
            entry["patch_id"],
            entry["position"],
            page.facts_by_patch_id.get(entry["patch_id"], ()),
            page.creation_counts_by_patch_id.get(entry["patch_id"], (0, 0)),
            current_graph_position,
        )
        for entry in page.proposals
    ]
    return GraphPatchAttemptsResponse(
        run_id=run_id,
        current_graph_position=current_graph_position,
        attempts=attempts,
        has_more=page.has_more,
        next_position=page.proposals[-1]["position"] if page.has_more and page.proposals else None,
        limit=limit,
        orphan_outcome_count=page.orphan_fact_count,
        capped_fact_count=page.capped_fact_count,
        partial=page.partial,
    )


def _bounded_patch_attempt(
    patch_id: str,
    proposal_position: int,
    facts: tuple[dict[str, Any], ...],
    creation_totals: tuple[int, int],
    current_graph_position: int,
) -> GraphPatchAttemptResponse:
    del proposal_position  # Cursor ownership is represented by the enclosing page.
    proposal = next(
        (fact for fact in facts if fact["event_type"] == "output_record_accepted"), None
    )
    outcomes = [
        fact
        for fact in facts
        if fact["event_type"]
        in {
            "graph_patch_accepted",
            "graph_patch_rejected",
            "graph_patch_superseded",
            "graph_patch_outcome",
        }
    ]
    proposal_payload = _patch_mapping(proposal.get("payload") if proposal else None)
    source = _patch_mapping(proposal_payload.get("value"))
    latest = outcomes[-1] if outcomes else None
    outcome = _patch_mapping(latest.get("payload") if latest else None)
    status = {
        "graph_patch_accepted": "accepted",
        "graph_patch_rejected": "rejected",
        "graph_patch_superseded": "superseded",
    }.get(latest["event_type"] if latest else "", "proposed")
    budget = _PatchPayloadBudget()
    bounded_patch_id, patch_id_meta = _bounded_patch_identifier(patch_id, budget)
    proposer = _patch_string(source, outcome, "proposed_by_node_id")
    bounded_proposer, proposer_meta = (
        _bounded_patch_identifier(proposer, budget) if proposer is not None else (None, None)
    )
    operations, operations_total, operations_truncated = _bounded_patch_list(source.get("ops"))
    requirements, requirements_total, requirements_truncated = _bounded_patch_list(
        source.get("requirements")
    )
    evidence, evidence_total, evidence_truncated = _bounded_patch_list(source.get("evidence"))
    reasons, reasons_total, reasons_truncated = _bounded_patch_reasons(
        source.get("reasons"),
        outcome.get("reasons"),
        outcome.get("reason"),
    )
    reason = outcome.get("reason")
    rejection_reason = _project_patch_json(reason, budget) if isinstance(reason, str) else None
    diagnostics = _project_patch_diagnostics(outcome, budget)
    read_set_diff = _project_patch_json(
        outcome.get("read_set_diff"), budget, path=("read_set_diff",)
    )
    projected_operations = [
        _project_patch_json(item, budget, path=("operations", str(index)))
        for index, item in enumerate(operations)
    ]
    projected_requirements = [
        _project_patch_json(
            item, budget, path=("requirements", str(index)), identifier_context=True
        )
        for index, item in enumerate(requirements)
    ]
    projected_evidence = [
        _project_patch_json(item, budget, path=("evidence", str(index)))
        for index, item in enumerate(evidence)
    ]
    projected_reasons = [
        _project_patch_json(item, budget, path=("reasons", str(index)))
        for index, item in enumerate(reasons)
    ]
    created_node_ids, observed_node_total, created_nodes_truncated, created_node_id_truncations = (
        _bounded_patch_identifiers(facts, "node_created", "node_id", creation_totals[0], budget)
    )
    created_edge_ids, observed_edge_total, created_edges_truncated, created_edge_id_truncations = (
        _bounded_patch_identifiers(facts, "edge_created", "edge_id", creation_totals[1], budget)
    )
    return GraphPatchAttemptResponse(
        patch_id=bounded_patch_id,
        patch_id_truncated=patch_id_meta is not None,
        patch_id_original_chars=patch_id_meta.original_chars if patch_id_meta else None,
        patch_id_sha256=patch_id_meta.sha256 if patch_id_meta else None,
        proposed_by_node_id=bounded_proposer,
        proposed_by_node_id_truncated=proposer_meta is not None,
        proposed_by_node_id_original_chars=proposer_meta.original_chars if proposer_meta else None,
        proposed_by_node_id_sha256=proposer_meta.sha256 if proposer_meta else None,
        base_graph_position=_patch_int(source, outcome, "base_graph_position"),
        current_graph_position=current_graph_position,
        status=cast(Any, status),
        rejection_reason=rejection_reason,
        diagnostics=diagnostics or None,
        read_set_diff=cast(dict[str, Any], read_set_diff)
        if isinstance(read_set_diff, dict)
        else None,
        accepted_event_id=_patch_event_value(outcomes, "graph_patch_accepted", "event_id"),
        accepted_position=_patch_event_value(outcomes, "graph_patch_accepted", "position"),
        rejected_event_id=_patch_event_value(outcomes, "graph_patch_rejected", "event_id"),
        rejected_position=_patch_event_value(outcomes, "graph_patch_rejected", "position"),
        created_node_ids=created_node_ids,
        created_node_ids_total=observed_node_total,
        created_node_ids_truncated=created_nodes_truncated,
        created_node_id_truncations=created_node_id_truncations,
        created_edge_ids=created_edge_ids,
        created_edge_ids_total=observed_edge_total,
        created_edge_ids_truncated=created_edges_truncated,
        created_edge_id_truncations=created_edge_id_truncations,
        operations=[
            cast(dict[str, Any], item) for item in projected_operations if isinstance(item, dict)
        ],
        operations_total=operations_total,
        operations_truncated=operations_truncated,
        requirements=projected_requirements,
        requirements_total=requirements_total,
        requirements_truncated=requirements_truncated,
        reasons=[item for item in projected_reasons if isinstance(item, str)],
        reasons_total=reasons_total,
        reasons_truncated=reasons_truncated,
        evidence=projected_evidence,
        evidence_total=evidence_total,
        evidence_truncated=evidence_truncated,
        text_truncated=budget.text_truncated,
        payload_truncated=budget.truncated,
        payload_truncation_reasons=sorted(budget.reasons),
        nested_identifier_truncations=budget.nested_identifier_truncations,
        nested_identifier_truncations_truncated=budget.nested_identifier_truncations_truncated,
    )


def _bounded_patch_identifiers(
    facts: tuple[dict[str, Any], ...],
    event_type: str,
    key: str,
    total: int,
    budget: "_PatchPayloadBudget",
) -> tuple[list[str], int, bool, list[GraphPatchIdentifierTruncationResponse]]:
    values: list[str] = []
    truncations: list[GraphPatchIdentifierTruncationResponse] = []
    for fact in facts:
        if len(values) >= MAX_GRAPH_PATCH_LIST_ITEMS:
            break
        if fact["event_type"] != event_type:
            continue
        payload = _patch_mapping(fact.get("payload"))
        value = payload.get(key)
        if isinstance(value, str):
            bounded, metadata = _bounded_patch_identifier(value, budget)
            values.append(bounded)
            if metadata is not None:
                truncations.append(
                    GraphPatchIdentifierTruncationResponse(
                        index=len(values) - 1,
                        original_chars=metadata.original_chars,
                        sha256=metadata.sha256,
                    )
                )
    return values, total, total > len(values), truncations


def _bounded_patch_list(value: Any) -> tuple[list[Any], int, bool]:
    if not isinstance(value, list):
        return [], 0, False
    items = cast(list[Any], value)
    return items[:MAX_GRAPH_PATCH_LIST_ITEMS], len(items), len(items) > MAX_GRAPH_PATCH_LIST_ITEMS


def _bounded_patch_reasons(*sources: Any) -> tuple[list[Any], int, bool]:
    """Bound reason aggregation without concatenating unbounded source lists."""
    total = 0
    for source in sources:
        if isinstance(source, list):
            total += len(cast(list[Any], source))
        elif isinstance(source, str):
            total += 1
    retained: list[Any] = []
    for source in sources:
        if len(retained) >= MAX_GRAPH_PATCH_LIST_ITEMS:
            break
        if isinstance(source, str):
            retained.append(source)
            continue
        if not isinstance(source, list):
            continue
        remaining = MAX_GRAPH_PATCH_LIST_ITEMS - len(retained)
        retained.extend(cast(list[Any], source)[:remaining])
    return retained, total, total > len(retained)


def _patch_mapping(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


@dataclass
class _PatchPayloadBudget:
    remaining_chars: int = MAX_GRAPH_PATCH_PAYLOAD_CHARS
    truncated: bool = False
    text_truncated: bool = False
    reasons: set[str] = field(default_factory=lambda: set[str]())
    nested_identifier_truncations: list[GraphPatchNestedIdentifierTruncationResponse] = field(
        default_factory=lambda: list[GraphPatchNestedIdentifierTruncationResponse]()
    )
    nested_identifier_truncations_truncated: bool = False

    def mark(self, reason: str, *, text: bool = False) -> None:
        self.truncated = True
        self.text_truncated = self.text_truncated or text
        self.reasons.add(reason)

    def record_nested_identifier(self, path: str, value: str) -> None:
        if len(self.nested_identifier_truncations) >= MAX_GRAPH_PATCH_JSON_SEQUENCE_ITEMS:
            self.nested_identifier_truncations_truncated = True
            self.mark("identifier_metadata_entries")
            return
        self.nested_identifier_truncations.append(
            GraphPatchNestedIdentifierTruncationResponse(
                path=path,
                original_chars=len(value),
                sha256=sha256(value.encode()).hexdigest(),
            )
        )


@dataclass(frozen=True)
class _PatchIdentifierMetadata:
    original_chars: int
    sha256: str


def _bounded_patch_identifier(
    value: str,
    budget: _PatchPayloadBudget,
) -> tuple[str, _PatchIdentifierMetadata | None]:
    allowed = min(MAX_GRAPH_PATCH_TEXT_CHARS, max(0, budget.remaining_chars))
    retained = value[:allowed]
    budget.remaining_chars -= len(retained)
    if len(retained) == len(value):
        return retained, None
    budget.mark("identifier_chars" if allowed else "payload_budget", text=True)
    return retained, _PatchIdentifierMetadata(
        original_chars=len(value),
        sha256=sha256(value.encode()).hexdigest(),
    )


def _project_patch_json(
    value: Any,
    budget: _PatchPayloadBudget,
    depth: int = 0,
    *,
    path: tuple[str, ...] = (),
    identifier_context: bool = False,
) -> Any:
    if depth >= MAX_GRAPH_PATCH_JSON_DEPTH:
        budget.mark("max_depth")
        return {} if isinstance(value, dict) else [] if isinstance(value, list) else None
    if isinstance(value, str):
        allowed = min(MAX_GRAPH_PATCH_TEXT_CHARS, max(0, budget.remaining_chars))
        retained = value[:allowed]
        budget.remaining_chars -= len(retained)
        if len(retained) != len(value):
            budget.mark("string_chars" if allowed else "payload_budget", text=True)
            if identifier_context:
                budget.record_nested_identifier(_bounded_patch_json_path(path), value)
        return retained
    if isinstance(value, dict):
        mapping_result: dict[str, Any] = {}
        for key, item in cast(dict[Any, Any], value).items():
            if len(mapping_result) >= MAX_GRAPH_PATCH_JSON_MAPPING_ENTRIES:
                budget.mark("mapping_entries")
                break
            if budget.remaining_chars <= 0:
                budget.mark("payload_budget")
                break
            if not isinstance(key, str):
                budget.mark("invalid_mapping_key")
                continue
            if len(key) > MAX_GRAPH_PATCH_JSON_KEY_CHARS:
                budget.mark("mapping_key_chars")
                continue
            key_cost = min(len(key), budget.remaining_chars)
            if key_cost != len(key):
                budget.mark("payload_budget")
                break
            budget.remaining_chars -= key_cost
            mapping_result[key] = _project_patch_json(
                item,
                budget,
                depth + 1,
                path=(*path, _bounded_patch_json_path_segment(key)),
                identifier_context=_patch_identifier_key(key),
            )
        return mapping_result
    if isinstance(value, list):
        sequence_result: list[Any] = []
        for index, item in enumerate(cast(list[Any], value)):
            if len(sequence_result) >= MAX_GRAPH_PATCH_JSON_SEQUENCE_ITEMS:
                budget.mark("sequence_items")
                break
            if budget.remaining_chars <= 0:
                budget.mark("payload_budget")
                break
            sequence_result.append(
                _project_patch_json(
                    item,
                    budget,
                    depth + 1,
                    path=(*path, str(index)),
                    identifier_context=identifier_context or _patch_identifier_list_path(path),
                )
            )
        return sequence_result
    if value is None or isinstance(value, (bool, int, float)):
        return value
    budget.mark("invalid_json_value")
    return None


def _patch_identifier_key(key: str) -> bool:
    return (
        key == "id"
        or key.endswith("_id")
        or key.endswith("_ids")
        or key
        in {
            "patch",
            "patches",
            "node",
            "nodes",
            "edge",
            "edges",
            "requirements",
        }
    )


def _patch_identifier_list_path(path: tuple[str, ...]) -> bool:
    return bool(path) and path[-1] in {"requirements", "node_ids", "edge_ids", "patch_ids"}


def _bounded_patch_json_path_segment(key: str) -> str:
    if len(key) <= MAX_GRAPH_PATCH_JSON_KEY_CHARS:
        return key
    return f"key-{sha256(key.encode()).hexdigest()[:16]}"


def _bounded_patch_json_path(path: tuple[str, ...]) -> str:
    rendered = ".".join(path)
    if len(rendered) <= MAX_GRAPH_PATCH_JSON_KEY_CHARS:
        return rendered
    suffix = sha256(rendered.encode()).hexdigest()[:16]
    prefix_length = MAX_GRAPH_PATCH_JSON_KEY_CHARS - len(suffix) - 1
    return f"{rendered[:prefix_length]}~{suffix}"


def _project_patch_diagnostics(
    value: dict[str, Any], budget: _PatchPayloadBudget
) -> dict[str, Any]:
    excluded = {
        "patch_id",
        "proposed_by_node_id",
        "base_graph_position",
        "reason",
        "reasons",
        "read_set_diff",
        "requirements",
        "evidence",
        "ops",
    }
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in excluded:
            continue
        if len(key) > MAX_GRAPH_PATCH_JSON_KEY_CHARS:
            budget.mark("mapping_key_chars")
            continue
        if len(result) >= MAX_GRAPH_PATCH_JSON_MAPPING_ENTRIES:
            budget.mark("mapping_entries")
            break
        if budget.remaining_chars <= 0:
            budget.mark("payload_budget")
            break
        key_cost = min(len(key), budget.remaining_chars)
        if key_cost != len(key):
            budget.mark("payload_budget")
            break
        budget.remaining_chars -= key_cost
        result[key] = _project_patch_json(
            item,
            budget,
            path=("diagnostics", _bounded_patch_json_path_segment(key)),
            identifier_context=_patch_identifier_key(key),
        )
    return result


def _patch_string(primary: dict[str, Any], fallback: dict[str, Any], key: str) -> str | None:
    value = primary.get(key, fallback.get(key))
    return value if isinstance(value, str) else None


def _patch_int(primary: dict[str, Any], fallback: dict[str, Any], key: str) -> int | None:
    value = primary.get(key, fallback.get(key))
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _patch_event_value(facts: list[dict[str, Any]], event_type: str, key: str) -> Any:
    event = next((fact for fact in reversed(facts) if fact["event_type"] == event_type), None)
    return event.get(key) if event else None


def build_final_invariant_blockers_response(
    run_id: str,
    events: list[EventEnvelope],
    *,
    failed_outbox_rows: list[GraphOutboxModel] | None = None,
) -> FinalInvariantBlockersResponse:
    return FinalInvariantBlockersResponse(
        run_id=run_id,
        event_count=max((event.position for event in events), default=0),
        blockers=[
            FinalInvariantBlockerResponse(**cast(dict[str, Any], blocker))
            for blocker in project_final_invariant_blockers(events)
        ]
        + _failed_outbox_blocker_responses(run_id, failed_outbox_rows or [])[0],
    )


def build_final_invariant_blockers_response_from_projection(
    run_id: str,
    projection: Any,
    *,
    event_count: int,
    failed_outbox_rows: list[GraphOutboxModel] | None = None,
    cursor: int = 0,
    limit: int = GRAPH_FIXED_VIEW_ITEMS,
) -> FinalInvariantBlockersResponse:
    """Render a bounded final-blocker page from the current checkpoint.

    Passing an empty event list selects the projection-native variants of
    history-derived facts.  The checkpoint is the durable, incrementally
    advanced read owner; GET must not replay ``events_v2``.
    """
    blockers = [
        FinalInvariantBlockerResponse(**cast(dict[str, Any], blocker))
        for blocker in project_final_invariant_blockers([], projection=projection)
    ] + _failed_outbox_blocker_responses(run_id, failed_outbox_rows or [])[0]
    page = blockers[cursor : cursor + limit]
    next_cursor = cursor + len(page) if cursor + len(page) < len(blockers) else None
    return FinalInvariantBlockersResponse(
        run_id=run_id,
        event_count=event_count,
        blockers=page,
        truncated=next_cursor is not None,
        total_known=len(blockers),
        next_cursor=next_cursor,
    )


def build_final_invariant_blockers_response_from_view(
    run_id: str,
    view: dict[str, Any],
    *,
    event_count: int,
    failed_outbox_rows: list[GraphOutboxModel],
    cursor: int,
    limit: int,
) -> FinalInvariantBlockersResponse:
    blockers = [
        FinalInvariantBlockerResponse(**cast(dict[str, Any], blocker))
        for blocker in view.get("blockers", [])
        if isinstance(blocker, dict)
    ] + _failed_outbox_blocker_responses(run_id, failed_outbox_rows)[0]
    page = blockers[cursor : cursor + limit]
    next_cursor = cursor + len(page) if cursor + len(page) < len(blockers) else None
    return FinalInvariantBlockersResponse(
        run_id=run_id,
        event_count=event_count,
        blockers=page,
        truncated=next_cursor is not None,
        total_known=len(blockers),
        next_cursor=next_cursor,
    )


@dataclass(frozen=True)
class _FailedOutboxRow:
    """The non-payload columns needed by the failed-outbox overlay."""

    outbox_id: int
    event_id: str
    kind: str
    last_error: str | None
    attempts: int


def _bounded_outbox_text(
    value: str,
    *,
    field: str,
    metadata: dict[str, GraphReadPageMetadataResponse],
    identity: str,
) -> str:
    """Keep an outbox overlay typed while reporting an omitted string exactly.

    Outbox ``payload`` is deliberately never selected by this route.  These
    text columns are independently bounded before becoming part of a public
    final-blocker response, so a failed side effect cannot bypass the archival
    page contract.
    """
    encoded = value.encode()
    if len(encoded) <= _FINAL_BLOCKER_OUTBOX_STRING_BYTES:
        return value
    digest = sha256(encoded).hexdigest()
    metadata[f"{identity}:$.{field}"] = GraphReadPageMetadataResponse(
        owner="final_blockers",
        truncated=True,
        total_known=1,
        next_cursor=f"sha256:{digest}",
        original_bytes=len(encoded),
        sha256=digest,
    )
    return f"sha256:{digest}"


def _failed_outbox_blocker_responses(
    run_id: str,
    rows: Iterable[_FailedOutboxRow | GraphOutboxModel],
) -> tuple[list[FinalInvariantBlockerResponse], bool, dict[str, GraphReadPageMetadataResponse]]:
    """Build bounded failed-outbox overlays without decoding their JSON payloads."""
    blockers: list[FinalInvariantBlockerResponse] = []
    metadata: dict[str, GraphReadPageMetadataResponse] = {}
    for row in rows:
        identity = f"outbox:{row.outbox_id}"
        event_id = _bounded_outbox_text(
            row.event_id, field="support_ids[0]", metadata=metadata, identity=identity
        )
        kind = _bounded_outbox_text(
            row.kind, field="outbox_kind", metadata=metadata, identity=identity
        )
        error = _bounded_outbox_text(
            row.last_error or "unknown error",
            field="outbox_last_error",
            metadata=metadata,
            identity=identity,
        )
        blockers.append(
            FinalInvariantBlockerResponse(
                kind="failed_outbox_row",
                reason=f"outbox row failed for run {run_id}: {kind}: {error}",
                state="failed",
                support_ids=[event_id],
                run_id=run_id,
                outbox_id=row.outbox_id,
                outbox_event_id=event_id,
                outbox_kind=kind,
                outbox_last_error=error,
                outbox_attempts=row.attempts,
            )
        )
    return blockers, bool(metadata), metadata


def _pack_failed_outbox_overlay(
    blockers: list[FinalInvariantBlockerResponse],
    metadata: dict[str, GraphReadPageMetadataResponse],
    *,
    byte_budget: int,
) -> tuple[list[FinalInvariantBlockerResponse], dict[str, GraphReadPageMetadataResponse]]:
    """Select a fitting overlay prefix before it joins an archival page.

    The response model adds a small amount of JSON framing around each
    blocker.  Reserve that framing here rather than assuming the archival
    owner's budget covers a separate, live outbox namespace.
    """
    packed: list[FinalInvariantBlockerResponse] = []
    used = 0
    for blocker in blockers:
        item_bytes = (
            len(json.dumps(blocker.model_dump(mode="json"), separators=(",", ":")).encode()) + 64
        )
        if packed and used + item_bytes > byte_budget:
            break
        if not packed and item_bytes > byte_budget:
            break
        packed.append(blocker)
        used += item_bytes
    kept_ids = {
        f"outbox:{blocker.outbox_id}:" for blocker in packed if blocker.outbox_id is not None
    }
    return packed, {
        key: value
        for key, value in metadata.items()
        if any(key.startswith(prefix) for prefix in kept_ids)
    }


def build_graph_regions_response(
    run_id: str,
    events: list[EventEnvelope],
) -> GraphRegionsResponse:
    if not events:
        return GraphRegionsResponse(run_id=run_id, event_count=0, regions=[])
    # Fold once and reuse across both views below.
    projection = build_projection(events)
    task_states = project_task_states(events, projection=projection)
    blockers = project_final_invariant_blockers(events, projection=projection)
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


def build_graph_regions_response_from_projection(
    run_id: str,
    projection: Any,
    *,
    event_count: int,
    cursor: int = 0,
    limit: int = GRAPH_FIXED_VIEW_ITEMS,
) -> GraphRegionsResponse:
    """Page task regions from the incrementally maintained projection."""
    task_states = project_task_states([], projection=projection)
    blockers = project_final_invariant_blockers([], projection=projection)
    blockers_by_region: dict[str, list[FinalInvariantBlockerResponse]] = {}
    for blocker in blockers:
        task_region_id = blocker.get("task_region_id")
        if isinstance(task_region_id, str) and task_region_id:
            blockers_by_region.setdefault(task_region_id, []).append(
                FinalInvariantBlockerResponse(**cast(dict[str, Any], blocker))
            )
    region_ids = sorted(set(task_states) | set(blockers_by_region))
    page_ids = region_ids[cursor : cursor + limit]
    next_cursor = cursor + len(page_ids) if cursor + len(page_ids) < len(region_ids) else None
    return GraphRegionsResponse(
        run_id=run_id,
        event_count=event_count,
        regions=[
            GraphRegionResponse(
                task_region_id=region_id,
                state=task_states.get(region_id, "blocked"),
                blockers=blockers_by_region.get(region_id, []),
            )
            for region_id in page_ids
        ],
        truncated=next_cursor is not None,
        total_known=len(region_ids),
        next_cursor=next_cursor,
    )


def build_graph_regions_response_from_view(
    run_id: str, view: dict[str, Any], *, event_count: int, cursor: int, limit: int
) -> GraphRegionsResponse:
    regions = [
        cast(dict[str, Any], item) for item in view.get("regions", []) if isinstance(item, dict)
    ]
    page = regions[cursor : cursor + limit]
    next_cursor = cursor + len(page) if cursor + len(page) < len(regions) else None
    return GraphRegionsResponse(
        run_id=run_id,
        event_count=event_count,
        regions=[GraphRegionResponse(**item) for item in page],
        truncated=next_cursor is not None,
        total_known=len(regions),
        next_cursor=next_cursor,
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

    # Fold once and reuse across both views below.
    projection = build_projection(events)
    scheduler_view = project_scheduler_view(events, projection=projection)
    lease_view = project_lease_view(events, projection=projection)
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
    collection_meta, page_meta = _snapshot_page_metadata(
        snapshot,
        ("scheduler", "lease_view"),
    )
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
        collection_meta=collection_meta,
        **page_meta,
    )


def build_graph_health_response(
    run_id: str,
    events: list[EventEnvelope],
) -> GraphHealthResponse:
    """Reduce authoritative graph facts into the bounded operator health contract."""
    empty_counts = GraphHealthCountsResponse(
        ready=0,
        blocked=0,
        waiting_resources=0,
        waiting_gates=0,
        active_leases=0,
        suspended_leases=0,
        expired_leases=0,
        failed_nodes=0,
        final_blockers=0,
        patches_accepted=0,
        patches_rejected=0,
        verifier_passed=0,
        verifier_failed=0,
        pending_gates=0,
    )

    if not events:
        return GraphHealthResponse(
            run_id=run_id,
            event_count=0,
            run_state=None,
            status="empty",
            health_status="complete",
            facts_status="complete",
            unavailable_checks=[],
            section_status={},
            counts=empty_counts,
            failed_nodes=[],
            expired_leases=[],
            blockers=[],
            recent_patch_decisions=[],
            verifier=GraphHealthVerifierResponse(passed=0, failed=0, recent=[]),
            pending_gates=[],
            review_blockers=[],
            detail_meta={},
        )

    projection = build_projection(events)
    scheduler = project_scheduler_view(events, projection=projection)
    leases = project_leases(events, projection=projection)
    decisions = project_decision_view(events, projection=projection)
    node_states = project_node_states(events, projection=projection)
    failed_reasons = _failed_node_reasons(events, node_states)
    failed_nodes = [
        GraphHealthFailedNodeResponse(node_id=node_id, reason=reason)
        for node_id, reason in sorted(failed_reasons.items())
    ]
    expired_leases = build_expired_lease_rows(leases, failed_reasons)
    blockers = [
        GraphHealthBlockerResponse(
            node_id=str(blocker.get("node_id", "run")),
            kind=str(blocker.get("kind", "final_invariant")),
            reason=str(blocker.get("reason", "blocked")),
        )
        for blocker in project_final_invariant_blockers(events, projection=projection)
    ]
    patches = _health_patch_decisions(events)
    verifier_recent = _health_verifier_results(events)
    pending_gates = _health_pending_gates(decisions["pending_gates"])
    pending_gate_ids = {gate.node_id for gate in pending_gates}
    review_blockers = list(decisions["review"]["blockers"])
    counts = GraphHealthCountsResponse(
        ready=len(scheduler["ready"]),
        blocked=sum(entry["node_id"] not in pending_gate_ids for entry in scheduler["blocked"]),
        waiting_resources=len(scheduler["waiting_resources"]),
        waiting_gates=len(scheduler["waiting_gates"])
        + sum(
            gate.node_id not in {entry["node_id"] for entry in scheduler["waiting_gates"]}
            for gate in pending_gates
        ),
        active_leases=sum(lease.get("state") == "active" for lease in leases.values()),
        suspended_leases=sum(lease.get("state") == "suspended" for lease in leases.values()),
        expired_leases=len(expired_leases),
        failed_nodes=len(failed_nodes),
        final_blockers=len(blockers),
        patches_accepted=sum(patch.decision == "accepted" for patch in patches),
        patches_rejected=sum(patch.decision == "rejected" for patch in patches),
        verifier_passed=sum(result.verdict == "passed" for result in verifier_recent),
        verifier_failed=sum(result.verdict == "failed" for result in verifier_recent),
        pending_gates=len(pending_gates),
    )
    run_state = project_run_state(events, projection=projection)
    detail_lists: dict[str, list[Any]] = {
        "failed_nodes": failed_nodes,
        "expired_leases": expired_leases,
        "blockers": blockers,
        "recent_patch_decisions": patches,
        "verifier_recent": verifier_recent,
        "pending_gates": pending_gates,
        "review_blockers": review_blockers,
    }
    detail_meta = {
        name: {"total": len(rows), "truncated": len(rows) > _GRAPH_HEALTH_MAX_DETAILS}
        for name, rows in detail_lists.items()
    }
    return GraphHealthResponse(
        run_id=run_id,
        event_count=max(event.position for event in events),
        run_state=run_state,
        status="blocked" if blockers or failed_nodes or pending_gates else (run_state or "unknown"),
        health_status="complete",
        facts_status="complete",
        unavailable_checks=[],
        section_status={},
        counts=counts,
        failed_nodes=failed_nodes[:_GRAPH_HEALTH_MAX_DETAILS],
        expired_leases=expired_leases[:_GRAPH_HEALTH_MAX_DETAILS],
        blockers=blockers[:_GRAPH_HEALTH_MAX_DETAILS],
        recent_patch_decisions=patches[-_GRAPH_HEALTH_MAX_DETAILS:],
        verifier=GraphHealthVerifierResponse(
            passed=counts.verifier_passed,
            failed=counts.verifier_failed,
            recent=verifier_recent[-_GRAPH_HEALTH_MAX_DETAILS:],
        ),
        pending_gates=pending_gates[:_GRAPH_HEALTH_MAX_DETAILS],
        review_blockers=review_blockers[:_GRAPH_HEALTH_MAX_DETAILS],
        detail_meta=detail_meta,
    )


def build_bounded_graph_health_response(
    run_id: str, health: BoundedGraphHealth
) -> GraphHealthResponse:
    """Translate compact-store facts without inventing projection-only health."""
    unavailable = [
        "scheduler",
        "leases",
        "expired_leases",
        "failed_nodes",
        "final_invariant_blockers",
        "pending_gates",
        "review_blockers",
    ]
    if not health.summaries_complete:
        unavailable = ["compact_event_summaries", *unavailable, "patches", "verifier", "run_state"]
        status: Literal["partial", "complete", "unavailable"] = "unavailable"
        section_status: dict[str, Literal["partial", "complete", "unavailable"]] = {
            name: "unavailable" for name in unavailable
        }
    elif health.event_count == 0:
        status = "complete"
        unavailable = []
        section_status = {}
    else:
        status = "partial"
        section_status = {
            "run_state": "complete",
            "patches": "complete",
            "verifier": "complete",
            **{name: "unavailable" for name in unavailable},
        }
    empty = health.event_count == 0 and health.summaries_complete
    counts = GraphHealthCountsResponse(
        ready=0 if empty else None,
        blocked=0 if empty else None,
        waiting_resources=0 if empty else None,
        waiting_gates=0 if empty else None,
        active_leases=0 if empty else None,
        suspended_leases=0 if empty else None,
        expired_leases=0 if empty else None,
        failed_nodes=0 if empty else None,
        final_blockers=0 if empty else None,
        patches_accepted=health.patches_accepted,
        patches_rejected=health.patches_rejected,
        verifier_passed=health.verifier_passed,
        verifier_failed=health.verifier_failed,
        pending_gates=0 if empty else None,
    )
    return GraphHealthResponse(
        run_id=run_id,
        event_count=health.event_count,
        run_state=health.run_state,
        status="empty" if health.event_count == 0 and health.summaries_complete else status,
        health_status=status,
        facts_status=status,
        unavailable_checks=unavailable,
        section_status=section_status,
        counts=counts,
        failed_nodes=[],
        expired_leases=[],
        blockers=[],
        recent_patch_decisions=[
            GraphHealthPatchDecisionResponse(**row) for row in health.patch_decisions
        ],
        verifier=GraphHealthVerifierResponse(
            passed=health.verifier_passed,
            failed=health.verifier_failed,
            recent=[GraphHealthVerifierResultResponse(**row) for row in health.verifier_results],
        ),
        pending_gates=[],
        review_blockers=[],
        detail_meta={}
        if empty
        else {
            "recent_patch_decisions": {
                "total": health.patch_decisions_total or 0,
                "truncated": health.patch_decisions_truncated,
            },
            "verifier_recent": {
                "total": health.verifier_results_total or 0,
                "truncated": health.verifier_results_truncated,
            },
        },
    )


def _failed_node_reasons(
    events: list[EventEnvelope], node_states: dict[str, str]
) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for event in events:
        if event.event_type != "node_state_changed" or event.payload.get("new_state") != "failed":
            continue
        node_id = event.payload.get("node_id")
        if not isinstance(node_id, str) or node_states.get(node_id) != "failed":
            continue
        reason = event.payload.get("reason", event.payload.get("trigger", "failed"))
        reasons[node_id] = reason if isinstance(reason, str) else "failed"
    return reasons


def _health_pending_gates(rows: list[PendingGateDecision]) -> list[GraphHealthPendingGateResponse]:
    return [
        GraphHealthPendingGateResponse(node_id=node_id, gate_type=gate_type)
        for row in rows
        if isinstance(node_id := row.get("node_id"), str)
        and isinstance(gate_type := row.get("gate_type"), str)
    ]


def build_expired_lease_rows(
    leases: dict[str, dict[str, Any]], failed_reasons: dict[str, str]
) -> list[GraphHealthExpiredLeaseResponse]:
    latest_by_node: dict[str, dict[str, Any]] = {}
    for lease in leases.values():
        node_id = lease.get("node_id")
        if not isinstance(node_id, str):
            continue
        prior = latest_by_node.get(node_id)
        if prior is None or int(lease.get("generation") or 0) > int(prior.get("generation") or 0):
            latest_by_node[node_id] = lease
    rows: list[GraphHealthExpiredLeaseResponse] = []
    for lease_id, lease in sorted(leases.items()):
        node_id = lease.get("node_id")
        if lease.get("state") != "expired" or not isinstance(node_id, str):
            continue
        if latest_by_node.get(node_id) is not lease:
            continue
        rows.append(
            GraphHealthExpiredLeaseResponse(
                lease_id=lease_id,
                node_id=node_id,
                reason=failed_reasons.get(node_id, "lease_expired_without_callback"),
            )
        )
    return rows


def _health_patch_decisions(events: list[EventEnvelope]) -> list[GraphHealthPatchDecisionResponse]:
    by_patch: dict[str, GraphHealthPatchDecisionResponse] = {}
    for event in events:
        if event.event_type not in {"graph_patch_accepted", "graph_patch_rejected"}:
            continue
        patch_id = event.payload.get("patch_id")
        if not isinstance(patch_id, str):
            continue
        accepted = event.event_type == "graph_patch_accepted"
        reason = event.payload.get("reason")
        by_patch[patch_id] = GraphHealthPatchDecisionResponse(
            patch_id=patch_id,
            decision="accepted" if accepted else "rejected",
            reason=reason if isinstance(reason, str) else None,
        )
    return list(by_patch.values())


def _health_verifier_results(
    events: list[EventEnvelope],
) -> list[GraphHealthVerifierResultResponse]:
    by_verifier_candidate: dict[tuple[str, str], GraphHealthVerifierResultResponse] = {}
    for event in events:
        if event.event_type not in {"verification_passed", "verification_failed"}:
            continue
        node_id, candidate_id = (
            event.payload.get("verifier_node_id"),
            event.payload.get("candidate_id"),
        )
        if isinstance(node_id, str) and isinstance(candidate_id, str):
            by_verifier_candidate[(node_id, candidate_id)] = GraphHealthVerifierResultResponse(
                node_id=node_id,
                candidate_id=candidate_id,
                verdict="passed" if event.event_type == "verification_passed" else "failed",
            )
    return list(by_verifier_candidate.values())


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
    collection_meta, page_meta = _snapshot_page_metadata(snapshot, ("decisions",))
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
        collection_meta=collection_meta,
        **page_meta,
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


def _iter_record_path_entries(record: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield producer source entries without copying or globally deduplicating them."""
    for key in ("classifications", "residue", "tracked", "untracked", "ignored", "external"):
        raw_entries = record.get(key)
        if not isinstance(raw_entries, list):
            continue
        for raw_entry in cast(list[Any], raw_entries):
            if not isinstance(raw_entry, dict):
                continue
            yield cast(dict[str, Any], raw_entry)


def _rejected_path_entries(
    record: dict[str, Any], path_limit: int
) -> tuple[list[FileStatePathResponse], int]:
    raw_entries = record.get("rejected_paths")
    if not isinstance(raw_entries, list):
        return [], 0
    entries: list[FileStatePathResponse] = []
    total = 0
    for raw_entry in cast(list[Any], raw_entries):
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, Any], raw_entry)
        path = _path_text(entry)
        if path is None:
            continue
        total += 1
        if len(entries) >= path_limit:
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
    return entries, total


def _gatekeeper_verdicts_by_record(
    events: list[EventEnvelope],
    path_limit: int,
) -> tuple[
    dict[str, list[FileStateGatekeeperVerdictResponse]],
    dict[str, int],
    dict[str, bool],
]:
    """Accumulate bounded verdict output with exact loaded-source metadata."""
    by_record: dict[str, list[FileStateGatekeeperVerdictResponse]] = {}
    source_totals: dict[str, int] = {}
    truncated: dict[str, bool] = {}
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
            source_totals[record_id] = source_totals.get(record_id, 0) + 1
            classification = cast(str | None, verdict.get("classification"))
            retained = by_record.setdefault(record_id, [])
            if len(retained) >= path_limit:
                truncated[record_id] = True
                continue
            retained.append(
                FileStateGatekeeperVerdictResponse(
                    path=path,
                    verdict="reject" if classification == "secret" else "allow",
                    classification=classification,
                    rationale=cast(str | None, verdict.get("rationale")),
                    confidence=cast(float | None, verdict.get("confidence")),
                    model_id=cast(str | None, verdict.get("model_id")),
                )
            )
    return by_record, source_totals, truncated


def _snapshot_type(record: dict[str, Any]) -> str:
    git = record.get("git")
    if isinstance(git, dict) and isinstance(cast(dict[str, Any], git).get("commit_sha"), str):
        return "git_commit"
    return "manifest"


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _diff_summary(
    record: dict[str, Any],
) -> FileStateDiffSummaryResponse | None:
    if _snapshot_type(record) != "git_commit":
        return None
    raw_summary: Any = record.get("diff_summary")
    git = record.get("git")
    if raw_summary is None and isinstance(git, dict):
        raw_summary = cast(dict[str, Any], git).get("diff_summary")
    if isinstance(raw_summary, dict):
        summary = cast(dict[str, Any], raw_summary)
        files_changed = _optional_int(summary.get("files_changed"))
        if files_changed is None:
            return None
        return FileStateDiffSummaryResponse(
            files_changed=files_changed,
            additions=_optional_int(summary.get("additions")),
            deletions=_optional_int(summary.get("deletions")),
        )
    return None


def _file_state_boundary_response(
    record: dict[str, Any],
    gatekeeper_verdicts: dict[str, list[FileStateGatekeeperVerdictResponse]],
    gatekeeper_verdict_source_totals: dict[str, int],
    gatekeeper_verdicts_omitted: dict[str, bool],
    path_limit: int,
    gatekeeper_fact_count: int,
    gatekeeper_facts_truncated: bool,
) -> FileStateBoundaryResponse | None:
    record_id = record.get("record_id")
    snapshot_id = record.get("snapshot_id")
    if not isinstance(record_id, str) or not isinstance(snapshot_id, str):
        return None

    counts: dict[str, int] = {}
    captured_paths: list[FileStatePathResponse] = []
    captured_source_entries_total = 0
    # This set is bounded by ``path_limit`` because paths after the response
    # list reaches its cap cannot affect retained first-occurrence output.
    retained_paths: set[str] = set()
    retained_entries: list[dict[str, Any]] = []
    captured_paths_truncated = False
    for entry in _iter_record_path_entries(record):
        path = _path_text(entry)
        if path is None:
            continue
        captured_source_entries_total += 1
        if path in retained_paths:
            continue
        if len(retained_entries) >= path_limit:
            captured_paths_truncated = True
            continue
        retained_paths.add(path)
        retained_entries.append(entry)

    stored_source_total = record.get("_captured_source_entries_total")
    if isinstance(stored_source_total, int) and stored_source_total >= 0:
        captured_source_entries_total = stored_source_total
        if stored_source_total > len(retained_entries):
            captured_paths_truncated = True

    # Keep only residue overrides for paths already retained above; this map
    # is consequently bounded by ``path_limit`` too.
    bounded_residue_by_path: dict[str, dict[str, Any]] = {}
    raw_residue = record.get("residue")
    if isinstance(raw_residue, list):
        for raw_entry in cast(list[Any], raw_residue):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, Any], raw_entry)
            path = _path_text(entry)
            if path in retained_paths and path not in bounded_residue_by_path:
                bounded_residue_by_path[path] = entry
    verdicts_by_path = {
        verdict.path: verdict
        for verdict in gatekeeper_verdicts.get(record_id, [])
        if verdict.path in retained_paths
    }
    for entry in retained_entries:
        path = _path_text(entry)
        if path is None:
            continue
        residue = bounded_residue_by_path.get(path, {})
        gatekeeper_verdict = verdicts_by_path.get(path)
        classification = (
            gatekeeper_verdict.classification
            if gatekeeper_verdict is not None and gatekeeper_verdict.classification is not None
            else residue.get("classification", entry.get("classification"))
        )
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
                    (
                        f"gatekeeper:{gatekeeper_verdict.model_id}"
                        if gatekeeper_verdict is not None
                        and gatekeeper_verdict.model_id is not None
                        else residue.get("matched_rule", entry.get("matched_rule"))
                    ),
                ),
                needs_gatekeeper=residue.get("needs_gatekeeper", entry.get("needs_gatekeeper"))
                is True,
            )
        )

    stored_classification_counts = record.get("_classification_counts")
    if isinstance(stored_classification_counts, dict):
        counts = {
            str(classification): count
            for classification, count in cast(dict[Any, Any], stored_classification_counts).items()
            if isinstance(classification, str) and isinstance(count, int) and count >= 0
        }

    rejected_paths, rejected_source_entries_total = _rejected_path_entries(record, path_limit)
    raw_rejected_paths = record.get("rejected_paths")
    if isinstance(raw_rejected_paths, list):
        for raw_rejected in cast(list[Any], raw_rejected_paths):
            rejected = cast(dict[str, Any], raw_rejected)
            if isinstance(rejected.get("classification"), str):
                classification = cast(str, rejected["classification"])
                counts[classification] = counts.get(classification, 0) + 1
    all_verdicts = gatekeeper_verdicts.get(record_id, [])
    verdicts_truncated = gatekeeper_facts_truncated or gatekeeper_verdicts_omitted.get(
        record_id, False
    )

    diff_summary = _diff_summary(record)
    return FileStateBoundaryResponse(
        record_id=record_id,
        node_id=cast(str | None, record.get("producer_node_id")),
        snapshot_id=snapshot_id,
        snapshot_type=_snapshot_type(record),
        verdict=cast(str | None, record.get("verdict")),
        classification_counts={key: counts[key] for key in sorted(counts)},
        captured_paths=captured_paths,
        captured_source_entries_total=captured_source_entries_total,
        captured_paths_truncated=captured_paths_truncated,
        rejected_paths=rejected_paths,
        rejected_source_entries_total=rejected_source_entries_total,
        rejected_paths_truncated=rejected_source_entries_total > len(rejected_paths),
        gatekeeper_verdicts=all_verdicts,
        gatekeeper_verdicts_total=(
            None
            if gatekeeper_facts_truncated
            else gatekeeper_verdict_source_totals.get(record_id, 0)
        ),
        gatekeeper_verdicts_truncated=verdicts_truncated,
        gatekeeper_facts_total=gatekeeper_fact_count,
        gatekeeper_facts_truncated=gatekeeper_facts_truncated,
        diff_summary=diff_summary,
        diff_summary_available=diff_summary is not None,
    )


def build_file_state_report_response(
    run_id: str,
    events: list[EventEnvelope],
    *,
    from_position: int,
    has_more: bool,
    path_limit: int,
    gatekeeper_fact_counts: dict[str, int],
    orphan_gatekeeper_fact_count: int,
    boundary_event_count: int,
    next_position: int | None,
) -> FileStateReportResponse:
    gatekeeper_metrics_truncated = any(
        count > MAX_FILE_STATE_GATEKEEPER_FACTS_PER_BOUNDARY
        for count in gatekeeper_fact_counts.values()
    )
    if not events:
        return FileStateReportResponse(
            run_id=run_id,
            event_count=boundary_event_count,
            from_position=from_position,
            has_more=False,
            next_position=None,
            path_limit=path_limit,
            nodes=[],
            gatekeeper_metrics_truncated=gatekeeper_metrics_truncated,
            orphan_gatekeeper_fact_count=orphan_gatekeeper_fact_count,
            gatekeeper=None,
        )

    gatekeeper_report = project_gatekeeper_report(events).get(run_id)
    (
        gatekeeper_verdicts,
        gatekeeper_verdict_source_totals,
        gatekeeper_verdicts_omitted,
    ) = _gatekeeper_verdicts_by_record(events, path_limit)
    by_node: dict[str, list[FileStateBoundaryResponse]] = {}
    for event in events:
        if event.event_type != "file_state_accepted":
            continue
        boundary = _file_state_boundary_response(
            dict(event.payload),
            gatekeeper_verdicts,
            gatekeeper_verdict_source_totals,
            gatekeeper_verdicts_omitted,
            path_limit,
            gatekeeper_fact_counts.get(str(event.payload.get("record_id")), 0),
            gatekeeper_fact_counts.get(str(event.payload.get("record_id")), 0)
            > MAX_FILE_STATE_GATEKEEPER_FACTS_PER_BOUNDARY,
        )
        if boundary is None:
            continue
        node_id = boundary.node_id or "unknown"
        by_node.setdefault(node_id, []).append(boundary)

    return FileStateReportResponse(
        run_id=run_id,
        event_count=boundary_event_count,
        from_position=from_position,
        has_more=has_more,
        next_position=next_position if has_more else None,
        path_limit=path_limit,
        gatekeeper_metrics_truncated=gatekeeper_metrics_truncated,
        orphan_gatekeeper_fact_count=orphan_gatekeeper_fact_count,
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

    # Fold once and reuse across every view below.
    projection = build_projection(events)
    node_states = project_node_states(events, projection=projection)
    node_metadata = project_node_metadata(events, projection=projection)
    leases = project_leases(events, projection=projection)
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
    input_ports = summary.input_ports
    output_records = summary.output_records
    file_state_records = summary.file_state_records
    active_lease = summary.active_lease
    prompt_summary = summary.prompt_summary
    candidate_collections: Any = (
        summary.read_contract.get("collections", {}) if summary.read_contract is not None else {}
    )
    if full_events is not None:
        persisted_collections = (
            dict(cast(dict[str, Any], candidate_collections))
            if isinstance(candidate_collections, dict)
            else {}
        )
        response_events = _full_node_event_responses(summary.events, full_events)
        callback_history = _full_node_event_responses(summary.callback_history, full_events)
        bounded_owner, candidate_collections = bound_node_detail_owner(
            {
                "input_ports": summary.input_ports,
                "output_records": _pick_output_records(full_events, summary.node_id),
                "file_state_records": _pick_file_state_records(full_events, summary.node_id),
                "leases": summary.leases,
                "active_lease": summary.active_lease,
                "callback_history": [event.model_dump(mode="json") for event in callback_history],
                "events": [event.model_dump(mode="json") for event in response_events],
                "prompt_summary": summary.prompt_summary,
            }
        )
        # Full mode hydrates the compact retained event window rather than
        # replaying the whole history.  Repacking that window must not erase
        # the persisted continuation facts for the complete collection.
        bounded_collections = cast(dict[str, Any], candidate_collections)
        for name in ("events", "callback_history"):
            persisted = persisted_collections.get(name)
            if isinstance(persisted, dict):
                persisted_metadata = cast(dict[str, Any], persisted)
                if persisted_metadata.get("truncated") is True:
                    bounded_collections[name] = persisted_metadata
        input_ports = cast(dict[str, list[str]], bounded_owner["input_ports"])
        output_records = cast(list[dict[str, Any]], bounded_owner["output_records"])
        file_state_records = cast(list[dict[str, Any]], bounded_owner["file_state_records"])
        active_lease = cast(dict[str, Any] | None, bounded_owner["active_lease"])
        callback_history = [
            GraphEventResponse(**event)
            for event in cast(list[dict[str, Any]], bounded_owner["callback_history"])
        ]
        response_events = [
            GraphEventResponse(**event)
            for event in cast(list[dict[str, Any]], bounded_owner["events"])
        ]
        prompt_summary = cast(dict[str, Any] | None, bounded_owner["prompt_summary"])
    raw_collections = (
        cast(dict[str, Any], candidate_collections)
        if isinstance(candidate_collections, dict)
        else {}
    )
    collection_meta: dict[str, GraphReadPageMetadataResponse] = {}
    for name, raw in raw_collections.items():
        item = _read_page_metadata(raw)
        if item is not None:
            collection_meta[name] = item
    truncated = any(item.truncated for item in collection_meta.values()) or any(
        _contains_partial_graph_contract(value)
        for value in (output_records, file_state_records, callback_history, response_events)
    )
    next_cursor = _route_metadata_cursor(collection_meta)
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
        input_ports=input_ports,
        output_records=output_records,
        file_state_records=file_state_records,
        active_lease=active_lease,
        callback_history=callback_history,
        events=response_events,
        prompt_summary=prompt_summary,
        truncated=truncated,
        total_known=max((item.total_known for item in collection_meta.values()), default=0),
        next_cursor=next_cursor,
        collection_meta=collection_meta,
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
        "outcome",
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
    if "value" in payload and _node_detail_record_value_should_be_included(payload):
        compact["value"] = payload["value"]
    return compact


def _node_detail_record_value_should_be_included(payload: dict[str, Any]) -> bool:
    return _node_detail_record_value_is_small_control_payload(
        payload
    ) or _is_verification_report_record_payload(payload)


def _node_detail_record_value_is_small_control_payload(payload: dict[str, Any]) -> bool:
    return payload.get("record_type") in {
        "authority_request_record",
        "decision_request",
    } or payload.get("port") in {
        "authority_request_record",
        "decision_request",
    }


def _is_verification_report_record_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "verification_report"
        or payload.get("record_kind") == "verification"
        or payload.get("port") == "verification_report"
        or payload.get("schema") == "VerificationReport"
    )


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
    resource_claims_resolved = False
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
        if event_claims is not None:
            resource_claims = event_claims
            resource_claims_resolved = True
        event_allowed_actions = _string_list_from_payload(
            payload,
            "allowed_actions",
        )
        if event_allowed_actions is not None:
            allowed_actions = event_allowed_actions
        event_preconditions = _string_list_from_payload(
            payload,
            "preconditions",
        )
        if event_preconditions is not None:
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

    if not resource_claims_resolved:
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


def _resource_claims_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    raw_claims = payload["resource_claims"] if "resource_claims" in payload else None
    if not isinstance(raw_claims, list):
        authority = payload.get("authority")
        if isinstance(authority, dict):
            raw_claims = cast(dict[str, Any], authority).get("resource_claims")
    if not isinstance(raw_claims, list):
        return None
    return [
        dict(cast(dict[str, Any], claim))
        for claim in cast(list[Any], raw_claims)
        if isinstance(claim, dict)
    ]


def _string_list_from_payload(payload: dict[str, Any], field: str) -> list[str] | None:
    raw_values = payload[field] if field in payload else None
    if not isinstance(raw_values, list):
        authority = payload.get("authority")
        if isinstance(authority, dict):
            raw_values = cast(dict[str, Any], authority).get(field)
    if not isinstance(raw_values, list):
        return None
    return [value for value in cast(list[Any], raw_values) if isinstance(value, str)]


@router.get("/{run_id}/artifacts/{sha256_hex}")
async def get_run_artifact(
    run_id: str,
    sha256_hex: ArtifactHash,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=65_536, ge=1, le=1_048_576),
    graph_store: GraphEventStore = Depends(get_graph_store),
    repo: RunRepository = Depends(get_run_repository),
    artifact_stores: ArtifactStoreResolver = Depends(get_artifact_store_resolver),
) -> Response:
    """Return an authorized byte range only after complete-blob verification."""
    run = await repo.get(run_id)
    content_hash = f"sha256:{sha256_hex}"
    raw_ref = await graph_store.read_authorized_artifact_reference(run_id, content_hash)
    if raw_ref is None:
        raise HTTPException(status_code=404, detail="Artifact reference not found for run")
    try:
        ref = StoredArtifactRef.model_validate(raw_ref)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Artifact reference is malformed") from exc
    try:
        content, total = await (await artifact_stores.for_run(run)).read_range(
            ref, offset=offset, limit=limit
        )
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Artifact blob not found") from exc
    except ArtifactIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="Artifact blob failed integrity verification",
        ) from exc
    if offset >= total:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{total}"},
        )
    end = offset + len(content)
    return Response(
        content=content,
        status_code=206,
        media_type=ref.media_type,
        headers={"Content-Range": f"bytes {offset}-{max(offset, end) - 1}/{total}"},
    )


@router.get("/{run_id}/graph", response_model=GraphProjectionResponse)
async def get_graph_projection(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
    service: Any = Depends(get_workflow_service),
) -> GraphProjectionResponse:
    try:
        snapshot = await graph_store.read_current_projection_snapshot(run_id)
    except GraphReadModelUnavailable as error:
        _raise_read_model_unavailable(error)
    response = build_graph_projection_response_from_snapshot(run_id, snapshot)
    try:
        run = await service.get_run(run_id)
    except RunNotFoundError:
        return response
    return response.model_copy(
        update={
            "run_state": _graph_api_run_state(
                response.run_state,
                cast(RunStatus | None, run.status),
            ),
        }
    )


@router.get("/{run_id}/graph/health", response_model=GraphHealthResponse)
async def get_graph_health(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
    service: Any = Depends(get_workflow_service),
) -> GraphHealthResponse:
    """Return bounded graph diagnostics only for a persisted run."""
    try:
        await service.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    health = await graph_store.read_bounded_graph_health(
        run_id, detail_limit=_GRAPH_HEALTH_MAX_DETAILS
    )
    return build_bounded_graph_health_response(run_id, health)


@router.get("/{run_id}/graph/topology", response_model=GraphTopologyResponse)
async def get_graph_topology(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=GRAPH_FIXED_VIEW_ITEMS, ge=1, le=GRAPH_FIXED_VIEW_ITEMS),
    expected_position: int | None = Query(default=None, ge=0),
) -> GraphTopologyResponse:
    try:
        archival = await graph_store.read_current_archival_view_page(
            run_id,
            "topology",
            after_sequence=cursor,
            limit=limit,
            expected_position=expected_position,
        )
    except GraphExpectedPositionMismatch as error:
        _raise_expected_position_mismatch(error)
    except GraphReadModelUnavailable as error:
        _raise_read_model_unavailable(error)
    if archival is None:
        return GraphTopologyResponse(run_id=run_id, event_count=0, nodes=[], edges=[])
    position, page = archival
    nodes: list[GraphTopologyNodeResponse] = []
    edges: list[GraphTopologyEdgeResponse] = []
    items, partial, collection_meta = _unpack_archival_items(
        page.items,
        identity_fields=("node_id", "edge_id"),
    )
    for item in items:
        entry_kind = item.pop("_entry_kind", None)
        if entry_kind == "node":
            nodes.append(GraphTopologyNodeResponse(**item))
        elif entry_kind == "edge":
            edges.append(GraphTopologyEdgeResponse(**item))
    return GraphTopologyResponse(
        run_id=run_id,
        event_count=position,
        nodes=nodes,
        edges=edges,
        truncated=page.truncated,
        total_known=page.total_known,
        next_cursor=page.next_cursor,
        partial=partial,
        collection_meta=collection_meta,
    )


@router.get("/{run_id}/graph/patches", response_model=GraphPatchAttemptsResponse)
async def get_graph_patch_attempts(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
    from_position: int = Query(default=0, ge=0),
    limit: int = Query(
        default=DEFAULT_GRAPH_PATCH_ATTEMPT_LIMIT,
        ge=1,
        le=MAX_GRAPH_PATCH_ATTEMPT_LIMIT,
    ),
) -> GraphPatchAttemptsResponse:
    page = await graph_store.read_graph_patch_attempt_page(
        run_id,
        after_position=from_position,
        limit=limit,
    )
    current_graph_position = await graph_store.current_position(run_id)
    return build_bounded_graph_patch_attempts_response(
        run_id,
        page,
        current_graph_position=current_graph_position,
        limit=limit,
    )


@router.post(
    "/{run_id}/graph/patch",
    response_model=SubmitGraphPatchResponse,
    response_model_exclude_none=True,
)
async def submit_operator_graph_patch(
    run_id: str,
    request: SubmitGraphPatchRequest,
    config: Annotated[GlobalConfig, Depends(get_global_config)],
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> SubmitGraphPatchResponse:
    current_position = await graph_store.current_position(run_id)
    if current_position == 0:
        raise HTTPException(status_code=404, detail="Graph not found for run")

    patch_id = request.patch_id or f"operator-patch-{uuid4().hex}"
    payload = request.model_dump(exclude_none=True)
    payload.update(
        {
            "patch_id": patch_id,
            "base_graph_position": request.base_graph_position
            if request.base_graph_position is not None
            else current_position,
        }
    )
    controller = GraphController(
        session_factory,
        _ApiGraphClock(),
        _ApiGraphIdGenerator(),
        auto_dispatch=False,
        journal_max_bytes=config.journal.max_bytes,
    )
    try:
        result = await controller.handle_command(
            run_id,
            current_position,
            "submit_patch",
            payload,
            context=PatchCommandContext(
                run_id=run_id,
                current_graph_position=current_position,
                actor=Actor(kind=ActorKind.HUMAN, id="human-operator", role="operator"),
                actor_role="human",
                proposed_by_node_id="human-operator",
            ),
        )
    except GraphReadModelUnavailable as exc:
        # Patch validation reads the bounded runtime checkpoint before it can
        # decide whether a submitted base is current.  A missing/stale owner
        # must remain a retryable read-model failure, never an accidental 500.
        _raise_read_model_unavailable(exc)
    except StaleProjectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    rejection = next(
        (
            event
            for event in result.events
            if event.event_type in {"graph_patch_rejected", "command_rejected"}
        ),
        None,
    )
    if rejection is not None:
        reason = rejection.payload.get("reason", "graph patch rejected")
        raise HTTPException(status_code=409, detail=str(reason))

    return SubmitGraphPatchResponse(
        run_id=run_id,
        graph_position=result.projection_position,
        accepted=True,
        patch_id=patch_id,
        events=[_event_to_response(event) for event in result.events],
    )


@router.get("/{run_id}/graph/final-blockers", response_model=FinalInvariantBlockersResponse)
async def get_graph_final_blockers(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    cursor: str = Query(default="0"),
    limit: int = Query(default=GRAPH_FIXED_VIEW_ITEMS, ge=1, le=GRAPH_FIXED_VIEW_ITEMS),
    expected_position: int | None = Query(default=None, ge=0),
) -> FinalInvariantBlockersResponse:
    cursor_kind, cursor_value = _parse_final_blocker_cursor(cursor)
    try:
        archival = await graph_store.read_current_archival_view_page(
            run_id,
            "final_blockers",
            after_sequence=cursor_value if cursor_kind == "archival" else 0,
            # The outbox continuation only needs the checkpoint/total facts;
            # do not fetch a page that belongs to the previous namespace.
            limit=limit if cursor_kind == "archival" else 1,
            expected_position=expected_position,
        )
    except GraphExpectedPositionMismatch as error:
        _raise_expected_position_mismatch(error)
    except GraphReadModelUnavailable as error:
        _raise_read_model_unavailable(error)
    archived_total = archival[1].total_known if archival is not None else 0
    archival_items = archival[1].items if archival is not None and cursor_kind == "archival" else ()
    archival_has_more = bool(
        archival is not None and cursor_kind == "archival" and archival[1].truncated
    )
    # Failed-outbox rows are a second cursor namespace.  Overlay them only
    # after the archival namespace is exhausted; otherwise every archival page
    # would repeat the same outbox prefix before its cursor can advance.
    remaining = 0 if archival_has_more else max(0, limit - len(archival_items))
    async with session_factory() as session:
        failed_count = int(
            await session.scalar(
                select(func.count())
                .select_from(GraphOutboxModel)
                .where(GraphOutboxModel.run_id == run_id)
                .where(GraphOutboxModel.status == "failed")
            )
            or 0
        )
        # Do not select ``payload`` here.  It is opaque side-effect input and
        # may be much larger than the public diagnostic overlay; selecting the
        # explicit scalar columns keeps this read outside the JSON decode path.
        failed_query = (
            select(
                GraphOutboxModel.outbox_id,
                GraphOutboxModel.event_id,
                GraphOutboxModel.kind,
                GraphOutboxModel.last_error,
                GraphOutboxModel.attempts,
            )
            .where(GraphOutboxModel.run_id == run_id)
            .where(GraphOutboxModel.status == "failed")
        )
        if cursor_kind == "outbox":
            failed_query = failed_query.where(GraphOutboxModel.outbox_id > cursor_value)
        result = await session.execute(
            failed_query.order_by(GraphOutboxModel.outbox_id).limit(remaining)
        )
        failed_outbox_rows = [
            _FailedOutboxRow(
                outbox_id=int(row.outbox_id),
                event_id=str(row.event_id),
                kind=str(row.kind),
                last_error=str(row.last_error) if row.last_error is not None else None,
                attempts=int(row.attempts),
            )
            for row in result
        ]
    failed, failed_partial, failed_meta = _failed_outbox_blocker_responses(
        run_id, failed_outbox_rows
    )

    if cursor_kind == "outbox":
        failed, failed_meta = _pack_failed_outbox_overlay(
            failed, failed_meta, byte_budget=_GRAPH_RESPONSE_BYTES - 4_096
        )
        failed_partial = bool(failed_meta)
        # A page can be exactly full even when there is no subsequent row.
        # Probe only the keyset successor, never a skipped offset range.
        next_cursor = (
            await _next_failed_outbox_cursor(
                session_factory, run_id, cast(int, failed[-1].outbox_id)
            )
            if failed_outbox_rows and failed
            else None
        )
        return FinalInvariantBlockersResponse(
            run_id=run_id,
            event_count=archival[0] if archival is not None else 0,
            blockers=failed,
            truncated=next_cursor is not None,
            total_known=archived_total + failed_count,
            next_cursor=next_cursor,
            partial=failed_partial,
            collection_meta=failed_meta,
        )

    if archival is None:
        failed, failed_meta = _pack_failed_outbox_overlay(
            failed, failed_meta, byte_budget=_GRAPH_RESPONSE_BYTES - 4_096
        )
        failed_partial = bool(failed_meta)
        next_cursor = (
            await _next_failed_outbox_cursor(
                session_factory,
                run_id,
                cast(int, failed[-1].outbox_id) if failed else 0,
            )
            if failed_outbox_rows
            else (f"{_FINAL_BLOCKER_OUTBOX_CURSOR_PREFIX}0" if failed_count else None)
        )
        return FinalInvariantBlockersResponse(
            run_id=run_id,
            event_count=0,
            blockers=failed,
            truncated=next_cursor is not None,
            total_known=failed_count,
            next_cursor=next_cursor,
            partial=failed_partial,
            collection_meta=failed_meta,
        )

    position, page = archival
    archival_payloads, archival_partial, archival_meta = _unpack_archival_items(
        archival_items,
        identity_fields=("node_id", "edge_id", "task_region_id", "proposal_id", "requirement_id"),
    )
    blockers = [FinalInvariantBlockerResponse(**item) for item in archival_payloads]
    archival_bytes = sum(
        len(json.dumps(blocker.model_dump(mode="json"), separators=(",", ":")).encode()) + 64
        for blocker in blockers
    )
    failed, failed_meta = _pack_failed_outbox_overlay(
        failed,
        failed_meta,
        byte_budget=max(0, _GRAPH_RESPONSE_BYTES - 4_096 - archival_bytes),
    )
    failed_partial = bool(failed_meta)
    blockers.extend(failed)
    total_known = archived_total + failed_count
    if page.truncated:
        next_cursor: str | int | None = page.next_cursor
    elif failed_outbox_rows:
        next_cursor = (
            await _next_failed_outbox_cursor(
                session_factory, run_id, cast(int, failed[-1].outbox_id)
            )
            if failed
            else f"{_FINAL_BLOCKER_OUTBOX_CURSOR_PREFIX}0"
        )
    else:
        next_cursor = f"{_FINAL_BLOCKER_OUTBOX_CURSOR_PREFIX}0" if failed_count else None
    return FinalInvariantBlockersResponse(
        run_id=run_id,
        event_count=position,
        blockers=blockers,
        truncated=next_cursor is not None,
        total_known=total_known,
        next_cursor=next_cursor,
        partial=archival_partial or failed_partial,
        collection_meta={**archival_meta, **failed_meta},
    )


def _parse_final_blocker_cursor(cursor: str) -> tuple[Literal["archival", "outbox"], int]:
    """Parse the two keyset cursor namespaces used by final blockers."""
    if cursor.isdecimal():
        return "archival", int(cursor)
    if cursor.startswith(_FINAL_BLOCKER_OUTBOX_CURSOR_PREFIX):
        raw_id = cursor.removeprefix(_FINAL_BLOCKER_OUTBOX_CURSOR_PREFIX)
        if raw_id.isdecimal():
            return "outbox", int(raw_id)
    raise HTTPException(
        status_code=422, detail="cursor must be a non-negative sequence or outbox:<id>"
    )


async def _next_failed_outbox_cursor(
    session_factory: async_sessionmaker[AsyncSession], run_id: str, after_outbox_id: int
) -> str | None:
    """Return the last consumed key only when a keyset successor exists."""
    async with session_factory() as session:
        next_id = await session.scalar(
            select(GraphOutboxModel.outbox_id)
            .where(GraphOutboxModel.run_id == run_id)
            .where(GraphOutboxModel.status == "failed")
            .where(GraphOutboxModel.outbox_id > after_outbox_id)
            .order_by(GraphOutboxModel.outbox_id)
            .limit(1)
        )
    return (
        f"{_FINAL_BLOCKER_OUTBOX_CURSOR_PREFIX}{after_outbox_id}" if next_id is not None else None
    )


@router.get("/{run_id}/graph/regions", response_model=GraphRegionsResponse)
async def get_graph_regions(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=GRAPH_FIXED_VIEW_ITEMS, ge=1, le=GRAPH_FIXED_VIEW_ITEMS),
    expected_position: int | None = Query(default=None, ge=0),
) -> GraphRegionsResponse:
    try:
        archival = await graph_store.read_current_archival_view_page(
            run_id,
            "regions",
            after_sequence=cursor,
            limit=limit,
            expected_position=expected_position,
        )
    except GraphExpectedPositionMismatch as error:
        _raise_expected_position_mismatch(error)
    except GraphReadModelUnavailable as error:
        _raise_read_model_unavailable(error)
    if archival is None:
        return GraphRegionsResponse(run_id=run_id, event_count=0, regions=[])
    position, page = archival
    region_payloads, partial, collection_meta = _unpack_archival_items(
        page.items,
        identity_fields=("task_region_id",),
    )
    return GraphRegionsResponse(
        run_id=run_id,
        event_count=position,
        regions=[GraphRegionResponse(**item) for item in region_payloads],
        truncated=page.truncated,
        total_known=page.total_known,
        next_cursor=page.next_cursor,
        partial=partial,
        collection_meta=collection_meta,
    )


@router.get(
    "/{run_id}/graph/events",
    response_model=list[GraphEventResponse],
    responses={
        200: {
            "headers": {
                "X-Has-More": {
                    "description": "Whether another page of matching events exists.",
                    "schema": {"type": "boolean"},
                },
                "X-Next-Position": {
                    "description": (
                        "Inclusive from_position for the next page, or null when this is the "
                        "final or an empty page."
                    ),
                    "schema": {"type": "string", "pattern": r"^(null|[0-9]+)$"},
                },
                "X-Truncated-By-Bytes": {
                    "description": "Whether the response byte ceiling ended this page.",
                    "schema": {"type": "boolean"},
                },
            }
        }
    },
)
async def get_graph_events(
    run_id: str,
    response: Response,
    from_position: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_GRAPH_EVENT_LIMIT, ge=1, le=MAX_GRAPH_EVENT_LIMIT),
    payload_mode: Literal["summary", "full"] = Query(default="summary"),
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> list[GraphEventResponse]:
    if payload_mode == "summary":
        try:
            page = await graph_store.read_current_run_summary_page(
                run_id,
                from_position=from_position,
                limit=limit + 1,
            )
        except GraphReadModelUnavailable as error:
            _raise_read_model_unavailable(error)
        events = [_summary_to_response(event) for event in page[:limit]]
    else:
        page = await graph_store.read_bounded_full_event_page(
            run_id,
            from_position=from_position,
            limit=limit + 1,
            payload_byte_cap=GRAPH_READ_CONTRACTS["events_full"].budget.rendered_payload_byte_cap
            or GRAPH_READ_CONTRACTS["events_full"].byte_cap,
        )
        events = [_bounded_full_event_to_response(event) for event in page[:limit]]

    events, byte_truncated = _bounded_graph_event_page(events)
    has_more = len(page) > limit or byte_truncated
    response.headers["X-Has-More"] = str(has_more).lower()
    response.headers["X-Truncated-By-Bytes"] = str(byte_truncated).lower()
    response.headers["X-Next-Position"] = (
        str(events[-1].position + 1) if has_more and events else "null"
    )
    return events


def _bounded_graph_event_page(
    events: list[GraphEventResponse],
) -> tuple[list[GraphEventResponse], bool]:
    retained: list[GraphEventResponse] = []
    serialized_bytes = 2
    for event in events:
        encoded = json.dumps(
            event.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        separator_bytes = 1 if retained else 0
        if (
            serialized_bytes + separator_bytes + len(encoded)
            > GRAPH_READ_CONTRACTS["events_summary"].byte_cap
        ):
            return retained, True
        retained.append(event)
        serialized_bytes += separator_bytes + len(encoded)
    return retained, False


@router.get("/{run_id}/graph/scheduler", response_model=SchedulerViewResponse)
async def get_graph_scheduler_view(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> SchedulerViewResponse:
    try:
        snapshot = await graph_store.read_current_projection_snapshot(run_id)
    except GraphReadModelUnavailable as error:
        _raise_read_model_unavailable(error)
    return build_scheduler_view_response_from_snapshot(run_id, snapshot)


@router.get(
    "/{run_id}/graph/decisions",
    response_model=DecisionViewResponse,
    response_model_exclude_none=True,
)
async def get_graph_decision_view(
    run_id: str,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> DecisionViewResponse:
    try:
        snapshot = await graph_store.read_current_projection_snapshot(run_id)
    except GraphReadModelUnavailable as error:
        _raise_read_model_unavailable(error)
    return build_decision_view_response_from_snapshot(run_id, snapshot)


@router.post(
    "/{run_id}/graph/decisions",
    response_model=RecordGraphDecisionResponse,
    response_model_exclude_none=True,
)
async def record_graph_decision(
    run_id: str,
    request: RecordGraphDecisionRequest,
    config: Annotated[GlobalConfig, Depends(get_global_config)],
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
        journal_max_bytes=config.journal.max_bytes,
    )
    try:
        result = await controller.handle_command(
            run_id,
            current_position,
            "record_decision",
            request.model_dump(exclude_none=True),
            context=GraphCommandContext(
                run_id=run_id,
                current_graph_position=current_position,
                actor=Actor(kind=ActorKind.HUMAN, id="human-operator", role="operator"),
            ),
        )
    except StaleProjectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    rejected = [event.payload for event in result.events if event.event_type == "command_rejected"]
    if rejected:
        reason = rejected[-1].get("reason", "decision rejected")
        raise HTTPException(status_code=409, detail=str(reason))

    response_events = list(result.events)
    # ``controller`` commits in its own session.  Read the compact owner in a
    # fresh session so this request's injected graph-store session cannot
    # return an identity-mapped pre-command snapshot.
    async with session_factory() as snapshot_session:
        try:
            post_decision_snapshot = await GraphEventStore(
                snapshot_session
            ).read_current_projection_snapshot(run_id)
        except GraphReadModelUnavailable as error:
            _raise_read_model_unavailable(error)
    if post_decision_snapshot is not None and post_decision_snapshot.run_state == "active":
        schedule_result = await controller.handle_command(
            run_id,
            result.projection_position,
            "schedule_tick",
            {
                "lease_seconds": 300,
                "max_grants": 0,
                "base_snapshot_id": "routine-snapshot",
            },
            context=GraphCommandContext(
                run_id=run_id,
                current_graph_position=result.projection_position,
                actor=Actor(kind=ActorKind.HUMAN, id="human-operator", role="operator"),
            ),
        )
        response_events.extend(schedule_result.events)
    try:
        snapshot = await graph_store.read_current_projection_snapshot(run_id)
    except GraphReadModelUnavailable as error:
        _raise_read_model_unavailable(error)
    return RecordGraphDecisionResponse(
        run_id=run_id,
        graph_position=snapshot.position if snapshot is not None else 0,
        events=[_event_to_response(event) for event in response_events],
        decision_view=build_decision_view_response_from_snapshot(run_id, snapshot),
    )


@router.get("/{run_id}/graph/file-state", response_model=FileStateReportResponse)
async def get_graph_file_state_report(
    run_id: str,
    from_position: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[
        int, Query(ge=1, le=MAX_FILE_STATE_PAGE_LIMIT)
    ] = DEFAULT_FILE_STATE_PAGE_LIMIT,
    path_limit: Annotated[
        int, Query(ge=1, le=MAX_FILE_STATE_PATH_LIMIT)
    ] = DEFAULT_FILE_STATE_PATH_LIMIT,
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> FileStateReportResponse:
    try:
        page = await graph_store.read_file_state_report_page(
            run_id,
            from_position=from_position,
            limit=limit,
            path_limit=path_limit,
        )
    except GraphReadModelUnavailable as error:
        _raise_read_model_unavailable(error)
    events = sorted((*page.boundaries, *page.associated_facts), key=lambda event: event.position)
    return build_file_state_report_response(
        run_id,
        events,
        from_position=from_position,
        has_more=page.has_more,
        path_limit=path_limit,
        gatekeeper_fact_counts=page.associated_fact_counts,
        orphan_gatekeeper_fact_count=page.orphan_gatekeeper_fact_count,
        boundary_event_count=len(page.boundaries),
        next_position=(page.boundaries[-1].position + 1 if page.boundaries else None),
    )


@router.get("/{run_id}/graph/nodes/{node_id}", response_model=NodeDetailResponse)
async def get_graph_node_detail(
    run_id: str,
    node_id: str,
    payload_mode: Literal["summary", "full"] = Query(default="summary"),
    graph_store: GraphEventStore = Depends(get_graph_store),
) -> NodeDetailResponse:
    try:
        summary = await graph_store.read_current_node_detail_summary(run_id, node_id)
    except GraphReadModelUnavailable as error:
        _raise_read_model_unavailable(error)
    if summary is None:
        if await graph_store.current_position(run_id) == 0:
            raise HTTPException(status_code=404, detail="No graph projection found for run")
        raise HTTPException(status_code=404, detail="Graph node not found")
    if payload_mode == "full":
        try:
            full_events = await graph_store.read_run_positions(
                run_id,
                _compact_event_positions(summary.events),
            )
        except GraphReadModelUnavailable as error:
            _raise_read_model_unavailable(error)
        return build_node_detail_response_from_summary(summary, full_events=full_events)
    return build_node_detail_response_from_summary(summary)
