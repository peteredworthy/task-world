"""Pure graph projections for scenario fixtures."""

from __future__ import annotations

from hashlib import sha256
from json import dumps
from bisect import bisect_left
from dataclasses import dataclass, field as dataclass_field
from datetime import UTC, datetime
from typing import Any, Iterable, Literal, TypeGuard, TypedDict, cast

from pydantic import ConfigDict, field_validator

from orchestrator.graph.command_bindings import check_command_reference
from orchestrator.graph.contracts import (
    DEFAULT_NODE_CONTRACTS,
    PortContract,
    binding_policy,
    input_port_contract,
    merge_bound_record_ids,
    node_contract_summary,
    output_port_contract,
    port_contract_summary,
)
from orchestrator.graph.event_registry import EVENT_PAYLOAD_MODELS, PROJECTION_NEUTRAL_EVENT_TYPES
from orchestrator.graph.models import (
    AcceptedOutputRecordPayload,
    AppealOpenedPayload,
    CandidateRecord,
    CheckResultRecord,
    CompletionDecisionRecord,
    DecisionRequestRecord,
    ApprovalDecisionRecordedPayload,
    AuthorityDecisionRecordedPayload,
    AuthorityRequestRecord,
    CallbackAcceptedPayload,
    CleanupAppliedPayload,
    CleanupRequestedPayload,
    EnvironmentFailureProjection,
    EventEnvelope,
    ExternalFileEntry,
    FileEntry,
    FileStateRecord,
    FailureRecord,
    freeze_canonical_record,
    GatekeeperCostRecordedPayload,
    GatekeeperVerdictRecordedPayload,
    GraphBaseModel,
    GraphPatchAcceptedPayload,
    GraphPatchRejectedPayload,
    GraphPatchResultRecord,
    InputBoundPayload,
    LeaseExpiredPayload,
    LeaseGrantedPayload,
    LeaseReleasedPayload,
    LeaseRenewedPayload,
    LeaseRevokedPayload,
    LeaseSuspendedPayload,
    NodeCreationProjection,
    NodeAuthorityChangedPayload,
    NodeCreatedPayload,
    NodeDeferredPayload,
    NodeReadyPayload,
    NodeRetiredPayload,
    NodeStateChangedPayload,
    NodeUsageRecordedPayload,
    NodeSuspectPayload,
    NodeKind,
    NodeState,
    OUTPUT_RECORD_MODELS_BY_TYPE,
    OversightDecisionProjection,
    OversightDecisionRecordedPayload,
    OutputRecordAcceptedPayload,
    OutputRecord,
    PlannerSessionStateChangedPayload,
    RequirementRevisionPayload,
    RunLifecycleChangedPayload,
    RuntimeRetryScheduledPayload,
    ResourceClaimProjection,
    RecoveryPlanRecord,
    SemanticArtifactRecord,
    SupportEvidencePayload,
    RoutineSnapshotRecord,
    StoredArtifactRef,
    VerificationFailedPayload,
    VerificationPassedPayload,
)
from orchestrator.graph.models import normalize_record_selector
from orchestrator.graph.payload_registry import (
    GRAPH_PROJECTION_PAYLOAD_FIELDS as _GENERATED_GRAPH_PROJECTION_PAYLOAD_FIELDS,
)
from orchestrator.graph.projection_collections import FrozenMap, freeze_json, map_set, thaw_json
from orchestrator.graph.projection_codec import PROJECTION_CHECKPOINT_SCHEMA_VERSION
from orchestrator.graph.projection_models import (
    ApprovalDecisionValue,
    AuthorityDecisionValue,
    CandidateValue,
    CallbackEventValue,
    CheckResultValue,
    CleanupRequestValue,
    EnvironmentFailureValue,
    ExecutionAuthorityValue,
    FinalInvariantBlockerProjection,
    GraphProjection,
    GraphRecordSummaryProjection,
    EdgeValue,
    InputBindingValue,
    LatestRoutineSnapshotProjection,
    LeaseValue,
    NodeProjection,
    NodeRuntimeProjection,
    NodeSchedulingProjection,
    NodeSpecProjection,
    OversightDecisionValue,
    PlannerSessionProjection,
    PlannerPatchDecisionValue,
    RecoveryNodeIndexValue,
    RecordStore,
    RegionSnapshotValue,
    ResourceClaimValue,
    RequirementRevisionValue,
    SupportEvidenceValue,
    TaskProjection,
    VerificationResultValue,
    VerifierVerdictValue,
    InvalidTestBlockValue,
)


_EDGE_METADATA_KEYS = (
    "purpose",
    "description",
    "selection",
    "binding_policy",
    "freshness_policy",
    "prompt_hydration_policy",
    "metadata",
)

_TASK_STATE_VALUES = {
    "accepted",
    "blocked_environment",
    "blocked_invalid_test",
    "in_progress",
    "needs_revision",
    "pending",
}
_NODE_STATE_VALUES = {state.value for state in NodeState}
_NODE_KIND_VALUES = {kind.value for kind in NodeKind}

# Bump this whenever reduce_event semantics or GraphProjection shape changes.
# Schema 15 is the disposable envelope introduced for projection checkpoints.
PROJECTION_SCHEMA_VERSION = PROJECTION_CHECKPOINT_SCHEMA_VERSION
GRAPH_PROJECTION_PAYLOAD_FIELDS = _GENERATED_GRAPH_PROJECTION_PAYLOAD_FIELDS


def checkpoint_schema_is_current(schema_version: int | None) -> TypeGuard[int]:
    """Return whether a persisted checkpoint can be read by this projection schema."""
    return type(schema_version) is int and schema_version == PROJECTION_SCHEMA_VERSION


class GraphRecordSummary(TypedDict, total=False):
    record_id: str
    record_type: str
    record_kind: str
    schema: str
    producer_node_id: str
    producer_port: str
    position: int


class AcceptedOutputRecord(TypedDict):
    record_id: str
    payload: AcceptedOutputRecordPayload


class RecoveryNodeIndexEntry(GraphBaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    node_id: str
    recovery_reason: str

    @field_validator("node_id", "recovery_reason")
    @classmethod
    def fields_must_be_non_empty(cls, value: str) -> str:
        if not value:
            msg = "field must be non-empty"
            raise ValueError(msg)
        return value


class LatestRoutineSnapshotRecord(GraphBaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    record_id: str
    producer_node_id: str
    port: str

    @field_validator("record_id", "producer_node_id", "port")
    @classmethod
    def fields_must_be_non_empty(cls, value: str) -> str:
        if not value:
            msg = "field must be non-empty"
            raise ValueError(msg)
        return value


class GraphTopologyBinding(TypedDict, total=False):
    edge_id: str
    to_node_id: str
    to_port: str
    record_ids: list[str]
    bound_at_position: int
    record_bound_positions: dict[str, int]
    binding_policy: str
    trigger: str


class GraphTopologyNode(TypedDict, total=False):
    node_id: str
    kind: str | None
    role: str | None
    state: str | None
    contract: dict[str, Any]


class GraphTopologyEdge(TypedDict, total=False):
    edge_id: str
    from_node_id: str
    from_node_kind: str
    from_node_role: str
    from_port: str
    to_node_id: str
    to_port: str
    required: bool
    dependency_type: str
    accepted_record_selector: dict[str, Any]
    metadata: dict[str, Any]
    source_port_contract: dict[str, Any]
    target_port_contract: dict[str, Any]
    record_types: list[str]
    binding: GraphTopologyBinding | None
    bound_records: list[GraphRecordSummary]


class GraphTopologyView(TypedDict):
    nodes: list[GraphTopologyNode]
    edges: list[GraphTopologyEdge]


class SchedulerBlockedNode(TypedDict):
    node_id: str
    reason: str


class SchedulerView(TypedDict):
    ready: list[str]
    blocked: list[SchedulerBlockedNode]
    waiting_resources: list[SchedulerBlockedNode]
    waiting_gates: list[SchedulerBlockedNode]


class LeaseViewEntry(TypedDict):
    lease_id: str
    node_id: str
    generation: int | None
    state: str
    execution_id: str | None
    expires_at: str | None


class LeaseView(TypedDict):
    active: list[LeaseViewEntry]
    suspended: list[LeaseViewEntry]


class PendingGateDecision(TypedDict, total=False):
    node_id: str
    gate_type: str
    prompt: str | None
    options: list[str]
    default_option: str
    consequence_summary: str
    expires_at: str
    requested_authority: list[str]
    target_node_id: str
    target_region_id: str


class AppealDecision(TypedDict):
    node_id: str
    state: str
    outcome: str | None


class ReviewReadiness(TypedDict):
    ready: bool
    blockers: list[str]


class DecisionView(TypedDict):
    pending_gates: list[PendingGateDecision]
    appeals: list[AppealDecision]
    review: ReviewReadiness


class SupportEvidenceFreshness(TypedDict):
    support_id: str
    evidence_id: str
    requirement_id: str
    requirement_version_id: str
    status: str
    freshness: Literal["fresh", "stale"]
    stale_reason: str | None


class RequirementFreshnessFact(TypedDict):
    requirement_id: str
    active_version_id: str
    revision_classification: str
    requires_authority: bool
    authority_required_reason: str | None
    fresh_support_ids: list[str]
    stale_support_ids: list[str]
    unsupported: bool


class FinalInvariantBlocker(TypedDict, total=False):
    kind: str
    reason: str
    node_id: str
    edge_id: str
    from_node_id: str
    to_port: str
    proposal_id: str
    requirement_id: str
    revision_id: str
    task_region_id: str
    batch_id: str
    state: str
    classification: str
    command_text: str
    stderr_tail: str
    exit_code: int
    support_ids: list[str]


_GRAPH_ARCHIVAL_READ_CONTRACT_KEY = "_graph_archival_read_contract"
_GRAPH_ARCHIVAL_READ_CONTRACT_REVISION = 1


def _with_archival_collection_metadata(
    payload: FinalInvariantBlocker,
    *,
    owner: str,
    path: str,
    total_known: int,
    retained: list[str],
    enabled: bool,
) -> FinalInvariantBlocker:
    if not enabled or total_known <= len(retained):
        return payload
    result = cast(dict[str, Any], dict(payload))
    contract = cast(
        dict[str, Any],
        result.setdefault(
            _GRAPH_ARCHIVAL_READ_CONTRACT_KEY,
            {
                "revision": _GRAPH_ARCHIVAL_READ_CONTRACT_REVISION,
                "partial": True,
                "fields": {},
            },
        ),
    )
    fields = cast(dict[str, Any], contract.setdefault("fields", {}))
    fields[path] = {
        "revision": _GRAPH_ARCHIVAL_READ_CONTRACT_REVISION,
        "owner": owner,
        "truncated": True,
        "total_known": total_known,
        "next_cursor": retained[-1] if retained else None,
        "original_bytes": None,
        "sha256": None,
    }
    contract["partial"] = True
    return cast(FinalInvariantBlocker, result)


def _bound_archival_blocker_support_ids(
    blocker: FinalInvariantBlocker,
    collection_limit: int,
) -> FinalInvariantBlocker:
    support_ids = blocker.get("support_ids")
    if not isinstance(support_ids, (list, tuple)):
        return blocker
    retained = list(support_ids[:collection_limit])
    result = cast(FinalInvariantBlocker, dict(blocker))
    result["support_ids"] = retained
    return _with_archival_collection_metadata(
        result,
        owner="final_blockers",
        path="$.support_ids",
        total_known=len(support_ids),
        retained=retained,
        enabled=True,
    )


TERMINAL_GRAPH_NODE_STATES = frozenset({"completed", "failed", "cancelled", "retired"})


@dataclass(frozen=True)
class GraphRunOutcome:
    """Pure driver-facing classification of a graph projection."""

    run_id: str
    run_state: str | None
    completed: bool
    blocked_reason: str | None = None


def _empty_str_dict() -> dict[str, str]:
    return {}


def _empty_environment_failures() -> dict[str, EnvironmentFailureProjection]:
    return {}


def _empty_int_dict() -> dict[str, int]:
    return {}


def _empty_str_list_dict() -> dict[str, list[str]]:
    return {}


@dataclass(frozen=True)
class GraphProjectionSnapshot:
    """Driver policy view derived solely from a graph event projection."""

    run_state: str | None
    ready_nodes: list[str]
    active_leases: dict[str, dict[str, Any]]
    schedulable_nodes: list[str]
    task_states: dict[str, str]
    node_states: dict[str, str] = dataclass_field(default_factory=_empty_str_dict)
    failed_node_reasons: dict[str, str] = dataclass_field(default_factory=_empty_str_dict)
    node_deferral_reasons: dict[str, str] = dataclass_field(default_factory=_empty_str_dict)
    missing_input_sources: dict[str, list[str]] = dataclass_field(
        default_factory=_empty_str_list_dict
    )
    environment_failures: dict[str, EnvironmentFailureProjection] = dataclass_field(
        default_factory=_empty_environment_failures
    )
    node_max_attempts: dict[str, int] = dataclass_field(default_factory=_empty_int_dict)


@dataclass(frozen=True)
class ActiveLeaseWaitPlan:
    execution_ids: set[str]
    timeout_seconds: float | None


class GraphPatchAttempt(TypedDict, total=False):
    patch_id: str
    proposed_by_node_id: str
    base_graph_position: int
    current_graph_position: int
    status: Literal["accepted", "rejected"]
    rejection_reason: str
    diagnostics: dict[str, Any]
    read_set_diff: dict[str, Any]
    accepted_event_id: str
    accepted_position: int
    rejected_event_id: str
    rejected_position: int
    created_node_ids: list[str]
    created_edge_ids: list[str]


class GraphPatchAttemptView(TypedDict):
    run_id: str
    current_graph_position: int
    attempts: list[GraphPatchAttempt]


def initial_projection() -> GraphProjection:
    return GraphProjection()


class ProjectionReplayConflictError(ValueError):
    """A replay event attempts to redefine an immutable graph identity."""


def _require_projection_reference(
    values: FrozenMap[str, Any], value: str, *, relation: str, event_id: str
) -> None:
    """Reject a dangling graph relationship at the event/reducer boundary."""
    if value not in values:
        raise ProjectionReplayConflictError(
            f"{relation} {value!r} is not represented before event {event_id!r}"
        )


def _validate_event_relationships(state: GraphProjection, event: EventEnvelope) -> None:
    """Validate relationships while accepting authoritative events.

    Pure fixture replay intentionally permits detached event fragments.  The
    runtime event store opts into this strict boundary before it persists a
    projection, so relationship failures are attributed to the event that
    introduced them instead of to checkpoint loading.
    """
    if event.event_type == "edge_created":
        from_node_id = event.payload.get("from_node_id")
        to_node_id = event.payload.get("to_node_id")
        if isinstance(from_node_id, str) and from_node_id != "*":
            _require_projection_reference(
                state.nodes,
                from_node_id,
                relation="edge source node",
                event_id=event.event_id,
            )
        if isinstance(to_node_id, str):
            _require_projection_reference(
                state.nodes,
                to_node_id,
                relation="edge target node",
                event_id=event.event_id,
            )
    elif event.event_type == "input_bound":
        payload = InputBoundPayload.model_validate(event.payload)
        _require_projection_reference(
            state.nodes,
            payload.to_node_id,
            relation="input binding target node",
            event_id=event.event_id,
        )
        edge = state.topology.edges.get(payload.edge_id)
        if edge is None:
            raise ProjectionReplayConflictError(
                f"input binding edge {payload.edge_id!r} is not represented before "
                f"event {event.event_id!r}"
            )
        if edge.to_node_id != payload.to_node_id or edge.to_port != payload.to_port:
            raise ProjectionReplayConflictError(
                f"input binding edge {payload.edge_id!r} does not target "
                f"{payload.to_node_id!r}:{payload.to_port!r}"
            )
        for record_id in (*payload.record_ids, payload.supersedes_record_id):
            if record_id is not None:
                _require_projection_reference(
                    state.records.by_id,
                    record_id,
                    relation="input binding record",
                    event_id=event.event_id,
                )
    elif event.event_type in {"output_record_accepted", "file_state_accepted"}:
        producer_node_id = event.payload.get("producer_node_id")
        if isinstance(producer_node_id, str):
            _require_projection_reference(
                state.nodes,
                producer_node_id,
                relation="accepted record producer node",
                event_id=event.event_id,
            )
        reference_fields = (
            "candidate_record_id",
            "file_state_record_id",
            "superseding_record_id",
            "verification_report_record_id",
        )
        referenced_ids: list[str] = []
        for field in reference_fields:
            value = event.payload.get(field)
            if isinstance(value, str):
                referenced_ids.append(value)
        for field in (
            "candidate_record_ids",
            "file_state_record_ids",
            "verification_report_record_ids",
            "evaluated_record_ids",
            "source_record_ids",
        ):
            value = event.payload.get(field)
            if isinstance(value, list):
                referenced_ids.extend(
                    record_id for record_id in cast(list[Any], value) if isinstance(record_id, str)
                )
        nested_value = event.payload.get("value")
        if isinstance(nested_value, dict):
            typed_nested_value = cast(dict[str, Any], nested_value)
            for field in reference_fields + (
                "candidate_record_ids",
                "file_state_record_ids",
                "verification_report_record_ids",
                "evaluated_record_ids",
                "source_record_ids",
            ):
                value = typed_nested_value.get(field)
                if isinstance(value, str):
                    referenced_ids.append(value)
                elif isinstance(value, list):
                    referenced_ids.extend(
                        record_id
                        for record_id in cast(list[Any], value)
                        if isinstance(record_id, str)
                    )
        created_record_id = event.payload.get("record_id")
        for record_id in referenced_ids:
            # A typed record may repeat its own identifier in a canonical
            # citation field; that is identity, not a dangling prior record.
            if record_id == created_record_id:
                continue
            _require_projection_reference(
                state.records.by_id,
                record_id,
                relation="accepted record reference",
                event_id=event.event_id,
            )
    elif event.event_type == "node_created":
        for relation, field in (
            ("recovery source node", "recovery_of_node_id"),
            ("recovery source record", "recovery_of_record_id"),
            ("appealed node", "appealed_node_id"),
            ("carryover record", "carryover_record_id"),
        ):
            value = event.payload.get(field)
            if not isinstance(value, str):
                continue
            values = state.nodes if field.endswith("node_id") else state.records.by_id
            _require_projection_reference(values, value, relation=relation, event_id=event.event_id)
    elif event.event_type in {"verification_passed", "verification_failed"}:
        verifier_node_id = event.payload.get("verifier_node_id")
        record_id = event.payload.get("record_id")
        if isinstance(verifier_node_id, str):
            _require_projection_reference(
                state.nodes,
                verifier_node_id,
                relation="verification node",
                event_id=event.event_id,
            )
        if isinstance(record_id, str):
            _require_projection_reference(
                state.records.by_id,
                record_id,
                relation="verification record",
                event_id=event.event_id,
            )
    elif event.event_type == "gatekeeper_verdict_recorded":
        record_id = event.payload.get("file_state_record_id")
        if isinstance(record_id, str):
            _require_projection_reference(
                state.records.by_id,
                record_id,
                relation="gatekeeper file-state record",
                event_id=event.event_id,
            )


def _replace_projection_groups(
    state: GraphProjection,
    **groups: object,
) -> GraphProjection:
    """Install already validated immutable groups without copying unchanged groups."""
    return state.model_copy(update=groups)


def _replace_node(state: GraphProjection, node: NodeProjection) -> GraphProjection:
    node_id = node.spec.node_id
    previous = state.nodes.get(node_id)
    nodes = map_set(state.nodes, node_id, node)
    was_ready = previous is not None and previous.runtime.state == "ready"
    is_ready = node.runtime.state == "ready"
    if was_ready == is_ready:
        return _replace_projection_groups(state, nodes=nodes)

    ready_node_ids = state.scheduling.ready_node_ids
    if was_ready:
        ready_node_ids = tuple(ready_id for ready_id in ready_node_ids if ready_id != node_id)
    else:
        order = (node.spec.creation_position, node_id)
        insertion_index = bisect_left(
            ready_node_ids,
            order,
            key=lambda ready_id: (nodes[ready_id].spec.creation_position, ready_id),
        )
        if insertion_index == len(ready_node_ids):
            ready_node_ids = (*ready_node_ids, node_id)
        else:
            ready_node_ids = (
                *ready_node_ids[:insertion_index],
                node_id,
                *ready_node_ids[insertion_index:],
            )
    scheduling = state.scheduling.model_copy(update={"ready_node_ids": ready_node_ids})
    return _replace_projection_groups(state, nodes=nodes, scheduling=scheduling)


def _node_from_parts(
    spec: NodeSpecProjection,
    runtime: NodeRuntimeProjection,
    scheduling: NodeSchedulingProjection,
) -> NodeProjection:
    values: dict[str, object] = {"spec": spec}
    if any(getattr(runtime, field) is not None for field in NodeRuntimeProjection.model_fields):
        values["runtime"] = runtime
    if any(
        getattr(scheduling, field) is not None for field in NodeSchedulingProjection.model_fields
    ):
        values["scheduling"] = scheduling
    return NodeProjection.model_validate(values)


_TASK_DERIVATION_EVENT_TYPES = frozenset(
    {
        "appeal_opened",
        "approval_decision_recorded",
        "authority_decision_recorded",
        "edge_created",
        "file_state_accepted",
        "gatekeeper_verdict_recorded",
        "lease_expired",
        "lease_granted",
        "lease_released",
        "lease_renewed",
        "lease_revoked",
        "lease_suspended",
        "node_created",
        "node_ready",
        "node_retired",
        "node_state_changed",
        "output_record_accepted",
        "oversight_decision_recorded",
        "verification_failed",
        "verification_passed",
    }
)


def _finalize_projection(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    """Install task facts only after events that can change their derivation."""
    if event.event_type not in _TASK_DERIVATION_EVENT_TYPES:
        return state
    if not state.tasks and not isinstance(event.payload.get("task_region_id"), str):
        return state
    tasks = _with_derived_task_states(state)
    return state if tasks is state.tasks else _replace_projection_groups(state, tasks=tasks)


def _with_derived_task_states(state: GraphProjection) -> FrozenMap[str, TaskProjection]:
    """Install changed task and snapshot-authority facts immutably."""
    derived = _derive_task_states(state)
    current = state.tasks
    task_ids = set(current) | set(derived)
    tasks = current
    changed = False
    for task_id in sorted(task_ids):
        existing = current.get(task_id, TaskProjection())
        next_state = derived.get(task_id)
        accepted, current_candidate, rejected = _task_snapshot_authority(state, task_id)
        updates: dict[str, object] = {}
        if existing.state != next_state:
            updates["state"] = next_state
        if existing.accepted_snapshot != accepted:
            updates["accepted_snapshot"] = accepted
        if existing.current_candidate_snapshot != current_candidate:
            updates["current_candidate_snapshot"] = current_candidate
        if existing.rejected_snapshots != rejected:
            updates["rejected_snapshots"] = rejected
        if updates:
            tasks = map_set(tasks, task_id, existing.model_copy(update=updates))
            changed = True
    return tasks if changed else current


def _task_snapshot_authority(
    state: GraphProjection,
    task_region_id: str,
) -> tuple[RegionSnapshotValue | None, RegionSnapshotValue | None, tuple[RegionSnapshotValue, ...]]:
    task = state.tasks.get(task_region_id)
    if task is None:
        return None, None, ()
    snapshots: list[RegionSnapshotValue] = []
    for candidate in task.candidates:
        file_state = next(
            (
                record
                for record_id in candidate.file_state_record_ids
                if isinstance((record := state.records.by_id.get(record_id)), FileStateRecord)
                and record.snapshot_id is not None
                and record.compromised is not True
            ),
            None,
        )
        if file_state is None or file_state.snapshot_id is None:
            continue
        outcome: Literal["passed", "failed"] | None = None
        verification_record_id: str | None = None
        verification_position = candidate.position
        for record_id, result in state.verification.passed_results_by_record_id.items():
            if result.candidate_id == candidate.candidate_id:
                outcome = "passed"
                verification_record_id = record_id
                verdict = next(
                    (
                        value
                        for value in state.verification.verdicts_by_node.values()
                        if value.candidate_id == candidate.candidate_id
                        and value.verdict == "passed"
                    ),
                    None,
                )
                verification_position = (
                    verdict.position if verdict is not None else candidate.position
                )
        for record_id, result in state.verification.failed_results_by_record_id.items():
            if result.candidate_id == candidate.candidate_id:
                outcome = "failed"
                verification_record_id = record_id
                verdict = next(
                    (
                        value
                        for value in state.verification.verdicts_by_node.values()
                        if value.candidate_id == candidate.candidate_id
                        and value.verdict == "failed"
                    ),
                    None,
                )
                verification_position = (
                    verdict.position if verdict is not None else candidate.position
                )
        snapshots.append(
            RegionSnapshotValue(
                candidate_id=candidate.candidate_id,
                snapshot_id=file_state.snapshot_id,
                base_snapshot_id=file_state.base_snapshot_id,
                file_state_record_id=file_state.record_id,
                verification_record_id=verification_record_id,
                verification_outcome=outcome,
                position=verification_position,
            )
        )
    ordered = tuple(sorted(snapshots, key=lambda item: (item.position, item.candidate_id)))
    accepted_items = tuple(item for item in ordered if item.verification_outcome == "passed")
    rejected = tuple(item for item in ordered if item.verification_outcome == "failed")
    accepted = accepted_items[-1] if accepted_items else None
    current = ordered[-1] if ordered else None
    return accepted, current, rejected


def _node_spec_from_created(payload: NodeCreatedPayload, position: int) -> NodeSpecProjection:
    fields = payload.model_fields_set
    spec_fields = (
        "kind",
        "role",
        "task_region_id",
        "base_snapshot_selection",
        "base_snapshot_region_id",
        "base_snapshot_candidate_id",
        "resource_claims",
        "allowed_actions",
        "preconditions",
        "gate_type",
        "approval_type",
        "reason",
        "prompt",
        "approval_prompt",
        "human_prompt",
        "message",
        "blocker",
        "blocker_reason",
        "decision_request",
        "authority_request_record_id",
        "authority_request",
        "authority",
        "command_definition",
        "command_definition_id",
        "hidden_oracle_command",
        "command_binding",
        "max_attempts",
        "cache_authority_hash",
    )
    data = payload.model_dump(mode="json", include=fields.intersection(spec_fields))
    dispatch_payload = payload.model_dump(mode="json", exclude_none=True)
    for embedded_record_field in (
        "artifact_reference_record",
        "authority_request_record",
        "candidate_record",
        "requirement_record",
        "routine_snapshot_record",
        "run_context_record",
    ):
        dispatch_payload.pop(embedded_record_field, None)
    spec: dict[str, object] = {
        "node_id": payload.node_id,
        "creation_position": position,
        "dispatch_payload": dispatch_payload,
    }
    for name in spec_fields:
        if name in fields:
            spec[name] = data[name]
    if payload.kind == "check":
        command_definition = check_command_reference(payload.model_dump(mode="json"))
        if isinstance(command_definition, dict):
            spec["command_definition"] = command_definition
    authority_request_record = payload.authority_request_record
    if authority_request_record is not None:
        request: dict[str, Any] = authority_request_record
        has_full_envelope = isinstance(request.get("value"), dict)
        if has_full_envelope:
            envelope_input = request
        else:
            envelope_input = {"value": request}
        envelope = AuthorityRequestRecord.model_validate(
            {
                "record_id": f"authority-request-{payload.node_id}",
                "record_kind": "graph_record",
                "record_type": "authority_request_record",
                "producer_node_id": payload.node_id,
                "port": "authority_request_record",
                "schema": "AuthorityRequest",
                **envelope_input,
            }
        )
        explicit_record_id = payload.authority_request_record_id
        if has_full_envelope and explicit_record_id not in {None, envelope.record_id}:
            raise ValueError(
                "authority_request_record_id must match authority_request_record.record_id"
            )
        spec["authority_request_record_id"] = explicit_record_id or envelope.record_id
    if payload.authority is not None:
        authority_data = payload.authority.model_dump(mode="json", exclude_unset=False)
        for name in ("resource_claims", "allowed_actions", "preconditions"):
            if name not in fields:
                spec[name] = authority_data[name]
    preconditions = tuple(payload.preconditions) if "preconditions" in fields else ()
    if "preconditions" not in fields and payload.authority is not None:
        preconditions = tuple(payload.authority.preconditions)
    if payload.kind == "check" and "has_command_definition" not in preconditions:
        spec["preconditions"] = (
            *preconditions,
            "has_command_definition",
        )
    return NodeSpecProjection.model_validate(spec)


def merge_node_created(
    existing: NodeProjection | None,
    payload: NodeCreatedPayload,
    *,
    position: int,
    event_id: str,
) -> NodeProjection:
    """Merge creation facts once, preserving runtime facts accrued after creation."""
    created_spec = _node_spec_from_created(payload, position)
    if existing is None:
        runtime = NodeRuntimeProjection.model_validate(
            {
                field: value
                for field, value in (
                    ("state", payload.state),
                    ("attempt_number", payload.attempt_number),
                    ("candidate_id", payload.candidate_id),
                    ("failed_candidate_id", payload.failed_candidate_id),
                )
                if value is not None
            }
        )
        return _node_from_parts(created_spec, runtime, NodeSchedulingProjection())

    merged = existing.spec.model_dump(exclude_unset=True)
    for field in NodeSpecProjection.model_fields:
        if field in {"node_id", "creation_position"}:
            continue
        old_value = getattr(existing.spec, field)
        new_value = getattr(created_spec, field)
        explicitly_present = field in payload.model_fields_set
        previously_present = field in existing.spec.model_fields_set
        if explicitly_present and (old_value is None or not previously_present):
            merged[field] = new_value
        elif explicitly_present and old_value != new_value:
            raise ProjectionReplayConflictError(
                f"node {payload.node_id!r} conflicts during replay for stable field {field!r} "
                f"in {event_id!r}"
            )
    merged["node_id"] = existing.spec.node_id
    merged["creation_position"] = existing.spec.creation_position
    spec = NodeSpecProjection.model_validate(merged)
    return _node_from_parts(spec, existing.runtime, existing.scheduling)


def _reduce_slice_a(state: GraphProjection, event: EventEnvelope) -> GraphProjection | None:
    if event.event_type == "run_lifecycle_changed":
        payload = RunLifecycleChangedPayload.model_validate(event.payload)
        return _replace_projection_groups(
            state, lifecycle=state.lifecycle.model_copy(update={"run_state": payload.to_state})
        )
    if event.event_type == "node_created":
        payload = NodeCreatedPayload.model_validate(event.payload)
        node = merge_node_created(
            state.nodes.get(payload.node_id),
            payload,
            position=event.position,
            event_id=event.event_id,
        )
        updated = _replace_node(state, node)
        planning = updated.planning
        governance = updated.governance
        verification = updated.verification
        if payload.kind == "root" and payload.planner_generation_budget is not None:
            planning = planning.model_copy(
                update={"generation_budget": payload.planner_generation_budget}
            )
        if payload.kind == "planner" and payload.role == "planner":
            sessions = planning.sessions
            if payload.session_id is not None and payload.session_id not in sessions:
                sessions = map_set(
                    sessions,
                    payload.session_id,
                    PlannerSessionProjection(state="detached"),
                )
            planning = planning.model_copy(
                update={
                    "generation_by_node": map_set(
                        planning.generation_by_node, payload.node_id, payload.generation_index
                    )
                    if payload.generation_index is not None
                    else planning.generation_by_node,
                    "region_label_by_node": map_set(
                        planning.region_label_by_node, payload.node_id, payload.region_label
                    )
                    if payload.region_label is not None
                    else planning.region_label_by_node,
                    "session_id_by_node": map_set(
                        planning.session_id_by_node, payload.node_id, payload.session_id
                    )
                    if payload.session_id is not None
                    else planning.session_id_by_node,
                    "sessions": sessions,
                }
            )
        if payload.kind == "gate" and payload.task_region_id is not None:
            gates = governance.configured_gates_by_task.get(payload.task_region_id, FrozenMap())
            governance = governance.model_copy(
                update={
                    "configured_gates_by_task": map_set(
                        governance.configured_gates_by_task,
                        payload.task_region_id,
                        map_set(gates, payload.node_id, True),
                    )
                }
            )
        if (
            payload.recovery_reason in {"failed_required_check", "failed_verification"}
            and payload.recovery_of_record_id
        ):
            entries = verification.recovery_nodes_by_record_id.get(
                payload.recovery_of_record_id, ()
            )
            entry = RecoveryNodeIndexValue(
                node_id=payload.node_id, recovery_reason=payload.recovery_reason
            )
            if entry not in entries:
                verification = verification.model_copy(
                    update={
                        "recovery_nodes_by_record_id": map_set(
                            verification.recovery_nodes_by_record_id,
                            payload.recovery_of_record_id,
                            (*entries, entry),
                        )
                    }
                )
        if (
            planning is not updated.planning
            or governance is not updated.governance
            or verification is not updated.verification
        ):
            updated = _replace_projection_groups(
                updated, planning=planning, governance=governance, verification=verification
            )
        return updated
    if event.event_type in {
        "node_state_changed",
        "node_retired",
        "node_deferred",
        "node_ready",
        "runtime_retry_scheduled",
        "plan_region_marked_suspect",
        "node_authority_changed",
    }:
        return _reduce_slice_a_node_update(state, event)
    if event.event_type == "edge_created":
        return _reduce_slice_a_edge(state, event)
    if event.event_type == "input_bound":
        return _reduce_slice_a_binding(state, event)
    return None


def _reduce_slice_a_node_update(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    if event.event_type == "plan_region_marked_suspect":
        payload = NodeSuspectPayload.model_validate(event.payload)
        updated = state
        for node_id in _node_ids_from_suspect_payload(payload):
            node = updated.nodes.get(node_id)
            if node is not None:
                updated = _replace_node(
                    updated,
                    _node_from_parts(
                        node.spec,
                        node.runtime.model_copy(
                            update={
                                "suspect_reason": payload.reason
                                or "suspect graph fact remains unresolved"
                            }
                        ),
                        node.scheduling,
                    ),
                )
        return updated
    if event.event_type == "node_state_changed":
        payload = NodeStateChangedPayload.model_validate(event.payload)
        node = state.nodes.get(payload.node_id)
        if node is None:
            return state
        runtime = node.runtime.model_copy(
            update={
                "state": payload.new_state,
                "attempt_number": payload.attempt_number
                if payload.attempt_number is not None
                else node.runtime.attempt_number,
            }
        )
        return _replace_node(state, _node_from_parts(node.spec, runtime, node.scheduling))
    if event.event_type == "node_retired":
        payload = NodeRetiredPayload.model_validate(event.payload)
        node = state.nodes.get(payload.node_id)
        if node is None:
            return state
        return _replace_node(
            state,
            _node_from_parts(
                node.spec, node.runtime.model_copy(update={"state": "retired"}), node.scheduling
            ),
        )
    if event.event_type == "node_deferred":
        payload = NodeDeferredPayload.model_validate(event.payload)
        node = state.nodes.get(payload.node_id)
        if node is None:
            return state
        return _replace_node(
            state,
            _node_from_parts(
                node.spec,
                node.runtime,
                node.scheduling.model_copy(update={"last_deferred_reason": payload.reason}),
            ),
        )
    if event.event_type == "node_ready":
        payload = NodeReadyPayload.model_validate(event.payload)
        node = state.nodes.get(payload.node_id)
        if node is None:
            return state
        return _replace_node(
            state,
            _node_from_parts(
                node.spec,
                node.runtime,
                node.scheduling.model_copy(update={"last_deferred_reason": None}),
            ),
        )
    if event.event_type == "runtime_retry_scheduled":
        payload = RuntimeRetryScheduledPayload.model_validate(event.payload)
        node = state.nodes.get(payload.node_id)
        if node is None:
            return state
        updated = _replace_node(
            state,
            _node_from_parts(
                node.spec,
                node.runtime,
                node.scheduling.model_copy(
                    update={
                        "retry_not_before": payload.retry_not_before,
                        "recovery_blocker_record_id": None,
                        "runtime_retry_count": node.scheduling.runtime_retry_count + 1,
                    }
                ),
            ),
        )
        matching_attempts = [
            attempt
            for attempt in state.execution.attempts_by_execution_id.values()
            if attempt.node_id == payload.node_id
            and attempt.lease_id == payload.lease_id
            and attempt.lease_generation == payload.generation
        ]
        if len(matching_attempts) > 1:
            raise ProjectionReplayConflictError(
                "runtime retry identifies multiple execution attempts"
            )
        if not matching_attempts:
            # Legacy and non-runner retry events predate execution-attempt
            # ownership. Preserve their node scheduling behavior without
            # fabricating a crash-drill lineage fact.
            return updated
        attempt = matching_attempts[0].model_copy(update={"retry_scheduled": True})
        execution = updated.execution.model_copy(
            update={
                "attempts_by_execution_id": map_set(
                    updated.execution.attempts_by_execution_id,
                    attempt.execution_id,
                    attempt,
                )
            }
        )
        return _replace_projection_groups(updated, execution=execution)
    payload = NodeAuthorityChangedPayload.model_validate(event.payload)
    node = state.nodes.get(payload.node_id)
    if node is None:
        return state
    authority = payload.authority
    resource_claims = payload.resource_claims
    if "resource_claims" not in payload.model_fields_set and authority is not None:
        resource_claims = authority.resource_claims
    allowed_actions = payload.allowed_actions
    if "allowed_actions" not in payload.model_fields_set and authority is not None:
        allowed_actions = authority.allowed_actions
    preconditions = payload.preconditions
    if "preconditions" not in payload.model_fields_set and authority is not None:
        preconditions = authority.preconditions
    spec = node.spec.model_copy(
        update={
            "authority": (
                ExecutionAuthorityValue.model_validate(authority.model_dump(mode="json"))
                if authority is not None
                else None
            ),
            "resource_claims": tuple(
                ResourceClaimValue.model_validate(claim.model_dump(mode="json"))
                for claim in resource_claims
            ),
            "allowed_actions": tuple(allowed_actions),
            "preconditions": tuple(preconditions),
            "base_snapshot_selection": (
                payload.base_snapshot_selection
                if "base_snapshot_selection" in payload.model_fields_set
                else node.spec.base_snapshot_selection
            ),
            "base_snapshot_candidate_id": (
                payload.base_snapshot_candidate_id
                if "base_snapshot_candidate_id" in payload.model_fields_set
                else node.spec.base_snapshot_candidate_id
            ),
        }
    )
    return _replace_node(state, _node_from_parts(spec, node.runtime, node.scheduling))


def _reduce_slice_a_edge(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    edge = EdgeValue.model_validate(_edge_payload_for_projection(event.payload))
    existing = state.topology.edges.get(edge.edge_id)
    if existing is not None and existing != edge:
        raise ProjectionReplayConflictError(f"edge {edge.edge_id!r} conflicts during replay")
    if existing is not None:
        return state
    topology = state.topology
    inbound = topology.inbound_edge_ids.get(edge.to_node_id, ())
    outbound = topology.outbound_edge_ids.get(edge.from_node_id, ())
    topology = topology.model_copy(
        update={
            "edges": map_set(topology.edges, edge.edge_id, edge),
            "inbound_edge_ids": map_set(
                topology.inbound_edge_ids, edge.to_node_id, (*inbound, edge.edge_id)
            ),
            "outbound_edge_ids": map_set(
                topology.outbound_edge_ids, edge.from_node_id, (*outbound, edge.edge_id)
            ),
        }
    )
    return _replace_projection_groups(state, topology=topology)


def _edge_payload_for_projection(payload: dict[str, Any]) -> dict[str, Any]:
    edge_id = (
        payload.get("edge_id")
        or f"{payload['from_node_id']}:{payload['from_port']}->{payload['to_node_id']}:{payload['to_port']}"
    )
    result = {key: value for key, value in payload.items() if key in EdgeValue.model_fields}
    result["edge_id"] = edge_id
    if result.get("required") is True:
        result.pop("required")
    if result.get("dependency_type") == "input_binding":
        result.pop("dependency_type")
    return result


def _reduce_slice_a_binding(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    payload = InputBoundPayload.model_validate(event.payload)
    binding_data = payload.model_dump()
    ports = state.topology.input_bindings.get(payload.to_node_id, FrozenMap())
    existing = ports.get(payload.to_port)
    edge = state.topology.edges.get(payload.edge_id)
    if edge is None:
        edge = next(
            (
                item
                for item in state.topology.edges.values()
                if item.to_node_id == payload.to_node_id and item.to_port == payload.to_port
            ),
            None,
        )
    target = state.nodes.get(payload.to_node_id)
    contract = (
        DEFAULT_NODE_CONTRACTS.contract_for(target.spec.kind, target.spec.role)
        if target is not None and target.spec.kind is not None
        else None
    )
    target_port = input_port_contract(contract, payload.to_port) if contract is not None else None
    policy = binding_policy(
        edge.binding_policy if edge is not None else payload.binding_policy,
        target_port,
    )
    merged_ids = merge_bound_record_ids(
        policy,
        list(existing.record_ids) if existing is not None else [],
        list(payload.record_ids),
        supersedes_record_id=payload.supersedes_record_id,
    )
    if existing is not None and merged_ids == list(existing.record_ids):
        return state
    positions = dict(existing.record_bound_positions or {}) if existing is not None else {}
    if existing is not None and existing.record_bound_positions is None:
        positions.update(dict.fromkeys(existing.record_ids, existing.bound_at_position))
    incoming_position = payload.bound_at_position or event.position
    incoming_positions: dict[str, int] = payload.record_bound_positions
    for record_id in payload.record_ids:
        positions.setdefault(record_id, incoming_positions.get(record_id, incoming_position))
    binding_data.update(
        {
            "edge_id": payload.edge_id or (edge.edge_id if edge is not None else None),
            "binding_policy": policy,
            "record_ids": merged_ids,
            "record_bound_positions": {
                record_id: positions[record_id]
                for record_id in merged_ids
                if record_id in positions
            },
        }
    )
    binding = InputBindingValue.model_validate(binding_data)
    input_binding_port_order = state.topology.input_binding_port_order
    if existing is None:
        port_order = input_binding_port_order.get(payload.to_node_id, ()) + (payload.to_port,)
        input_binding_port_order = map_set(input_binding_port_order, payload.to_node_id, port_order)
    topology = state.topology.model_copy(
        update={
            "input_bindings": map_set(
                state.topology.input_bindings,
                payload.to_node_id,
                map_set(ports, payload.to_port, binding),
            ),
            "input_binding_port_order": input_binding_port_order,
        }
    )
    return _replace_projection_groups(state, topology=topology)


def _canonical_record(record: AcceptedOutputRecordPayload) -> dict[str, Any]:
    """Return the accepted-record content used for replay identity.

    Delivery timestamp, position, and graph position are attached to file-state
    records by the accepting event. They intentionally do not turn a later
    redelivery into a conflicting accepted record; run id remains part of the
    logical identity.
    """
    canonical = record.model_dump(mode="json", by_alias=True)
    if isinstance(record, FileStateRecord):
        canonical.pop("created_at", None)
        canonical.pop("position", None)
        canonical.pop("graph_position", None)
    return canonical


def _file_state_acceptance_identity(record: FileStateRecord) -> str:
    """Return a compact identity for immutable file-state acceptance facts."""
    canonical = _canonical_record(record)
    canonical.pop("acceptance_identity", None)
    encoded = dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


def insert_record(
    store: RecordStore, record: AcceptedOutputRecordPayload, *, event_id: str
) -> RecordStore:
    """Insert one canonical record, rejecting every non-identical id reuse."""
    record = cast(AcceptedOutputRecordPayload, freeze_canonical_record(record))
    if isinstance(record, FileStateRecord) and record.acceptance_identity is None:
        record = record.model_copy(
            update={"acceptance_identity": _file_state_acceptance_identity(record)}
        )
    existing = store.by_id.get(record.record_id)
    if existing is not None:
        if isinstance(existing, FileStateRecord) and isinstance(record, FileStateRecord):
            if existing.acceptance_identity == record.acceptance_identity:
                return store
            raise ProjectionReplayConflictError(
                f"record {record.record_id!r} conflicts during replay (event {event_id!r})"
            )
        if _canonical_record(existing) == _canonical_record(record):
            return store
        raise ProjectionReplayConflictError(
            f"record {record.record_id!r} conflicts during replay (event {event_id!r})"
        )

    node_id = record.producer_node_id
    port = record.port
    summary = GraphRecordSummaryProjection(
        record_id=record.record_id,
        record_type=record.record_type,
        record_kind=record.record_kind,
        schema=record.schema_,
        producer_node_id=node_id,
        producer_port=port,
        position=record.position if isinstance(record, FileStateRecord) else record.graph_position,
    )
    indexes = store.ids_by_node_port
    if node_id is not None:
        node_ports = indexes.get(node_id, FrozenMap())
        ids = node_ports.get(port, ())
        indexes = map_set(indexes, node_id, map_set(node_ports, port, ids + (record.record_id,)))
    return RecordStore.model_construct(
        by_id=map_set(store.by_id, record.record_id, record),
        ids_by_node_port=indexes,
        summaries_by_id=map_set(store.summaries_by_id, record.record_id, summary),
    )


def _record_destination(
    record: DecisionRequestRecord | AuthorityRequestRecord,
) -> str:
    """Return the node addressed by a grouped governance request record."""
    return record.producer_node_id


def _replace_record(store: RecordStore, record: AcceptedOutputRecordPayload) -> RecordStore:
    """Replace a canonical record after a directly-caused immutable side effect."""
    if store.by_id.get(record.record_id) is None:
        return store
    return store.model_copy(update={"by_id": map_set(store.by_id, record.record_id, record)})


def _apply_record_side_effects(
    state: GraphProjection, record: AcceptedOutputRecordPayload, *, position: int
) -> GraphProjection:
    """Apply only facts directly entailed by a newly accepted canonical record."""
    next_state = state
    if isinstance(record, FailureRecord):
        node = state.nodes.get(record.value.failed_node_id)
        if (
            node is not None
            and record.value.error_class == "runtime_death_recovery_required"
            and record.value.retryable
        ):
            next_state = _replace_node(
                next_state,
                _node_from_parts(
                    node.spec,
                    node.runtime,
                    node.scheduling.model_copy(
                        update={"recovery_blocker_record_id": record.record_id}
                    ),
                ),
            )
    elif isinstance(record, RecoveryPlanRecord):
        node = state.nodes.get(record.producer_node_id)
        if (
            node is not None
            and node.scheduling.recovery_blocker_record_id is not None
            and record.value.action == "retry"
            and record.value.retry_basis != "no_differentiating_action"
        ):
            next_state = _replace_node(
                next_state,
                _node_from_parts(
                    node.spec,
                    node.runtime,
                    node.scheduling.model_copy(update={"recovery_blocker_record_id": None}),
                ),
            )
    elif isinstance(record, RoutineSnapshotRecord):
        planning = state.planning.model_copy(
            update={
                "latest_routine_snapshot": LatestRoutineSnapshotProjection(
                    record_id=record.record_id,
                    producer_node_id=record.producer_node_id,
                    port=record.port,
                )
            }
        )
        next_state = _replace_projection_groups(next_state, planning=planning)
    elif isinstance(record, CompletionDecisionRecord) and record.value.status == "passed":
        if not state.lifecycle.completion_decision_passed:
            next_state = _replace_projection_groups(
                next_state,
                lifecycle=state.lifecycle.model_copy(update={"completion_decision_passed": True}),
            )
    elif isinstance(record, CandidateRecord | OutputRecord):
        producer = state.nodes.get(record.producer_node_id)
        task_region_id = record.task_region_id or (
            producer.spec.task_region_id if producer is not None else None
        )
        if task_region_id is not None:
            attempt_number = record.attempt_number
            if attempt_number is None and producer is not None:
                attempt_number = producer.runtime.attempt_number
            file_state_record_ids = record.file_state_record_ids
            supersedes_task_region_ids: tuple[str, ...] = ()
            if isinstance(record, CandidateRecord):
                file_state_record_ids = file_state_record_ids or record.value.file_state_record_ids
                supersedes_task_region_ids = (
                    *record.supersedes_task_region_ids,
                    *(
                        (record.supersedes_task_region_id,)
                        if record.supersedes_task_region_id is not None
                        else ()
                    ),
                )
            candidate = CandidateValue(
                candidate_id=record.candidate_id or record.record_id,
                attempt_number=attempt_number or 0,
                position=position,
                file_state_record_ids=tuple(file_state_record_ids),
                supersedes_task_region_ids=supersedes_task_region_ids,
            )
            task = state.tasks.get(task_region_id, TaskProjection())
            if not any(item.candidate_id == candidate.candidate_id for item in task.candidates):
                tasks = map_set(
                    state.tasks,
                    task_region_id,
                    task.model_copy(update={"candidates": (*task.candidates, candidate)}),
                )
                next_state = _replace_projection_groups(next_state, tasks=tasks)
    elif isinstance(record, CheckResultRecord):
        result = CheckResultValue(
            node_id=record.producer_node_id,
            status=record.value.status,
            position=position,
            task_region_id=record.task_region_id,
            record_id=record.record_id,
            classification=record.value.classification,
            command_text=record.value.command_text,
            stderr_tail=record.value.stderr_tail,
            stdout_tail=record.value.stdout_tail,
            exit_code=record.value.exit_code,
            candidate_record_ids=tuple(
                record.candidate_record_ids or record.value.candidate_record_ids
            ),
            file_state_record_ids=tuple(
                record.file_state_record_ids or record.value.file_state_record_ids
            ),
            evaluated_record_ids=tuple(
                record.evaluated_record_ids or record.value.evaluated_record_ids
            ),
        )
        verification = state.verification.model_copy(
            update={
                "check_results_by_node": map_set(
                    state.verification.check_results_by_node, record.producer_node_id, result
                )
            }
        )
        next_state = _replace_projection_groups(next_state, verification=verification)
        if record.value.classification in {"environment_error", "tool_error", "tool_unavailable"}:
            failure = EnvironmentFailureValue(
                position=position,
                node_id=record.producer_node_id,
                classification=record.value.classification,
                reason=_environment_failure_reason_from_check_value(
                    record.value.model_dump(mode="json")
                ),
                task_region_id=record.task_region_id,
                record_id=record.record_id,
                command_text=record.value.command_text,
                stderr_tail=record.value.stderr_tail,
                exit_code=record.value.exit_code,
            )
            execution = next_state.execution.model_copy(
                update={
                    "environment_failures_by_task": map_set(
                        next_state.execution.environment_failures_by_task,
                        record.task_region_id,
                        failure,
                    )
                }
            )
            next_state = _replace_projection_groups(next_state, execution=execution)
    elif isinstance(record, DecisionRequestRecord):
        destination = _record_destination(record)
        governance = state.governance.model_copy(
            update={
                "decision_requests_by_node": map_set(
                    state.governance.decision_requests_by_node, destination, record.value
                )
            }
        )
        next_state = _replace_projection_groups(next_state, governance=governance)
    elif isinstance(record, AuthorityRequestRecord):
        node = state.nodes.get(_record_destination(record))
        if node is not None and node.spec.authority_request_record_id is None:
            next_state = _replace_node(
                state,
                _node_from_parts(
                    node.spec.model_copy(update={"authority_request_record_id": record.record_id}),
                    node.runtime,
                    node.scheduling,
                ),
            )
    return next_state


def _reduce_record_event(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    record_type = event.payload.get("record_type")
    if (
        record_type == "routine_snapshot"
        and set(event.payload)
        == {
            "record_id",
            "record_kind",
            "record_type",
            "producer_node_id",
            "port",
            "schema",
        }
        and isinstance(event.payload["record_id"], str)
        and event.payload["record_kind"] == "graph_record"
        and isinstance(event.payload["producer_node_id"], str)
        and event.payload["port"] in {"routine_snapshot", "snapshot"}
        and event.payload["schema"] == "RoutineSnapshot"
    ):
        return state
    record_model = (
        OUTPUT_RECORD_MODELS_BY_TYPE.get(record_type) if isinstance(record_type, str) else None
    )
    payload = (
        cast(AcceptedOutputRecordPayload, record_model.model_validate(event.payload))
        if record_model is not None
        else OutputRecordAcceptedPayload.model_validate(event.payload).root
    )
    record = payload
    if isinstance(record, FileStateRecord):
        record = record.model_copy(
            update={
                "run_id": event.run_id,
                "position": event.position,
            }
        )
        record = record.model_copy(
            update={"acceptance_identity": _file_state_acceptance_identity(record)}
        )
    records = insert_record(state.records, record, event_id=event.event_id)
    if records is state.records:
        return state
    next_state = _replace_projection_groups(state, records=records)
    return _apply_record_side_effects(next_state, record, position=event.position)


def _reduce_gatekeeper_verdict(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    payload = GatekeeperVerdictRecordedPayload.model_validate(event.payload)
    record = state.records.by_id.get(payload.file_state_record_id)
    if not isinstance(record, FileStateRecord):
        return state
    verdicts = {verdict.path: verdict.model_dump(mode="json") for verdict in payload.verdicts}
    if not record.paths:
        return state
    resolved_paths = tuple(_resolved_file_entry(entry, verdicts) for entry in record.paths)
    if list(resolved_paths) == record.paths:
        return state
    return _replace_projection_groups(
        state,
        records=_replace_record(state.records, record.model_copy(update={"paths": resolved_paths})),
    )


def _reduce_slice_b2(state: GraphProjection, event: EventEnvelope) -> GraphProjection | None:
    """Reduce planning, verification, governance, and requirements facts.

    Every branch validates its canonical event first and installs only frozen
    replacement groups.  Slice C families intentionally remain outside this
    dispatcher until their execution/usage ownership conversion.
    """
    if event.event_type == "session_state_changed":
        return _reduce_planner_session_state(state, event)
    if event.event_type == "graph_patch_accepted":
        return _reduce_accepted_graph_patch(state, event)
    if event.event_type == "graph_patch_rejected":
        return _reduce_rejected_graph_patch(state, event)
    if event.event_type in {"verification_passed", "verification_failed"}:
        return _reduce_verification_outcome(state, event)
    if event.event_type == "appeal_opened":
        return _reduce_open_appeal(state, event)
    if event.event_type in {
        "oversight_decision_recorded",
        "approval_decision_recorded",
        "authority_decision_recorded",
    }:
        return _reduce_governance_decision(state, event)
    if event.event_type == "requirement_revision_recorded":
        return _reduce_requirement_revision(state, event)
    if event.event_type == "support_evidence_recorded":
        return _reduce_support_evidence(state, event)
    return None


def _reduce_planner_session_state(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    payload = PlannerSessionStateChangedPayload.model_validate(event.payload)
    if payload.session_id is None or payload.state is None:
        raise ValueError("session_state_changed requires session_id and state")
    existing = state.planning.sessions.get(payload.session_id)
    current_node_id = existing.current_node_id if existing is not None else None
    carryover_record_id = existing.carryover_record_id if existing is not None else None
    if payload.state == "attached" and payload.node_id is not None:
        current_node_id = payload.node_id
    elif payload.state in {"suspended", "detached", "dead"}:
        current_node_id = None
    if "carryover_record_id" in payload.model_fields_set:
        carryover_record_id = payload.carryover_record_id
    session = (
        existing.model_copy(
            update={
                "state": payload.state,
                "current_node_id": current_node_id,
                "carryover_record_id": carryover_record_id,
            }
        )
        if existing is not None
        else PlannerSessionProjection(
            state=payload.state,
            current_node_id=current_node_id,
            carryover_record_id=carryover_record_id,
        )
    )
    planning = state.planning.model_copy(
        update={"sessions": map_set(state.planning.sessions, payload.session_id, session)}
    )
    return _replace_projection_groups(state, planning=planning)


def _reduce_accepted_graph_patch(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    payload = GraphPatchAcceptedPayload.model_validate(event.payload)
    if payload.proposed_by_node_id is None:
        return state
    planning = state.planning
    node_id = payload.proposed_by_node_id
    accepted = planning.accepted_patch_ids_by_node.get(node_id, ())
    if payload.patch_id not in accepted:
        accepted = (*accepted, payload.patch_id)
    successors = tuple(payload.successor_planner_node_ids)
    updates: dict[str, object] = {
        "accepted_patch_ids_by_node": map_set(
            planning.accepted_patch_ids_by_node, node_id, accepted
        ),
        "patch_decisions_by_id": map_set(
            planning.patch_decisions_by_id,
            payload.patch_id,
            PlannerPatchDecisionValue(
                patch_id=payload.patch_id,
                status="accepted",
                position=event.position,
                proposed_by_node_id=payload.proposed_by_node_id,
                base_graph_position=payload.base_graph_position,
                operation_key=payload.operation_key,
                operation_fingerprint=payload.operation_fingerprint,
                successor_planner_node_ids=tuple(payload.successor_planner_node_ids),
            ),
        ),
    }
    if successors:
        updates["successor_by_node"] = map_set(planning.successor_by_node, node_id, successors[0])
        updates["no_successor_patch_ids_by_node"] = map_set(
            planning.no_successor_patch_ids_by_node, node_id, ()
        )
        latest = dict(planning.latest_no_successor_patch_id_by_node)
        latest.pop(node_id, None)
        updates["latest_no_successor_patch_id_by_node"] = FrozenMap(latest)
    else:
        no_successor = planning.no_successor_patch_ids_by_node.get(node_id, ())
        if payload.patch_id not in no_successor:
            no_successor = (*no_successor, payload.patch_id)
        updates["no_successor_patch_ids_by_node"] = map_set(
            planning.no_successor_patch_ids_by_node, node_id, no_successor
        )
        updates["latest_no_successor_patch_id_by_node"] = map_set(
            planning.latest_no_successor_patch_id_by_node, node_id, payload.patch_id
        )
    governance = state.governance.model_copy(
        update={
            "resolved_patch_ids": map_set(
                state.governance.resolved_patch_ids, payload.patch_id, True
            )
        }
    )
    return _replace_projection_groups(
        state, planning=planning.model_copy(update=updates), governance=governance
    )


def _reduce_rejected_graph_patch(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    payload = GraphPatchRejectedPayload.model_validate(event.payload)
    decision = PlannerPatchDecisionValue(
        patch_id=payload.patch_id,
        status="rejected",
        position=event.position,
        proposed_by_node_id=payload.proposed_by_node_id,
        base_graph_position=payload.base_graph_position,
        reason=payload.reason or payload.rejection_reason,
    )
    planning = state.planning.model_copy(
        update={
            "patch_decisions_by_id": map_set(
                state.planning.patch_decisions_by_id, payload.patch_id, decision
            )
        }
    )
    governance = state.governance.model_copy(
        update={
            "resolved_patch_ids": map_set(
                state.governance.resolved_patch_ids, payload.patch_id, True
            )
        }
    )
    return _replace_projection_groups(state, planning=planning, governance=governance)


def _reduce_verification_outcome(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    payload_type = (
        VerificationPassedPayload
        if event.event_type == "verification_passed"
        else VerificationFailedPayload
    )
    payload = payload_type.model_validate(event.payload)
    result = VerificationResultValue(
        node_id=payload.verifier_node_id,
        record_id=payload.record_id,
        candidate_id=payload.candidate_id,
        task_region_id=payload.task_region_id,
    )
    verdict = VerifierVerdictValue(
        candidate_id=payload.candidate_id, verdict=payload.outcome, position=event.position
    )
    verification = state.verification
    updates: dict[str, object] = {
        "verdicts_by_node": map_set(
            verification.verdicts_by_node, payload.verifier_node_id, verdict
        ),
    }
    if event.event_type == "verification_passed":
        updates["passed_results_by_record_id"] = map_set(
            verification.passed_results_by_record_id, payload.record_id, result
        )
        updates["failed_results_by_record_id"] = verification.failed_results_by_record_id
        passed_ids = verification.passed_candidate_ids
        if payload.candidate_id not in passed_ids:
            passed_ids = (*passed_ids, payload.candidate_id)
        updates["passed_candidate_ids"] = passed_ids
    else:
        updates["failed_results_by_record_id"] = map_set(
            verification.failed_results_by_record_id, payload.record_id, result
        )
        updates["passed_results_by_record_id"] = verification.passed_results_by_record_id
        updates["failed_candidate_ids"] = map_set(
            verification.failed_candidate_ids, payload.candidate_id, True
        )
    return _replace_projection_groups(state, verification=verification.model_copy(update=updates))


def _task_region_for_candidate_id(state: GraphProjection, candidate_id: str) -> str | None:
    for task_region_id, task in state.tasks.items():
        if any(candidate.candidate_id == candidate_id for candidate in task.candidates):
            return task_region_id
    return None


def _reduce_open_appeal(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    payload = AppealOpenedPayload.model_validate(event.payload)
    governance = state.governance.model_copy(
        update={
            "pending_appeals_by_node": map_set(
                state.governance.pending_appeals_by_node, payload.appealed_node_id, True
            )
        }
    )
    verification = state.verification
    task_region_id = payload.task_region_id or (
        _task_region_for_candidate_id(state, payload.candidate_id) if payload.candidate_id else None
    )
    if payload.appeal_type == "invalid_test" and task_region_id is not None:
        previous = verification.invalid_test_blocks_by_task.get(task_region_id)
        block = InvalidTestBlockValue(
            position=event.position,
            accepted=previous.accepted if previous is not None else None,
            appeal_open=True,
            candidate_id=payload.candidate_id,
        )
        verification = verification.model_copy(
            update={
                "invalid_test_blocks_by_task": map_set(
                    verification.invalid_test_blocks_by_task, task_region_id, block
                )
            }
        )
    return _replace_projection_groups(state, governance=governance, verification=verification)


def _decision_value(payload: object, value_type: type[object], position: int) -> object:
    raw = cast(Any, payload).model_dump(mode="json")
    fields = cast(Any, value_type).model_fields
    value = {key: raw[key] for key in fields if key in raw}
    if "position" in fields:
        value["position"] = position
    return cast(Any, value_type).model_validate(value)


def _is_duplicate_governance_decision(
    existing: object | None,
    incoming: object,
    *,
    family: str,
    decision_id: str,
    event_id: str,
) -> bool:
    """Reject a decision-ID collision before changing canonical or derived indexes."""
    if existing is None:
        return False
    existing_value = cast(Any, existing).model_dump(mode="json")
    incoming_value = cast(Any, incoming).model_dump(mode="json")
    existing_value.pop("position", None)
    incoming_value.pop("position", None)
    if existing_value == incoming_value:
        return True
    raise ProjectionReplayConflictError(
        f"{family} decision {decision_id!r} conflicts during replay (event {event_id!r})"
    )


def _reduce_governance_decision(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    governance = state.governance
    if event.event_type == "approval_decision_recorded":
        payload = ApprovalDecisionRecordedPayload.model_validate(event.payload)
        decision_id = payload.record_id or event.event_id
        value = cast(
            ApprovalDecisionValue, _decision_value(payload, ApprovalDecisionValue, event.position)
        )
        if _is_duplicate_governance_decision(
            governance.approval_decisions_by_id.get(decision_id),
            value,
            family="approval",
            decision_id=decision_id,
            event_id=event.event_id,
        ):
            return state
        aliases = (payload.node_id, payload.appeal_node_id)
        governance = governance.model_copy(
            update={
                "approval_decisions_by_id": map_set(
                    governance.approval_decisions_by_id, decision_id, value
                ),
                "approval_decision_id_by_node": _set_aliases(
                    governance.approval_decision_id_by_node, aliases, decision_id
                ),
                "node_gate_decisions": map_set(
                    governance.node_gate_decisions, payload.node_id, payload.decision == "approved"
                ),
                "gate_decisions_by_task": _set_gate_decision(
                    state,
                    payload.task_region_id,
                    payload.gate_id or payload.node_id,
                    payload.decision == "approved",
                ),
            }
        )
    elif event.event_type == "authority_decision_recorded":
        payload = AuthorityDecisionRecordedPayload.model_validate(event.payload)
        decision_id = payload.record_id or event.event_id
        value = cast(
            AuthorityDecisionValue, _decision_value(payload, AuthorityDecisionValue, event.position)
        )
        if _is_duplicate_governance_decision(
            governance.authority_decisions_by_id.get(decision_id),
            value,
            family="authority",
            decision_id=decision_id,
            event_id=event.event_id,
        ):
            return state
        blockers = governance.authority_revision_blockers
        revision_id = _authority_decision_revision_id(payload)
        if payload.decision == "granted" and revision_id is not None:
            blocker_values = dict(blockers)
            blocker_values.pop(revision_id, None)
            blockers = FrozenMap(blocker_values)
        governance = governance.model_copy(
            update={
                "authority_decisions_by_id": map_set(
                    governance.authority_decisions_by_id, decision_id, value
                ),
                "authority_decision_id_by_node": _set_aliases(
                    governance.authority_decision_id_by_node,
                    (payload.node_id, payload.appeal_node_id),
                    decision_id,
                ),
                "node_gate_decisions": map_set(
                    governance.node_gate_decisions, payload.node_id, payload.decision == "granted"
                ),
                "authority_revision_blockers": blockers,
            }
        )
    else:
        payload = OversightDecisionRecordedPayload.model_validate(event.payload)
        decision_id = payload.record_id or event.event_id
        value = cast(
            OversightDecisionValue, _decision_value(payload, OversightDecisionValue, event.position)
        )
        if _is_duplicate_governance_decision(
            governance.oversight_decisions_by_id.get(decision_id),
            value,
            family="oversight",
            decision_id=decision_id,
            event_id=event.event_id,
        ):
            return state
        pending = governance.pending_appeals_by_node
        if payload.appealed_node_id is not None:
            pending = map_set(pending, payload.appealed_node_id, False)
        task_region_id = payload.task_region_id or (
            _task_region_for_candidate_id(state, payload.candidate_id)
            if payload.candidate_id
            else None
        )
        verification = state.verification
        if (
            task_region_id is not None
            and payload.decision in {"accepted", "invalid_test_accepted"}
            and payload.appeal_type in {None, "invalid_test"}
        ):
            verification = verification.model_copy(
                update={
                    "invalid_test_blocks_by_task": map_set(
                        verification.invalid_test_blocks_by_task,
                        task_region_id,
                        InvalidTestBlockValue(
                            position=event.position,
                            accepted=True,
                            candidate_id=payload.candidate_id,
                        ),
                    )
                }
            )
        governance = governance.model_copy(
            update={
                "oversight_decisions_by_id": map_set(
                    governance.oversight_decisions_by_id, decision_id, value
                ),
                "oversight_decision_id_by_node": _set_aliases(
                    governance.oversight_decision_id_by_node,
                    (payload.node_id, payload.appeal_node_id, payload.appealed_node_id),
                    decision_id,
                ),
                "pending_appeals_by_node": pending,
            }
        )
        return _replace_projection_groups(state, governance=governance, verification=verification)
    return _replace_projection_groups(state, governance=governance)


def _set_aliases(
    index: FrozenMap[str, str], aliases: tuple[str | None, ...], decision_id: str
) -> FrozenMap[str, str]:
    updated = index
    for alias in aliases:
        if alias is not None:
            updated = map_set(updated, alias, decision_id)
    return updated


def _set_gate_decision(
    state: GraphProjection, task_region_id: str | None, gate_id: str, passed: bool
) -> FrozenMap[str, FrozenMap[str, bool]]:
    node = state.nodes.get(gate_id)
    task_id = task_region_id or (node.spec.task_region_id if node is not None else None)
    if task_id is None:
        return state.governance.gate_decisions_by_task
    gates = state.governance.gate_decisions_by_task.get(task_id, FrozenMap())
    return map_set(
        state.governance.gate_decisions_by_task, task_id, map_set(gates, gate_id, passed)
    )


def _reduce_requirement_revision(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    payload = RequirementRevisionPayload.model_validate(event.payload)
    requirement_id = payload.requirement_id or payload.id
    version_id = payload.version_id or payload.requirement_version_id or payload.revision_id
    if requirement_id is None or version_id is None:
        raise ValueError("requirement_revision_recorded requires requirement_id and version_id")
    classification = _requirement_revision_classification(payload.model_dump(mode="json"))
    requires_authority = _requires_explicit_requirement_authority(
        payload.model_dump(mode="json"), classification
    )
    revision = RequirementRevisionValue(
        requirement_id=requirement_id,
        version_id=version_id,
        change_classification=classification,
        requires_authority=requires_authority,
        position=event.position,
        previous_version_id=payload.previous_version_id,
        revision_index=payload.revision_index,
        authority_required_reason=_authority_required_reason(
            payload.model_dump(mode="json"), classification
        ),
        validation_strengthening=payload.validation_strengthening is True
        or classification == "validation_strengthening",
    )
    requirements = state.requirements
    existing_revision = requirements.revisions_by_id.get(version_id)
    if existing_revision is not None:
        existing_content = existing_revision.model_dump(mode="json")
        replayed_content = revision.model_dump(mode="json")
        existing_content.pop("position")
        replayed_content.pop("position")
        if existing_content == replayed_content:
            return state
        raise ProjectionReplayConflictError(
            f"requirement revision {version_id!r} conflicts during replay (event {event.event_id!r})"
        )
    revisions = map_set(requirements.revisions_by_id, version_id, revision)
    active = requirements.active_version_id_by_requirement
    support = requirements.support_by_id
    if payload.active is not False:
        active = map_set(active, requirement_id, version_id)
    if revision.validation_strengthening:
        for support_id, value in support.items():
            if (
                value.requirement_id == requirement_id
                and value.requirement_version_id != version_id
            ):
                support = map_set(
                    support,
                    support_id,
                    value.model_copy(
                        update={
                            "status": "stale",
                            "stale_reason": value.stale_reason
                            or "Evidence was produced for an older requirement version and does not prove the strengthened validation definition.",
                        }
                    ),
                )
    governance = state.governance
    if requires_authority:
        blocker = FinalInvariantBlockerProjection(
            kind="unresolved_authority_required_revision",
            reason=revision.authority_required_reason or classification,
            requirement_id=requirement_id,
            revision_id=version_id,
        )
        governance = governance.model_copy(
            update={
                "authority_revision_blockers": map_set(
                    governance.authority_revision_blockers, version_id, blocker
                )
            }
        )
    return _replace_projection_groups(
        state,
        requirements=requirements.model_copy(
            update={
                "revisions_by_id": revisions,
                "active_version_id_by_requirement": active,
                "support_by_id": support,
            }
        ),
        governance=governance,
    )


def _reduce_support_evidence(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    payload = SupportEvidencePayload.model_validate(event.payload)
    support_id = payload.support_id or payload.edge_id
    version_id = (
        payload.requirement_version_id
        or payload.version_id
        or (
            state.requirements.active_version_id_by_requirement.get(payload.requirement_id)
            if payload.requirement_id
            else None
        )
    )
    if (
        support_id is None
        or payload.evidence_id is None
        or payload.requirement_id is None
        or version_id is None
    ):
        raise ValueError(
            "support_evidence_recorded requires support, evidence, requirement, and version IDs"
        )
    support = SupportEvidenceValue(
        support_id=support_id,
        evidence_id=payload.evidence_id,
        requirement_id=payload.requirement_id,
        requirement_version_id=version_id,
        status=payload.status or "active",
        position=event.position,
        stale_reason=payload.stale_reason,
        confidence=payload.confidence,
    )
    existing_support = state.requirements.support_by_id.get(support_id)
    if existing_support is not None:
        existing_content = existing_support.model_dump(mode="json")
        replayed_content = support.model_dump(mode="json")
        existing_content.pop("position")
        replayed_content.pop("position")
        if existing_content == replayed_content:
            return state
        raise ProjectionReplayConflictError(
            f"support evidence {support_id!r} conflicts during replay (event {event.event_id!r})"
        )
    requirements = state.requirements.model_copy(
        update={"support_by_id": map_set(state.requirements.support_by_id, support_id, support)}
    )
    return _replace_projection_groups(state, requirements=requirements)


def reduce_event(
    state: GraphProjection,
    event: EventEnvelope,
    *,
    enforce_relationships: bool = False,
) -> GraphProjection:
    if enforce_relationships:
        _validate_event_relationships(state, event)
    slice_a_state = _reduce_slice_a(state, event)
    if slice_a_state is not None:
        return _finalize_projection(slice_a_state, event)
    if event.event_type in {"output_record_accepted", "file_state_accepted"}:
        return _finalize_projection(_reduce_record_event(state, event), event)
    if event.event_type == "gatekeeper_verdict_recorded":
        return _finalize_projection(_reduce_gatekeeper_verdict(state, event), event)
    slice_b2_state = _reduce_slice_b2(state, event)
    if slice_b2_state is not None:
        return _finalize_projection(slice_b2_state, event)
    slice_c_state = _reduce_slice_c(state, event)
    if slice_c_state is not None:
        return _finalize_projection(slice_c_state, event)

    # These events are canonical audit facts with no owned projection state.
    # Keeping this registry explicit makes unrecognised events fail loudly.
    if event.event_type in PROJECTION_NEUTRAL_EVENT_TYPES:
        EVENT_PAYLOAD_MODELS[event.event_type].model_validate(event.payload)
        return state
    raise ValueError(f"unsupported graph projection event type: {event.event_type!r}")


def _reduce_slice_c(state: GraphProjection, event: EventEnvelope) -> GraphProjection | None:
    if event.event_type in {
        "decision_answer_rejected",
        "runner_baseline_recorded",
        "runner_submission_staged",
        "runner_completion_witnessed",
        "runner_boundary_mismatch",
        "runner_recovery_requested",
        "runner_recovery_completed",
        "runner_execution_finalized",
        "validation_environment_blockage_resolution_requested",
        "validation_environment_blockage_resolved",
    }:
        return _reduce_runner_execution(state, event)
    if event.event_type == "node_usage_recorded":
        return _reduce_node_usage(state, event)
    if event.event_type in {
        "lease_granted",
        "lease_renewed",
        "lease_suspended",
        "lease_revoked",
        "lease_expired",
        "lease_released",
    }:
        return _reduce_lease(state, event)
    if event.event_type in {"cleanup_requested", "cleanup_applied"}:
        return _reduce_cleanup(state, event)
    if event.event_type == "callback_accepted":
        return _reduce_callback_accepted(state, event)
    return None


def _attempt_root_union(existing: object, observed: tuple[object, ...]) -> tuple[object, ...]:
    """Return phase-root union without interpreting legacy strings as authority."""
    attempt = cast(Any, existing)
    phases = (
        attempt.baseline_cache_roots,
        attempt.staged_cache_roots,
        attempt.final_cache_roots,
        attempt.recovery_observed_cache_roots,
        observed,
    )
    values: tuple[object, ...] = tuple(value for phase in phases for value in phase)
    from orchestrator.graph.cache_authority import latest_cache_root_union

    strings = [value for value in values if isinstance(value, str)]
    typed_phases = (
        tuple(value for value in phase if not isinstance(value, str)) for phase in phases
    )
    return (*tuple(sorted(set(strings))), *latest_cache_root_union(*typed_phases))


def _legacy_recovery_completion_disposition(existing: object) -> str:
    """Derive old completion events that predate an explicit disposition."""
    recovery_reason = getattr(existing, "recovery_reason", None)
    if recovery_reason == "staged_artifact_missing":
        return "restored_artifact_missing"
    if recovery_reason == "staged_artifact_corrupt":
        return "restored_artifact_corrupt"
    if getattr(existing, "runner_return_kind", None) == "successful_return":
        return "restored_boundary_mismatch"
    return "restored_unwitnessed"


def _validate_replay_cache_authority(state: GraphProjection, payload: object) -> None:
    """Replay the same snapshot/hash/root checks performed by commands."""
    from orchestrator.graph.cache_authority import validate_authorized_cache_roots
    from orchestrator.graph.projection_queries import (
        cache_authority_binding,
        cache_authority_is_new_format,
        lease_by_id,
        node_cache_authority_hash,
    )

    value = cast(Any, payload)
    binding = cache_authority_binding(state)
    supplied = value.cache_authority_hash
    if cache_authority_is_new_format(state) and supplied != binding.hash:
        raise ProjectionReplayConflictError(
            "runner cache_authority_hash differs from routine snapshot"
        )
    if supplied is not None and supplied != binding.hash:
        raise ProjectionReplayConflictError(
            "runner cache_authority_hash differs from routine snapshot"
        )
    if (
        cache_authority_is_new_format(state)
        and node_cache_authority_hash(state, value.node_id) != binding.hash
    ):
        raise ProjectionReplayConflictError(
            "runner node cache_authority_hash differs from routine snapshot"
        )
    lease = lease_by_id(state, value.lease_id)
    if lease is None or (
        cache_authority_is_new_format(state) and lease.cache_authority_hash != binding.hash
    ):
        raise ProjectionReplayConflictError(
            "runner lease cache_authority_hash differs from routine snapshot"
        )
    roots = _replay_cache_roots(state, value)
    fields_set = value.model_fields_set
    status = (
        value.cache_status_evidence or ()
        if (
            "observed_cache_roots" in fields_set
            or ("observed_cache_roots" not in fields_set and "cache_roots" not in fields_set)
        )
        # Earlier typed aggregate facts did not carry observed status evidence;
        # validate policy authority without misrepresenting them as current.
        else None
    )
    if not any(isinstance(root, str) for root in roots):
        try:
            validate_authorized_cache_roots(
                cast(Any, roots),
                binding.policy,
                status=status,
            )
        except ValueError as exc:
            raise ProjectionReplayConflictError(str(exc)) from exc


def _replay_cache_roots(state: GraphProjection, payload: object) -> tuple[object, ...]:
    """Resolve compact event roots from evidence and snapshot-owned policy."""
    from orchestrator.graph.cache_authority import derive_cache_roots
    from orchestrator.graph.projection_queries import cache_authority_binding

    value = cast(Any, payload)
    fields_set = value.model_fields_set
    if "observed_cache_roots" in fields_set:
        return tuple(value.observed_cache_roots or ())
    if "cache_roots" in fields_set:
        return tuple(value.cache_roots)
    return tuple(
        derive_cache_roots(
            value.cache_status_evidence or (),
            cache_authority_binding(state).policy,
        )
    )


def _explicit_cache_carrier_fields(payload: object) -> set[str]:
    """Return cache carriers that contain an explicit non-null value."""
    value = cast(Any, payload)
    names = {
        "cache_roots",
        "observed_cache_roots",
        "authorized_cache_roots",
        "legacy_cache_root_paths",
    }
    return {
        name for name in value.model_fields_set & names if getattr(value, name, None) is not None
    }


def _reduce_runner_execution(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    from orchestrator.graph.models import (
        DecisionAnswerRejectionPayload,
        RunnerBaselineRecordedPayload,
        RunnerExecutionFinalizedPayload,
        RunnerCompletionWitnessedPayload,
        RunnerRecoveryCompletedPayload,
        RunnerRecoveryRequestedPayload,
        RunnerSubmissionStagedPayload,
        ValidationEnvironmentBlockageResolutionPayload,
    )
    from orchestrator.graph.projection_models import (
        DecisionAnswerRejectionValue,
        ExecutionAttemptValue,
    )

    attempts = state.execution.attempts_by_execution_id
    if event.event_type == "decision_answer_rejected":
        payload = DecisionAnswerRejectionPayload.model_validate(event.payload)
        existing = attempts.get(payload.execution_id)
        if (
            existing is None
            or existing.node_id != payload.node_id
            or existing.lease_id != payload.lease_id
        ):
            raise ProjectionReplayConflictError(
                "decision answer rejection has no compatible execution attempt"
            )
        prior = next(
            (
                item
                for item in existing.decision_answer_rejections
                if item.delivery_id == payload.delivery_id
            ),
            None,
        )
        candidate_value = DecisionAnswerRejectionValue(
            **payload.model_dump(mode="python"),
            position=event.position,
        )
        if prior is not None:
            if prior == candidate_value:
                return state
            raise ProjectionReplayConflictError(
                "decision answer rejection delivery conflicts during replay"
            )
        candidate = existing.model_copy(
            update={
                "decision_answer_rejections": (
                    *existing.decision_answer_rejections,
                    candidate_value,
                )
            }
        )
    elif event.event_type in {
        "validation_environment_blockage_resolution_requested",
        "validation_environment_blockage_resolved",
    }:
        payload = ValidationEnvironmentBlockageResolutionPayload.model_validate(event.payload)
        existing = attempts.get(payload.execution_id)
        if (
            existing is None
            or existing.node_id != payload.node_id
            or existing.recovery_id != payload.recovery_id
            or existing.state != "recovered"
            or existing.recovery_reason != "validation_environment_blocked"
        ):
            raise ProjectionReplayConflictError(
                "validation environment resolution conflicts with recovered execution"
            )
        identity = {
            "continuation_resolution_id": payload.resolution_id,
            "continuation_snapshot_selection": payload.snapshot_selection,
            "continuation_snapshot_id": payload.snapshot_id,
            "continuation_snapshot_ref": payload.snapshot_ref,
            "continuation_commit_sha": payload.commit_sha,
            "continuation_tree_sha": payload.tree_sha,
        }
        if existing.continuation_resolution_id is not None and any(
            getattr(existing, key) != value for key, value in identity.items()
        ):
            raise ProjectionReplayConflictError(
                "validation environment resolution identity conflicts during replay"
            )
        target_status = (
            "requested"
            if event.event_type == "validation_environment_blockage_resolution_requested"
            else "completed"
        )
        if target_status == "completed" and existing.continuation_resolution_status != "requested":
            if existing.continuation_resolution_status == "completed":
                return state
            raise ProjectionReplayConflictError(
                "validation environment resolution completed before request"
            )
        candidate = existing.model_copy(
            update={**identity, "continuation_resolution_status": target_status}
        )
    elif event.event_type == "runner_baseline_recorded":
        payload = RunnerBaselineRecordedPayload.model_validate(event.payload)
        _validate_replay_cache_authority(state, payload)
        _verify_boundary_hash(
            payload.baseline_tree_sha,
            payload.entries,
            payload.boundary_hash,
            payload.cache_status_evidence or (),
            payload.cache_authority_hash,
        )
        baseline_data = payload.model_dump()
        baseline_data["baseline_entries"] = baseline_data.pop("entries")
        baseline_data["baseline_boundary_hash"] = baseline_data.pop("boundary_hash")
        replay_roots = _replay_cache_roots(state, payload)
        baseline_data["cache_roots"] = replay_roots
        baseline_data["baseline_cache_roots"] = replay_roots
        baseline_data["legacy_cache_root_paths"] = tuple(
            root for root in payload.cache_roots if isinstance(root, str)
        )
        baseline_data["baseline_cache_status_evidence"] = (
            baseline_data.pop("cache_status_evidence", []) or []
        )
        candidate = ExecutionAttemptValue.model_validate(
            {
                **baseline_data,
                "state": "baseline_captured",
                "lease_base_snapshot_id": payload.lease_base_snapshot_id,
                "cache_authority_hash": payload.cache_authority_hash,
            }
        )
    elif event.event_type == "runner_submission_staged":
        payload = RunnerSubmissionStagedPayload.model_validate(event.payload)
        _validate_replay_cache_authority(state, payload)
        _verify_boundary_hash(
            payload.staged_tree_sha,
            payload.boundary_entries,
            payload.boundary_hash,
            payload.cache_status_evidence or (),
            payload.cache_authority_hash,
        )
        existing = attempts.get(payload.execution_id)
        replay_roots = _replay_cache_roots(state, payload)
        if existing is None:
            raise ProjectionReplayConflictError("runner submission has no baseline")
        if existing.state == "submission_staged":
            if (
                existing.node_id == payload.node_id
                and existing.lease_id == payload.lease_id
                and existing.lease_generation == payload.lease_generation
                and existing.idempotency_key == payload.idempotency_key
                and (
                    existing.payload_ref.model_dump(mode="json")
                    if existing.payload_ref is not None
                    else None
                )
                == (
                    payload.payload_ref.model_dump(mode="json")
                    if payload.payload_ref is not None
                    else None
                )
                and existing.payload_hash == payload.payload_hash
                and existing.staged_snapshot_id == payload.staged_snapshot_id
                and existing.staged_snapshot_ref == payload.staged_snapshot_ref
                and existing.staged_commit_sha == payload.staged_commit_sha
                and existing.staged_tree_sha == payload.staged_tree_sha
                and existing.staged_boundary_hash == payload.boundary_hash
                and existing.staged_boundary_entries == tuple(payload.boundary_entries)
                and existing.callback_base_snapshot_id == payload.base_snapshot_id
                and existing.observed_graph_position == payload.observed_graph_position
                and existing.is_mutating == payload.is_mutating
                and existing.complete_node == payload.complete_node
                and existing.new_state == payload.new_state
                and existing.payload_size_bytes == payload.payload_size_bytes
                and existing.staged_cache_roots == replay_roots
                and existing.cache_authority_hash == payload.cache_authority_hash
                and thaw_json(existing.validation_witness) == payload.validation_witness
            ):
                return state
            raise ProjectionReplayConflictError(
                "runner submission duplicate conflicts during replay"
            )
        if (
            existing.state != "baseline_captured"
            or existing.node_id != payload.node_id
            or existing.lease_id != payload.lease_id
            or existing.lease_generation != payload.lease_generation
        ):
            raise ProjectionReplayConflictError("runner submission conflicts with baseline")
        candidate = existing.model_copy(
            update={
                "state": "submission_staged",
                "idempotency_key": payload.idempotency_key,
                "payload": freeze_json(payload.payload) if payload.payload is not None else None,
                "payload_ref": (
                    StoredArtifactRef.model_validate(payload.payload_ref.model_dump(mode="json"))
                    if payload.payload_ref is not None
                    else None
                ),
                "payload_hash": payload.payload_hash,
                "payload_size_bytes": payload.payload_size_bytes,
                "staged_snapshot_id": payload.staged_snapshot_id,
                "staged_snapshot_ref": payload.staged_snapshot_ref,
                "staged_commit_sha": payload.staged_commit_sha,
                "staged_tree_sha": payload.staged_tree_sha,
                "staged_boundary_hash": payload.boundary_hash,
                "staged_boundary_entries": tuple(payload.boundary_entries),
                "observed_graph_position": payload.observed_graph_position,
                "callback_base_snapshot_id": payload.base_snapshot_id,
                "is_mutating": payload.is_mutating,
                "complete_node": payload.complete_node,
                "new_state": payload.new_state,
                "completion_disposition": "durably_staged",
                "staged_cache_roots": replay_roots,
                "staged_cache_status_evidence": tuple(payload.cache_status_evidence or ()),
                "validation_witness": freeze_json(payload.validation_witness)
                if payload.validation_witness is not None
                else None,
            }
        )
    elif event.event_type == "runner_completion_witnessed":
        payload = RunnerCompletionWitnessedPayload.model_validate(event.payload)
        _validate_replay_cache_authority(state, payload)
        _verify_boundary_hash(
            payload.final_tree_sha,
            payload.boundary_entries,
            payload.boundary_hash,
            payload.cache_status_evidence or (),
            payload.cache_authority_hash,
        )
        existing = attempts.get(payload.execution_id)
        replay_roots = _replay_cache_roots(state, payload)
        if existing is None:
            raise ProjectionReplayConflictError("runner completion witness has no staged attempt")
        if existing.state in {"completion_witnessed", "finalized"}:
            if (
                existing.node_id == payload.node_id
                and existing.lease_id == payload.lease_id
                and existing.lease_generation == payload.lease_generation
                and existing.payload_hash == payload.staged_payload_hash
                and existing.payload_size_bytes == payload.staged_payload_size_bytes
                and existing.staged_snapshot_id == payload.staged_snapshot_id
                and existing.staged_snapshot_ref == payload.staged_snapshot_ref
                and existing.staged_commit_sha == payload.staged_commit_sha
                and existing.staged_tree_sha == payload.staged_tree_sha
                and existing.staged_boundary_hash == payload.staged_boundary_hash
                and existing.runner_return_kind == payload.runner_return_kind
                and existing.final_snapshot_id == payload.final_snapshot_id
                and existing.final_snapshot_ref == payload.final_snapshot_ref
                and existing.final_commit_sha == payload.final_commit_sha
                and existing.final_tree_sha == payload.final_tree_sha
                and existing.final_boundary_hash == payload.boundary_hash
                and existing.final_boundary_entries == tuple(payload.boundary_entries)
                and existing.final_cache_roots == replay_roots
                and existing.cache_authority_hash == payload.cache_authority_hash
            ):
                return state
            raise ProjectionReplayConflictError(
                "runner completion witness duplicate conflicts during replay"
            )
        if (
            existing.state != "submission_staged"
            or existing.node_id != payload.node_id
            or existing.lease_id != payload.lease_id
            or existing.lease_generation != payload.lease_generation
            or existing.payload_hash != payload.staged_payload_hash
            or existing.payload_size_bytes != payload.staged_payload_size_bytes
            or existing.staged_snapshot_id != payload.staged_snapshot_id
            or existing.staged_snapshot_ref != payload.staged_snapshot_ref
            or existing.staged_commit_sha != payload.staged_commit_sha
            or existing.staged_tree_sha != payload.staged_tree_sha
            or existing.staged_boundary_hash != payload.staged_boundary_hash
        ):
            raise ProjectionReplayConflictError(
                "runner completion witness conflicts with staged execution"
            )
        candidate = existing.model_copy(
            update={
                "state": "completion_witnessed",
                "completion_disposition": "completion_witnessed",
                "runner_return_kind": payload.runner_return_kind,
                "final_snapshot_id": payload.final_snapshot_id,
                "final_snapshot_ref": payload.final_snapshot_ref,
                "final_commit_sha": payload.final_commit_sha,
                "final_tree_sha": payload.final_tree_sha,
                "final_boundary_hash": payload.boundary_hash,
                "final_boundary_entries": tuple(payload.boundary_entries),
                "final_cache_roots": replay_roots,
                "final_cache_status_evidence": tuple(payload.cache_status_evidence or ()),
                "cache_roots": _attempt_root_union(existing, replay_roots),
            }
        )
    elif event.event_type == "runner_recovery_requested":
        from orchestrator.graph.boundary_types import derive_recovery_paths
        from orchestrator.graph.cache_authority import RunnerCacheRoot

        payload = RunnerRecoveryRequestedPayload.model_validate(event.payload)
        _validate_replay_cache_authority(state, payload)
        _verify_boundary_hash(
            payload.final_tree_sha,
            payload.final_boundary_entries,
            payload.final_boundary_hash,
            payload.cache_status_evidence or (),
            payload.cache_authority_hash,
        )
        existing = attempts.get(payload.execution_id)
        if existing is None:
            raise ProjectionReplayConflictError("runner recovery has no baseline")
        # Older durable recovery events predate ``cache_roots`` on this event.
        # Their requested paths were derived from the baseline attempt roots;
        # preserve that replay behavior while all new emitters carry the union.
        carrier_fields = _explicit_cache_carrier_fields(payload)
        compact_event = not carrier_fields
        legacy_event = (
            "cache_roots" in carrier_fields
            and "observed_cache_roots" not in carrier_fields
            and "authorized_cache_roots" not in carrier_fields
            and "legacy_cache_root_paths" not in carrier_fields
        )
        recovery_cache_roots = (
            _replay_cache_roots(state, payload)
            if not legacy_event
            else tuple(payload.cache_roots) or existing.cache_roots
        )
        if not legacy_event and not compact_event:
            expected_authorized = tuple(
                RunnerCacheRoot.model_validate(root)
                for root in _attempt_root_union(existing, recovery_cache_roots)
                if not isinstance(root, str)
            )
            if (
                tuple(payload.authorized_cache_roots or ()) != expected_authorized
                or tuple(payload.legacy_cache_root_paths or ()) != existing.legacy_cache_root_paths
            ):
                raise ProjectionReplayConflictError("runner recovery root authority conflicts")
        if existing.state == "recovery_requested":
            if (
                existing.recovery_id == payload.recovery_id
                and existing.recovery_reason == payload.reason
                and existing.recovery_error_detail == payload.error_detail
                and existing.recovery_first_error_detail == payload.first_error_detail
                and existing.node_id == payload.node_id
                and existing.lease_id == payload.lease_id
                and existing.lease_generation == payload.lease_generation
                and existing.baseline_snapshot_id == payload.baseline_snapshot_id
                and existing.baseline_tree_sha == payload.baseline_tree_sha
                and existing.recovery_paths == tuple(payload.paths)
                and existing.recovery_scope == payload.recovery_scope
                and existing.recovery_snapshot_id == payload.recovery_snapshot_id
                and existing.recovery_snapshot_ref == payload.recovery_snapshot_ref
                and existing.recovery_commit_sha == payload.recovery_commit_sha
                and existing.recovery_max_attempts == payload.max_attempts
                and existing.retry_after_recovery == payload.retry_after_recovery
                and existing.final_tree_sha == payload.final_tree_sha
                and existing.final_snapshot_id == payload.final_snapshot_id
                and existing.final_snapshot_ref == payload.final_snapshot_ref
                and existing.final_commit_sha == payload.final_commit_sha
                and existing.final_boundary_hash == payload.final_boundary_hash
                and existing.final_boundary_entries == tuple(payload.final_boundary_entries)
                and existing.recovery_observed_cache_roots == recovery_cache_roots
                and existing.cache_authority_hash == payload.cache_authority_hash
            ):
                return state
            raise ProjectionReplayConflictError("runner recovery duplicate conflicts during replay")
        if (
            existing.state
            not in {
                "baseline_captured",
                "submission_staged",
                "completion_witnessed",
            }
            or existing.node_id != payload.node_id
            or existing.lease_id != payload.lease_id
            or existing.lease_generation != payload.lease_generation
            or existing.baseline_snapshot_id != payload.baseline_snapshot_id
            or existing.baseline_tree_sha != payload.baseline_tree_sha
            or (
                payload.recovery_scope == "selective"
                and tuple(payload.paths)
                != derive_recovery_paths(
                    existing.baseline_entries,
                    existing.staged_boundary_entries,
                    payload.final_boundary_entries,
                    [
                        RunnerCacheRoot.model_validate(root)
                        for root in _attempt_root_union(existing, recovery_cache_roots)
                        if not isinstance(root, str)
                    ],
                    existing.legacy_cache_root_paths,
                )
            )
        ):
            raise ProjectionReplayConflictError("runner recovery conflicts with staged execution")
        candidate = existing.model_copy(
            update={
                "state": "recovery_requested",
                "recovery_id": payload.recovery_id,
                "recovery_reason": payload.reason,
                "recovery_error_detail": payload.error_detail,
                "recovery_first_error_detail": payload.first_error_detail,
                "recovery_max_attempts": payload.max_attempts,
                "retry_after_recovery": payload.retry_after_recovery,
                "recovery_snapshot_id": payload.recovery_snapshot_id,
                "recovery_snapshot_ref": payload.recovery_snapshot_ref,
                "recovery_commit_sha": payload.recovery_commit_sha,
                "recovery_scope": payload.recovery_scope,
                "recovery_paths": tuple(payload.paths),
                "final_tree_sha": payload.final_tree_sha,
                "final_snapshot_id": payload.final_snapshot_id,
                "final_snapshot_ref": payload.final_snapshot_ref,
                "final_commit_sha": payload.final_commit_sha,
                "final_boundary_hash": payload.final_boundary_hash,
                "final_boundary_entries": tuple(payload.final_boundary_entries),
                "recovery_observed_cache_roots": recovery_cache_roots,
                "recovery_authorized_cache_roots": tuple(
                    payload.authorized_cache_roots
                    if not legacy_event
                    and not compact_event
                    and payload.authorized_cache_roots is not None
                    else [
                        root
                        for root in _attempt_root_union(existing, recovery_cache_roots)
                        if not isinstance(root, str)
                    ]
                ),
                "legacy_cache_root_paths": tuple(
                    payload.legacy_cache_root_paths
                    if not legacy_event
                    and not compact_event
                    and payload.legacy_cache_root_paths is not None
                    else existing.legacy_cache_root_paths
                ),
                "recovery_cache_status_evidence": tuple(payload.cache_status_evidence or ()),
                "cache_roots": _attempt_root_union(existing, recovery_cache_roots),
            }
        )
    elif event.event_type == "runner_recovery_completed":
        payload = RunnerRecoveryCompletedPayload.model_validate(event.payload)
        existing = attempts.get(payload.execution_id)
        if existing is None or existing.recovery_id != payload.recovery_id:
            raise ProjectionReplayConflictError(
                "runner recovery completion conflicts during replay"
            )
        if existing.state != "recovery_requested":
            if existing.state == "recovered":
                if (
                    payload.node_id == existing.node_id
                    and payload.lease_id == existing.lease_id
                    and payload.lease_generation == existing.lease_generation
                    and payload.baseline_snapshot_id == existing.baseline_snapshot_id
                    and payload.baseline_tree_sha == existing.baseline_tree_sha
                    and tuple(payload.requested_paths or ()) == existing.recovery_paths
                    and payload.recovery_scope == existing.recovery_scope
                    and tuple(payload.restored_paths) == existing.restored_paths
                    and tuple(payload.removed_paths) == existing.removed_paths
                    and payload.proof_hash == existing.recovery_proof_hash
                ):
                    return state
                raise ProjectionReplayConflictError(
                    "runner recovery completion duplicate conflicts"
                )
            raise ProjectionReplayConflictError("runner recovery completion is out of order")
        if (
            payload.node_id != existing.node_id
            or payload.lease_id != existing.lease_id
            or payload.lease_generation != existing.lease_generation
            or payload.baseline_snapshot_id != existing.baseline_snapshot_id
            or payload.baseline_tree_sha != existing.baseline_tree_sha
            or payload.requested_paths is None
            or tuple(payload.requested_paths) != existing.recovery_paths
            or payload.recovery_scope != existing.recovery_scope
            or payload.proof_hash is None
        ):
            raise ProjectionReplayConflictError("runner recovery proof conflicts with request")
        if existing.recovery_scope == "selective" and (
            len(set(payload.restored_paths)) != len(payload.restored_paths)
            or len(set(payload.removed_paths)) != len(payload.removed_paths)
            or set(payload.restored_paths) & set(payload.removed_paths)
            or set(payload.restored_paths) | set(payload.removed_paths)
            != set(existing.recovery_paths)
        ):
            raise ProjectionReplayConflictError("runner recovery accounting conflicts with request")
        from orchestrator.graph.boundary_types import recovery_proof_hash

        if payload.proof_hash != recovery_proof_hash(
            execution_id=payload.execution_id,
            recovery_id=payload.recovery_id,
            node_id=existing.node_id,
            lease_id=existing.lease_id,
            lease_generation=existing.lease_generation,
            baseline_snapshot_id=existing.baseline_snapshot_id or "",
            baseline_tree_sha=existing.baseline_tree_sha or "",
            requested_paths=tuple(payload.requested_paths),
            restored_paths=tuple(payload.restored_paths),
            removed_paths=tuple(payload.removed_paths),
            recovery_scope=payload.recovery_scope,
        ):
            raise ProjectionReplayConflictError("runner recovery proof hash is invalid")
        candidate = existing.model_copy(
            update={
                "state": "recovered",
                "completion_disposition": payload.disposition
                or _legacy_recovery_completion_disposition(existing),
                "recovery_proof_hash": payload.proof_hash,
                "restored_paths": tuple(payload.restored_paths),
                "removed_paths": tuple(payload.removed_paths),
            }
        )
    elif event.event_type == "runner_execution_finalized":
        payload = RunnerExecutionFinalizedPayload.model_validate(event.payload)
        _validate_replay_cache_authority(state, payload)
        _verify_boundary_hash(
            payload.final_tree_sha,
            payload.boundary_entries,
            payload.boundary_hash,
            payload.cache_status_evidence or (),
            payload.cache_authority_hash,
        )
        existing = attempts.get(payload.execution_id)
        replay_roots = _replay_cache_roots(state, payload)
        if existing is None:
            raise ProjectionReplayConflictError("runner finalization has no baseline")
        if existing.state == "finalized":
            if (
                existing.node_id == payload.node_id
                and existing.lease_id == payload.lease_id
                and existing.lease_generation == payload.lease_generation
                and existing.final_snapshot_id == payload.final_snapshot_id
                and existing.final_snapshot_ref == payload.final_snapshot_ref
                and existing.final_commit_sha == payload.final_commit_sha
                and existing.final_tree_sha == payload.final_tree_sha
                and existing.final_boundary_hash == payload.boundary_hash
                and existing.final_boundary_entries == tuple(payload.boundary_entries)
                and existing.final_cache_roots == replay_roots
                and existing.cache_authority_hash == payload.cache_authority_hash
            ):
                return state
            raise ProjectionReplayConflictError(
                "runner finalization duplicate conflicts during replay"
            )
        if (
            existing.state not in {"submission_staged", "completion_witnessed"}
            or existing.node_id != payload.node_id
            or existing.lease_id != payload.lease_id
            or existing.lease_generation != payload.lease_generation
            or existing.staged_boundary_hash != payload.boundary_hash
        ):
            raise ProjectionReplayConflictError(
                "runner finalization conflicts with staged execution"
            )
        candidate = existing.model_copy(
            update={
                "state": "finalized",
                "completion_disposition": "finalized_accepted",
                "final_snapshot_id": payload.final_snapshot_id,
                "final_snapshot_ref": payload.final_snapshot_ref,
                "final_commit_sha": payload.final_commit_sha,
                "final_tree_sha": payload.final_tree_sha,
                "final_boundary_hash": payload.boundary_hash,
                "final_boundary_entries": tuple(payload.boundary_entries),
                "final_cache_roots": replay_roots,
                "final_cache_status_evidence": tuple(payload.cache_status_evidence or ()),
                "cache_roots": _attempt_root_union(existing, replay_roots),
            }
        )
    else:
        # A mismatch is an audit fact; recovery_requested owns the state transition.
        from orchestrator.graph.cache_authority import RunnerCacheRoot
        from orchestrator.graph.models import RunnerBoundaryMismatchPayload

        payload = RunnerBoundaryMismatchPayload.model_validate(event.payload)
        _validate_replay_cache_authority(state, payload)
        _verify_boundary_hash(
            payload.final_tree_sha,
            payload.final_boundary_entries,
            payload.final_boundary_hash,
            payload.cache_status_evidence or (),
            payload.cache_authority_hash,
        )
        existing = attempts.get(payload.execution_id)
        if (
            existing is None
            or existing.state not in {"submission_staged", "completion_witnessed"}
            or existing.node_id != payload.node_id
            or existing.lease_id != payload.lease_id
            or existing.lease_generation != payload.lease_generation
            or existing.staged_boundary_hash != payload.staged_boundary_hash
            or payload.staged_boundary_hash == payload.final_boundary_hash
        ):
            raise ProjectionReplayConflictError(
                "runner boundary mismatch conflicts with staged execution"
            )
        # The mismatch is audit-only, but it still carries the same authority
        # chain as its recovery request.  Do not permit a persisted audit fact
        # to widen (or rewrite) the roots from which recovery is derived.
        # Older facts used the aggregate ``cache_roots`` field only, so retain
        # their replay compatibility when the new observed-root carrier is
        # absent.
        carrier_fields = _explicit_cache_carrier_fields(payload)
        if (
            "observed_cache_roots" in carrier_fields
            or "authorized_cache_roots" in carrier_fields
            or "legacy_cache_root_paths" in carrier_fields
        ):
            observed_roots = _replay_cache_roots(state, payload)
            expected_authorized = tuple(
                RunnerCacheRoot.model_validate(root)
                for root in _attempt_root_union(existing, observed_roots)
                if not isinstance(root, str)
            )
            if (
                tuple(payload.authorized_cache_roots or ()) != expected_authorized
                or tuple(payload.legacy_cache_root_paths or ()) != existing.legacy_cache_root_paths
            ):
                raise ProjectionReplayConflictError(
                    "runner boundary mismatch root authority conflicts"
                )
        return state
    existing = attempts.get(candidate.execution_id)
    if existing == candidate:
        return state
    if existing is not None and event.event_type == "runner_baseline_recorded":
        raise ProjectionReplayConflictError(
            f"execution {candidate.execution_id!r} conflicts during replay"
        )
    execution = state.execution.model_copy(
        update={"attempts_by_execution_id": map_set(attempts, candidate.execution_id, candidate)}
    )
    return _replace_projection_groups(state, execution=execution)


def _verify_boundary_hash(
    tree_sha: str,
    entries: object,
    expected_hash: str,
    cache_status_evidence: object = (),
    cache_authority_hash: str | None = None,
) -> None:
    """Keep replay independently strict even for externally persisted events."""
    from orchestrator.graph.boundary_types import BoundaryValidationError, boundary_manifest_hash

    try:
        actual_hash = boundary_manifest_hash(
            tree_sha, cast(Any, entries), cast(Any, cache_status_evidence), cache_authority_hash
        )
    except BoundaryValidationError as exc:
        raise ProjectionReplayConflictError(f"invalid runner boundary manifest: {exc}") from exc
    if actual_hash != expected_hash:
        raise ProjectionReplayConflictError("runner boundary hash conflicts with manifest")


def _reduce_node_usage(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    usage = NodeUsageRecordedPayload.model_validate(event.payload)
    current = state.usage
    if usage.usage_key in current.recorded_keys:
        return state
    tokens = usage.gen_ai_usage_input_tokens + usage.gen_ai_usage_output_tokens
    updates: dict[str, object] = {
        "recorded_keys": map_set(current.recorded_keys, usage.usage_key, True),
        "tokens_by_node": map_set(
            current.tokens_by_node,
            usage.node_id,
            current.tokens_by_node.get(usage.node_id, 0) + tokens,
        ),
        "tokens_by_node_kind": map_set(
            current.tokens_by_node_kind,
            usage.node_kind,
            current.tokens_by_node_kind.get(usage.node_kind, 0) + tokens,
        ),
    }
    if usage.usage_index == 0:
        updates.update(
            {
                "latency_ms_by_node_kind": map_set(
                    current.latency_ms_by_node_kind,
                    usage.node_kind,
                    current.latency_ms_by_node_kind.get(usage.node_kind, 0) + usage.latency_ms,
                ),
                "execution_count_by_node_kind": map_set(
                    current.execution_count_by_node_kind,
                    usage.node_kind,
                    current.execution_count_by_node_kind.get(usage.node_kind, 0) + 1,
                ),
                "action_count_by_node_kind": map_set(
                    current.action_count_by_node_kind,
                    usage.node_kind,
                    current.action_count_by_node_kind.get(usage.node_kind, 0) + usage.num_actions,
                ),
            }
        )
    return _replace_projection_groups(state, usage=current.model_copy(update=updates))


def _reduce_lease(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    if event.event_type == "lease_granted":
        lease_id = LeaseGrantedPayload.model_validate(event.payload).lease_id
    elif event.event_type == "lease_renewed":
        lease_id = LeaseRenewedPayload.model_validate(event.payload).lease_id
    elif event.event_type == "lease_suspended":
        lease_id = LeaseSuspendedPayload.model_validate(event.payload).lease_id
    elif event.event_type == "lease_revoked":
        lease_id = LeaseRevokedPayload.model_validate(event.payload).lease_id
    elif event.event_type == "lease_expired":
        lease_id = LeaseExpiredPayload.model_validate(event.payload).lease_id
    else:
        lease_id = LeaseReleasedPayload.model_validate(event.payload).lease_id
    existing = state.execution.leases.get(lease_id)
    values: dict[str, object] = (
        existing.model_dump() if existing is not None else {"lease_id": lease_id}
    )
    granted_node_id: str | None = None
    if event.event_type == "lease_granted":
        payload = LeaseGrantedPayload.model_validate(event.payload)
        node = state.nodes.get(payload.node_id)
        granted_node_id = payload.node_id
        values.update(
            {
                "node_id": payload.node_id,
                "state": "active",
                "generation": payload.generation,
                "execution_id": payload.execution_id,
                "expires_at": payload.expires_at,
                "session_id": payload.session_id,
                "base_snapshot_id": payload.base_snapshot_id,
                "task_region_id": payload.task_region_id
                or (node.spec.task_region_id if node is not None else None),
                "kind": payload.kind or (node.spec.kind if node is not None else None),
                "resource_claims": tuple(
                    ResourceClaimValue.model_validate(claim.model_dump(mode="json"))
                    for claim in payload.resource_claims
                )
                if payload.resource_claims
                else (node.spec.resource_claims if node is not None else ()),
                "cache_authority_hash": payload.cache_authority_hash,
            }
        )
    elif event.event_type == "lease_renewed":
        payload = LeaseRenewedPayload.model_validate(event.payload)
        values["state"] = "active"
        if payload.node_id is not None:
            values["node_id"] = payload.node_id
        if payload.generation is not None:
            values["generation"] = payload.generation
        if payload.execution_id is not None:
            values["execution_id"] = payload.execution_id
        if payload.expires_at is not None:
            values["expires_at"] = payload.expires_at
    else:
        values["state"] = event.event_type.removeprefix("lease_")
    lease = LeaseValue.model_validate(values)
    if lease == existing:
        return state
    execution = state.execution.model_copy(
        update={
            "leases": map_set(state.execution.leases, lease_id, lease),
            "lease_ids_in_grant_order": (
                (*state.execution.lease_ids_in_grant_order, lease_id)
                if event.event_type == "lease_granted" and existing is None
                else state.execution.lease_ids_in_grant_order
            ),
        }
    )
    updated = _replace_projection_groups(state, execution=execution)
    if granted_node_id is not None and lease.session_id is not None:
        planning = updated.planning.model_copy(
            update={
                "session_id_by_node": map_set(
                    updated.planning.session_id_by_node, granted_node_id, lease.session_id
                )
            }
        )
        updated = _replace_projection_groups(updated, planning=planning)
    return updated


def _reduce_cleanup(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    if event.event_type == "cleanup_requested":
        payload = CleanupRequestedPayload.model_validate(event.payload)
        existing = state.execution.cleanup_requests_by_id.get(payload.cleanup_id)
        request = CleanupRequestValue.model_validate(
            {**payload.model_dump(), "position": event.position}
        )
        if existing is not None and existing != request:
            raise ProjectionReplayConflictError(
                f"cleanup {payload.cleanup_id!r} conflicts during replay"
            )
        execution = state.execution
        if existing is None:
            execution = execution.model_copy(
                update={
                    "cleanup_requests_by_id": map_set(
                        execution.cleanup_requests_by_id, payload.cleanup_id, request
                    )
                }
            )
        record_id = payload.file_state_record_id
        record = state.records.by_id.get(record_id) if record_id is not None else None
        records = state.records
        if isinstance(record, FileStateRecord):
            replacement = record.model_copy(
                update={
                    "compromised": True,
                    "superseded_pending": True,
                    "cleanup_id": payload.cleanup_id,
                    "cleanup_reason": payload.reason,
                    "compromised_paths": tuple(payload.paths),
                }
            )
            records = _replace_record(records, replacement)
        if execution is state.execution and records is state.records:
            return state
        return _replace_projection_groups(state, execution=execution, records=records)

    payload = CleanupAppliedPayload.model_validate(event.payload)
    requested = state.execution.cleanup_requests_by_id.get(payload.cleanup_id)
    if requested is None:
        raise ProjectionReplayConflictError(
            f"cleanup application {payload.cleanup_id!r} has no matching request"
        )
    if requested.snapshot_role is not None:
        ownership = (
            (payload.old_snapshot_id, requested.snapshot_id),
            (payload.snapshot_ref, requested.snapshot_ref),
            (payload.tree_sha, requested.tree_sha),
            (payload.commit_sha, requested.commit_sha),
            (payload.node_id, requested.node_id),
            (payload.lease_id, requested.lease_id),
            (payload.lease_generation, requested.lease_generation),
            (payload.snapshot_role, requested.snapshot_role),
        )
        if any(actual != expected for actual, expected in ownership):
            raise ProjectionReplayConflictError(
                f"cleanup application {payload.cleanup_id!r} conflicts with request"
            )
    execution = state.execution
    if payload.cleanup_id not in execution.applied_cleanup_ids:
        execution = execution.model_copy(
            update={
                "applied_cleanup_ids": map_set(
                    execution.applied_cleanup_ids, payload.cleanup_id, True
                )
            }
        )
    record = (
        state.records.by_id.get(payload.file_state_record_id)
        if payload.file_state_record_id
        else None
    )
    records = state.records
    if isinstance(record, FileStateRecord):
        records = _replace_record(
            records,
            record.model_copy(
                update={
                    "compromised": True,
                    "superseded_pending": False,
                    "superseded_by_record_id": payload.superseding_record_id,
                    "cleanup_applied_event_id": event.event_id,
                    "compromised_snapshot_deleted": payload.deleted_snapshot_ref is True,
                }
            ),
        )
    if execution is state.execution and records is state.records:
        return state
    return _replace_projection_groups(state, execution=execution, records=records)


def _reduce_callback_accepted(state: GraphProjection, event: EventEnvelope) -> GraphProjection:
    payload = CallbackAcceptedPayload.model_validate(event.payload)
    key = _callback_idempotency_projection_key(payload.node_id, payload.idempotency_key)
    if key in state.execution.callback_events_by_key:
        return state
    callback = CallbackEventValue(
        event_type="callback_accepted",
        node_id=payload.node_id,
        idempotency_key=payload.idempotency_key,
        outcome="callback_accepted",
        payload=freeze_json(payload.payload) if payload.payload is not None else None,
        payload_hash=payload.payload_hash,
        payload_size_bytes=payload.payload_size_bytes,
        record_ids=tuple(payload.record_ids),
    )
    execution = state.execution.model_copy(
        update={
            "callback_events_by_key": map_set(state.execution.callback_events_by_key, key, callback)
        }
    )
    return _replace_projection_groups(state, execution=execution)


def project_run_state(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> str | None:
    projection = projection if projection is not None else _project(events)
    run_state = projection.lifecycle.run_state
    blockers = final_invariant_blockers_for_events(events, projection)
    if run_state == "completed":
        if blockers:
            return "active"
        return run_state
    if run_state != "active":
        return run_state
    if blockers:
        return run_state
    task_states = {
        task_id: task.state for task_id, task in projection.tasks.items() if task.state is not None
    }
    if task_states and all(state == "accepted" for state in task_states.values()):
        return "completed"
    return run_state


def project_final_invariant_blockers(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> list[FinalInvariantBlocker]:
    proj = projection if projection is not None else _project(events)
    return list(iter_final_invariant_blockers(events, proj))


def final_invariant_blockers_for_events(
    events: list[EventEnvelope],
    projection: GraphProjection,
    *,
    include_completion_decision: bool = True,
) -> list[FinalInvariantBlocker]:
    return list(
        iter_final_invariant_blockers(
            events,
            projection,
            include_completion_decision=include_completion_decision,
        )
    )


def iter_final_invariant_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
    *,
    include_completion_decision: bool = True,
) -> Iterable[FinalInvariantBlocker]:
    """Yield final blockers without constructing the aggregate blocker list."""
    return _iter_final_invariant_blockers(
        events,
        projection,
        include_completion_decision=include_completion_decision,
        support_ids_limit=None,
    )


def iter_archival_final_invariant_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
    *,
    include_completion_decision: bool = True,
    collection_limit: int = 50,
) -> Iterable[FinalInvariantBlocker]:
    """Yield blockers whose nested collections are capped before row creation."""
    if collection_limit < 1:
        raise ValueError("collection_limit must be positive")
    return _iter_final_invariant_blockers(
        events,
        projection,
        include_completion_decision=include_completion_decision,
        support_ids_limit=collection_limit,
    )


def _iter_final_invariant_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
    *,
    include_completion_decision: bool,
    support_ids_limit: int | None,
) -> Iterable[FinalInvariantBlocker]:
    blocked_node_ids: set[str] = set()

    def emit(values: Iterable[FinalInvariantBlocker]) -> Iterable[FinalInvariantBlocker]:
        for blocker in values:
            if support_ids_limit is not None:
                blocker = _bound_archival_blocker_support_ids(blocker, support_ids_limit)
            node_id = blocker.get("node_id")
            if isinstance(node_id, str):
                blocked_node_ids.add(node_id)
            yield blocker

    pending_states = {"planned", "ready", "leased", "running", "blocked", "suspended"}
    for node_id, node in sorted(projection.nodes.items()):
        node_state = node.runtime.state
        if node_state is None:
            continue
        kind = node.spec.kind
        role = node.spec.role
        is_planner = kind == "planner" and role == "planner"
        is_gap_planner = kind == "gap_planner" or role == "gap_planner"
        if (is_planner or is_gap_planner) and node_state in pending_states:
            blocked_node_ids.add(node_id)
            blocker: FinalInvariantBlocker = {
                "kind": "pending_gap_planner" if is_gap_planner else "pending_planner",
                "reason": "planner node has not completed",
                "node_id": node_id,
                "state": node_state,
            }
            if node.spec.task_region_id is not None:
                blocker["task_region_id"] = node.spec.task_region_id
            yield blocker
            continue
        if (
            kind == "gate"
            and role == "planner_generation_budget_gate"
            and node_state in pending_states
        ):
            blocked_node_ids.add(node_id)
            blocker = {
                "kind": "pending_planner_generation_budget_gate",
                "reason": "planner generation budget gate is unresolved",
                "node_id": node_id,
                "state": node_state,
            }
            if node.spec.task_region_id is not None:
                blocker["task_region_id"] = node.spec.task_region_id
            yield blocker
            continue
        if kind == "check" and node_state in pending_states:
            blocked_node_ids.add(node_id)
            blocker = {
                "kind": "pending_check",
                "reason": "check node has not completed",
                "node_id": node_id,
                "state": node_state,
            }
            if node.spec.task_region_id is not None:
                blocker["task_region_id"] = node.spec.task_region_id
            yield blocker
    yield from emit(_open_proposal_blockers(events, projection))
    yield from emit(_suspect_node_blockers(events, projection))
    yield from emit(
        _requirement_evidence_blockers(
            events,
            projection,
            support_ids_limit=support_ids_limit,
        )
    )
    yield from emit(
        _authority_revision_blockers(
            events,
            projection,
            support_ids_limit=support_ids_limit,
        )
    )
    yield from emit(_blocked_requirement_node_blockers(events, projection))
    yield from emit(_dead_required_input_blockers(projection))
    yield from emit(_impossible_input_blockers(projection))
    yield from emit(_failed_check_result_blockers(events, projection))
    if include_completion_decision:
        yield from emit(_completion_decision_blockers(events, projection))
    yield from emit(_node_fulfillment_blockers(projection))
    for cleanup_id, cleanup in sorted(projection.execution.cleanup_requests_by_id.items()):
        if (
            cleanup.snapshot_role is not None
            and cleanup_id not in projection.execution.applied_cleanup_ids
        ):
            yield {
                "kind": "pending_managed_snapshot_cleanup",
                "reason": "managed runner snapshot cleanup is pending",
                "state": cleanup.snapshot_role,
            }
    for node_id, node in sorted(projection.nodes.items()):
        node_state = node.runtime.state
        if (
            node_state is None
            or node_id in blocked_node_ids
            or node_state not in pending_states
            or node.spec.kind == "final_gate"
        ):
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "pending_node",
            "reason": "node has not reached a terminal state",
            "node_id": node_id,
            "state": node_state,
        }
        task_region_id = node.spec.task_region_id
        if task_region_id is not None:
            blocker["task_region_id"] = task_region_id
        yield blocker
    for task_region_id, task in sorted(projection.tasks.items()):
        task_state = task.state
        if task_state is None:
            continue
        if task_state == "accepted":
            continue
        yield {
            "kind": "task_not_accepted",
            "reason": "task region has not reached accepted",
            "task_region_id": task_region_id,
            "state": task_state,
        }


def _node_fulfillment_blockers(projection: GraphProjection) -> Iterable[FinalInvariantBlocker]:
    for node_id, node in sorted(projection.nodes.items()):
        node_state = node.runtime.state
        if node_state is None:
            continue
        if node_state in {"cancelled", "retired"}:
            continue
        if node_state not in {"completed", "failed"}:
            continue
        contract = _grouped_contract_for_node(projection, node_id)
        if contract is None or contract.fulfillment_contribution == "none":
            continue
        if contract.fulfillment_contribution == "task_acceptance":
            continue
        if contract.node_type == "final_gate":
            continue
        missing_ports = _grouped_missing_fulfillment_ports(projection, node_id)
        if not missing_ports:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "node_unfulfilled",
            "reason": "node contract fulfillment outputs are missing",
            "node_id": node_id,
            "state": node_state,
            "support_ids": missing_ports,
        }
        task_region_id = node.spec.task_region_id
        if task_region_id is not None:
            blocker["task_region_id"] = task_region_id
        yield blocker


def _impossible_input_blockers(projection: GraphProjection) -> Iterable[FinalInvariantBlocker]:
    terminal_states = {"completed", "failed", "cancelled", "retired"}
    for edge_id, edge in sorted(projection.topology.edges.items()):
        if not edge.required:
            continue
        if edge.dependency_type != "input_binding":
            continue
        from_node_id = edge.from_node_id
        to_node_id = edge.to_node_id
        to_port = edge.to_port
        target = projection.nodes[to_node_id] if to_node_id in projection.nodes else None
        if target is not None and target.runtime.state in terminal_states:
            continue
        if from_node_id in projection.nodes:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "impossible_input",
            "reason": "required input edge has no producer node",
            "node_id": to_node_id,
            "edge_id": str(edge_id),
            "to_port": to_port,
            "state": target.runtime.state
            if target is not None and target.runtime.state is not None
            else "unknown",
        }
        task_region_id = target.spec.task_region_id if target is not None else None
        if task_region_id is not None:
            blocker["task_region_id"] = task_region_id
        yield blocker


def _dead_required_input_blockers(projection: GraphProjection) -> Iterable[FinalInvariantBlocker]:
    dead_source_states = {"failed", "cancelled", "retired"}
    target_terminal_states = {"completed", "failed", "cancelled", "retired"}
    for edge_id, edge in sorted(projection.topology.edges.items()):
        if not edge.required:
            continue
        if edge.dependency_type != "input_binding":
            continue
        from_node_id = edge.from_node_id
        to_node_id = edge.to_node_id
        to_port = edge.to_port
        source = projection.nodes[from_node_id] if from_node_id in projection.nodes else None
        source_state = source.runtime.state if source is not None else None
        if source_state not in dead_source_states:
            continue
        target = projection.nodes[to_node_id] if to_node_id in projection.nodes else None
        target_state = (
            target.runtime.state
            if target is not None and target.runtime.state is not None
            else "unknown"
        )
        if target_state in target_terminal_states:
            continue
        ports = projection.topology.input_bindings.get(to_node_id)
        binding = ports[to_port] if ports is not None and to_port in ports else None
        if binding is not None and binding.record_ids:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "dead_required_input",
            "reason": "required input source is terminal before producing a bound record",
            "node_id": to_node_id,
            "edge_id": str(edge_id),
            "from_node_id": str(from_node_id),
            "to_port": str(to_port),
            "state": target_state,
        }
        task_region_id = target.spec.task_region_id if target is not None else None
        if task_region_id is not None:
            blocker["task_region_id"] = task_region_id
        yield blocker


def _failed_check_result_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> Iterable[FinalInvariantBlocker]:
    if not _has_full_event_history(events):
        yield from _failed_check_result_blockers_from_projection(projection)
        return
    blockers_by_record: dict[str, FinalInvariantBlocker] = {}
    for event in events:
        if event.event_type != "output_record_accepted":
            continue
        if not _is_check_result_record(event.payload):
            continue
        status = _check_result_status(event.payload)
        if status is None:
            continue
        if status in {"passed", "pass", "ok"}:
            continue
        if _check_result_recovery_superseded(projection, event.payload):
            continue
        record_id = event.payload.get("record_id")
        key = record_id if isinstance(record_id, str) else f"position-{event.position}"
        blocker: FinalInvariantBlocker = {
            "kind": "failed_check_result",
            "reason": "check result did not pass",
        }
        value = event.payload.get("value")
        if isinstance(value, dict):
            typed_value = cast(dict[str, Any], value)
            classification = typed_value.get("classification")
            command_text = typed_value.get("command_text")
            stderr = typed_value.get("stderr_tail")
            exit_code = typed_value.get("exit_code")
            if isinstance(classification, str):
                blocker["classification"] = classification
            if isinstance(command_text, str):
                blocker["command_text"] = command_text
            if isinstance(stderr, str):
                blocker["stderr_tail"] = stderr
            if isinstance(exit_code, int) and (
                isinstance(command_text, str)
                or isinstance(stderr, str)
                or isinstance(classification, str)
            ):
                blocker["exit_code"] = exit_code
            if classification in {"environment_error", "tool_error", "tool_unavailable"}:
                blocker["reason"] = _environment_failure_reason_from_check_value(typed_value)
        node_id = event.payload.get("producer_node_id") or event.payload.get("node_id")
        if isinstance(node_id, str):
            blocker["node_id"] = node_id
        task_region_id = event.payload.get("task_region_id")
        if isinstance(task_region_id, str):
            blocker["task_region_id"] = task_region_id
        blocker["state"] = status
        blockers_by_record[key] = blocker
    for key in sorted(blockers_by_record):
        yield blockers_by_record[key]


def _failed_check_result_blockers_from_projection(
    projection: GraphProjection,
) -> Iterable[FinalInvariantBlocker]:
    blockers_by_record: dict[str, FinalInvariantBlocker] = {}
    for node_id, payload in projection.verification.check_results_by_node.items():
        status = payload.status
        if status in {"passed", "pass", "ok"}:
            continue
        if _check_result_recovery_superseded(projection, payload):
            continue
        key = payload.record_id or node_id
        blocker: FinalInvariantBlocker = {
            "kind": "failed_check_result",
            "reason": "check result did not pass",
            "node_id": node_id,
            "state": status,
        }
        if payload.classification is not None:
            blocker["classification"] = payload.classification
        if payload.command_text is not None:
            blocker["command_text"] = payload.command_text
        if payload.stderr_tail is not None:
            blocker["stderr_tail"] = payload.stderr_tail
        if payload.exit_code is not None and (
            payload.command_text is not None
            or payload.stderr_tail is not None
            or payload.classification is not None
        ):
            blocker["exit_code"] = payload.exit_code
        if payload.classification in {"environment_error", "tool_error", "tool_unavailable"}:
            blocker["reason"] = _environment_failure_reason_from_check_value(
                payload.model_dump(mode="json"),
            )
        if payload.task_region_id is not None:
            blocker["task_region_id"] = payload.task_region_id
        blockers_by_record[key] = blocker
    for key in sorted(blockers_by_record):
        yield blockers_by_record[key]


def _is_check_result_record(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "check_result"
        or payload.get("port") == "check_result"
        or payload.get("record_kind") == "check_result"
    )


def _check_result_status(payload: dict[str, Any]) -> str | None:
    status = payload.get("status")
    if isinstance(status, str):
        return status.lower()
    value = payload.get("value")
    if isinstance(value, dict):
        value_status = cast(dict[str, Any], value).get("status")
        if isinstance(value_status, str):
            return value_status.lower()
    return None


def _completion_decision_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> Iterable[FinalInvariantBlocker]:
    reliable_plan_node_ids = {
        node_id
        for node_id, node in projection.nodes.items()
        if isinstance(node.spec.dispatch_payload.get("reliable_plan_skeleton_id"), str)
        and node.runtime.state not in {"retired", "cancelled"}
    }
    final_gate_node_ids = {
        node_id
        for node_id, node in projection.nodes.items()
        if node.spec.kind == "final_gate" and node.runtime.state not in {"retired", "cancelled"}
    }
    if not final_gate_node_ids:
        if reliable_plan_node_ids:
            carrier_node_id = next(
                (
                    node_id
                    for node_id in sorted(reliable_plan_node_ids)
                    if projection.nodes[node_id].spec.kind == "root"
                ),
                min(reliable_plan_node_ids),
            )
            yield {
                "kind": "missing_reliable_plan_final_gate",
                "reason": (
                    "active reliable-plan skeleton has no active final gate or passing "
                    "completion decision"
                ),
                "node_id": carrier_node_id,
                "state": projection.nodes[carrier_node_id].runtime.state or "unknown",
            }
        return

    latest: dict[str, tuple[str, dict[str, Any]]] = {}
    payloads: Iterable[dict[str, Any]]
    if _has_full_event_history(events):
        payloads = (
            event.payload for event in events if event.event_type == "output_record_accepted"
        )
    else:
        payloads = (
            record.model_dump(mode="json", by_alias=True)
            for record in projection.records.by_id.values()
            if record.record_type != "file_state"
        )
    for payload in payloads:
        node_id = payload.get("producer_node_id")
        if not isinstance(node_id, str) or node_id not in final_gate_node_ids:
            continue
        if payload.get("port") != "completion_decision":
            continue
        status = _completion_decision_status(payload)
        if status is None:
            continue
        latest[node_id] = (status, payload)

    for node_id in sorted(final_gate_node_ids):
        decision = latest.get(node_id)
        if decision is None:
            yield {
                "kind": "missing_completion_decision",
                "reason": "final gate has not produced a completion_decision",
                "node_id": node_id,
                "state": projection.nodes[node_id].runtime.state or "unknown",
            }
            continue
        status, payload = decision
        if status == "passed":
            continue
        emitted = False
        for blocker in _completion_decision_payload_blockers(payload):
            emitted = True
            yield blocker
        if emitted:
            continue
        yield {
            "kind": "blocked_completion_decision",
            "reason": "final gate completion_decision is blocked",
            "node_id": node_id,
            "state": projection.nodes[node_id].runtime.state or "unknown",
        }


def _completion_decision_status(payload: dict[str, Any]) -> str | None:
    status = payload.get("status")
    if isinstance(status, str):
        return status
    value = payload.get("value")
    if isinstance(value, dict):
        value_status = cast(dict[str, Any], value).get("status")
        if isinstance(value_status, str):
            return value_status
    return None


def _completion_decision_payload_blockers(
    payload: dict[str, Any],
) -> Iterable[FinalInvariantBlocker]:
    value = payload.get("value")
    raw_blockers: Any = payload.get("blockers")
    if raw_blockers is None and isinstance(value, dict):
        raw_blockers = cast(dict[str, Any], value).get("blockers")
    if not isinstance(raw_blockers, list):
        return
    for raw_blocker in cast(list[Any], raw_blockers):
        if not isinstance(raw_blocker, dict):
            continue
        blocker = cast(dict[str, Any], raw_blocker)
        kind = blocker.get("kind")
        reason = blocker.get("reason")
        if not isinstance(kind, str) or not isinstance(reason, str):
            continue
        yield cast(FinalInvariantBlocker, dict(blocker))


def _open_proposal_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> Iterable[FinalInvariantBlocker]:
    if not _has_full_event_history(events):
        return
    open_proposals: dict[str, FinalInvariantBlocker] = {}
    for event in events:
        payload = _patch_event_payload(event)
        if payload is None:
            continue
        proposal_id = _proposal_id(payload)
        if proposal_id is None:
            continue
        if event.event_type in {"graph_patch_accepted", "graph_patch_rejected"}:
            open_proposals.pop(proposal_id, None)
    for key in sorted(open_proposals):
        yield open_proposals[key]


def _suspect_node_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> Iterable[FinalInvariantBlocker]:
    if _has_full_event_history(events):
        suspect_nodes: dict[str, str] = {}
        for event in events:
            if event.event_type == "plan_region_marked_suspect":
                payload = NodeSuspectPayload.model_validate(event.payload)
                reason = payload.reason or "suspect graph fact remains unresolved"
                for node_id in _node_ids_from_suspect_payload(payload):
                    suspect_nodes[node_id] = reason
    else:
        suspect_nodes = {
            node_id: node.runtime.suspect_reason
            for node_id, node in projection.nodes.items()
            if node.runtime.suspect_reason is not None
        }

    inactive_states = {"completed", "failed", "cancelled", "retired"}
    for node_id in sorted(suspect_nodes):
        node = projection.nodes[node_id] if node_id in projection.nodes else None
        node_state = node.runtime.state if node is not None else None
        if node_state in inactive_states:
            continue
        blocker: FinalInvariantBlocker = {
            "kind": "suspect_active_node",
            "reason": suspect_nodes[node_id],
            "node_id": node_id,
        }
        if node_state is not None:
            blocker["state"] = node_state
        yield blocker


def _requirement_evidence_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
    *,
    support_ids_limit: int | None,
) -> Iterable[FinalInvariantBlocker]:
    del events
    for requirement_id, _active_version_id in sorted(
        projection.requirements.active_version_id_by_requirement.items()
    ):
        stale_support_ids: list[str] = []
        stale_total = 0
        has_fresh_support = False
        for support_id, support in sorted(projection.requirements.support_by_id.items()):
            if support.requirement_id != requirement_id:
                continue
            stale_reason = _support_stale_reason(projection, support)
            if stale_reason is None and support.status == "active":
                has_fresh_support = True
                continue
            stale_total += 1
            if support_ids_limit is None or len(stale_support_ids) < support_ids_limit:
                stale_support_ids.append(support_id)
        if has_fresh_support:
            continue
        if stale_support_ids:
            yield _with_archival_collection_metadata(
                {
                    "kind": "stale_support_evidence",
                    "reason": "active requirement is supported only by stale evidence",
                    "requirement_id": requirement_id,
                    "support_ids": stale_support_ids,
                },
                owner="final_blockers",
                path="$.support_ids",
                total_known=stale_total,
                retained=stale_support_ids,
                enabled=support_ids_limit is not None,
            )
        yield _with_archival_collection_metadata(
            {
                "kind": "unsupported_active_requirement",
                "reason": "active requirement has no current supporting evidence",
                "requirement_id": requirement_id,
                "support_ids": stale_support_ids,
            },
            owner="final_blockers",
            path="$.support_ids",
            total_known=stale_total,
            retained=stale_support_ids,
            enabled=support_ids_limit is not None,
        )


def _authority_revision_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
    *,
    support_ids_limit: int | None,
) -> Iterable[FinalInvariantBlocker]:
    if not _has_full_event_history(events):
        for _, projected_blocker in sorted(
            projection.governance.authority_revision_blockers.items()
        ):
            payload = cast(
                FinalInvariantBlocker,
                projected_blocker.model_dump(
                    mode="json", exclude_none=True, exclude={"support_ids"}
                ),
            )
            support_ids = list(
                projected_blocker.support_ids
                if support_ids_limit is None
                else projected_blocker.support_ids[:support_ids_limit]
            )
            payload["support_ids"] = support_ids
            yield _with_archival_collection_metadata(
                payload,
                owner="final_blockers",
                path="$.support_ids",
                total_known=len(projected_blocker.support_ids),
                retained=support_ids,
                enabled=support_ids_limit is not None,
            )
        return
    unresolved: dict[str, FinalInvariantBlocker] = {}
    for event in events:
        if event.event_type == "authority_decision_recorded":
            authority_payload = AuthorityDecisionRecordedPayload.model_validate(event.payload)
            if authority_payload.decision in {"granted", "approved", "passed", "accepted"}:
                authority_revision_id = _authority_decision_revision_id(authority_payload)
                if authority_revision_id is not None:
                    unresolved.pop(authority_revision_id, None)
            continue
        payload = _authority_revision_payload_for_event(event)
        if payload is None:
            continue
        revision_id = _revision_id(payload)
        if revision_id is None:
            continue
        if event.event_type == "requirement_revision_recorded":
            if not _requires_authority_resolution(payload):
                continue
            blocker: FinalInvariantBlocker = {
                "kind": "unresolved_authority_required_revision",
                "reason": "semantic or new-behavior requirement revision lacks authority resolution",
                "revision_id": revision_id,
            }
            requirement_id = _requirement_id(payload)
            if requirement_id is not None:
                blocker["requirement_id"] = requirement_id
            unresolved[revision_id] = blocker
    for key in sorted(unresolved):
        yield unresolved[key]


def _blocked_requirement_node_blockers(
    events: list[EventEnvelope],
    projection: GraphProjection,
) -> Iterable[FinalInvariantBlocker]:
    for node_id, node in sorted(projection.nodes.items()):
        node_state = node.runtime.state
        if node.spec.kind != "requirement" or node_state != "blocked":
            continue
        payload = _node_creation_payload_from_node(node).model_dump(mode="json")
        priority = _requirement_priority(payload)
        if priority not in {"must", "expected", "critical"}:
            continue
        requirement_id = _requirement_id(payload) or node_id
        yield {
            "kind": "blocked_requirement",
            "reason": "must or expected requirement is blocked without accepted blocker",
            "node_id": node_id,
            "requirement_id": requirement_id,
            "state": node_state,
        }


def _proposal_id(payload: dict[str, Any]) -> str | None:
    for key in ("proposal_id", "patch_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _patch_event_payload(event: EventEnvelope) -> dict[str, Any] | None:
    if event.event_type == "graph_patch_accepted":
        return GraphPatchAcceptedPayload.model_validate(event.payload).model_dump(mode="json")
    if event.event_type == "graph_patch_rejected":
        return GraphPatchRejectedPayload.model_validate(event.payload).model_dump(mode="json")
    return None


def _node_ids_from_suspect_payload(payload: NodeSuspectPayload) -> list[str]:
    return sorted(
        set(
            [node_id for node_id in [payload.node_id, payload.region_id] if node_id is not None]
            + payload.node_ids
            + payload.region_node_ids
        )
    )


def _authority_revision_payload_for_event(event: EventEnvelope) -> dict[str, Any] | None:
    if event.event_type == "requirement_revision_recorded":
        return RequirementRevisionPayload.model_validate(event.payload).model_dump(mode="json")
    return None


def _revision_id(payload: dict[str, Any]) -> str | None:
    for key in ("revision_id", "version_id", "requirement_version_id", "proposal_id", "patch_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return _requirement_id(payload)


def _requirement_id(payload: dict[str, Any]) -> str | None:
    for key in ("requirement_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    requirement = payload.get("requirement")
    if isinstance(requirement, dict):
        value = cast(dict[str, Any], requirement).get("id")
        if isinstance(value, str) and value:
            return value
    node_id = payload.get("node_id")
    if isinstance(node_id, str) and node_id:
        return node_id
    return None


def _requires_authority_resolution(payload: dict[str, Any]) -> bool:
    if payload.get("requires_authority") is True:
        return True
    if payload.get("semantic_change") is True:
        return True
    revision_type = payload.get("revision_type")
    if not isinstance(revision_type, str):
        revision_type = payload.get("classification")
    return revision_type in {
        "semantic",
        "new_behavior",
        "new-behavior",
        "scope_expansion",
        "scope_reduction",
        "priority_change",
    }


def _requirement_priority(payload: dict[str, Any]) -> str | None:
    priority = payload.get("priority")
    if isinstance(priority, str):
        return priority.lower()
    requirement = payload.get("requirement")
    if isinstance(requirement, dict):
        value = cast(dict[str, Any], requirement).get("priority")
        if isinstance(value, str):
            return value.lower()
    return None


def project_planner_chain(events: list[EventEnvelope]) -> list[dict[str, Any]]:
    projection = _project(events)
    planner_ids = [
        node_id
        for node_id, node in projection.nodes.items()
        if node.spec.kind == "planner" and node.spec.role == "planner"
    ]
    ordered = sorted(
        planner_ids,
        key=lambda node_id: (
            projection.planning.generation_by_node[node_id]
            if node_id in projection.planning.generation_by_node
            else 0,
            projection.nodes[node_id].spec.creation_position,
            node_id,
        ),
    )
    return [
        {
            "node_id": node_id,
            "generation_index": projection.planning.generation_by_node[node_id]
            if node_id in projection.planning.generation_by_node
            else 0,
            "session_id": projection.planning.session_id_by_node[node_id]
            if node_id in projection.planning.session_id_by_node
            else None,
            "lease_generation": _latest_lease_generation_from_projection(projection, node_id),
            "region_label": _planner_region_label(events, projection, node_id),
            "state": projection.nodes[node_id].runtime.state,
            "successor_node_id": projection.planning.successor_by_node[node_id]
            if node_id in projection.planning.successor_by_node
            else None,
        }
        for node_id in ordered
    ]


def project_planner_session(events: list[EventEnvelope]) -> dict[str, Any]:
    projection = _project(events)
    session_ids = list(projection.planning.sessions)
    if not session_ids:
        session_ids = list(projection.planning.session_id_by_node.values())
    session_id = sorted(set(session_ids))[0] if session_ids else None
    if session_id is None:
        return {
            "session_id": None,
            "state": None,
            "generations": [],
            "current_node_id": None,
            "carryover_record_id": None,
        }

    generations: list[dict[str, Any]] = [
        {
            "node_id": lease.node_id,
            "lease_generation": lease.generation,
            "region_label": _planner_region_label(events, projection, lease.node_id),
            "state": lease.state,
        }
        for lease in projection.execution.leases.values()
        if lease.session_id == session_id
        and lease.node_id is not None
        and lease.generation is not None
    ]
    generations.sort(key=lambda generation: int(generation["lease_generation"]))
    return {
        "session_id": session_id,
        "state": projection.planning.sessions[session_id].state
        if session_id in projection.planning.sessions
        else None,
        "generations": generations,
        "current_node_id": projection.planning.sessions[session_id].current_node_id
        if session_id in projection.planning.sessions
        else None,
        "carryover_record_id": projection.planning.sessions[session_id].carryover_record_id
        if session_id in projection.planning.sessions
        else None,
    }


def project_node_states(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> dict[str, str]:
    proj = projection if projection is not None else _project(events)
    return {
        node_id: node.runtime.state
        for node_id, node in proj.nodes.items()
        if node.runtime.state is not None
    }


def project_node_metadata(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> dict[str, dict[str, Any]]:
    projection = projection if projection is not None else _project(events)
    metadata: dict[str, dict[str, Any]] = {}
    for node_id, node in projection.nodes.items():
        kind = node.spec.kind
        role = node.spec.role
        detail: dict[str, Any] = {
            "kind": kind,
            "role": role,
            "task_region_id": node.spec.task_region_id,
            "input_ports": {},
            "resource_claims": [
                claim.model_dump(mode="json", exclude_none=True)
                for claim in node.spec.resource_claims
            ],
            "allowed_actions": list(node.spec.allowed_actions),
            "preconditions": list(node.spec.preconditions),
        }
        if node.spec.command_definition is not None:
            detail["command_definition"] = thaw_json(node.spec.command_definition.value)
        bindings = projection.topology.input_bindings.get(node_id)
        if bindings is not None:
            detail["input_ports"] = {
                port: _bound_record_ids(binding) for port, binding in bindings.items()
            }
        contract = node_contract_summary(kind, role)
        if contract is not None:
            detail["contract"] = contract
        metadata[node_id] = detail
    return metadata


def project_graph_topology(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> GraphTopologyView:
    """Project topology from the current durable projection when supplied.

    Read-model consumers deliberately pass the incrementally maintained
    projection checkpoint here.  That keeps an API read from replaying the
    authoritative event stream merely to render topology.  Event history is
    still accepted for the pure replay/reference path and supplies the same
    record-position enrichment when available.
    """
    projection = projection if projection is not None else _project(events)
    record_summaries = {
        record_id: cast(
            GraphRecordSummary,
            summary.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        for record_id, summary in projection.records.summaries_by_id.items()
    }
    _add_record_summary_positions(record_summaries, events)
    nodes: list[GraphTopologyNode] = []
    for node_id, projected_node in sorted(projection.nodes.items()):
        kind = projected_node.spec.kind
        role = projected_node.spec.role
        node: GraphTopologyNode = {
            "node_id": node_id,
            "kind": kind,
            "role": role,
            "state": projected_node.runtime.state,
        }
        contract = node_contract_summary(kind, role)
        if contract is not None:
            node["contract"] = contract
        nodes.append(node)

    edges = [
        _topology_edge(edge, projection, record_summaries)
        for _, edge in sorted(projection.topology.edges.items())
    ]
    return {"nodes": nodes, "edges": edges}


def iter_graph_topology_entries(
    projection: GraphProjection,
) -> Iterable[tuple[str, str, dict[str, Any]]]:
    """Yield topology rows directly from durable projection groups.

    The archival contract is canonical rather than insertion ordered: nodes
    precede edges and identities are lexical within each kind.  This makes
    keyset pages stable across live maintenance and delete-and-rebuild paths.
    """
    for node_id, projected_node in sorted(projection.nodes.items()):
        kind = projected_node.spec.kind
        role = projected_node.spec.role
        node: GraphTopologyNode = {
            "node_id": node_id,
            "kind": kind,
            "role": role,
            "state": projected_node.runtime.state,
        }
        contract = node_contract_summary(kind, role)
        if contract is not None:
            node["contract"] = contract
        yield "node", node_id, dict(node)
    for edge_id, edge in sorted(projection.topology.edges.items()):
        binding = _binding_for_edge(projection, edge)
        record_summaries: dict[str, GraphRecordSummary] = {}
        if binding is not None:
            for record_id in binding.record_ids:
                summary = projection.records.summaries_by_id.get(record_id)
                if summary is not None:
                    record_summaries[record_id] = cast(
                        GraphRecordSummary,
                        summary.model_dump(mode="json", by_alias=True, exclude_none=True),
                    )
        yield "edge", str(edge_id), dict(_topology_edge(edge, projection, record_summaries))


def iter_archival_graph_topology_entries(
    projection: GraphProjection,
    *,
    collection_limit: int = 50,
) -> Iterable[tuple[str, str, dict[str, Any]]]:
    """Yield topology rows with binding collections capped before allocation."""
    if collection_limit < 1:
        raise ValueError("collection_limit must be positive")
    for node_id, projected_node in sorted(projection.nodes.items()):
        kind = projected_node.spec.kind
        role = projected_node.spec.role
        node: GraphTopologyNode = {
            "node_id": node_id,
            "kind": kind,
            "role": role,
            "state": projected_node.runtime.state,
        }
        contract = node_contract_summary(kind, role)
        if contract is not None:
            node["contract"] = contract
        yield "node", node_id, dict(node)

    for edge_id, edge in sorted(projection.topology.edges.items()):
        topology_edge = _topology_edge_base(edge, projection)
        binding = _binding_for_edge(projection, edge)
        if binding is not None:
            total_record_ids = len(binding.record_ids)
            retained_record_ids = list(binding.record_ids[:collection_limit])
            topology_edge["binding"] = _topology_binding(
                binding,
                record_ids=retained_record_ids,
                record_bound_position_ids=retained_record_ids,
            )
            _attach_topology_archival_metadata(
                topology_edge,
                path="$.binding.record_ids",
                total_known=total_record_ids,
                retained_cursor=retained_record_ids[-1] if retained_record_ids else None,
                retained_count=len(retained_record_ids),
            )

            retained_records: list[GraphRecordSummary] = []
            total_records = 0
            last_retained_record_id: str | None = None
            for record_id in binding.record_ids:
                summary = projection.records.summaries_by_id.get(record_id)
                if summary is None:
                    continue
                total_records += 1
                if len(retained_records) >= collection_limit:
                    continue
                retained_records.append(
                    cast(
                        GraphRecordSummary,
                        summary.model_dump(mode="json", by_alias=True, exclude_none=True),
                    )
                )
                last_retained_record_id = record_id
            topology_edge["bound_records"] = retained_records
            _attach_topology_archival_metadata(
                topology_edge,
                path="$.bound_records",
                total_known=total_records,
                retained_cursor=last_retained_record_id,
                retained_count=len(retained_records),
            )

            positions = binding.record_bound_positions
            if positions is not None:
                total_positions = len(positions)
                retained_position_ids = [
                    record_id for record_id in retained_record_ids if record_id in positions
                ]
                _attach_topology_archival_metadata(
                    topology_edge,
                    path="$.binding.record_bound_positions",
                    total_known=total_positions,
                    retained_cursor=(retained_position_ids[-1] if retained_position_ids else None),
                    retained_count=len(retained_position_ids),
                )
        yield "edge", str(edge_id), cast(dict[str, Any], topology_edge)


def _attach_topology_archival_metadata(
    payload: GraphTopologyEdge,
    *,
    path: str,
    total_known: int,
    retained_cursor: str | None,
    retained_count: int,
) -> None:
    if total_known <= retained_count:
        return
    raw_payload = cast(dict[str, Any], payload)
    contract = cast(
        dict[str, Any],
        raw_payload.setdefault(
            _GRAPH_ARCHIVAL_READ_CONTRACT_KEY,
            {
                "revision": _GRAPH_ARCHIVAL_READ_CONTRACT_REVISION,
                "partial": True,
                "fields": {},
            },
        ),
    )
    fields = cast(dict[str, Any], contract.setdefault("fields", {}))
    fields[path] = {
        "revision": _GRAPH_ARCHIVAL_READ_CONTRACT_REVISION,
        "owner": "topology",
        "truncated": True,
        "total_known": total_known,
        "next_cursor": retained_cursor,
        "original_bytes": None,
        "sha256": None,
    }
    contract["partial"] = True


def project_graph_patch_attempts(
    events: list[EventEnvelope],
    *,
    run_id: str = "",
    current_graph_position: int | None = None,
) -> GraphPatchAttemptView:
    attempts: dict[str, GraphPatchAttempt] = {}
    order: list[str] = []
    active_patch_id: str | None = None

    def ensure_attempt(patch_id: str) -> GraphPatchAttempt:
        attempt = attempts.get(patch_id)
        if attempt is None:
            attempt = GraphPatchAttempt(
                patch_id=patch_id,
                created_node_ids=[],
                created_edge_ids=[],
            )
            attempts[patch_id] = attempt
            order.append(patch_id)
        return attempt

    for event in events:
        payload = _patch_event_payload(event) or event.payload
        patch_id = _patch_id(payload)
        if event.event_type == "graph_patch_accepted" and patch_id is not None:
            attempt = ensure_attempt(patch_id)
            attempt["status"] = "accepted"
            attempt["accepted_event_id"] = event.event_id
            attempt["accepted_position"] = event.position
            _apply_patch_payload(attempt, payload)
            if current_graph_position is not None:
                attempt["current_graph_position"] = current_graph_position
            active_patch_id = patch_id
            continue
        if event.event_type == "graph_patch_rejected" and patch_id is not None:
            attempt = ensure_attempt(patch_id)
            attempt["status"] = "rejected"
            attempt["rejected_event_id"] = event.event_id
            attempt["rejected_position"] = event.position
            _apply_patch_payload(attempt, payload)
            if current_graph_position is not None:
                attempt["current_graph_position"] = current_graph_position
            active_patch_id = None
            continue
        if active_patch_id is None:
            continue
        attempt = attempts.get(active_patch_id)
        if attempt is None:
            continue
        if event.event_type == "node_created":
            node_id = _created_node_id(event)
            if node_id is not None:
                created = attempt.setdefault("created_node_ids", [])
                created.append(node_id)
        elif event.event_type == "edge_created":
            edge_id = payload.get("edge_id")
            if isinstance(edge_id, str):
                created = attempt.setdefault("created_edge_ids", [])
                created.append(edge_id)
        else:
            active_patch_id = None

    if current_graph_position is None:
        current_graph_position = max((event.position for event in events), default=0)
    ordered_attempts: list[GraphPatchAttempt] = []
    for patch_id in order:
        attempt = attempts[patch_id]
        if "status" not in attempt:
            continue
        attempt.setdefault("current_graph_position", current_graph_position)
        ordered_attempts.append(
            cast(
                GraphPatchAttempt,
                GraphPatchResultRecord.model_validate(attempt).model_dump(mode="json"),
            )
        )
    return {
        "run_id": run_id,
        "current_graph_position": current_graph_position,
        "attempts": ordered_attempts,
    }


def _apply_patch_payload(attempt: GraphPatchAttempt, payload: dict[str, Any]) -> None:
    proposed_by_node_id = payload.get("proposed_by_node_id")
    if isinstance(proposed_by_node_id, str):
        attempt["proposed_by_node_id"] = proposed_by_node_id
    base_graph_position = payload.get("base_graph_position")
    if (
        isinstance(base_graph_position, int)
        and not isinstance(base_graph_position, bool)
        and base_graph_position >= 0
    ):
        attempt["base_graph_position"] = base_graph_position
    reason = payload.get("reason")
    if isinstance(reason, str) and reason:
        attempt["rejection_reason"] = reason
    read_set_diff = payload.get("read_set_diff")
    if isinstance(read_set_diff, dict):
        attempt["read_set_diff"] = cast(dict[str, Any], read_set_diff)
    diagnostics = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "patch_id",
            "proposed_by_node_id",
            "base_graph_position",
            "reason",
            "read_set_diff",
        }
    }
    if diagnostics:
        attempt["diagnostics"] = diagnostics


def _patch_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("patch_id")
    if isinstance(value, str) and value:
        return value
    return None


def _created_node_id(event: EventEnvelope) -> str | None:
    if event.event_type != "node_created":
        return None
    return NodeCreatedPayload.model_validate(event.payload).node_id


def project_task_states(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> dict[str, str]:
    proj = projection if projection is not None else _project(events)
    return {task_id: task.state for task_id, task in proj.tasks.items() if task.state is not None}


def project_requirement_revisions(events: list[EventEnvelope]) -> dict[str, dict[str, Any]]:
    return {
        version_id: revision.model_dump(mode="json")
        for version_id, revision in _project(events).requirements.revisions_by_id.items()
    }


def support_evidence_freshness_from_projection(
    projection: GraphProjection,
) -> dict[str, SupportEvidenceFreshness]:
    freshness: dict[str, SupportEvidenceFreshness] = {}
    for support_id, support in sorted(projection.requirements.support_by_id.items()):
        stale_reason = _support_stale_reason(projection, support)
        is_fresh = stale_reason is None and support.status == "active"
        freshness[support_id] = {
            "support_id": support_id,
            "evidence_id": support.evidence_id,
            "requirement_id": support.requirement_id,
            "requirement_version_id": support.requirement_version_id,
            "status": support.status,
            "freshness": "fresh" if is_fresh else "stale",
            "stale_reason": stale_reason,
        }
    return freshness


def project_support_evidence_freshness(
    events: list[EventEnvelope],
) -> dict[str, SupportEvidenceFreshness]:
    return support_evidence_freshness_from_projection(_project(events))


def requirement_freshness_facts_from_projection(
    projection: GraphProjection,
) -> list[RequirementFreshnessFact]:
    support_freshness = support_evidence_freshness_from_projection(projection)
    facts: list[RequirementFreshnessFact] = []
    for requirement_id, active_version_id in sorted(
        projection.requirements.active_version_id_by_requirement.items()
    ):
        revision = projection.requirements.revisions_by_id.get(active_version_id)
        fresh_support_ids: list[str] = []
        stale_support_ids: list[str] = []
        for support_id, support in sorted(projection.requirements.support_by_id.items()):
            if support.requirement_id != requirement_id:
                continue
            support_fact = support_freshness.get(support_id)
            if support_fact is None:
                continue
            if support_fact["freshness"] == "fresh":
                fresh_support_ids.append(support_id)
            else:
                stale_support_ids.append(support_id)
        facts.append(
            {
                "requirement_id": requirement_id,
                "active_version_id": active_version_id,
                "revision_classification": (
                    revision.change_classification
                    if isinstance(revision, RequirementRevisionValue)
                    else "initial"
                ),
                "requires_authority": (
                    revision.requires_authority
                    if isinstance(revision, RequirementRevisionValue)
                    else False
                ),
                "authority_required_reason": (
                    revision.authority_required_reason
                    if isinstance(revision, RequirementRevisionValue)
                    else None
                ),
                "fresh_support_ids": fresh_support_ids,
                "stale_support_ids": stale_support_ids,
                "unsupported": not fresh_support_ids,
            }
        )
    return facts


def project_requirement_freshness_facts(
    events: list[EventEnvelope],
) -> list[RequirementFreshnessFact]:
    return requirement_freshness_facts_from_projection(_project(events))


def project_planner_freshness_packet(events: list[EventEnvelope]) -> dict[str, Any]:
    """Expose compact requirement/evidence freshness facts for gap planners."""
    facts = project_requirement_freshness_facts(events)
    return {
        "requirement_freshness": facts,
        "unsupported_requirement_ids": [
            fact["requirement_id"] for fact in facts if fact["unsupported"]
        ],
        "stale_support_ids": [
            support_id for fact in facts for support_id in fact["stale_support_ids"]
        ],
        "authority_required_requirement_ids": [
            fact["requirement_id"] for fact in facts if fact["requires_authority"]
        ],
    }


def project_leases(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> dict[str, dict[str, Any]]:
    proj = projection if projection is not None else _project(events)
    return {
        lease_id: _public_lease(proj.execution.leases[lease_id])
        for lease_id in proj.execution.lease_ids_in_grant_order
    }


def _public_lease(lease: LeaseValue) -> dict[str, Any]:
    public = lease.model_dump(mode="json", exclude_none=True)
    if not lease.resource_claims:
        del public["resource_claims"]
    return public


def project_ready_nodes(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> list[str]:
    proj = projection if projection is not None else _project(events)
    return list(proj.scheduling.ready_node_ids)


def project_scheduler_view(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> SchedulerView:
    """Project ready/deferred scheduler buckets from graph events.

    Readiness remains governed by node_state_changed facts. Deferred scheduler
    events are audit facts, so this view exposes the latest deferral reason
    even when a node is still ready but blocked by a transient scheduler
    precondition such as a resource conflict.
    """
    proj = projection if projection is not None else _project(events)
    node_states = project_node_states([], projection=proj)
    ready = sorted(project_ready_nodes([], projection=proj))
    latest_deferrals = {
        node_id: node.scheduling.last_deferred_reason
        for node_id, node in proj.nodes.items()
        if node.scheduling.last_deferred_reason is not None
    }
    view: SchedulerView = {
        "ready": ready,
        "blocked": [],
        "waiting_resources": [],
        "waiting_gates": [],
    }
    for node_id, node_state in sorted(node_states.items()):
        reason = latest_deferrals.get(node_id)
        if node_state not in {"planned", "blocked", "ready"}:
            continue
        if node_state == "ready" and reason == "max_grants_reached":
            continue
        if reason is None and node_state not in {"blocked"}:
            continue
        if reason is None:
            reason = "blocked"
        entry: SchedulerBlockedNode = {"node_id": node_id, "reason": reason}
        bucket = _scheduler_bucket_for_reason(reason)
        view[bucket].append(entry)
    return view


def project_lease_view(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> LeaseView:
    leases = project_leases(events, projection=projection)
    view: LeaseView = {"active": [], "suspended": []}
    for lease_id in sorted(leases):
        lease = leases[lease_id]
        state = lease.get("state")
        if state not in {"active", "suspended"}:
            continue
        node_id = lease.get("node_id")
        if not isinstance(node_id, str):
            continue
        entry: LeaseViewEntry = {
            "lease_id": lease_id,
            "node_id": node_id,
            "generation": _optional_int(lease.get("generation")),
            "state": state,
            "execution_id": _optional_str(lease.get("execution_id")),
            "expires_at": _optional_str(lease.get("expires_at")),
        }
        if state == "active":
            view["active"].append(entry)
        else:
            view["suspended"].append(entry)
    return view


def project_decision_view(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> DecisionView:
    """Project human decisions, appeal outcomes, and review readiness."""
    projection = projection if projection is not None else _project(events)
    return project_decision_view_from_projection(projection)


def project_decision_view_from_projection(projection: GraphProjection) -> DecisionView:
    """Project decision readback from an already-folded graph projection."""
    latest_deferrals = {
        node_id: node.scheduling.last_deferred_reason
        for node_id, node in projection.nodes.items()
        if node.scheduling.last_deferred_reason is not None
    }

    pending_gates: list[PendingGateDecision] = []
    appeals: list[AppealDecision] = []
    review_blockers: list[str] = []
    review_node_count = 0
    review_complete_count = 0

    for node_id, node in sorted(projection.nodes.items()):
        state = node.runtime.state
        if state is None:
            continue
        kind = node.spec.kind
        if (
            kind in {"gate", "human_gate"}
            and state in _PENDING_DECISION_STATES
            and node_id not in projection.governance.approval_decision_id_by_node
        ):
            pending_gate: PendingGateDecision = {
                "node_id": node_id,
                "gate_type": _gate_type(node),
                "prompt": _gate_prompt(node),
            }
            pending_gate.update(_request_details_for_pending_gate(node_id, node, projection))
            pending_gates.append(pending_gate)
        elif (
            kind == "authority_request"
            and state in _PENDING_DECISION_STATES
            and node_id not in projection.governance.authority_decision_id_by_node
        ):
            pending_gate = {
                "node_id": node_id,
                "gate_type": "authority_request",
                "prompt": _gate_prompt(node),
            }
            pending_gate.update(_request_details_for_pending_gate(node_id, node, projection))
            pending_gates.append(pending_gate)
        elif kind == "appeal":
            appeals.append(
                {
                    "node_id": node_id,
                    "state": state,
                    "outcome": _decision_outcome(_oversight_decision_for_node(projection, node_id)),
                }
            )
        elif kind == "review":
            review_node_count += 1
            if state == "completed":
                review_complete_count += 1
            else:
                review_blockers.append(_review_blocker(node_id, state, node, latest_deferrals))

    return {
        "pending_gates": pending_gates,
        "appeals": appeals,
        "review": {
            "ready": review_node_count > 0 and review_complete_count == review_node_count,
            "blockers": review_blockers,
        },
    }


def project_residue_report(events: list[EventEnvelope]) -> dict[str, list[dict[str, Any]]]:
    """Project accepted file-state residue classifications by path."""
    report: dict[str, list[dict[str, Any]]] = {}
    for record in _project(events).records.by_id.values():
        if not isinstance(record, FileStateRecord):
            continue
        entries = record.residue or record.classifications
        for raw_entry in entries:
            entry = raw_entry.model_dump(mode="json", by_alias=True, exclude_none=True)
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            report.setdefault(path, []).append(
                {
                    "path": path,
                    "classification": entry.get("classification"),
                    "matched_rule": entry.get("matched_rule") or entry.get("policy"),
                    "needs_gatekeeper": entry.get("needs_gatekeeper") is True,
                    "run_id": record.run_id,
                    "node_id": record.producer_node_id,
                    "record_id": record.record_id,
                    "source": entry.get("source"),
                }
            )
    return {path: report[path] for path in sorted(report)}


def _bound_record_ids(binding: InputBindingValue) -> list[str]:
    return list(binding.record_ids)


def _topology_edge(
    edge: EdgeValue,
    projection: GraphProjection,
    record_summaries: dict[str, GraphRecordSummary],
) -> GraphTopologyEdge:
    topology_edge = _topology_edge_base(edge, projection)
    binding = _binding_for_edge(projection, edge)
    if binding is not None:
        binding_summary = _topology_binding(binding)
        topology_edge["binding"] = binding_summary
        record_ids = binding_summary.get("record_ids", [])
        topology_edge["bound_records"] = [
            record_summaries[record_id] for record_id in record_ids if record_id in record_summaries
        ]
    return topology_edge


def _topology_edge_base(
    edge: EdgeValue,
    projection: GraphProjection,
) -> GraphTopologyEdge:
    source_contract, target_contract = _edge_port_contracts(edge, projection)
    metadata = {
        key: thaw_json(value)
        for key in _EDGE_METADATA_KEYS
        if (value := getattr(edge, key)) is not None
    }
    topology_edge: GraphTopologyEdge = {
        "edge_id": edge.edge_id,
        "from_node_id": edge.from_node_id,
        "from_port": edge.from_port,
        "to_node_id": edge.to_node_id,
        "to_port": edge.to_port,
        "required": edge.required,
        "dependency_type": edge.dependency_type,
        "metadata": dict(metadata),
        "record_types": _compatible_edge_record_types(source_contract, target_contract),
        "binding": None,
        "bound_records": [],
    }
    from_node_kind = edge.from_node_kind
    if isinstance(from_node_kind, str):
        topology_edge["from_node_kind"] = from_node_kind
    from_node_role = edge.from_node_role
    if isinstance(from_node_role, str):
        topology_edge["from_node_role"] = from_node_role
    selector = thaw_json(edge.accepted_record_selector)
    if isinstance(selector, dict):
        topology_edge["accepted_record_selector"] = normalize_record_selector(selector)
    if source_contract is not None:
        topology_edge["source_port_contract"] = port_contract_summary(source_contract)
    if target_contract is not None:
        topology_edge["target_port_contract"] = port_contract_summary(target_contract)

    return topology_edge


def _edge_port_contracts(
    edge: EdgeValue,
    projection: GraphProjection,
) -> tuple[PortContract | None, PortContract | None]:
    from_node_id = edge.from_node_id
    to_node_id = edge.to_node_id
    from_port = edge.from_port
    to_port = edge.to_port
    source = projection.nodes[from_node_id] if from_node_id in projection.nodes else None
    source_kind = source.spec.kind if source is not None else None
    if source_kind is None and from_node_id == "*":
        raw_source_kind = edge.from_node_kind
        source_kind = raw_source_kind if isinstance(raw_source_kind, str) else None
    source_role = source.spec.role if source is not None else None
    if source_role is None and from_node_id == "*":
        raw_source_role = edge.from_node_role
        source_role = raw_source_role if isinstance(raw_source_role, str) else None
    target = projection.nodes[to_node_id] if to_node_id in projection.nodes else None
    target_kind = target.spec.kind if target is not None else None
    target_role = target.spec.role if target is not None else None
    source_contract = (
        DEFAULT_NODE_CONTRACTS.contract_for(source_kind, source_role)
        if source_kind is not None
        else None
    )
    target_contract = (
        DEFAULT_NODE_CONTRACTS.contract_for(target_kind, target_role)
        if target_kind is not None
        else None
    )
    source_port_contract = (
        output_port_contract(source_contract, from_port) if source_contract is not None else None
    )
    target_port_contract = (
        input_port_contract(target_contract, to_port) if target_contract is not None else None
    )
    return source_port_contract, target_port_contract


def _compatible_edge_record_types(
    source: PortContract | None,
    target: PortContract | None,
) -> list[str]:
    if source is None or target is None:
        return []
    return sorted(source.record_types & target.record_types)


def _binding_for_edge(
    projection: GraphProjection,
    edge: EdgeValue,
) -> InputBindingValue | None:
    edge_id = edge.edge_id
    to_node_id = edge.to_node_id
    to_port = edge.to_port
    ports = projection.topology.input_bindings.get(to_node_id)
    if ports is None:
        return None
    binding = ports[to_port] if to_port in ports else None
    if binding is not None and binding.edge_id in {None, edge_id}:
        return binding
    for ports in projection.topology.input_bindings.values():
        for binding in ports.values():
            if binding.edge_id == edge_id:
                return binding
    return None


def _topology_binding(
    binding: InputBindingValue,
    *,
    record_ids: list[str] | None = None,
    record_bound_position_ids: list[str] | None = None,
) -> GraphTopologyBinding:
    summary: GraphTopologyBinding = {
        "record_ids": _bound_record_ids(binding) if record_ids is None else record_ids,
    }
    for key in ("edge_id", "to_node_id", "to_port", "binding_policy", "trigger"):
        value = getattr(binding, key)
        if isinstance(value, str):
            summary[key] = value
    bound_at_position = binding.bound_at_position
    summary["bound_at_position"] = bound_at_position
    record_bound_positions = binding.record_bound_positions
    if record_bound_positions is not None:
        if record_bound_position_ids is None:
            summary["record_bound_positions"] = dict(record_bound_positions.items())
        else:
            summary["record_bound_positions"] = {
                record_id: record_bound_positions[record_id]
                for record_id in record_bound_position_ids
                if record_id in record_bound_positions
            }
    return summary


def _add_record_summary_positions(
    summaries: dict[str, GraphRecordSummary],
    events: list[EventEnvelope],
) -> None:
    for event in events:
        if event.event_type not in {"output_record_accepted", "file_state_accepted"}:
            continue
        record_id = event.payload.get("record_id")
        if not isinstance(record_id, str):
            continue
        summary = summaries.get(record_id)
        if summary is not None:
            summary["position"] = event.position


def project_pattern_library(events: list[EventEnvelope]) -> dict[str, Any]:
    """Project accepted gatekeeper verdicts into exact paths and derived globs.

    Learned patterns are scoped to untracked/ignored residue. The derived
    pattern rule is deterministic: ``dirname/*.ext`` when a non-root path has
    an extension, otherwise the exact path. Root-level files derive exact-path
    patterns only, never bare ``*.ext`` globs. Identical derived patterns merge
    and accumulate occurrence counts; exact paths are kept separately so the
    next boundary can classify both the same path and sibling files with the
    same directory-scoped shape.
    """
    patterns: dict[str, dict[str, Any]] = {}
    paths: dict[str, dict[str, Any]] = {}
    file_state_records: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.event_type == "file_state_accepted":
            record_id = event.payload.get("record_id")
            if isinstance(record_id, str):
                file_state_records[record_id] = event.payload
            continue
        if event.event_type != "gatekeeper_verdict_recorded":
            continue
        record_id = event.payload.get("file_state_record_id")
        verdicts = event.payload.get("verdicts")
        if not isinstance(verdicts, list):
            continue
        source_by_path = _file_state_source_by_path(file_state_records.get(str(record_id)))
        for raw_verdict in cast(list[Any], verdicts):
            if not isinstance(raw_verdict, dict):
                continue
            verdict = cast(dict[str, Any], raw_verdict)
            path = verdict.get("path")
            classification = verdict.get("classification")
            if not isinstance(path, str) or not isinstance(classification, str):
                continue
            source = source_by_path.get(path)
            if source not in {"untracked", "ignored"} or classification == "secret":
                continue
            pattern = _derive_gatekeeper_pattern(path)
            _merge_pattern_entry(
                patterns,
                pattern,
                classification,
                path,
                event.position,
                record_id,
            )
            paths[path] = {
                "path": path,
                "classification": classification,
                "matched_rule": f"pattern_library:{path}",
                "source_record_ids": [record_id] if isinstance(record_id, str) else [],
                "last_position": event.position,
                "source_kinds": ["untracked", "ignored"],
            }
    return {
        "patterns": {pattern: patterns[pattern] for pattern in sorted(patterns)},
        "paths": {path: paths[path] for path in sorted(paths)},
    }


def project_gatekeeper_report(events: list[EventEnvelope]) -> dict[str, dict[str, Any]]:
    """Project gatekeeper cost, hit-rate, and pattern-library growth per run."""
    reports: dict[str, dict[str, Any]] = {}
    prefixes: dict[str, list[EventEnvelope]] = {}
    for event in events:
        run = reports.setdefault(event.run_id, _empty_gatekeeper_report(event.run_id))
        prefixes.setdefault(event.run_id, []).append(event)
        if event.event_type == "file_state_accepted":
            classifications = _payload_entries(
                event.payload, "classifications"
            ) or _payload_entries(event.payload, "paths")
            deterministic = sum(
                1 for entry in classifications if entry.get("needs_gatekeeper") is not True
            )
            unresolved = sum(
                1 for entry in classifications if entry.get("needs_gatekeeper") is True
            )
            run["deterministic_classifications"] += deterministic
            run["unresolved_residue"] += unresolved
            run["boundary_count"] += 1
            library = project_pattern_library(prefixes[event.run_id])
            run["pattern_library_size_over_time"].append(
                {
                    "position": event.position,
                    "file_state_record_id": event.payload.get("record_id"),
                    "size": len(library["patterns"]),
                }
            )
        elif event.event_type == "gatekeeper_verdict_recorded":
            verdicts = event.payload.get("verdicts")
            resolved = len(cast(list[Any], verdicts)) if isinstance(verdicts, list) else 0
            run["gatekeeper_resolved"] += resolved
            run["unresolved_residue"] = max(0, int(run["unresolved_residue"]) - resolved)
            library = project_pattern_library(prefixes[event.run_id])
            run["pattern_library_size_over_time"].append(
                {
                    "position": event.position,
                    "file_state_record_id": event.payload.get("file_state_record_id"),
                    "size": len(library["patterns"]),
                }
            )
        elif event.event_type == "gatekeeper_cost_recorded":
            try:
                cost = GatekeeperCostRecordedPayload.model_validate(event.payload)
            except ValueError:
                continue
            cost_payload = cost.model_dump(mode="json")
            run["gatekeeper_consults"] += 1
            run["gen_ai_usage_input_tokens"] += cost.gen_ai_usage_input_tokens
            run["gen_ai_usage_output_tokens"] += cost.gen_ai_usage_output_tokens
            run["gen_ai_usage_cache_read_input_tokens"] += cost.gen_ai_usage_cache_read_input_tokens
            run["gen_ai_usage_cache_creation_input_tokens"] += (
                cost.gen_ai_usage_cache_creation_input_tokens
            )
            run["cost_usd"] += cost.cost_usd
            run["wall_time_ms"] += cost.wall_time_ms
            _record_model_cost(run, cost_payload)

    for run in reports.values():
        total_classified = int(run["deterministic_classifications"]) + int(
            run["gatekeeper_resolved"]
        )
        run["total_classified"] = total_classified
        run["hit_rate"] = (
            float(run["deterministic_classifications"]) / total_classified
            if total_classified
            else 0.0
        )
        run["pattern_library_size"] = (
            int(run["pattern_library_size_over_time"][-1]["size"])
            if run["pattern_library_size_over_time"]
            else 0
        )
    return reports


def _project(events: list[EventEnvelope]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


def build_projection(events: list[EventEnvelope]) -> GraphProjection:
    """Fold *events* into a full :class:`GraphProjection`.

    Public entry point for callers (e.g. read-model presenters) that need to
    fold the event stream once and pass the result into the various
    ``project_*`` view functions via their ``projection=`` argument, avoiding
    a full re-fold per view.
    """
    return _project(events)


def project_graph_projection_snapshot(
    events: list[EventEnvelope],
    *,
    projection: GraphProjection | None = None,
) -> GraphProjectionSnapshot:
    """Build the pure policy view consumed by graph-run drivers.

    ``projection`` may be a transactional materialization of an event prefix.
    Runtime callers may pass an empty event list when the durable checkpoint is
    current: all scheduling facts then come directly from the projection rather
    than forcing an unbounded second history read merely for diagnostic text.
    """
    projection = projection if projection is not None else build_projection(events)
    node_states = project_node_states(events, projection=projection)
    active_leases = {
        lease_id: _public_lease(lease)
        for lease_id, lease in projection.execution.leases.items()
        if lease.state == "active"
    }
    if events:
        failed_node_reasons = _project_failed_node_reasons(events)
        node_deferral_reasons = _project_node_deferral_reasons(events)
        missing_input_sources = _project_missing_input_sources(
            projection,
            node_deferral_reasons,
        )
    else:
        failed_node_reasons = {
            node_id: reason
            for node_id, node in projection.nodes.items()
            if node.runtime.state == "failed"
            and isinstance((reason := node.runtime.suspect_reason), str)
        }
        node_deferral_reasons = {
            node_id: reason
            for node_id, node in projection.nodes.items()
            if isinstance((reason := node.scheduling.last_deferred_reason), str)
        }
        missing_input_sources = _project_missing_input_sources(
            projection,
            node_deferral_reasons,
        )
    return GraphProjectionSnapshot(
        run_state=project_run_state(events, projection=projection),
        ready_nodes=project_ready_nodes(events, projection=projection),
        active_leases=active_leases,
        schedulable_nodes=[
            node_id
            for node_id, node in sorted(projection.nodes.items())
            if node.runtime.state in {"planned", "blocked", "ready"}
        ],
        task_states=project_task_states(events, projection=projection),
        node_states=node_states,
        failed_node_reasons=failed_node_reasons,
        node_deferral_reasons=node_deferral_reasons,
        missing_input_sources=missing_input_sources,
        environment_failures={
            task_region_id: EnvironmentFailureProjection.model_validate(
                failure.model_dump(mode="json")
            )
            for task_region_id, failure in projection.execution.environment_failures_by_task.items()
        },
        node_max_attempts=project_node_max_attempts(projection),
    )


def project_node_max_attempts(events: list[EventEnvelope] | GraphProjection) -> dict[str, int]:
    """Return effective finite executable retry budgets keyed by node id."""
    from orchestrator.graph.retry_policy import effective_node_max_attempts

    if isinstance(events, GraphProjection):
        return {
            node_id: effective
            for node_id, node in events.nodes.items()
            if (effective := effective_node_max_attempts(node.spec.kind, node.spec.max_attempts))
            is not None
        }
    max_attempts: dict[str, int] = {}
    for event in events:
        if event.event_type != "node_created":
            continue
        node_id = event.payload.get("node_id")
        if not isinstance(node_id, str) or node_id in max_attempts:
            continue
        effective = effective_node_max_attempts(
            event.payload.get("kind"), event.payload.get("max_attempts")
        )
        if effective is not None:
            max_attempts[node_id] = effective
    return max_attempts


def project_graph_completion_eligible(projection: GraphProjectionSnapshot) -> bool:
    return (
        projection.run_state == "active"
        and bool(projection.task_states)
        and all(state == "accepted" for state in projection.task_states.values())
    )


def project_graph_outcome(run_id: str, projection: GraphProjectionSnapshot) -> GraphRunOutcome:
    if projection.run_state == "completed":
        return GraphRunOutcome(run_id=run_id, run_state=projection.run_state, completed=True)
    return GraphRunOutcome(
        run_id=run_id,
        run_state=projection.run_state,
        completed=False,
        blocked_reason=project_graph_blocked_reason(projection),
    )


def project_graph_blocked_reason(projection: GraphProjectionSnapshot) -> str:
    if projection.run_state in {"paused", "pausing"}:
        return "graph paused"
    if projection.run_state in {"failed", "cancelled"}:
        return f"graph {projection.run_state}"
    if projection.run_state is None:
        return "graph has not started"
    if projection.ready_nodes:
        return f"graph has ready node(s) not dispatched: {', '.join(sorted(projection.ready_nodes)[:3])}"
    if projection.active_leases:
        leased_nodes = sorted(
            str(lease.get("node_id"))
            for lease in projection.active_leases.values()
            if lease.get("node_id") is not None
        )
        if leased_nodes:
            return f"graph has active lease(s) without callback: {', '.join(leased_nodes[:3])}"
    failed_nodes = sorted(
        node_id for node_id, state in projection.node_states.items() if state == "failed"
    )
    if failed_nodes:
        details = [
            f"{node_id}: {reason}"
            if (reason := projection.failed_node_reasons.get(node_id))
            else node_id
            for node_id in failed_nodes[:3]
        ]
        suffix = "" if len(failed_nodes) <= 3 else f" (+{len(failed_nodes) - 3} more)"
        return f"graph has failed node(s): {', '.join(details)}{suffix}"
    missing_input_nodes = _project_nonterminal_node_details(projection, require_missing_input=True)
    if missing_input_nodes:
        suffix = "" if len(missing_input_nodes) <= 3 else f" (+{len(missing_input_nodes) - 3} more)"
        return (
            "graph quiescent with non-terminal node(s): "
            + ", ".join(missing_input_nodes[:3])
            + suffix
        )
    nonterminal_nodes = _project_nonterminal_node_details(projection)
    if nonterminal_nodes:
        suffix = "" if len(nonterminal_nodes) <= 3 else f" (+{len(nonterminal_nodes) - 3} more)"
        return (
            f"graph quiescent with non-terminal node(s): {', '.join(nonterminal_nodes[:3])}{suffix}"
        )
    if projection.environment_failures:
        details: list[str] = []
        for task_region_id, failure in sorted(projection.environment_failures.items())[:3]:
            label = failure.classification or "environment"
            details.append(
                f"{task_region_id}: {label}: {failure.reason}"
                if failure.reason
                else f"{task_region_id}: {label}"
            )
        suffix = (
            ""
            if len(projection.environment_failures) <= 3
            else f" (+{len(projection.environment_failures) - 3} more)"
        )
        return f"graph needs human/operator help for check environment issue(s): {', '.join(details)}{suffix}"
    blocked_tasks = sorted(
        f"{task_id}={state}"
        for task_id, state in projection.task_states.items()
        if state != "accepted"
    )
    if blocked_tasks:
        suffix = "" if len(blocked_tasks) <= 3 else f" (+{len(blocked_tasks) - 3} more)"
        return f"graph quiescent with non-accepted task(s): {', '.join(blocked_tasks[:3])}{suffix}"
    return "graph quiescent without completion"


def project_active_lease_wait_plan(
    projection: GraphProjectionSnapshot,
    now: datetime,
    *,
    renewal_lead_seconds: float = 0.0,
) -> ActiveLeaseWaitPlan:
    """Plan a bounded executor wait before the next lease maintenance pass.

    ``renewal_lead_seconds`` lets the driver wake before the kernel expiry
    sweep can revoke a still-running execution.  It is intentionally supplied
    by driver policy rather than embedded in the projection layer.
    """
    renewal_lead_seconds = max(0.0, renewal_lead_seconds)
    execution_ids: set[str] = set()
    timeouts: list[float] = []
    for lease in projection.active_leases.values():
        execution_id = lease.get("execution_id")
        if isinstance(execution_id, str) and execution_id:
            execution_ids.add(execution_id)
        expires_at = lease.get("expires_at")
        if not isinstance(expires_at, str):
            continue
        try:
            expires_at_dt = datetime.fromisoformat(expires_at)
        except ValueError:
            continue
        if expires_at_dt.tzinfo is None:
            expires_at_dt = expires_at_dt.replace(tzinfo=UTC)
        timeouts.append(max(0.0, (expires_at_dt - now).total_seconds() - renewal_lead_seconds))
    if not execution_ids:
        return ActiveLeaseWaitPlan(execution_ids=set(), timeout_seconds=0.0)
    if not timeouts:
        return ActiveLeaseWaitPlan(execution_ids=execution_ids, timeout_seconds=None)
    return ActiveLeaseWaitPlan(execution_ids=execution_ids, timeout_seconds=min(timeouts))


def _project_failed_node_reasons(events: list[EventEnvelope]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for event in events:
        node_id = event.payload.get("node_id")
        if not isinstance(node_id, str):
            continue
        if event.event_type == "agent_died":
            reason = event.payload.get("reason")
        elif (
            event.event_type == "node_state_changed" and event.payload.get("new_state") == "failed"
        ):
            reason = event.payload.get("reason")
        else:
            continue
        if isinstance(reason, str):
            reasons[node_id] = reason
    return reasons


def _project_node_deferral_reasons(events: list[EventEnvelope]) -> dict[str, str]:
    return {
        node_id: reason
        for event in events
        if event.event_type == "node_deferred"
        and isinstance((node_id := event.payload.get("node_id")), str)
        and isinstance((reason := event.payload.get("reason")), str)
    }


def _project_missing_input_sources(
    projection: GraphProjection,
    node_deferral_reasons: dict[str, str],
) -> dict[str, list[str]]:
    details: dict[str, list[str]] = {}
    for node_id, reason in node_deferral_reasons.items():
        if not reason.startswith("missing_required_input:"):
            continue
        missing_port = reason.removeprefix("missing_required_input:")
        sources = sorted(
            f"{missing_port} from {edge.from_node_id}={_node_state_or_unknown(projection, edge.from_node_id)}"
            for edge in projection.topology.edges.values()
            if edge.to_node_id == node_id and edge.to_port == missing_port
        )
        if sources:
            details[node_id] = sources
    return details


def _project_nonterminal_node_details(
    projection: GraphProjectionSnapshot, *, require_missing_input: bool = False
) -> list[str]:
    details: list[str] = []
    for node_id, state in projection.node_states.items():
        if state in TERMINAL_GRAPH_NODE_STATES:
            continue
        reason = projection.node_deferral_reasons.get(node_id)
        if require_missing_input and not (
            isinstance(reason, str) and reason.startswith("missing_required_input:")
        ):
            continue
        detail = f"{node_id}={state}"
        if reason is not None:
            detail = f"{detail}: {reason}"
        if sources := projection.missing_input_sources.get(node_id):
            detail = f"{detail} ({'; '.join(sources[:3])})"
        details.append(detail)
    return sorted(details)


def _has_full_event_history(events: list[EventEnvelope]) -> bool:
    return bool(events) and events[0].position <= 1


_PENDING_DECISION_STATES = {"planned", "blocked", "ready", "leased", "running", "suspended"}


def _callback_idempotency_projection_key(node_id: str, idempotency_key: str) -> str:
    return f"{node_id}\0{idempotency_key}"


def _scheduler_bucket_for_reason(
    reason: str,
) -> Literal["blocked", "waiting_resources", "waiting_gates"]:
    if reason.startswith("resource_") or reason.startswith("invalid_claim:"):
        return "waiting_resources"
    if (
        reason.startswith("gate_")
        or reason.startswith("waiting_gate")
        or reason.startswith("authority_")
    ):
        return "waiting_gates"
    return "blocked"


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _latest_lease_generation_from_projection(
    projection: GraphProjection, node_id: str
) -> int | None:
    generations = [
        lease.generation
        for lease in projection.execution.leases.values()
        if lease.node_id == node_id and lease.generation is not None
    ]
    return max(generations) if generations else None


def _node_state_or_unknown(projection: GraphProjection, node_id: str) -> str:
    if node_id not in projection.nodes:
        return "unknown"
    return projection.nodes[node_id].runtime.state or "unknown"


def _node_creation_payload_from_node(node: NodeProjection) -> NodeCreationProjection:
    return NodeCreationProjection(
        node_id=node.spec.node_id,
        position=node.spec.creation_position,
        kind=node.spec.kind,
        role=node.spec.role,
        state=node.runtime.state,
        task_region_id=node.spec.task_region_id,
        attempt_number=node.runtime.attempt_number,
        candidate_id=node.runtime.candidate_id,
        failed_candidate_id=node.runtime.failed_candidate_id,
        resource_claims=[
            ResourceClaimProjection.model_validate(claim.model_dump(mode="json"))
            for claim in node.spec.resource_claims
        ],
        allowed_actions=list(node.spec.allowed_actions),
        preconditions=list(node.spec.preconditions),
        gate_type=node.spec.gate_type,
        approval_type=node.spec.approval_type,
        reason=node.spec.reason,
        prompt=node.spec.prompt,
        approval_prompt=node.spec.approval_prompt,
        human_prompt=node.spec.human_prompt,
        message=node.spec.message,
        blocker=node.spec.blocker,
        blocker_reason=node.spec.blocker_reason,
        decision_request=(
            node.spec.decision_request.model_dump(mode="json")
            if node.spec.decision_request is not None
            else None
        ),
        authority_request_record_id=node.spec.authority_request_record_id,
        authority_request=(
            node.spec.authority_request.model_dump(mode="json")
            if node.spec.authority_request is not None
            else None
        ),
    )


def _oversight_decision_for_node(
    projection: GraphProjection, node_id: str
) -> OversightDecisionProjection | None:
    if node_id not in projection.governance.oversight_decision_id_by_node:
        return None
    decision_id = projection.governance.oversight_decision_id_by_node[node_id]
    if decision_id not in projection.governance.oversight_decisions_by_id:
        return None
    return OversightDecisionProjection.model_validate(
        projection.governance.oversight_decisions_by_id[decision_id].model_dump(mode="json")
    )


def _request_details_for_pending_gate(
    node_id: str,
    node: NodeProjection,
    projection: GraphProjection,
) -> PendingGateDecision:
    request = projection.governance.decision_requests_by_node.get(node_id)
    if request is not None:
        return _pending_gate_request_details(request)
    if node.spec.decision_request is not None:
        return _pending_gate_request_details(node.spec.decision_request)
    authority_request_record_id = node.spec.authority_request_record_id
    if authority_request_record_id is not None:
        record = projection.records.by_id.get(authority_request_record_id)
        if isinstance(record, AuthorityRequestRecord):
            return _pending_gate_request_details(record.value)
    if node.spec.authority_request is not None:
        return _pending_gate_request_details(node.spec.authority_request)
    return {}


def _pending_gate_request_details(request: object) -> PendingGateDecision:
    details: PendingGateDecision = {}
    options = getattr(request, "options", ())
    if isinstance(options, tuple) and options:
        details["options"] = [
            option for option in cast(tuple[object, ...], options) if isinstance(option, str)
        ]
    requested_authority = getattr(request, "requested_authority", ())
    if isinstance(requested_authority, tuple) and requested_authority:
        details["requested_authority"] = [
            authority
            for authority in cast(tuple[object, ...], requested_authority)
            if isinstance(authority, str)
        ]
    for field in (
        "default_option",
        "consequence_summary",
        "expires_at",
        "target_node_id",
        "target_region_id",
    ):
        value = getattr(request, field, None)
        if isinstance(value, str) and value:
            details[field] = value
    return details


def _gate_type(node: NodeProjection) -> str:
    for value in (
        node.spec.gate_type,
        node.spec.approval_type,
        node.spec.reason,
        node.spec.role,
    ):
        if isinstance(value, str) and value:
            return value
    return "approval"


def _gate_prompt(node: NodeProjection) -> str | None:
    for value in (
        node.spec.prompt,
        node.spec.approval_prompt,
        node.spec.human_prompt,
        node.spec.message,
        node.spec.reason,
    ):
        if isinstance(value, str) and value:
            return value
    return None


def _decision_outcome(decision: OversightDecisionProjection | None) -> str | None:
    return decision.decision if decision is not None else None


def _review_blocker(
    node_id: str,
    state: str,
    node: NodeProjection,
    latest_deferrals: dict[str, str],
) -> str:
    for value in (node.spec.blocker, node.spec.blocker_reason, node.spec.reason):
        if isinstance(value, str) and value:
            return f"{node_id}: {value}"
    reason = latest_deferrals.get(node_id)
    return f"{node_id}: {reason if reason is not None else state}"


def _planner_region_label(
    events: list[EventEnvelope],
    projection: GraphProjection,
    node_id: str,
) -> str | None:
    if node_id in projection.planning.region_label_by_node:
        return projection.planning.region_label_by_node[node_id]
    generation_index = projection.planning.generation_by_node.get(node_id)
    if generation_index is None:
        return None
    for event in events:
        if event.event_type != "node_created":
            continue
        payload = NodeCreatedPayload.model_validate(event.payload)
        if payload.planner_chain is None:
            continue
        for region in payload.planner_chain.regions:
            if region.generation_index == generation_index:
                return region.region_label
    return None


def _authority_decision_revision_id(payload: AuthorityDecisionRecordedPayload) -> str | None:
    scope_value: object = payload.scope
    if isinstance(scope_value, dict):
        scope = cast(dict[str, Any], scope_value)
        for key in ("revision_id", "requirement_version_id", "version_id"):
            value = scope.get(key)
            if isinstance(value, str) and value:
                return value
    return payload.record_id


def _support_stale_reason(
    projection: GraphProjection,
    support: SupportEvidenceValue,
) -> str | None:
    status = support.status
    if status != "active":
        return support.stale_reason or f"support edge status is {status}"

    active_version_id = projection.requirements.active_version_id_by_requirement.get(
        support.requirement_id
    )
    if active_version_id is None:
        return "requirement has no active version"
    if support.requirement_version_id != active_version_id:
        return "support edge targets a superseded requirement version"
    return None


def _requirement_revision_classification(payload: dict[str, Any]) -> str:
    for key in ("change_classification", "classification", "revision_type"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    if payload.get("validation_strengthening") is True:
        return "validation_strengthening"
    if payload.get("new_behavior") is True:
        return "new_behavior"
    if payload.get("semantic_change") is True:
        return "semantic"
    return "initial"


def _requires_explicit_requirement_authority(
    payload: dict[str, Any],
    classification: str,
) -> bool:
    if payload.get("requires_authority") is True:
        return True
    if payload.get("explicit_authority_required") is True:
        return True
    if payload.get("new_behavior") is True or payload.get("behavior_change") is True:
        return True
    return classification in {
        "semantic",
        "semantic_change",
        "new_behavior",
        "scope_expansion",
        "scope_reduction",
        "priority_change",
    }


def _authority_required_reason(payload: dict[str, Any], classification: str) -> str | None:
    reason = payload.get("authority_required_reason")
    if isinstance(reason, str) and reason:
        return reason
    if not _requires_explicit_requirement_authority(payload, classification):
        return None
    if payload.get("new_behavior") is True or classification in {"new_behavior", "scope_expansion"}:
        return "new_behavior"
    if payload.get("behavior_change") is True:
        return "behavior_change"
    return classification


def _environment_failure_reason_from_check_value(value: dict[str, Any]) -> str:
    classification = value.get("classification")
    command_text = value.get("command_text")
    command_label = (
        command_text if isinstance(command_text, str) and command_text else "check command"
    )
    stderr = value.get("stderr_tail")
    if classification == "tool_unavailable":
        return f"check tool unavailable while running: {command_label}"
    if classification == "tool_error":
        return f"check tool error while running: {command_label}"
    if classification == "environment_error":
        return f"check environment setup failed while running: {command_label}"
    if isinstance(stderr, str) and stderr.strip():
        return stderr.strip().splitlines()[0]
    return "check failed because of the execution environment"


def _resolved_file_entry(
    raw_entry: FileEntry | ExternalFileEntry,
    verdicts_by_path: dict[str, dict[str, Any]],
) -> FileEntry | ExternalFileEntry:
    entry = _file_entry_dict(raw_entry)
    path = entry.get("path")
    if not isinstance(path, str) or path not in verdicts_by_path:
        return raw_entry
    verdict = verdicts_by_path[path]
    entry["classification"] = verdict.get("classification")
    entry["matched_rule"] = f"gatekeeper:{verdict.get('model_id', 'unknown')}"
    entry["needs_gatekeeper"] = False
    entry["gatekeeper_confidence"] = verdict.get("confidence")
    entry["gatekeeper_rationale"] = verdict.get("rationale")
    if isinstance(raw_entry, ExternalFileEntry):
        return ExternalFileEntry.model_validate(entry)
    return FileEntry.model_validate(entry)


def _file_entry_dict(
    entry: FileEntry | ExternalFileEntry,
) -> dict[str, Any]:
    return entry.model_dump(mode="json")


def _derive_gatekeeper_pattern(path: str) -> str:
    normalized = path.replace("\\", "/").strip("/")
    dirname, _, filename = normalized.rpartition("/")
    if not dirname:
        return filename
    stem, dot, extension = filename.rpartition(".")
    if dot and stem:
        glob = f"*.{extension}"
    else:
        glob = filename
    return f"{dirname}/{glob}"


def _merge_pattern_entry(
    patterns: dict[str, dict[str, Any]],
    pattern: str,
    classification: str,
    path: str,
    position: int,
    record_id: Any,
) -> None:
    entry = patterns.get(pattern)
    if entry is None:
        patterns[pattern] = {
            "pattern": pattern,
            "classification": classification,
            "occurrences": 1,
            "paths": [path],
            "source_record_ids": [record_id] if isinstance(record_id, str) else [],
            "source_kinds": ["untracked", "ignored"],
            "first_position": position,
            "last_position": position,
        }
        return
    entry["occurrences"] = int(entry["occurrences"]) + 1
    entry["last_position"] = position
    if path not in entry["paths"]:
        entry["paths"].append(path)
        entry["paths"].sort()
    if isinstance(record_id, str) and record_id not in entry["source_record_ids"]:
        entry["source_record_ids"].append(record_id)


def _file_state_source_by_path(record: dict[str, Any] | FileStateRecord | None) -> dict[str, str]:
    if record is None:
        return {}
    sources: dict[str, str] = {}
    if isinstance(record, FileStateRecord):
        entry_groups: tuple[list[FileEntry], list[FileEntry]] = (
            record.residue,
            record.classifications,
        )
        for entries in entry_groups:
            for raw_entry in entries:
                entry = _file_entry_dict(raw_entry)
                path = entry.get("path")
                source = entry.get("source")
                if isinstance(path, str) and isinstance(source, str):
                    sources[path] = source
        return sources

    for key in ("paths", "residue", "classifications"):
        raw_entries = record.get(key)
        if not isinstance(raw_entries, list):
            continue
        for raw_entry in cast(list[Any], raw_entries):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, Any], raw_entry)
            path = entry.get("path")
            source = entry.get("source")
            if isinstance(path, str) and isinstance(source, str):
                sources[path] = source
    return sources


def _payload_entries(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [
        dict(cast(dict[str, Any], entry))
        for entry in cast(list[Any], value)
        if isinstance(entry, dict)
    ]


def _payload_number(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return int(value)
    return 0


def _payload_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _empty_gatekeeper_report(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "boundary_count": 0,
        "deterministic_classifications": 0,
        "gatekeeper_consults": 0,
        "gatekeeper_resolved": 0,
        "unresolved_residue": 0,
        "total_classified": 0,
        "hit_rate": 0.0,
        "pattern_library_size": 0,
        "pattern_library_size_over_time": [],
        "gen_ai_usage_input_tokens": 0,
        "gen_ai_usage_output_tokens": 0,
        "gen_ai_usage_cache_read_input_tokens": 0,
        "gen_ai_usage_cache_creation_input_tokens": 0,
        "cost_usd": 0.0,
        "wall_time_ms": 0,
        "models": {},
    }


def _record_model_cost(run: dict[str, Any], payload: dict[str, Any]) -> None:
    model_id = payload.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        model_id = "unknown"
    models = cast(dict[str, dict[str, Any]], run["models"])
    model = models.setdefault(
        model_id,
        {
            "model_id": model_id,
            "consults": 0,
            "gen_ai_usage_input_tokens": 0,
            "gen_ai_usage_output_tokens": 0,
            "gen_ai_usage_cache_read_input_tokens": 0,
            "gen_ai_usage_cache_creation_input_tokens": 0,
            "cost_usd": 0.0,
            "wall_time_ms": 0,
            "executions": [],
        },
    )
    model["consults"] += 1
    model["gen_ai_usage_input_tokens"] += _payload_number(payload, "gen_ai_usage_input_tokens")
    model["gen_ai_usage_output_tokens"] += _payload_number(payload, "gen_ai_usage_output_tokens")
    model["gen_ai_usage_cache_read_input_tokens"] += _payload_number(
        payload, "gen_ai_usage_cache_read_input_tokens"
    )
    model["gen_ai_usage_cache_creation_input_tokens"] += _payload_number(
        payload, "gen_ai_usage_cache_creation_input_tokens"
    )
    model["cost_usd"] += _payload_float(payload, "cost_usd")
    model["wall_time_ms"] += _payload_number(payload, "wall_time_ms")
    execution_id = payload.get("execution_id")
    if isinstance(execution_id, str) and execution_id not in model["executions"]:
        model["executions"].append(execution_id)


def _derive_task_states(state: GraphProjection) -> dict[str, str]:
    task_region_ids = set(state.tasks)
    task_region_ids.update(state.verification.invalid_test_blocks_by_task)
    task_region_ids.update(state.governance.configured_gates_by_task)
    task_region_ids.update(state.governance.gate_decisions_by_task)
    task_region_ids.update(state.execution.environment_failures_by_task)
    task_region_ids.update(
        lease.task_region_id
        for lease in state.execution.leases.values()
        if lease.task_region_id is not None
    )
    task_region_ids.update(
        node.spec.task_region_id
        for node in state.nodes.values()
        if node.spec.task_region_id is not None
    )

    task_states: dict[str, str] = {}
    for task_region_id in sorted(task_region_ids):
        if _semantic_plan_region_accepted(state, task_region_id):
            task_states[task_region_id] = "accepted"
            continue
        task = state.tasks.get(task_region_id)
        latest_candidate = _latest_candidate(task.candidates if task is not None else ())
        if latest_candidate is None:
            task_states[task_region_id] = _derive_candidate_free_region_state(
                state,
                task_region_id,
            )
            continue

        candidate_id = latest_candidate.candidate_id
        configured_gates = state.governance.configured_gates_by_task.get(
            task_region_id, FrozenMap()
        )
        gate_decisions = state.governance.gate_decisions_by_task.get(task_region_id, FrozenMap())
        gates_passed = _all_configured_gates_passed(configured_gates, gate_decisions)
        invalid_block = state.verification.invalid_test_blocks_by_task.get(task_region_id)

        verifier_passed = _verifier_requirement_passed(state, task_region_id, candidate_id)
        verdict = _verifier_verdict_for_candidate(state, candidate_id)
        file_state_accepted = _task_file_state_accepted(state, task_region_id, candidate_id)
        checks_passed = _required_checks_passed(state, task_region_id)
        verifier_failure_superseded = _failed_verification_recovery_superseded(
            state,
            task_region_id,
            candidate_id,
        )

        if verifier_passed and gates_passed and file_state_accepted and checks_passed:
            task_states[task_region_id] = "accepted"
        elif (
            invalid_block is not None
            and invalid_block.accepted is True
            and not _replacement_verification_passed(state, task_region_id, invalid_block)
        ):
            task_states[task_region_id] = "blocked_invalid_test"
        elif (
            verdict is not None
            and verdict.verdict == "failed"
            and not verifier_failure_superseded
            and not _active_invalid_test_override(invalid_block, candidate_id)
        ):
            task_states[task_region_id] = "needs_revision"
        elif task_region_id in state.execution.environment_failures_by_task:
            task_states[task_region_id] = "blocked_environment"
        elif _has_active_task_lease(state, task_region_id):
            task_states[task_region_id] = "in_progress"
        else:
            task_states[task_region_id] = "pending"

    _apply_accepted_region_supersessions(state, task_states)
    return task_states


def _semantic_plan_region_accepted(
    state: GraphProjection,
    task_region_id: str,
) -> bool:
    """Accept both a passed plan verifier region and its semantic producer region."""
    passed_plan_verifier_ids = {
        node_id
        for node_id, node in state.nodes.items()
        if node.spec.dispatch_payload.get("semantic_stage") == "plan_verification"
        and node.runtime.state == "completed"
        and (verdict := state.verification.verdicts_by_node.get(node_id)) is not None
        and verdict.verdict == "passed"
    }
    if any(
        state.nodes[node_id].spec.task_region_id == task_region_id
        for node_id in passed_plan_verifier_ids
    ):
        return True
    semantic_plan_record_ids = {
        record_id
        for record_id, record in state.records.by_id.items()
        if isinstance(record, SemanticArtifactRecord)
        and record.value.semantic_role == "implementation_plan"
        and (producer := state.nodes.get(record.producer_node_id)) is not None
        and producer.spec.task_region_id == task_region_id
    }
    return any(
        any(record_id in semantic_plan_record_ids for record_id in binding.record_ids)
        for verifier_node_id in passed_plan_verifier_ids
        if (
            binding := state.topology.input_bindings.get(verifier_node_id, FrozenMap()).get(
                "semantic_artifact"
            )
        )
        is not None
    )


def _apply_accepted_region_supersessions(
    state: GraphProjection,
    task_states: dict[str, str],
) -> None:
    for task_region_id, task in sorted(state.tasks.items()):
        if task_states.get(task_region_id) != "accepted":
            continue
        latest_candidate = _latest_candidate(task.candidates)
        if latest_candidate is None:
            continue
        for superseded_region_id in latest_candidate.supersedes_task_region_ids:
            if task_states.get(superseded_region_id) in {"needs_revision", "pending"}:
                task_states[superseded_region_id] = "accepted"


def _derive_candidate_free_region_state(
    state: GraphProjection,
    task_region_id: str,
) -> str:
    if _has_active_task_lease(state, task_region_id):
        return "in_progress"
    node_ids = _task_region_node_ids(state, task_region_id)
    active_node_ids = [
        node_id
        for node_id in node_ids
        if state.nodes[node_id].runtime.state not in {"retired", "cancelled"}
    ]
    if node_ids and not active_node_ids:
        return "accepted"
    task_contributing_node_ids = [
        node_id
        for node_id in active_node_ids
        if _contract_fulfillment_contribution(state, node_id) == "task_acceptance"
    ]
    contributing_node_ids = task_contributing_node_ids or [
        node_id
        for node_id in active_node_ids
        if _contract_fulfillment_contribution(state, node_id) == "final_invariant"
    ]
    if not contributing_node_ids:
        return "pending"
    if all(_node_contract_fulfilled(state, node_id) for node_id in contributing_node_ids):
        return "accepted"
    return "pending"


def _task_region_node_ids(state: GraphProjection, task_region_id: str) -> list[str]:
    return [
        node_id
        for node_id, node in sorted(state.nodes.items())
        if node.spec.task_region_id == task_region_id
    ]


def _grouped_contract_for_node(state: GraphProjection, node_id: str) -> Any | None:
    if node_id not in state.nodes:
        return None
    node = state.nodes[node_id]
    if node.spec.kind is None:
        return None
    return DEFAULT_NODE_CONTRACTS.contract_for(node.spec.kind, node.spec.role)


def _contract_fulfillment_contribution(state: GraphProjection, node_id: str) -> str:
    contract = _grouped_contract_for_node(state, node_id)
    if contract is None:
        return "none"
    return contract.fulfillment_contribution


def _node_contract_fulfilled(state: GraphProjection, node_id: str) -> bool:
    node = state.nodes.get(node_id)
    node_state = node.runtime.state if node is not None else None
    if node_state != "completed":
        return False
    missing_ports = _grouped_missing_fulfillment_ports(state, node_id)
    if missing_ports:
        return False
    contract = _grouped_contract_for_node(state, node_id)
    if contract is None:
        return False
    if contract.fulfillment_contribution == "final_invariant":
        return _final_invariant_node_passed(state, node_id)
    return True


def _grouped_missing_fulfillment_ports(state: GraphProjection, node_id: str) -> list[str]:
    contract = _grouped_contract_for_node(state, node_id)
    if contract is None:
        return []
    ports = state.records.ids_by_node_port.get(node_id)
    if ports is None:
        return sorted(contract.fulfillment_required_outputs)
    return [
        port
        for port in sorted(contract.fulfillment_required_outputs)
        if port not in ports or not ports[port]
    ]


# Legacy reducer-tail helpers remain until the dedicated deletion pass.  They
# operate on the transient derivation dictionary, never on GraphProjection.


def _final_invariant_node_passed(state: GraphProjection, node_id: str) -> bool:
    contract = _grouped_contract_for_node(state, node_id)
    if contract is None:
        return False
    if "check_result" in contract.fulfillment_required_outputs:
        result = state.verification.check_results_by_node.get(node_id)
        return result is not None and result.status in {"passed", "pass", "ok"}
    if "completion_decision" in contract.fulfillment_required_outputs:
        ports = state.records.ids_by_node_port.get(node_id, FrozenMap())
        return "completion_decision" in ports and bool(ports["completion_decision"])
    return True


def _verifier_requirement_passed(
    state: GraphProjection,
    task_region_id: str,
    candidate_id: str,
) -> bool:
    verdict = _verifier_verdict_for_candidate(state, candidate_id)
    if verdict is not None:
        if verdict.verdict == "failed" and _failed_verification_recovery_superseded(
            state,
            task_region_id,
            candidate_id,
        ):
            return True
        return verdict.verdict == "passed"

    return not any(
        node.spec.kind == "verifier"
        and node.spec.task_region_id == task_region_id
        and node.runtime.state not in {"retired", "cancelled"}
        for node in state.nodes.values()
    )


def _task_file_state_accepted(
    state: GraphProjection,
    task_region_id: str,
    candidate_id: str,
) -> bool:
    for record in state.records.by_id.values():
        if not isinstance(record, FileStateRecord):
            continue
        record_region_id = record.task_region_id
        if not isinstance(record_region_id, str):
            producer_node_id = record.producer_node_id
            if isinstance(producer_node_id, str):
                producer = (
                    state.nodes[producer_node_id] if producer_node_id in state.nodes else None
                )
                record_region_id = producer.spec.task_region_id if producer is not None else None
        if record_region_id != task_region_id:
            continue
        record_candidate_id = record.candidate_id
        if isinstance(record_candidate_id, str) and record_candidate_id != candidate_id:
            continue
        verdict = record.verdict
        if verdict in {"rejected", "failed"}:
            continue
        return True
    return False


def _required_checks_passed(state: GraphProjection, task_region_id: str) -> bool:
    task = state.tasks[task_region_id] if task_region_id in state.tasks else None
    latest_candidate = _latest_candidate(task.candidates) if task is not None else None
    check_node_ids = [
        node_id
        for node_id, node in state.nodes.items()
        if node.spec.kind == "check"
        and node.spec.task_region_id == task_region_id
        and node.runtime.state not in {"retired", "cancelled"}
    ]
    if not check_node_ids:
        return True
    for node_id in check_node_ids:
        result = (
            state.verification.check_results_by_node[node_id]
            if node_id in state.verification.check_results_by_node
            else None
        )
        if result is None:
            return False
        status = result.status
        if status not in {"passed", "pass", "ok"} and _check_result_recovery_superseded(
            state,
            result,
        ):
            continue
        if status not in {"passed", "pass", "ok"}:
            return False
        if latest_candidate is not None and not _check_result_cites_latest_candidate(
            result,
            latest_candidate,
        ):
            return False
    return True


def _check_result_cites_latest_candidate(
    result: CheckResultValue,
    latest_candidate: CandidateValue,
) -> bool:
    candidate_id = latest_candidate.candidate_id
    candidate_record_ids = result.candidate_record_ids
    if candidate_id not in candidate_record_ids:
        return False

    expected_file_state_ids = latest_candidate.file_state_record_ids
    if not expected_file_state_ids:
        return True
    cited_file_state_ids = set(result.file_state_record_ids)
    return all(record_id in cited_file_state_ids for record_id in expected_file_state_ids)


def _check_result_recovery_superseded(
    state: GraphProjection,
    check_result: CheckResultValue | dict[str, Any],
) -> bool:
    record_id = (
        check_result.record_id
        if isinstance(check_result, CheckResultValue)
        else check_result.get("record_id")
    )
    if not isinstance(record_id, str) or not record_id:
        return False
    task_region_id = (
        check_result.task_region_id
        if isinstance(check_result, CheckResultValue)
        else check_result.get("task_region_id")
    )
    candidate_id = (
        (check_result.candidate_record_ids[0] if check_result.candidate_record_ids else None)
        if isinstance(check_result, CheckResultValue)
        else check_result.get("candidate_id")
    )
    if (
        isinstance(task_region_id, str)
        and isinstance(candidate_id, str)
        and _accepted_candidate_supersedes_region(state, task_region_id)
    ):
        task = state.tasks.get(task_region_id)
        latest = _latest_candidate(task.candidates) if task is not None else None
        if latest is not None and latest.candidate_id == candidate_id:
            return True
    recoveries = (
        state.verification.recovery_nodes_by_record_id[record_id]
        if record_id in state.verification.recovery_nodes_by_record_id
        else ()
    )
    for recovery in recoveries:
        if _recovery_lineage_passed(state, recovery.node_id):
            return True
    return False


def _failed_verification_recovery_superseded(
    state: GraphProjection,
    task_region_id: str,
    candidate_id: str,
) -> bool:
    if _accepted_candidate_supersedes_region(state, task_region_id):
        task = state.tasks.get(task_region_id)
        latest = _latest_candidate(task.candidates) if task is not None else None
        if latest is not None and latest.candidate_id == candidate_id:
            return True
    for verification in state.verification.failed_results_by_record_id.values():
        if verification.candidate_id != candidate_id:
            continue
        if verification.task_region_id != task_region_id:
            continue
        record_id = verification.record_id
        if not record_id:
            continue
        recoveries = (
            state.verification.recovery_nodes_by_record_id[record_id]
            if record_id in state.verification.recovery_nodes_by_record_id
            else ()
        )
        for recovery in recoveries:
            if _recovery_lineage_has_complete_verification(state, recovery.node_id):
                return True
    return False


def _accepted_candidate_supersedes_region(
    state: GraphProjection,
    superseded_region_id: str,
) -> bool:
    """Require the superseding candidate's own region to pass every direct gate."""
    for task_region_id, task in state.tasks.items():
        if task_region_id == superseded_region_id:
            continue
        candidate = _latest_candidate(task.candidates)
        if candidate is None or superseded_region_id not in candidate.supersedes_task_region_ids:
            continue
        if task.state == "accepted":
            return True
        verdict = _verifier_verdict_for_candidate(state, candidate.candidate_id)
        if verdict is None or verdict.verdict != "passed":
            continue
        configured = state.governance.configured_gates_by_task.get(task_region_id, FrozenMap())
        decisions = state.governance.gate_decisions_by_task.get(task_region_id, FrozenMap())
        if not _all_configured_gates_passed(configured, decisions):
            continue
        if not _task_file_state_accepted(state, task_region_id, candidate.candidate_id):
            continue
        if not _required_checks_passed(state, task_region_id):
            continue
        return True
    return False


def _recovery_lineage_has_complete_verification(
    state: GraphProjection,
    recovery_node_id: str,
) -> bool:
    reachable = _downstream_node_ids(state, recovery_node_id)
    if not reachable:
        return False
    for verification in state.verification.passed_results_by_record_id.values():
        verifier_node_id = verification.node_id
        if verifier_node_id not in reachable:
            continue
        candidate_id = verification.candidate_id
        if not isinstance(candidate_id, str) or not candidate_id:
            continue
        verdict = _verifier_verdict_for_candidate(state, candidate_id)
        if verdict is not None and verdict.verdict != "passed":
            continue
        task_region_id = verification.task_region_id
        if not isinstance(task_region_id, str):
            verifier = state.nodes.get(verifier_node_id)
            task_region_id = verifier.spec.task_region_id if verifier is not None else None
        if not isinstance(task_region_id, str) or not task_region_id:
            continue
        configured_gates = state.governance.configured_gates_by_task.get(
            task_region_id, FrozenMap()
        )
        gate_decisions = state.governance.gate_decisions_by_task.get(task_region_id, FrozenMap())
        if not _all_configured_gates_passed(configured_gates, gate_decisions):
            continue
        if not _task_file_state_accepted(state, task_region_id, candidate_id):
            continue
        if not _required_checks_passed(state, task_region_id):
            continue
        return True
    return False


def _recovery_lineage_passed(state: GraphProjection, recovery_node_id: str) -> bool:
    reachable = _downstream_node_ids(state, recovery_node_id)
    if not reachable:
        return False
    for verification in state.verification.passed_results_by_record_id.values():
        if verification.node_id not in reachable:
            continue
        candidate_id = verification.candidate_id
        verdict = _verifier_verdict_for_candidate(state, candidate_id or "")
        if verdict is None or verdict.verdict == "passed":
            return True
    for check_node_id, result in state.verification.check_results_by_node.items():
        if check_node_id not in reachable:
            continue
        if result.status in {"passed", "pass", "ok"}:
            return True
    return False


def _downstream_node_ids(state: GraphProjection, start_node_id: str) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for edge in state.topology.edges.values():
        source = edge.from_node_id
        target = edge.to_node_id
        adjacency.setdefault(source, set()).add(target)
    seen: set[str] = set()
    frontier = [start_node_id]
    while frontier:
        node_id = frontier.pop()
        for neighbor in adjacency.get(node_id, set()):
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append(neighbor)
    return seen


def _latest_candidate(candidates: tuple[CandidateValue, ...]) -> CandidateValue | None:
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate.attempt_number, candidate.position))


def _verifier_verdict_for_candidate(
    state: GraphProjection, candidate_id: str
) -> VerifierVerdictValue | None:
    """Resolve duplicate candidate verdicts in a stable event-position/node-id order."""
    matching = (
        (node_id, verdict)
        for node_id, verdict in state.verification.verdicts_by_node.items()
        if verdict.candidate_id == candidate_id
    )
    try:
        return max(matching, key=lambda item: (item[1].position, item[0]))[1]
    except ValueError:
        if candidate_id in state.verification.failed_candidate_ids:
            return VerifierVerdictValue(candidate_id=candidate_id, verdict="failed", position=-1)
        if candidate_id in state.verification.passed_candidate_ids:
            return VerifierVerdictValue(candidate_id=candidate_id, verdict="passed", position=-1)
        return None


def _active_invalid_test_override(
    block: InvalidTestBlockValue | None,
    candidate_id: str,
) -> bool:
    if block is None:
        return False
    return block.appeal_open is True and block.candidate_id == candidate_id


def _all_configured_gates_passed(
    configured_gates: FrozenMap[str, bool],
    gate_decisions: FrozenMap[str, bool],
) -> bool:
    return all(gate_decisions.get(gate_id) is True for gate_id in configured_gates) and all(
        gate_decisions.values()
    )


def _replacement_verification_passed(
    state: GraphProjection,
    task_region_id: str,
    invalid_block: InvalidTestBlockValue,
) -> bool:
    block_position = invalid_block.position
    task = state.tasks.get(task_region_id)
    for candidate in task.candidates if task is not None else ():
        verdict = _verifier_verdict_for_candidate(state, candidate.candidate_id)
        if (
            verdict is not None
            and verdict.verdict == "passed"
            and candidate.position > block_position
        ):
            return True
    return False


def _has_active_task_lease(state: GraphProjection, task_region_id: str) -> bool:
    for lease in state.execution.leases.values():
        if lease.state != "active":
            continue
        if lease.task_region_id != task_region_id:
            continue
        if lease.kind in {"worker", "verifier", "check"}:
            return True
    return False
