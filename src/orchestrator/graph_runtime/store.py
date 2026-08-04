"""SQLite-backed event store for graph event envelopes."""

from __future__ import annotations

import json

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from types import MappingProxyType
from typing import Annotated, Any, Generic, Literal, Mapping, TypeVar, cast, get_args, get_origin

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import LargeBinary, case, cast as sql_cast, delete, func, select, true, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db import (
    EventV2Model,
    GraphArchivalViewCheckpointModel,
    GraphArtifactReferenceModel,
    GraphEventSummaryModel,
    GraphFinalBlockerViewEntryModel,
    GraphNodeDetailSummaryCheckpointModel,
    GraphNodeDetailSummaryModel,
    GraphProjectionSnapshotModel,
    GraphRegionViewEntryModel,
    GraphTopologyViewEntryModel,
    JsonlOutboxObserver,
    StoredEvent,
    queue_event_outbox,
    resolve_default_journal_path_from_session,
)
from orchestrator.graph import (
    node_states_view,
    ready_nodes_view,
    task_states_view,
    run_state as query_run_state,
    Actor,
    ActorKind,
    checkpoint_schema_is_current,
    EventEnvelope,
    EVENT_PAYLOAD_SPECS,
    GraphProjection,
    GRAPH_PROJECTION_PAYLOAD_FIELDS,
    LIGHT_GRAPH_PAYLOAD_FIELDS,
    NODE_DETAIL_PAYLOAD_FIELDS,
    PROJECTION_SCHEMA_VERSION,
    ProjectionCheckpointCodecError,
    ProjectionCheckpointIntegrityError,
    RetentionMode,
    NodeUsageRecordedPayload,
    StoredArtifactRef,
    SUMMARY_REBUILD_PAYLOAD_FIELDS,
    initial_projection,
    build_projection,
    merge_bound_record_ids,
    project_decision_view,
    project_decision_view_from_projection,
    project_final_invariant_blockers,
    project_graph_topology,
    project_leases,
    project_lease_view,
    projection_from_checkpoint,
    projection_to_checkpoint,
    project_scheduler_view,
    reduce_event,
)
from orchestrator.graph_runtime.errors import StaleProjectionError
from orchestrator.db import RunModel
from orchestrator.state import ModelTokenUsage

GRAPH_AGGREGATE_PREFIX = "graph:"
FILE_STATE_BOUNDARY_EVENT_TYPES = frozenset({"file_state_accepted", "file_state_rejected"})
FILE_STATE_GATEKEEPER_FACT_EVENT_TYPES = frozenset(
    {"gatekeeper_verdict_recorded", "gatekeeper_cost_recorded"}
)
MAX_FILE_STATE_GATEKEEPER_FACTS_PER_BOUNDARY = 100
MAX_GRAPH_PATCH_FACTS_PER_ATTEMPT = 100
MAX_EVIDENCE_DIGEST_EVENTS_PER_NODE = 20
MAX_EVIDENCE_DIGEST_LEASE_IDENTITIES_PER_NODE = 20
GRAPH_READ_CONTRACT_REVISION = 1
GRAPH_STRING_BYTES = 4_096
GRAPH_JSON_OBJECT_ENTRIES = 32
GRAPH_JSON_ARRAY_ITEMS = 50
GRAPH_JSON_DEPTH = 6
GRAPH_RESPONSE_BYTES = 262_144
GRAPH_FIXED_VIEW_ITEMS = 100
GRAPH_EVENT_PAYLOAD_BYTES = 16_384
GRAPH_RUNTIME_TAIL_EVENTS = 128
GRAPH_READ_MODEL_REBUILD_BATCH_EVENTS = 100
_READ_CONTRACT_KEY = "_graph_read_contract"
_CHECKPOINT_PROJECTION_KEY = "_projection_checkpoint"
_CHECKPOINT_SCHEMA_VERSION_KEY = "_projection_schema_version"
_CHECKPOINT_TERMINAL_KEY = "_projection_terminal"
# Compatibility-only location used by snapshots written before the dedicated
# archival view tables.  No public route reads this adjunct.
_MATERIALIZED_VIEWS_KEY = "_materialized_views"
HEAVY_GRAPH_EVENT_TYPES = frozenset(
    {
        "callback_accepted",
        "callback_rejected_conflict",
        "callback_rejected_stale",
        "file_state_accepted",
        "file_state_rejected",
        "output_record_accepted",
    }
)
SUMMARY_PAYLOAD_FIELDS = (
    "accepted_patches",
    "actor_role",
    "allowed_actions",
    "authority",
    "blocker",
    "command_binding",
    "command_definition",
    "command_type",
    "candidate_id",
    "execution_id",
    "evidence",
    "generation",
    "grade",
    "kind",
    "lease_generation",
    "lease_id",
    "new_state",
    "node",
    "node_id",
    "node_kind",
    "outcome",
    "patch_id",
    "port",
    "producer_node_id",
    "proposed_by_node_id",
    "reason",
    "record_id",
    "record_kind",
    "resource_claims",
    "preconditions",
    "rejected_patches",
    "rejection_reason",
    "role",
    "state",
    "task_region_id",
    "to_state",
    "tokens",
    "verifier_node_id",
)
SUMMARY_EDGE_FIELDS = frozenset(
    {"edge_id", "from_node_id", "to_node_id", "dependency_type", "patch_id"}
)
MAX_SUMMARY_EDGE_STRING_CHARS = 200
MAX_SUMMARY_CANDIDATE_ID_BYTES = 200
DECISION_RECORD_VALUE_FIELDS = (
    "decision",
    "decision_type",
    "decider",
    "scope",
    "consequence_summary",
    "default_option",
    "expires_at",
    "options",
    "reason",
    "requested_authority",
    "target_node_id",
    "target_region_id",
)
BOOLEAN_PAYLOAD_FIELDS = frozenset(
    {
        "active",
        "behavior_change",
        "deleted_snapshot_ref",
        "explicit_authority_required",
        "complete_node",
        "is_mutating",
        "new_behavior",
        "rate_missing",
        "required",
        "requires_authority",
        "semantic_change",
        "validation_strengthening",
    }
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PydanticCollectionContract:
    """Serialization contract carried by a typed Pydantic collection field."""

    shape: Literal["list", "map"]
    max_items: int
    stable_identity: str
    ordering: Literal["lexical", "numeric"] = "lexical"
    continuation: bool = True
    byte_cap: int | None = None
    cursor_mode: Literal["retained", "next_integer"] = "retained"
    item_mode: Literal["typed", "opaque"] = "typed"


@dataclass(frozen=True, slots=True)
class PydanticOpaqueJson:
    """Marks JSON whose shape is intentionally not defined by the read schema."""

    continuation: bool = True
    root_object_entry_cap: int | None = None
    collapse_when_owner_exceeds: bool = True


def _list_contract(max_items: int, stable_identity: str) -> PydanticCollectionContract:
    return PydanticCollectionContract("list", max_items, stable_identity)


def _map_contract(max_items: int) -> PydanticCollectionContract:
    return PydanticCollectionContract("map", max_items, "key")


class _TypedReadModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class _SchedulerBlockedReadModel(_TypedReadModel):
    node_id: str
    reason: str


class _SchedulerReadModel(_TypedReadModel):
    ready: Annotated[list[str], _list_contract(GRAPH_FIXED_VIEW_ITEMS, "self")]
    blocked: Annotated[
        list[_SchedulerBlockedReadModel],
        _list_contract(GRAPH_FIXED_VIEW_ITEMS, "node_id"),
    ]
    waiting_resources: Annotated[
        list[_SchedulerBlockedReadModel],
        _list_contract(GRAPH_FIXED_VIEW_ITEMS, "node_id"),
    ]
    waiting_gates: Annotated[
        list[_SchedulerBlockedReadModel],
        _list_contract(GRAPH_FIXED_VIEW_ITEMS, "node_id"),
    ]


class _LeaseReadModel(_TypedReadModel):
    lease_id: str
    node_id: str


class _LeaseViewReadModel(_TypedReadModel):
    active: Annotated[list[_LeaseReadModel], _list_contract(GRAPH_FIXED_VIEW_ITEMS, "lease_id")]
    suspended: Annotated[list[_LeaseReadModel], _list_contract(GRAPH_FIXED_VIEW_ITEMS, "lease_id")]


class _PendingGateReadModel(_TypedReadModel):
    node_id: str
    options: Annotated[list[str] | None, _list_contract(GRAPH_JSON_ARRAY_ITEMS, "self")] = None
    requested_authority: Annotated[
        list[str] | None, _list_contract(GRAPH_JSON_ARRAY_ITEMS, "self")
    ] = None


class _AppealReadModel(_TypedReadModel):
    node_id: str
    state: str
    outcome: str | None = None


class _ReviewReadModel(_TypedReadModel):
    ready: bool
    blockers: Annotated[list[str], _list_contract(GRAPH_FIXED_VIEW_ITEMS, "self")]


class _DecisionReadModel(_TypedReadModel):
    pending_gates: Annotated[
        list[_PendingGateReadModel],
        _list_contract(GRAPH_FIXED_VIEW_ITEMS, "node_id"),
    ]
    appeals: Annotated[list[_AppealReadModel], _list_contract(GRAPH_FIXED_VIEW_ITEMS, "node_id")]
    review: _ReviewReadModel


class _NodeDetailRecordReadModel(_TypedReadModel):
    record_id: str
    value: Annotated[Any | None, PydanticOpaqueJson()] = None


class _ProjectionOwnerReadModel(_TypedReadModel):
    node_states: Annotated[dict[str, str], _map_contract(GRAPH_FIXED_VIEW_ITEMS)]
    task_states: Annotated[dict[str, str], _map_contract(GRAPH_FIXED_VIEW_ITEMS)]
    leases: Annotated[dict[str, dict[str, Any]], _map_contract(GRAPH_FIXED_VIEW_ITEMS)]
    ready_nodes: Annotated[list[str], _list_contract(GRAPH_FIXED_VIEW_ITEMS, "self")]
    scheduler: _SchedulerReadModel
    lease_view: _LeaseViewReadModel
    decisions: _DecisionReadModel


class _NodeDetailOwnerReadModel(_TypedReadModel):
    input_ports: Annotated[dict[str, list[str]], _map_contract(GRAPH_JSON_ARRAY_ITEMS)]
    output_records: Annotated[
        list[_NodeDetailRecordReadModel], _list_contract(GRAPH_JSON_ARRAY_ITEMS, "record_id")
    ]
    file_state_records: Annotated[
        list[_NodeDetailRecordReadModel], _list_contract(GRAPH_JSON_ARRAY_ITEMS, "record_id")
    ]
    leases: Annotated[list[dict[str, Any]], _list_contract(GRAPH_JSON_ARRAY_ITEMS, "lease_id")]
    active_lease: dict[str, Any] | None
    callback_history: Annotated[
        list[dict[str, Any]],
        PydanticCollectionContract(
            "list",
            GRAPH_JSON_ARRAY_ITEMS,
            "position",
            ordering="numeric",
            byte_cap=GRAPH_RESPONSE_BYTES // 6,
            cursor_mode="next_integer",
            item_mode="opaque",
        ),
    ]
    events: Annotated[
        list[dict[str, Any]],
        PydanticCollectionContract(
            "list",
            GRAPH_JSON_ARRAY_ITEMS,
            "position",
            ordering="numeric",
            byte_cap=GRAPH_RESPONSE_BYTES // 6,
            cursor_mode="next_integer",
            item_mode="opaque",
        ),
    ]
    prompt_summary: Annotated[
        dict[str, Any] | None,
        PydanticOpaqueJson(root_object_entry_cap=GRAPH_JSON_OBJECT_ENTRIES - 1),
    ]


@dataclass(frozen=True, slots=True)
class GraphReadBudget:
    """Machine-checked limits for one graph read boundary."""

    sql_row_cap: int
    decode_cap: int
    byte_cap: int
    string_byte_cap: int = GRAPH_STRING_BYTES
    object_entry_cap: int = GRAPH_JSON_OBJECT_ENTRIES
    array_item_cap: int = GRAPH_JSON_ARRAY_ITEMS
    depth_cap: int = GRAPH_JSON_DEPTH
    rendered_payload_byte_cap: int | None = None


@dataclass(frozen=True, slots=True)
class GraphReadContract:
    """Stable read contract owned by one disposable view or indexed fact source."""

    route_name: str
    budget: GraphReadBudget
    ordering_key: str
    cursor_field: str
    stale_policy: str
    owner_read_model_name: str

    @property
    def sql_row_cap(self) -> int:
        return self.budget.sql_row_cap

    @property
    def decode_cap(self) -> int:
        return self.budget.decode_cap

    @property
    def byte_cap(self) -> int:
        return self.budget.byte_cap


@dataclass(frozen=True, slots=True)
class BoundedGraphPage(Generic[T]):
    """One stable bounded page with explicit continuation metadata."""

    items: tuple[T, ...]
    truncated: bool
    total_known: int
    next_cursor: str | int | None


class GraphReadModelUnavailable(RuntimeError):
    """A requested current view is absent, corrupt, or behind authoritative events."""

    def __init__(
        self,
        run_id: str,
        owner_read_model_name: str,
        reason: str,
        *,
        current_position: int | None = None,
    ) -> None:
        self.run_id = run_id
        self.owner_read_model_name = owner_read_model_name
        self.reason = reason
        self.current_position = current_position
        super().__init__(
            f"graph read model unavailable for run {run_id}: {owner_read_model_name} ({reason})"
        )


def _contract(
    route_name: str,
    sql_rows: int,
    decoded_values: int,
    byte_cap: int,
    ordering_key: str,
    cursor_field: str,
    owner: str,
    *,
    rendered_payload_byte_cap: int | None = None,
) -> GraphReadContract:
    return GraphReadContract(
        route_name=route_name,
        budget=GraphReadBudget(
            sql_row_cap=sql_rows,
            decode_cap=decoded_values,
            byte_cap=byte_cap,
            rendered_payload_byte_cap=rendered_payload_byte_cap,
        ),
        ordering_key=ordering_key,
        cursor_field=cursor_field,
        stale_policy="read_model_unavailable",
        owner_read_model_name=owner,
    )


GRAPH_READ_CONTRACTS: Mapping[str, GraphReadContract] = MappingProxyType(
    {
        "graph": _contract(
            "/graph",
            1,
            0,
            GRAPH_RESPONSE_BYTES,
            "identity",
            "next_cursor",
            "graph_projection_snapshot",
        ),
        "scheduler": _contract(
            "/scheduler",
            1,
            0,
            GRAPH_RESPONSE_BYTES,
            "identity",
            "next_cursor",
            "graph_projection_snapshot",
        ),
        "decisions": _contract(
            "/decisions",
            1,
            0,
            GRAPH_RESPONSE_BYTES,
            "identity",
            "next_cursor",
            "graph_projection_snapshot",
        ),
        "topology": _contract(
            "/topology",
            100,
            0,
            GRAPH_RESPONSE_BYTES,
            "identity",
            "next_cursor",
            "graph_topology_view",
        ),
        "final_blockers": _contract(
            "/final-blockers",
            100,
            0,
            GRAPH_RESPONSE_BYTES,
            "identity",
            "next_cursor",
            "graph_final_blockers_view",
        ),
        "regions": _contract(
            "/regions",
            100,
            0,
            GRAPH_RESPONSE_BYTES,
            "identity",
            "next_cursor",
            "graph_regions_view",
        ),
        "events_summary": _contract(
            "/events?payload_mode=summary",
            101,
            101,
            GRAPH_RESPONSE_BYTES,
            "position",
            "from_position",
            "graph_event_summaries",
            rendered_payload_byte_cap=GRAPH_EVENT_PAYLOAD_BYTES,
        ),
        "events_full": _contract(
            "/events?payload_mode=full",
            101,
            101,
            GRAPH_RESPONSE_BYTES,
            "position",
            "from_position",
            "events_v2",
            rendered_payload_byte_cap=GRAPH_EVENT_PAYLOAD_BYTES,
        ),
        "node_detail": _contract(
            "/nodes/{node_id}",
            51,
            50,
            GRAPH_RESPONSE_BYTES,
            "position",
            "event_position",
            "graph_node_detail_summaries",
        ),
        "file_state": _contract(
            "/file-state",
            101,
            100,
            GRAPH_RESPONSE_BYTES,
            "position",
            "from_position",
            "graph_file_state_index",
        ),
        "patches": _contract(
            "/patches",
            101,
            100,
            GRAPH_RESPONSE_BYTES,
            "position",
            "from_position",
            "graph_event_summaries",
        ),
        "evidence_digest": _contract(
            "/evidence-digest",
            100,
            100,
            GRAPH_RESPONSE_BYTES,
            "node_id",
            "next_cursor",
            "graph_node_detail_summaries",
        ),
        "artifact": _contract(
            "/artifacts/{sha}",
            1,
            1,
            1_048_576,
            "content_hash",
            "offset",
            "graph_artifact_references",
        ),
        "runtime": _contract(
            "graph-runtime",
            129,
            GRAPH_RUNTIME_TAIL_EVENTS,
            0,
            "position",
            "position",
            "graph_projection_checkpoint",
        ),
    }
)
graph_read_contracts = GRAPH_READ_CONTRACTS


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _json_utf8_byte_length(value: Any) -> Any:
    """Return the database UTF-8 byte length of a JSON text expression.

    SQLite's ``length(text)`` counts characters, which lets a non-ASCII body
    pass a nominal byte budget and then be decoded into Python.  Casting to a
    binary value makes SQLite count bytes and is also the portable SQLAlchemy
    representation of the on-wire JSON body we are about to decode.
    """
    return func.length(sql_cast(value, LargeBinary))


def _truncated_json_value(value: Any, bounded_value: Any) -> dict[str, Any]:
    original = _canonical_json_bytes(value)
    return {
        "value": bounded_value,
        "truncated": True,
        "original_bytes": len(original),
        "sha256": sha256(original).hexdigest(),
    }


def _normalize_graph_json(
    value: Any,
    budget: GraphReadBudget,
    depth: int,
    *,
    embed_metadata: bool,
    root_object_entry_cap: int | None,
    root_array_item_cap: int | None,
) -> tuple[Any, bool]:
    if isinstance(value, str):
        encoded = value.encode()
        if len(encoded) <= budget.string_byte_cap:
            return value, False
        digest = sha256(encoded).hexdigest()
        bounded = f"sha256:{digest}"
        return (
            _truncated_json_value(value, bounded) if embed_metadata else bounded,
            True,
        )
    if value is None or isinstance(value, (bool, int, float)):
        return value, False
    if depth >= budget.depth_cap:
        return (_truncated_json_value(value, None) if embed_metadata else None), True
    if isinstance(value, dict):
        source = cast(dict[Any, Any], value)
        items = sorted(source.items(), key=lambda item: str(item[0]))
        entry_cap = (
            root_object_entry_cap
            if depth == 0 and root_object_entry_cap is not None
            else budget.object_entry_cap
        )
        retained = items[:entry_cap]
        normalized: dict[str, Any] = {}
        nested_truncated = False
        for raw_key, raw_value in retained:
            key = str(raw_key)
            key_bytes = key.encode()
            if len(key_bytes) > budget.string_byte_cap:
                digest = sha256(key_bytes).hexdigest()
                key = f"sha256:{digest}"
                nested_truncated = True
            child, child_truncated = _normalize_graph_json(
                raw_value,
                budget,
                depth + 1,
                embed_metadata=True,
                root_object_entry_cap=root_object_entry_cap,
                root_array_item_cap=root_array_item_cap,
            )
            normalized[key] = child
            nested_truncated = nested_truncated or child_truncated
        if len(items) > entry_cap:
            return (
                _truncated_json_value(value, normalized) if embed_metadata else normalized,
                True,
            )
        return normalized, nested_truncated
    if isinstance(value, (list, tuple)):
        source = list(cast(list[Any] | tuple[Any, ...], value))
        item_cap = (
            root_array_item_cap
            if depth == 0 and root_array_item_cap is not None
            else budget.array_item_cap
        )
        normalized_items: list[Any] = []
        nested_truncated = False
        for item in source[:item_cap]:
            child, child_truncated = _normalize_graph_json(
                item,
                budget,
                depth + 1,
                embed_metadata=True,
                root_object_entry_cap=root_object_entry_cap,
                root_array_item_cap=root_array_item_cap,
            )
            normalized_items.append(child)
            nested_truncated = nested_truncated or child_truncated
        if len(source) > item_cap:
            return (
                _truncated_json_value(value, normalized_items)
                if embed_metadata
                else normalized_items,
                True,
            )
        return normalized_items, nested_truncated
    rendered = str(value)
    return _normalize_graph_json(
        rendered,
        budget,
        depth,
        embed_metadata=embed_metadata,
        root_object_entry_cap=root_object_entry_cap,
        root_array_item_cap=root_array_item_cap,
    )


def bound_graph_json(
    value: Any,
    budget: GraphReadBudget | None = None,
    *,
    root_object_entry_cap: int | None = None,
    root_array_item_cap: int | None = None,
) -> dict[str, Any]:
    """Return a deterministic bounded JSON value and exact truncation metadata."""
    selected = budget or GraphReadBudget(0, 0, GRAPH_RESPONSE_BYTES)
    normalized, truncated = _normalize_graph_json(
        value,
        selected,
        0,
        embed_metadata=False,
        root_object_entry_cap=root_object_entry_cap,
        root_array_item_cap=root_array_item_cap,
    )
    original = _canonical_json_bytes(value) if truncated else b""
    return {
        "value": normalized,
        "truncated": truncated,
        "original_bytes": len(original) if truncated else None,
        "sha256": sha256(original).hexdigest() if truncated else None,
    }


def _bounded_meta(
    owner: str,
    original: Any,
    bounded: Any,
    result: dict[str, Any],
) -> dict[str, Any]:
    if isinstance(original, dict):
        source_mapping = cast(dict[Any, Any], original)
        total_known = len(source_mapping)
        identities = sorted(str(key) for key in cast(dict[Any, Any], bounded))
    elif isinstance(original, (list, tuple)):
        source_sequence = cast(list[Any] | tuple[Any, ...], original)
        total_known = len(source_sequence)
        identities = [str(item) for item in cast(list[Any] | tuple[Any, ...], bounded)]
    else:
        total_known = 1
        identities = []
    return {
        "revision": GRAPH_READ_CONTRACT_REVISION,
        "owner": owner,
        "truncated": bool(result["truncated"]),
        "total_known": total_known,
        "next_cursor": identities[-1] if result["truncated"] and identities else None,
        "original_bytes": result["original_bytes"],
        "sha256": result["sha256"],
    }


def _bounded_event_payload_for_storage(payload: dict[str, Any]) -> dict[str, Any]:
    budget = GRAPH_READ_CONTRACTS["events_summary"].budget
    result = bound_graph_json(
        payload,
        budget,
        root_object_entry_cap=GRAPH_JSON_OBJECT_ENTRIES - 1,
    )
    bounded = cast(dict[str, Any], result["value"])
    bounded[_READ_CONTRACT_KEY] = _bounded_meta(
        "events_summary",
        payload,
        bounded,
        result,
    )
    rendered_cap = budget.rendered_payload_byte_cap or GRAPH_EVENT_PAYLOAD_BYTES
    if len(_canonical_json_bytes(bounded)) <= rendered_cap:
        return bounded
    retained_keys = (
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
    compact = {key: bounded[key] for key in retained_keys if key in bounded}
    original = _canonical_json_bytes(payload)
    compact[_READ_CONTRACT_KEY] = {
        "revision": GRAPH_READ_CONTRACT_REVISION,
        "owner": "events_summary",
        "truncated": True,
        "total_known": len(payload),
        "next_cursor": None,
        "original_bytes": len(original),
        "sha256": sha256(original).hexdigest(),
    }
    return compact


def _retained_cursor(value: Any) -> str | int | None:
    if isinstance(value, dict):
        keys = list(cast(dict[str, Any], value))
        return keys[-1] if keys else None
    if not isinstance(value, list) or not value:
        return None
    item = cast(list[Any], value)[-1]
    if isinstance(item, (str, int)) and not isinstance(item, bool):
        return item
    if isinstance(item, dict):
        entry = cast(dict[str, Any], item)
        for key in ("record_id", "lease_id", "node_id", "event_id", "position"):
            identity = entry.get(key)
            if isinstance(identity, (str, int)) and not isinstance(identity, bool):
                return identity
    return None


def _field_collection_contract(field: Any) -> PydanticCollectionContract | None:
    return next(
        (item for item in field.metadata if isinstance(item, PydanticCollectionContract)),
        None,
    )


def _field_opaque_contract(field: Any) -> PydanticOpaqueJson | None:
    return next(
        (item for item in field.metadata if isinstance(item, PydanticOpaqueJson)),
        None,
    )


def _annotation_model(annotation: Any) -> type[BaseModel] | None:
    candidates = (annotation, *get_args(annotation))
    for candidate in candidates:
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
    return None


def _collection_item_annotation(annotation: Any) -> Any:
    candidates = (annotation, *get_args(annotation))
    for candidate in candidates:
        if get_origin(candidate) in (list, dict):
            arguments = get_args(candidate)
            return arguments[-1] if arguments else Any
    return Any


def _typed_collection_identity(
    value: Any,
    contract: PydanticCollectionContract,
) -> str | int:
    if contract.stable_identity in {"self", "key"}:
        identity = value
    elif isinstance(value, BaseModel):
        identity = getattr(value, contract.stable_identity, "")
    elif isinstance(value, dict):
        identity = cast(dict[str, Any], value).get(contract.stable_identity, "")
    else:
        identity = ""
    if contract.ordering == "numeric":
        if isinstance(identity, int) and not isinstance(identity, bool):
            return identity
        raise TypeError(
            f"{contract.stable_identity!r} must be an integer for numeric collection ordering"
        )
    return str(identity)


def _typed_collection_metadata(
    owner: str,
    original: Any,
    bounded: Any,
    *,
    truncated: bool,
    contract: PydanticCollectionContract | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "truncated": truncated,
        "original_bytes": None,
        "sha256": None,
    }
    if truncated:
        original_bytes = _canonical_json_bytes(original)
        result["original_bytes"] = len(original_bytes)
        result["sha256"] = sha256(original_bytes).hexdigest()
    metadata = _bounded_meta(owner, original, bounded, result)
    if truncated and contract is not None and contract.continuation:
        if isinstance(bounded, dict) and bounded:
            metadata["next_cursor"] = list(cast(dict[str, Any], bounded))[-1]
        elif isinstance(bounded, list) and bounded:
            metadata["next_cursor"] = _typed_collection_identity(
                cast(list[Any], bounded)[-1], contract
            )
            if contract.cursor_mode == "next_integer":
                cursor = metadata["next_cursor"]
                if isinstance(cursor, int) and not isinstance(cursor, bool):
                    metadata["next_cursor"] = cursor + 1
        if metadata["next_cursor"] is None:
            digest = cast(str, metadata["sha256"])
            metadata["next_cursor"] = f"sha256:{digest}"
    return metadata


def _aggregate_continuation_token(cursors: list[tuple[str, str | int]]) -> str:
    """Identify a multi-field continuation without pretending it is one field cursor."""
    digest = sha256(_canonical_json_bytes(cursors)).hexdigest()
    return f"aggregate:sha256:{digest}"


def _field_metadata_cursor(fields: dict[str, Any]) -> str | int | None:
    cursors = [
        (path, cursor)
        for path, raw in sorted(fields.items())
        if isinstance(raw, dict)
        and cast(dict[str, Any], raw).get("truncated") is True
        and isinstance(
            cursor := cast(dict[str, Any], raw).get("next_cursor"),
            (str, int),
        )
        and not isinstance(cursor, bool)
    ]
    if not cursors:
        return None
    unique = {cursor for _, cursor in cursors}
    if len(unique) == 1:
        return cursors[0][1]
    return _aggregate_continuation_token(cursors)


def _normalize_typed_value(
    value: Any,
    annotation: Any,
    budget: GraphReadBudget,
    *,
    owner: str,
) -> tuple[Any, bool, dict[str, dict[str, Any]]]:
    model_type = _annotation_model(annotation)
    if model_type is not None and value is not None:
        instance = value if isinstance(value, model_type) else model_type.model_validate(value)
        return _normalize_typed_model(instance, budget, owner=owner)
    normalized, truncated = _normalize_graph_json(
        value,
        budget,
        1,
        embed_metadata=True,
        root_object_entry_cap=None,
        root_array_item_cap=None,
    )
    return normalized, truncated, {}


def _normalize_typed_collection(
    value: Any,
    annotation: Any,
    contract: PydanticCollectionContract,
    budget: GraphReadBudget,
    *,
    owner: str,
) -> tuple[Any, dict[str, Any], dict[str, dict[str, Any]]]:
    item_annotation = _collection_item_annotation(annotation)
    nested_metadata: dict[str, dict[str, Any]] = {}
    bounded: dict[str, Any] | list[Any]
    if contract.shape == "map":
        source = cast(dict[str, Any], value or {})
        ordered = {key: source[key] for key in sorted(source)}
        retained_items = list(ordered.items())[: contract.max_items]
        bounded = {}
        for key, item in retained_items:
            if contract.item_mode == "opaque":
                normalized, child_metadata = deepcopy(item), {}
            else:
                normalized, _, child_metadata = _normalize_typed_value(
                    item,
                    item_annotation,
                    budget,
                    owner=f"{owner}.{key}",
                )
            bounded[key] = normalized
            nested_metadata.update(
                {
                    f"{key}.{path}": metadata
                    for path, metadata in child_metadata.items()
                    if metadata.get("truncated") is True
                }
            )
        original: Any = ordered
        count_truncated = len(ordered) > contract.max_items
    else:
        source_items = list(cast(list[Any], value or []))
        ordered_items = sorted(
            source_items,
            key=lambda item: _typed_collection_identity(item, contract),
        )
        bounded_items: list[Any] = []
        for index, item in enumerate(ordered_items[: contract.max_items]):
            identity = _typed_collection_identity(item, contract) or str(index)
            if contract.item_mode == "opaque":
                normalized, child_metadata = deepcopy(item), {}
            else:
                normalized, _, child_metadata = _normalize_typed_value(
                    item,
                    item_annotation,
                    budget,
                    owner=f"{owner}.{identity}",
                )
            bounded_items.append(normalized)
            nested_metadata.update(
                {
                    f"{identity}.{path}": metadata
                    for path, metadata in child_metadata.items()
                    if metadata.get("truncated") is True
                }
            )
        original = [
            item.model_dump(mode="python", exclude_unset=True)
            if isinstance(item, BaseModel)
            else item
            for item in ordered_items
        ]
        bounded = bounded_items
        count_truncated = len(ordered_items) > contract.max_items
    if contract.byte_cap is not None:
        while bounded and len(_canonical_json_bytes(bounded)) > contract.byte_cap:
            if isinstance(bounded, dict):
                bounded.pop(next(reversed(bounded)))
            else:
                bounded.pop()
            count_truncated = True
    metadata = _typed_collection_metadata(
        owner,
        original,
        bounded,
        truncated=count_truncated,
        contract=contract,
    )
    return bounded, metadata, nested_metadata


def _normalize_typed_model(
    instance: BaseModel,
    budget: GraphReadBudget,
    *,
    owner: str,
) -> tuple[dict[str, Any], bool, dict[str, dict[str, Any]]]:
    normalized: dict[str, Any] = {}
    field_metadata: dict[str, dict[str, Any]] = {}
    any_truncated = False
    for field_name, field in type(instance).model_fields.items():
        value = getattr(instance, field_name)
        if value is None and field_name not in instance.model_fields_set:
            continue
        contract = _field_collection_contract(field)
        if contract is not None:
            bounded, metadata, nested = _normalize_typed_collection(
                value,
                field.annotation,
                contract,
                budget,
                owner=f"{owner}.{field_name}",
            )
            normalized[field_name] = bounded
            field_metadata[field_name] = metadata
            field_metadata.update({f"{field_name}.{key}": item for key, item in nested.items()})
            any_truncated = (
                any_truncated
                or metadata["truncated"]
                or any(item.get("truncated") is True for item in nested.values())
            )
            continue
        model_type = _annotation_model(field.annotation)
        if model_type is not None and value is not None:
            child, child_truncated, child_metadata = _normalize_typed_model(
                value if isinstance(value, BaseModel) else model_type.model_validate(value),
                budget,
                owner=f"{owner}.{field_name}",
            )
            normalized[field_name] = child
            field_metadata.update(
                {f"{field_name}.{key}": item for key, item in child_metadata.items()}
            )
            any_truncated = any_truncated or child_truncated
            continue
        opaque_contract = _field_opaque_contract(field)
        if opaque_contract is not None:
            result = bound_graph_json(
                value or {},
                budget,
                root_object_entry_cap=opaque_contract.root_object_entry_cap,
            )
            normalized[field_name] = result["value"]
            field_meta = _bounded_meta(
                f"{owner}.{field_name}",
                value or {},
                result["value"],
                result,
            )
            if field_meta["truncated"] and opaque_contract.continuation:
                field_meta["next_cursor"] = f"sha256:{field_meta['sha256']}"
            field_metadata[field_name] = field_meta
            any_truncated = any_truncated or bool(result["truncated"])
            continue
        result = bound_graph_json(value, budget)
        normalized[field_name] = result["value"]
        any_truncated = any_truncated or bool(result["truncated"])
    for extra_name in sorted(instance.model_extra or {}):
        normalized[extra_name] = deepcopy(cast(dict[str, Any], instance.model_extra)[extra_name])
    return normalized, any_truncated, field_metadata


def _bounded_pydantic_owner_for_storage(
    value: dict[str, Any],
    model_type: type[BaseModel],
    owner: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    budget = GRAPH_READ_CONTRACTS[owner].budget
    instance = model_type.model_validate(value)
    normalized: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    for field_name, field in model_type.model_fields.items():
        raw_value = getattr(instance, field_name)
        contract = _field_collection_contract(field)
        if contract is not None:
            bounded, field_meta, nested_fields = _normalize_typed_collection(
                raw_value,
                field.annotation,
                contract,
                budget,
                owner=owner,
            )
            normalized[field_name] = bounded
            if nested_fields:
                field_meta["fields"] = nested_fields
                if any(item.get("truncated") is True for item in nested_fields.values()):
                    original_value: Any = raw_value
                    if isinstance(raw_value, list):
                        original_value = [
                            item.model_dump(mode="python", exclude_unset=True)
                            if isinstance(item, BaseModel)
                            else item
                            for item in cast(list[Any], raw_value)
                        ]
                    _mark_owner_collection_truncated(field_meta, original_value, bounded)
                    field_meta["next_cursor"] = _field_metadata_cursor(nested_fields)
            metadata[field_name] = field_meta
            continue
        nested_model = _annotation_model(field.annotation)
        if nested_model is not None and raw_value is not None:
            child, child_truncated, child_fields = _normalize_typed_model(
                raw_value,
                budget,
                owner=field_name,
            )
            normalized[field_name] = child
            raw_child = raw_value.model_dump(mode="python")
            owner_meta = _typed_collection_metadata(
                owner,
                raw_child,
                child,
                truncated=child_truncated,
            )
            owner_meta["fields"] = child_fields
            owner_meta["next_cursor"] = _field_metadata_cursor(child_fields)
            metadata[field_name] = owner_meta
            continue
        opaque_contract = _field_opaque_contract(field)
        if opaque_contract is not None:
            result = bound_graph_json(
                raw_value or {},
                budget,
                root_object_entry_cap=opaque_contract.root_object_entry_cap,
            )
            normalized[field_name] = result["value"]
            metadata[field_name] = _bounded_meta(
                owner,
                raw_value or {},
                result["value"],
                result,
            )
            if metadata[field_name]["truncated"] and opaque_contract.continuation:
                metadata[field_name]["next_cursor"] = f"sha256:{metadata[field_name]['sha256']}"
            continue
        result = bound_graph_json(raw_value, budget)
        normalized[field_name] = result["value"]
    for extra_name in sorted(instance.model_extra or {}):
        normalized[extra_name] = deepcopy(cast(dict[str, Any], instance.model_extra)[extra_name])
    return normalized, metadata


@dataclass(frozen=True, slots=True)
class _WholeOwnerPackTarget:
    """One independently pageable collection inside a persisted read-model owner."""

    path: tuple[str, ...]
    owner: str
    field: str | None = None
    reserved_keys: frozenset[str] = frozenset()
    opaque: PydanticOpaqueJson | None = None


def _pydantic_pack_targets(
    model_type: type[BaseModel],
    *,
    path: tuple[str, ...] = (),
    owner: str | None = None,
    field_prefix: str = "",
) -> tuple[_WholeOwnerPackTarget, ...]:
    """Derive byte-pack candidates solely from Pydantic field annotations."""
    targets: list[_WholeOwnerPackTarget] = []
    for field_name, field in model_type.model_fields.items():
        field_path = (*path, field_name)
        field_owner = owner or field_name
        nested_name = f"{field_prefix}.{field_name}" if field_prefix else field_name
        if _field_collection_contract(field) is not None:
            targets.append(
                _WholeOwnerPackTarget(
                    path=field_path,
                    owner=field_owner,
                    field=None if owner is None else nested_name,
                )
            )
            continue
        opaque_contract = _field_opaque_contract(field)
        if opaque_contract is not None and opaque_contract.collapse_when_owner_exceeds:
            targets.append(
                _WholeOwnerPackTarget(
                    path=field_path,
                    owner=field_owner,
                    reserved_keys=frozenset({_READ_CONTRACT_KEY}),
                    opaque=opaque_contract,
                )
            )
            continue
        nested_model = _annotation_model(field.annotation)
        if nested_model is not None:
            targets.extend(
                _pydantic_pack_targets(
                    nested_model,
                    path=field_path,
                    owner=field_owner,
                    field_prefix="" if owner is None else nested_name,
                )
            )
    return tuple(targets)


def _value_at_path(root: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = root
    for key in path:
        if not isinstance(value, dict):
            return None
        value = cast(dict[str, Any], value).get(key)
    return value


def _set_value_at_path(root: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    owner: dict[str, Any] = root
    for key in path[:-1]:
        child = owner.get(key)
        if not isinstance(child, dict):
            return
        owner = cast(dict[str, Any], child)
    owner[path[-1]] = value


def _drop_collection_tail(value: Any, reserved_keys: frozenset[str]) -> Any:
    if isinstance(value, dict):
        source = cast(dict[str, Any], value)
        content_keys = sorted(key for key in source if key not in reserved_keys)
        if not content_keys:
            return source
        retained = {key: source[key] for key in content_keys[:-1]}
        retained.update({key: source[key] for key in sorted(reserved_keys) if key in source})
        return retained
    if isinstance(value, list):
        return list(cast(list[Any], value)[:-1])
    return value


def _collection_content(value: Any, reserved_keys: frozenset[str]) -> Any:
    if not reserved_keys or not isinstance(value, dict):
        return value
    source = cast(dict[str, Any], value)
    return {key: source[key] for key in sorted(source) if key not in reserved_keys}


def _owner_collection_value(payload: dict[str, Any], owner: str) -> Any:
    value = _value_at_path(payload, (owner,))
    if not isinstance(value, dict):
        return value
    reserved_keys = {_READ_CONTRACT_KEY}
    if owner == "decisions":
        reserved_keys.update(
            {
                _CHECKPOINT_PROJECTION_KEY,
                _CHECKPOINT_SCHEMA_VERSION_KEY,
                _CHECKPOINT_TERMINAL_KEY,
            }
        )
    return {
        key: item
        for key, item in sorted(cast(dict[str, Any], value).items())
        if key not in reserved_keys
    }


def _mark_owner_collection_truncated(
    metadata: dict[str, Any],
    original: Any,
    retained: Any,
) -> None:
    already_truncated = metadata.get("truncated") is True
    original_bytes = _canonical_json_bytes(original)
    stored_original_bytes = metadata.get("original_bytes")
    stored_digest = metadata.get("sha256")
    metadata.update(
        {
            "truncated": True,
            "next_cursor": _retained_cursor(retained),
            "original_bytes": (
                stored_original_bytes
                if already_truncated and isinstance(stored_original_bytes, int)
                else len(original_bytes)
            ),
            "sha256": (
                stored_digest
                if already_truncated and isinstance(stored_digest, str)
                else sha256(original_bytes).hexdigest()
            ),
        }
    )


def _refresh_owner_cursor(metadata: dict[str, Any]) -> None:
    raw_fields = metadata.get("fields")
    if isinstance(raw_fields, dict):
        metadata["next_cursor"] = _field_metadata_cursor(cast(dict[str, Any], raw_fields))


def _opaque_continuation_value(value: Any, metadata: dict[str, Any]) -> dict[str, Any]:
    continuation = metadata.get("next_cursor")
    if not isinstance(continuation, (str, int)) or isinstance(continuation, bool):
        digest = metadata.get("sha256")
        if isinstance(digest, str):
            continuation = f"sha256:{digest}"
            metadata["next_cursor"] = continuation
    contract = (
        cast(dict[str, Any], value).get(_READ_CONTRACT_KEY) if isinstance(value, dict) else None
    )
    result: dict[str, Any] = {
        "value": {},
        "truncated": True,
        "total_known": metadata.get("total_known", 0),
        "next_cursor": continuation,
        "original_bytes": metadata.get("original_bytes"),
        "sha256": metadata.get("sha256"),
    }
    if isinstance(contract, dict):
        result[_READ_CONTRACT_KEY] = contract
    return result


def _fresh_field_metadata(owner: str, field: str, original: Any) -> dict[str, Any]:
    if isinstance(original, dict):
        total_known = len(cast(dict[str, Any], original))
    elif isinstance(original, list):
        total_known = len(cast(list[Any], original))
    else:
        total_known = 1
    return {
        "revision": GRAPH_READ_CONTRACT_REVISION,
        "owner": f"{owner}.{field}",
        "truncated": False,
        "total_known": total_known,
        "next_cursor": None,
        "original_bytes": None,
        "sha256": None,
    }


def _target_metadata(
    collections: dict[str, Any],
    target: _WholeOwnerPackTarget,
    original: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    raw_owner_metadata = collections.get(target.owner)
    if not isinstance(raw_owner_metadata, dict):
        return None, None
    owner_metadata = cast(dict[str, Any], raw_owner_metadata)
    if target.field is None:
        return owner_metadata, owner_metadata
    raw_fields = owner_metadata.setdefault("fields", {})
    if not isinstance(raw_fields, dict):
        raw_fields = {}
        owner_metadata["fields"] = raw_fields
    fields = cast(dict[str, Any], raw_fields)
    raw_field_metadata = fields.get(target.field)
    if not isinstance(raw_field_metadata, dict):
        raw_field_metadata = _fresh_field_metadata(target.owner, target.field, original)
        fields[target.field] = raw_field_metadata
    return owner_metadata, cast(dict[str, Any], raw_field_metadata)


def _pack_whole_owner_payload(
    payload: dict[str, Any],
    collections: dict[str, Any],
    targets: tuple[_WholeOwnerPackTarget, ...],
) -> dict[str, Any]:
    """Trim any declared collection until the complete persisted owner is bounded.

    Values are removed only from the lexical tail of mappings or the ordered tail
    of lists. The largest remaining collection is trimmed first, with its canonical
    path as the stable tie-breaker. Originals are captured before packing so field
    and owner integrity metadata always describes the pre-pack value.
    """
    packed = deepcopy(payload)
    packed_collections = _read_contract_collections(packed, collections)
    originals = {
        target.path: deepcopy(
            _collection_content(_value_at_path(packed, target.path), target.reserved_keys)
        )
        for target in targets
    }
    owner_originals = {
        target.owner: deepcopy(_owner_collection_value(packed, target.owner)) for target in targets
    }

    for target in targets:
        original = originals[target.path]
        _target_metadata(packed_collections, target, original)

    while len(_canonical_json_bytes(packed)) > GRAPH_RESPONSE_BYTES:
        candidates: list[tuple[int, str, _WholeOwnerPackTarget]] = []
        for target in targets:
            value = _value_at_path(packed, target.path)
            if target.opaque is not None:
                if not isinstance(value, dict):
                    continue
                opaque_value = cast(dict[str, Any], value)
                if opaque_value.get("truncated") is True and opaque_value.get("value") == {}:
                    continue
                candidate_retained: Any = {}
            else:
                candidate_retained = _drop_collection_tail(value, target.reserved_keys)
            if candidate_retained == value:
                continue
            candidates.append((len(_canonical_json_bytes(value)), ".".join(target.path), target))
        if not candidates:
            break
        _, _, selected = max(candidates)
        current_value = _value_at_path(packed, selected.path)
        retained: Any = (
            {}
            if selected.opaque is not None
            else _drop_collection_tail(current_value, selected.reserved_keys)
        )
        retained_content = _collection_content(retained, selected.reserved_keys)
        owner_metadata, field_metadata = _target_metadata(
            packed_collections,
            selected,
            originals[selected.path],
        )
        if field_metadata is not None:
            _mark_owner_collection_truncated(
                field_metadata,
                originals[selected.path],
                retained_content,
            )
            if selected.opaque is not None:
                digest = field_metadata.get("sha256")
                if isinstance(digest, str):
                    field_metadata["next_cursor"] = f"sha256:{digest}"
                retained = _opaque_continuation_value(current_value, field_metadata)
        _set_value_at_path(packed, selected.path, retained)
        if owner_metadata is not None and owner_metadata is not field_metadata:
            retained_owner = _owner_collection_value(packed, selected.owner)
            _mark_owner_collection_truncated(
                owner_metadata,
                owner_originals[selected.owner],
                retained_owner,
            )
            _refresh_owner_cursor(owner_metadata)
    return packed


def _read_contract_collections(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    decisions = payload.get("decisions")
    prompt_summary = payload.get("prompt_summary")
    for owner in (decisions, prompt_summary):
        if not isinstance(owner, dict):
            continue
        raw_contract = cast(dict[str, Any], owner).get(_READ_CONTRACT_KEY)
        if not isinstance(raw_contract, dict):
            continue
        raw_collections = cast(dict[str, Any], raw_contract).get("collections")
        if isinstance(raw_collections, dict):
            return cast(dict[str, Any], raw_collections)
    return fallback


def _projection_snapshot_payload(row: GraphProjectionSnapshotModel) -> dict[str, Any]:
    return {
        "node_states": row.node_states,
        "task_states": row.task_states,
        "leases": row.leases,
        "ready_nodes": row.ready_nodes,
        "scheduler": row.scheduler,
        "lease_view": row.lease_view,
        "decisions": row.decisions,
    }


def _pack_projection_snapshot_row(row: GraphProjectionSnapshotModel) -> None:
    raw_contract = row.decisions.get(_READ_CONTRACT_KEY)
    if not isinstance(raw_contract, dict):
        return
    collections = cast(dict[str, Any], raw_contract).get("collections")
    if not isinstance(collections, dict):
        return
    packed = _pack_whole_owner_payload(
        _projection_snapshot_payload(row),
        cast(dict[str, Any], collections),
        _pydantic_pack_targets(_ProjectionOwnerReadModel),
    )
    for field in ("node_states", "task_states", "leases", "ready_nodes"):
        setattr(row, field, packed[field])
    row.scheduler = cast(dict[str, Any], packed["scheduler"])
    row.lease_view = cast(dict[str, Any], packed["lease_view"])
    row.decisions = cast(dict[str, Any], packed["decisions"])


def _node_detail_payload(row: GraphNodeDetailSummaryModel) -> dict[str, Any]:
    return {
        "input_ports": row.input_ports,
        "output_records": row.output_records,
        "file_state_records": row.file_state_records,
        "leases": row.leases,
        "active_lease": row.active_lease,
        "callback_history": row.callback_history,
        "events": row.events,
        "prompt_summary": row.prompt_summary,
    }


def _pack_node_detail_row(row: GraphNodeDetailSummaryModel) -> None:
    prompt_summary = row.prompt_summary
    if not isinstance(prompt_summary, dict):
        return
    raw_contract = prompt_summary.get(_READ_CONTRACT_KEY)
    if not isinstance(raw_contract, dict):
        return
    collections = cast(dict[str, Any], raw_contract).get("collections")
    if not isinstance(collections, dict):
        return
    packed = _pack_whole_owner_payload(
        _node_detail_payload(row),
        cast(dict[str, Any], collections),
        _pydantic_pack_targets(_NodeDetailOwnerReadModel),
    )
    row.input_ports = cast(dict[str, Any], packed["input_ports"])
    row.output_records = cast(list[dict[str, Any]], packed["output_records"])
    row.file_state_records = cast(list[dict[str, Any]], packed["file_state_records"])
    row.leases = cast(list[dict[str, Any]], packed["leases"])
    row.active_lease = cast(dict[str, Any] | None, packed["active_lease"])
    row.callback_history = cast(list[dict[str, Any]], packed["callback_history"])
    row.events = cast(list[dict[str, Any]], packed["events"])
    row.prompt_summary = cast(dict[str, Any], packed["prompt_summary"])


def bound_node_detail_owner(
    value: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Serialize one node-detail owner from the canonical Pydantic annotations."""
    bounded, metadata = _bounded_pydantic_owner_for_storage(
        value,
        _NodeDetailOwnerReadModel,
        "node_detail",
    )
    prompt_storage = cast(dict[str, Any], bounded["prompt_summary"])
    prompt_storage[_READ_CONTRACT_KEY] = {
        "revision": GRAPH_READ_CONTRACT_REVISION,
        "collections": metadata,
    }
    packed = _pack_whole_owner_payload(
        bounded,
        metadata,
        _pydantic_pack_targets(_NodeDetailOwnerReadModel),
    )
    packed_prompt = cast(dict[str, Any], packed["prompt_summary"])
    raw_contract = packed_prompt.pop(_READ_CONTRACT_KEY)
    packed_metadata = cast(dict[str, Any], raw_contract)["collections"]
    if not packed_prompt:
        packed["prompt_summary"] = None
    return packed, cast(dict[str, Any], packed_metadata)


def graph_aggregate_id(run_id: str) -> str:
    """events_v2 aggregate key for a run's graph event stream.

    Legacy workflow events use ``aggregate_id == run_id``; graph events are
    namespaced so the two streams never contend for the same
    (aggregate_id, version) sequence and never appear in each other's reads.
    """
    return f"{GRAPH_AGGREGATE_PREFIX}{run_id}"


def _payload_with_durable_graph_position(
    event: EventEnvelope,
    position: int,
    run_id: str,
) -> dict[str, Any]:
    payload = dict(event.payload)
    if event.event_type in {"output_record_accepted", "file_state_accepted"}:
        _add_durable_record_base_fields(event, payload, position, run_id)
        _validate_durable_record_base_fields(event.event_type, payload)
    if event.event_type != "input_bound":
        return payload
    bound_at_position = payload.get("bound_at_position")
    if (
        isinstance(bound_at_position, int)
        and not isinstance(bound_at_position, bool)
        and bound_at_position > 0
    ):
        return payload
    payload["bound_at_position"] = position
    return payload


def _artifact_references_from_events(
    events: list[EventEnvelope],
) -> list[tuple[int, StoredArtifactRef]]:
    """Extract validated check-result CAS references from accepted output only."""
    references: list[tuple[int, StoredArtifactRef]] = []
    for event in events:
        if event.event_type != "output_record_accepted":
            continue
        payload = event.payload
        if payload.get("record_type") != "check_result":
            continue
        raw_value = payload.get("value")
        if not isinstance(raw_value, dict):
            continue
        value = cast(dict[str, Any], raw_value)
        for field in ("stdout_ref", "stderr_ref"):
            raw_ref: Any = value.get(field)
            if not isinstance(raw_ref, dict):
                continue
            try:
                ref = StoredArtifactRef.model_validate(raw_ref)
            except ValidationError:
                # The accepted-record schema should prevent this.  Keeping the
                # projection narrow nevertheless avoids authorizing malformed
                # historical JSON during recovery.
                continue
            if ref.artifact_id != ref.content_hash:
                continue
            references.append((event.position, ref))
    return references


_RECORD_PAYLOAD_BASE_FIELDS = {
    "created_at",
    "graph_position",
    "payload",
    "producer_node_id",
    "producer_port",
    "provenance",
    "record_id",
    "record_type",
    "run_id",
    "schema_version",
}

_LEGACY_RECORD_METADATA_FIELDS = {"port", "record_kind", "schema"}


def _add_durable_record_base_fields(
    event: EventEnvelope,
    payload: dict[str, Any],
    position: int,
    run_id: str,
) -> None:
    port = payload.get("port")
    if event.event_type == "file_state_accepted" and not isinstance(port, str):
        port = "file_state"
        payload["port"] = port
    if isinstance(port, str) and port:
        payload.setdefault("producer_port", port)
        payload.setdefault("record_type", _record_type_for_port(port, payload))
    payload.setdefault("schema_version", 1)
    payload["run_id"] = run_id
    payload["created_at"] = event.timestamp.isoformat()
    payload["graph_position"] = position
    payload.setdefault("payload", _typed_record_payload(payload))


def _validate_durable_record_base_fields(event_type: str, payload: dict[str, Any]) -> None:
    for field in (
        "record_id",
        "record_type",
        "producer_node_id",
        "producer_port",
        "created_at",
        "graph_position",
        "run_id",
        "payload",
    ):
        value = payload.get(field)
        if value is None or value == "":
            msg = f"{event_type} missing durable record base field: {field}"
            raise ValueError(msg)
    schema_version = payload.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version <= 0
    ):
        msg = f"{event_type} has invalid durable record schema_version"
        raise ValueError(msg)
    port = payload.get("port")
    producer_port = payload.get("producer_port")
    if isinstance(port, str) and producer_port != port:
        msg = f"{event_type} producer_port does not match port"
        raise ValueError(msg)
    if not isinstance(payload.get("payload"), dict):
        msg = f"{event_type} payload base field must be an object"
        raise ValueError(msg)


def _record_type_for_port(port: str, payload: dict[str, Any]) -> str:
    if payload.get("record_kind") == "verification":
        return "verification_report"
    if payload.get("record_kind") == "file_state":
        return "file_state"
    if port in {"file_state", "accepted_file_state"}:
        return "file_state"
    return port


def _typed_record_payload(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("value")
    if isinstance(value, dict):
        return dict(cast(dict[str, Any], value))
    return {
        key: value
        for key, value in payload.items()
        if key not in _RECORD_PAYLOAD_BASE_FIELDS and key not in _LEGACY_RECORD_METADATA_FIELDS
    }


def _is_verification_report_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "verification_report"
        or payload.get("record_kind") == "verification"
        or payload.get("port") == "verification_report"
        or payload.get("schema") == "VerificationReport"
    )


@dataclass(frozen=True)
class GraphEventSummary:
    event_id: str
    event_type: str
    run_id: str
    position: int
    timestamp: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class BoundedFullGraphEvent:
    """One public full-event row whose payload was selected under a byte cap.

    Event envelopes are stored as a single JSON value.  Request handlers must
    not deserialize an arbitrarily large envelope merely to then replace its
    payload with a bounded rendering.  Rows above ``payload_byte_cap`` retain
    their stable envelope identity and exact payload length, but deliberately
    omit the body.
    """

    event_id: str
    event_type: str
    run_id: str
    position: int
    timestamp: str
    payload_json: str | None
    payload_original_bytes: int


@dataclass(frozen=True)
class BoundedGraphHealth:
    """Compact, bounded facts for the graph-health endpoint.

    This deliberately does not attempt to reconstruct the full projection.
    ``summaries_complete`` is a proof about the disposable event-summary
    stream, not about the richer projection and node-detail read models.
    """

    event_count: int
    summaries_complete: bool
    run_state: str | None
    patches_accepted: int | None
    patches_rejected: int | None
    patch_decisions: tuple[dict[str, Any], ...]
    patch_decisions_total: int | None
    patch_decisions_truncated: bool
    verifier_passed: int | None
    verifier_failed: int | None
    verifier_results: tuple[dict[str, Any], ...]
    verifier_results_total: int | None
    verifier_results_truncated: bool


@dataclass(frozen=True)
class FileStateReportPage:
    """One boundary-cursor page plus bounded facts owned by those boundaries."""

    boundaries: tuple[EventEnvelope, ...]
    has_more: bool
    associated_facts: tuple[EventEnvelope, ...]
    associated_fact_counts: dict[str, int]
    orphan_gatekeeper_fact_count: int


@dataclass(frozen=True)
class GraphPatchAttemptPage:
    """A bounded page of patch identities and all selected identity-owned facts.

    The primary query chooses one canonical position per patch ID.  The second
    query deliberately fetches facts for those IDs rather than an event window,
    so an outcome cannot spill into the next page.
    """

    proposals: tuple[dict[str, Any], ...]
    facts_by_patch_id: dict[str, tuple[dict[str, Any], ...]]
    creation_counts_by_patch_id: dict[str, tuple[int, int]]
    has_more: bool
    orphan_fact_count: int
    capped_fact_count: int
    partial: bool


@dataclass(frozen=True)
class GraphNodeDetailSummary:
    run_id: str
    node_id: str
    position: int
    kind: str | None
    role: str | None
    state: str | None
    task_region_id: str | None
    input_ports: dict[str, list[str]]
    output_records: list[dict[str, Any]]
    file_state_records: list[dict[str, Any]]
    leases: list[dict[str, Any]]
    active_lease: dict[str, Any] | None
    callback_history: list[dict[str, Any]]
    events: list[dict[str, Any]]
    prompt_summary: dict[str, Any] | None = None
    read_contract: dict[str, Any] | None = None


@dataclass(frozen=True)
class GraphProjectionCheckpoint:
    run_id: str
    position: int
    projection: GraphProjection
    schema_version: int
    terminal: bool


@dataclass(frozen=True)
class BoundedNodeEvidence:
    """Small, node-owned event windows for the evidence digest.

    ``truncated_node_ids`` means the digest deliberately did not inspect all
    evidence events for that node.  Callers must not describe those summaries
    as complete.
    """

    events_by_node: dict[str, tuple[EventEnvelope, ...]]
    lease_ids_by_node: dict[str, frozenset[str]]
    truncated_node_ids: frozenset[str]


@dataclass(frozen=True)
class EvidenceDigestNodeSummary:
    node_id: str
    state: str | None
    role: str | None
    deferred_reason: str | None


@dataclass(frozen=True)
class EvidenceDigestReadModel:
    """Fixed-size digest facts derived from compact, indexed read models."""

    node_summaries: tuple[EvidenceDigestNodeSummary, ...]
    ready_count: int
    blocked_count: int
    waiting_resource_count: int
    waiting_gate_count: int
    active_lease_count: int
    suspended_lease_count: int
    blockers: tuple[str, ...]


class GraphEventStore:
    """Append-only graph event store backed by ``events_v2``.

    ``events_v2.version`` is the run-local graph event position. Empty streams
    are considered to be at position ``0``; the first event is stored at
    position/version ``1``.

    Direct appends bypass graph-runtime outbox enforcement. Production command
    handling must use ``GraphController`` so side-effect-bearing events and
    their outbox rows commit atomically. This store is for read/replay and the
    controller's transaction boundary.
    """

    def __init__(self, session: AsyncSession, *, journal_max_bytes: int = 64 * 1024 * 1024) -> None:
        self._session = session
        self._journal_max_bytes = journal_max_bytes

    async def append_events(
        self,
        run_id: str,
        expected_position: int,
        events: list[EventEnvelope],
    ) -> list[EventEnvelope]:
        """Append events if the run stream is still at ``expected_position``."""
        if not events:
            return []

        current_position = await self.current_position(run_id)
        if current_position < expected_position:
            msg = (
                f"stale graph projection for run {run_id}: "
                f"expected {expected_position}, found {current_position}"
            )
            raise StaleProjectionError(msg)

        stored_events: list[EventEnvelope] = []
        rows: list[EventV2Model] = []
        for offset, event in enumerate(events, start=1):
            position = expected_position + offset
            stored = event.model_copy(
                update={
                    "run_id": run_id,
                    "position": position,
                    "payload": _payload_with_durable_graph_position(event, position, run_id),
                }
            )
            stored_events.append(stored)
            rows.append(
                EventV2Model(
                    aggregate_id=graph_aggregate_id(run_id),
                    version=position,
                    event_type=stored.event_type,
                    payload=stored.model_dump_json(),
                    timestamp=stored.timestamp.isoformat(),
                )
            )

        self._session.add_all(rows)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            msg = f"stale graph projection for run {run_id}"
            raise StaleProjectionError(msg) from exc
        journal_path = resolve_default_journal_path_from_session(self._session)
        if journal_path is not None:
            queue_event_outbox(
                self._session,
                JsonlOutboxObserver(journal_path, max_bytes=self._journal_max_bytes),
                [
                    StoredEvent(
                        position=row.position,
                        aggregate_id=row.aggregate_id,
                        event_type=row.event_type,
                        payload=row.payload,
                        timestamp=row.timestamp,
                        version=row.version,
                    )
                    for row in rows
                ],
            )
        await self.append_event_summaries(run_id, stored_events)
        await self.append_artifact_references(run_id, stored_events)
        await self.append_node_detail_summaries(
            run_id,
            stored_events,
            expected_position=expected_position,
        )
        await self.advance_projection_snapshot(
            run_id,
            [_projection_event(event) for event in stored_events],
            expected_position=expected_position,
        )
        usage_events = [
            event for event in stored_events if event.event_type == "node_usage_recorded"
        ]
        if usage_events:
            await self.apply_run_usage_events(run_id, usage_events)
        return stored_events

    async def read_run(
        self,
        run_id: str,
        from_position: int = 0,
        limit: int | None = None,
    ) -> list[EventEnvelope]:
        """Read graph events for a run ordered by run-local position."""
        stmt = (
            select(EventV2Model)
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.version >= from_position)
            .order_by(EventV2Model.version)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        events: list[EventEnvelope] = []
        for row in result.scalars():
            payload = json.loads(row.payload)
            events.append(EventEnvelope.model_validate(payload))
        return events

    async def read_bounded_full_event_page(
        self,
        run_id: str,
        *,
        from_position: int,
        limit: int,
        payload_byte_cap: int,
    ) -> list[BoundedFullGraphEvent]:
        """Read a page of full-event identities without decoding oversized bodies.

        The SQL ``CASE`` is important: a length probe alone would still select
        the raw event JSON into Python.  A body over the public payload cap is
        represented truthfully as unavailable/truncated instead of being
        decoded before the response budget can take effect.
        """
        if limit < 1:
            raise ValueError("limit must be positive")
        if payload_byte_cap < 1:
            raise ValueError("payload_byte_cap must be positive")
        payload_json = func.json_extract(EventV2Model.payload, "$.payload")
        payload_size = _json_utf8_byte_length(payload_json)
        result = await self._session.execute(
            select(
                EventV2Model.event_type,
                EventV2Model.version,
                EventV2Model.timestamp,
                func.json_extract(EventV2Model.payload, "$.event_id").label("event_id"),
                payload_size.label("payload_size"),
                case(
                    (payload_size <= payload_byte_cap, payload_json),
                    else_=None,
                ).label("bounded_payload"),
            )
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.version >= from_position)
            .order_by(EventV2Model.version)
            .limit(limit)
        )
        return [
            BoundedFullGraphEvent(
                event_id=str(row.event_id or f"graph-event-{row.version}"),
                event_type=str(row.event_type),
                run_id=run_id,
                position=int(row.version),
                timestamp=str(row.timestamp),
                payload_json=(
                    str(row.bounded_payload) if row.bounded_payload is not None else None
                ),
                payload_original_bytes=int(row.payload_size or 0),
            )
            for row in result
        ]

    async def read_artifact_content_hashes(self, run_ids: list[str]) -> frozenset[str]:
        """Read durable artifact mark facts without scanning event JSON history."""
        if not run_ids:
            return frozenset()
        result = await self._session.execute(
            select(GraphArtifactReferenceModel.content_hash)
            .where(GraphArtifactReferenceModel.run_id.in_(run_ids))
            .order_by(GraphArtifactReferenceModel.content_hash)
        )
        return frozenset(str(content_hash) for content_hash in result.scalars())

    async def append_artifact_references(
        self,
        run_id: str,
        events: list[EventEnvelope],
    ) -> None:
        """Persist exact artifact authorization facts with accepted graph output.

        This table is deliberately not a lossy API summary.  It is the durable
        authorization projection for CAS blobs, so an artifact request can use
        its primary key instead of searching JSON event payloads.
        """
        references = _artifact_references_from_events(events)
        if not references:
            return
        for position, ref in references:
            key = (run_id, ref.content_hash)
            row = await self._session.get(GraphArtifactReferenceModel, key)
            if row is None:
                self._session.add(
                    GraphArtifactReferenceModel(
                        run_id=run_id,
                        content_hash=ref.content_hash,
                        artifact_id=ref.artifact_id,
                        size_bytes=ref.size_bytes,
                        media_type=ref.media_type,
                        encoding=ref.encoding,
                        storage_uri=ref.storage_uri,
                        position=position,
                    )
                )
                continue
            # A content hash has one immutable identity.  Retaining the first
            # accepted reference makes duplicate output idempotent while a
            # conflicting claimed identity remains unavailable for serving.
            if (
                row.artifact_id != ref.artifact_id
                or row.size_bytes != ref.size_bytes
                or row.storage_uri != ref.storage_uri
            ):
                raise ValueError(
                    f"conflicting durable artifact reference for {run_id}:{ref.content_hash}"
                )
        await self._session.flush()

    async def read_authorized_artifact_reference(
        self,
        run_id: str,
        content_hash: str,
    ) -> dict[str, Any] | None:
        """Read one durable indexed artifact authorization fact.

        No request-path fallback examines ``events_v2``.  A missing durable
        fact is intentionally unavailable until the writer/recovery path has
        projected an accepted reference, rather than making range latency scale
        with the complete graph history.
        """
        row = await self._session.get(GraphArtifactReferenceModel, (run_id, content_hash))
        if row is None:
            return None
        return {
            "artifact_id": row.artifact_id,
            "content_hash": row.content_hash,
            "size_bytes": row.size_bytes,
            "media_type": row.media_type,
            "encoding": row.encoding,
            "storage_uri": row.storage_uri,
        }

    async def read_bounded_graph_health(
        self,
        run_id: str,
        detail_limit: int = 20,
    ) -> BoundedGraphHealth:
        """Read only compact, bounded facts suitable for graph health.

        The authoritative stream is consulted solely through scalar ``count``
        and ``max(version)`` queries to prove whether the disposable compact
        event summary is current.  No event payload, projection snapshot, or
        checkpoint is selected here.  If that proof fails, callers must expose
        unavailable facts rather than replaying history on the request path.
        """
        if detail_limit < 1:
            raise ValueError("detail_limit must be positive")
        aggregate_id = graph_aggregate_id(run_id)
        event_row = (
            await self._session.execute(
                select(func.count(), func.max(EventV2Model.version)).where(
                    EventV2Model.aggregate_id == aggregate_id
                )
            )
        ).one()
        event_count, event_position = int(event_row[0] or 0), int(event_row[1] or 0)
        summary_row = (
            await self._session.execute(
                select(func.count(), func.max(GraphEventSummaryModel.position)).where(
                    GraphEventSummaryModel.run_id == run_id
                )
            )
        ).one()
        summary_count, summary_position = int(summary_row[0] or 0), int(summary_row[1] or 0)
        summaries_complete = (
            event_count == summary_count
            and event_position == summary_position
            and not await self._has_over_budget_summary_candidate_id(run_id)
        )
        if not summaries_complete:
            return BoundedGraphHealth(
                event_count=event_position,
                summaries_complete=False,
                run_state=None,
                patches_accepted=None,
                patches_rejected=None,
                patch_decisions=(),
                patch_decisions_total=None,
                patch_decisions_truncated=False,
                verifier_passed=None,
                verifier_failed=None,
                verifier_results=(),
                verifier_results_total=None,
                verifier_results_truncated=False,
            )
        if event_count == 0:
            return BoundedGraphHealth(
                event_count=0,
                summaries_complete=True,
                run_state=None,
                patches_accepted=0,
                patches_rejected=0,
                patch_decisions=(),
                patch_decisions_total=0,
                patch_decisions_truncated=False,
                verifier_passed=0,
                verifier_failed=0,
                verifier_results=(),
                verifier_results_total=0,
                verifier_results_truncated=False,
            )
        run_state = await self._bounded_health_run_state(run_id)
        patches = await self._bounded_health_patch_facts(run_id, detail_limit)
        verifiers = await self._bounded_health_verifier_facts(run_id, detail_limit)
        return BoundedGraphHealth(
            event_count=event_position,
            summaries_complete=True,
            run_state=run_state,
            patches_accepted=patches[0],
            patches_rejected=patches[1],
            patch_decisions=patches[2],
            patch_decisions_total=patches[3],
            patch_decisions_truncated=patches[3] > detail_limit,
            verifier_passed=verifiers[0],
            verifier_failed=verifiers[1],
            verifier_results=verifiers[2],
            verifier_results_total=verifiers[3],
            verifier_results_truncated=verifiers[3] > detail_limit,
        )

    async def _has_over_budget_summary_candidate_id(self, run_id: str) -> bool:
        """Reject legacy compact rows that can leak an unbounded candidate ID."""
        candidate_id = func.json_extract(GraphEventSummaryModel.payload, "$.candidate_id")
        count = await self._session.scalar(
            select(func.count())
            .select_from(GraphEventSummaryModel)
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(
                GraphEventSummaryModel.event_type.in_(
                    ("verification_passed", "verification_failed")
                )
            )
            .where(candidate_id.is_not(None))
            .where(func.length(func.hex(candidate_id)) > MAX_SUMMARY_CANDIDATE_ID_BYTES * 2)
        )
        return bool(count)

    async def _bounded_health_run_state(self, run_id: str) -> str | None:
        result = await self._session.execute(
            select(func.json_extract(GraphEventSummaryModel.payload, "$.to_state"))
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(GraphEventSummaryModel.event_type == "run_lifecycle_changed")
            .order_by(
                GraphEventSummaryModel.position.desc(), GraphEventSummaryModel.event_id.desc()
            )
            .limit(1)
        )
        value = result.scalar_one_or_none()
        return value if isinstance(value, str) else None

    async def _bounded_health_patch_facts(
        self, run_id: str, detail_limit: int
    ) -> tuple[int, int, tuple[dict[str, Any], ...], int]:
        patch_id = func.json_extract(GraphEventSummaryModel.payload, "$.patch_id")
        ranked = (
            select(
                GraphEventSummaryModel.event_type.label("event_type"),
                patch_id.label("patch_id"),
                func.json_extract(GraphEventSummaryModel.payload, "$.reason").label("reason"),
                GraphEventSummaryModel.position.label("position"),
                func.row_number()
                .over(
                    partition_by=patch_id,
                    order_by=(
                        GraphEventSummaryModel.position.desc(),
                        GraphEventSummaryModel.event_id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(
                GraphEventSummaryModel.event_type.in_(
                    ("graph_patch_accepted", "graph_patch_rejected")
                )
            )
            .where(patch_id.is_not(None))
            .subquery()
        )
        aggregate = (
            await self._session.execute(
                select(
                    func.sum(case((ranked.c.event_type == "graph_patch_accepted", 1), else_=0)),
                    func.sum(case((ranked.c.event_type == "graph_patch_rejected", 1), else_=0)),
                    func.count(),
                ).where(ranked.c.row_number == 1)
            )
        ).one()
        rows = (
            (
                await self._session.execute(
                    select(ranked)
                    .where(ranked.c.row_number == 1)
                    .order_by(ranked.c.position.desc(), ranked.c.patch_id.desc())
                    .limit(detail_limit + 1)
                )
            )
            .mappings()
            .all()
        )
        return (
            int(aggregate[0] or 0),
            int(aggregate[1] or 0),
            tuple(
                {
                    "patch_id": str(row["patch_id"]),
                    "decision": "accepted"
                    if row["event_type"] == "graph_patch_accepted"
                    else "rejected",
                    "reason": row["reason"] if isinstance(row["reason"], str) else None,
                }
                for row in reversed(rows[:detail_limit])
            ),
            int(aggregate[2] or 0),
        )

    async def _bounded_health_verifier_facts(
        self, run_id: str, detail_limit: int
    ) -> tuple[int, int, tuple[dict[str, Any], ...], int]:
        node_id = func.json_extract(GraphEventSummaryModel.payload, "$.verifier_node_id")
        candidate_id = func.json_extract(GraphEventSummaryModel.payload, "$.candidate_id")
        candidate_id_hashed = func.json_extract(
            GraphEventSummaryModel.payload, "$.candidate_id_hashed"
        )
        candidate_id_namespace = func.coalesce(candidate_id_hashed, 0)
        candidate_id_original_chars = func.json_extract(
            GraphEventSummaryModel.payload, "$.candidate_id_original_chars"
        )
        candidate_id_original_bytes = func.json_extract(
            GraphEventSummaryModel.payload, "$.candidate_id_original_bytes"
        )
        candidate_id_sha256 = func.json_extract(
            GraphEventSummaryModel.payload, "$.candidate_id_sha256"
        )
        ranked = (
            select(
                GraphEventSummaryModel.event_type.label("event_type"),
                node_id.label("node_id"),
                candidate_id.label("candidate_id"),
                candidate_id_hashed.label("candidate_id_hashed"),
                candidate_id_original_chars.label("candidate_id_original_chars"),
                candidate_id_original_bytes.label("candidate_id_original_bytes"),
                candidate_id_sha256.label("candidate_id_sha256"),
                GraphEventSummaryModel.position.label("position"),
                func.row_number()
                .over(
                    partition_by=(node_id, candidate_id, candidate_id_namespace),
                    order_by=(
                        GraphEventSummaryModel.position.desc(),
                        GraphEventSummaryModel.event_id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(
                GraphEventSummaryModel.event_type.in_(
                    ("verification_passed", "verification_failed")
                )
            )
            .where(node_id.is_not(None))
            .where(candidate_id.is_not(None))
            .subquery()
        )
        aggregate = (
            await self._session.execute(
                select(
                    func.sum(case((ranked.c.event_type == "verification_passed", 1), else_=0)),
                    func.sum(case((ranked.c.event_type == "verification_failed", 1), else_=0)),
                    func.count(),
                ).where(ranked.c.row_number == 1)
            )
        ).one()
        rows = (
            (
                await self._session.execute(
                    select(ranked)
                    .where(ranked.c.row_number == 1)
                    .order_by(
                        ranked.c.position.desc(),
                        ranked.c.node_id.desc(),
                        ranked.c.candidate_id.desc(),
                    )
                    .limit(detail_limit + 1)
                )
            )
            .mappings()
            .all()
        )
        return (
            int(aggregate[0] or 0),
            int(aggregate[1] or 0),
            tuple(_bounded_health_verifier_result(row) for row in reversed(rows[:detail_limit])),
            int(aggregate[2] or 0),
        )

    async def read_graph_patch_attempt_page(
        self,
        run_id: str,
        *,
        after_position: int,
        limit: int,
    ) -> GraphPatchAttemptPage:
        """Read logical patch attempts without deserializing graph history.

        JSON predicates run in SQLite and only the ``limit + 1`` selected
        identities plus their associated facts cross the JSON decoder boundary.
        A malformed unrelated event therefore cannot affect this endpoint.
        """
        if after_position < 0 or limit < 1:
            raise ValueError("after_position must be non-negative and limit must be positive")
        aggregate_id = graph_aggregate_id(run_id)
        valid_payload = func.json_valid(EventV2Model.payload) == 1
        proposal_patch_id = case(
            (valid_payload, func.json_extract(EventV2Model.payload, "$.payload.value.patch_id")),
            else_=None,
        )
        direct_patch_id = case(
            (valid_payload, func.json_extract(EventV2Model.payload, "$.payload.patch_id")),
            else_=None,
        )
        proposal_rows = (
            select(
                proposal_patch_id.label("patch_id"),
                EventV2Model.version.label("position"),
            )
            .where(EventV2Model.aggregate_id == aggregate_id)
            .where(EventV2Model.event_type == "output_record_accepted")
            .where(valid_payload)
            .where(
                func.json_extract(EventV2Model.payload, "$.payload.record_type")
                == "graph_patch_proposal"
            )
            .where(proposal_patch_id.is_not(None))
        )
        outcome_types = (
            "graph_patch_accepted",
            "graph_patch_rejected",
            "graph_patch_superseded",
            "graph_patch_outcome",
        )
        outcome_rows = (
            select(
                direct_patch_id.label("patch_id"),
                EventV2Model.version.label("position"),
            )
            .where(EventV2Model.aggregate_id == aggregate_id)
            .where(EventV2Model.event_type.in_(outcome_types))
            .where(valid_payload)
            .where(direct_patch_id.is_not(None))
        )
        candidates = union_all(proposal_rows, outcome_rows).subquery()
        identities = (
            select(candidates.c.patch_id, func.min(candidates.c.position).label("position"))
            .group_by(candidates.c.patch_id)
            .having(func.min(candidates.c.position) > after_position)
            .order_by(func.min(candidates.c.position), candidates.c.patch_id)
            .limit(limit + 1)
        )
        identity_rows = list((await self._session.execute(identities)).mappings())
        has_more = len(identity_rows) > limit
        identity_rows = identity_rows[:limit]
        patch_ids = tuple(str(row["patch_id"]) for row in identity_rows)
        if not patch_ids:
            return GraphPatchAttemptPage((), {}, {}, False, 0, 0, False)

        # These are bounded by the identity page. Creation rows participate only
        # when their durable payload patch_id exactly matches; positional
        # adjacency would incorrectly attach an unrelated node to a patch.
        selected_patch_id = case(
            (EventV2Model.event_type == "output_record_accepted", proposal_patch_id),
            else_=direct_patch_id,
        )
        association_types = (
            "output_record_accepted",
            *outcome_types,
            "node_created",
            "edge_created",
        )
        facts_base = (
            select(
                EventV2Model.position.label("position"),
                selected_patch_id.label("patch_id"),
                func.row_number()
                .over(partition_by=selected_patch_id, order_by=EventV2Model.version)
                .label("row_number"),
            )
            .where(EventV2Model.aggregate_id == aggregate_id)
            .where(EventV2Model.event_type.in_(association_types))
            .where(valid_payload)
            .where(
                (EventV2Model.event_type != "output_record_accepted")
                | (
                    func.json_extract(EventV2Model.payload, "$.payload.record_type")
                    == "graph_patch_proposal"
                )
            )
            .where(selected_patch_id.in_(patch_ids))
            .subquery()
        )
        fact_payload_json = func.json_extract(EventV2Model.payload, "$.payload")
        fact_payload_size = _json_utf8_byte_length(fact_payload_json)
        facts_stmt = (
            select(
                EventV2Model.event_type,
                EventV2Model.version,
                func.json_extract(EventV2Model.payload, "$.event_id").label("event_id"),
                case(
                    (fact_payload_size <= GRAPH_EVENT_PAYLOAD_BYTES, fact_payload_json),
                    else_=None,
                ).label("bounded_payload"),
            )
            .join(facts_base, EventV2Model.position == facts_base.c.position)
            .where(facts_base.c.row_number <= MAX_GRAPH_PATCH_FACTS_PER_ATTEMPT + 1)
            .order_by(EventV2Model.version, EventV2Model.position)
        )
        facts_by_patch_id: dict[str, list[dict[str, Any]]] = {
            patch_id: [] for patch_id in patch_ids
        }
        partial = False
        for row in await self._session.execute(facts_stmt):
            if row.bounded_payload is None:
                partial = True
                continue
            try:
                typed_payload = cast(dict[str, Any], json.loads(str(row.bounded_payload)))
            except json.JSONDecodeError:
                partial = True
                continue
            value = typed_payload.get("value")
            patch_id = (
                cast(dict[str, Any], value).get("patch_id")
                if row.event_type == "output_record_accepted" and isinstance(value, dict)
                else typed_payload.get("patch_id")
            )
            if isinstance(patch_id, str) and patch_id in facts_by_patch_id:
                facts_by_patch_id[patch_id].append(
                    {
                        "event_id": row.event_id,
                        "event_type": row.event_type,
                        "position": row.version,
                        "payload": typed_payload,
                    }
                )
        # Historical accepted patches emitted uncorrelated creation events.
        # Every accepted attempt gets the legacy continuity window: an exact
        # same-patch creation keeps it open, while a foreign correlation closes
        # it. Exact rows are deduplicated below by durable event identity.
        legacy_creation_counts: dict[str, tuple[int, int]] = {}
        for patch_id, facts in facts_by_patch_id.items():
            accepted = next(
                (fact for fact in facts if fact["event_type"] == "graph_patch_accepted"), None
            )
            if accepted is None:
                continue
            fallback_facts, fallback_counts = await self._read_legacy_patch_creation_fallback(
                run_id,
                after_position=int(accepted["position"]),
                patch_id=patch_id,
            )
            if fallback_facts:
                facts.extend(fallback_facts)
            legacy_creation_counts[patch_id] = fallback_counts
        for patch_id, facts in facts_by_patch_id.items():
            unique: dict[str, dict[str, Any]] = {}
            for fact in facts:
                event_id = fact.get("event_id")
                identity = (
                    event_id
                    if isinstance(event_id, str)
                    else f"{fact['position']}:{fact['event_type']}"
                )
                unique.setdefault(identity, fact)
            facts_by_patch_id[patch_id] = sorted(
                unique.values(),
                key=lambda fact: (int(fact["position"]), str(fact.get("event_id", ""))),
            )
        # An outcome can legitimately predate/miss a proposal during recovery;
        # retain it but make the missing association explicit to callers.
        proposal_ids = {
            patch_id
            for patch_id, facts in facts_by_patch_id.items()
            if any(fact["event_type"] == "output_record_accepted" for fact in facts)
        }
        orphan_fact_count = sum(
            len(facts)
            for patch_id, facts in facts_by_patch_id.items()
            if patch_id not in proposal_ids
        )
        capped_fact_count = sum(
            max(0, len(facts) - MAX_GRAPH_PATCH_FACTS_PER_ATTEMPT)
            for facts in facts_by_patch_id.values()
        )
        if capped_fact_count:
            for patch_id, facts in facts_by_patch_id.items():
                facts_by_patch_id[patch_id] = facts[:MAX_GRAPH_PATCH_FACTS_PER_ATTEMPT]
        creation_counts_result = await self._session.execute(
            select(
                selected_patch_id.label("patch_id"),
                EventV2Model.event_type,
                func.count().label("count"),
            )
            .where(EventV2Model.aggregate_id == aggregate_id)
            .where(EventV2Model.event_type.in_(("node_created", "edge_created")))
            .where(valid_payload)
            .where(selected_patch_id.in_(patch_ids))
            .group_by(selected_patch_id, EventV2Model.event_type)
        )
        creation_counts: dict[str, list[int]] = {patch_id: [0, 0] for patch_id in patch_ids}
        for row in creation_counts_result.mappings():
            patch_id = row.get("patch_id")
            if isinstance(patch_id, str) and patch_id in creation_counts:
                index = 0 if row.get("event_type") == "node_created" else 1
                creation_counts[patch_id][index] = int(cast(int, row["count"]))
        for patch_id, counts in legacy_creation_counts.items():
            creation_counts[patch_id][0] += counts[0]
            creation_counts[patch_id][1] += counts[1]
        return GraphPatchAttemptPage(
            proposals=tuple(
                {"patch_id": str(row["patch_id"]), "position": int(row["position"])}
                for row in identity_rows
            ),
            facts_by_patch_id={
                patch_id: tuple(facts) for patch_id, facts in facts_by_patch_id.items()
            },
            creation_counts_by_patch_id={
                patch_id: (counts[0], counts[1]) for patch_id, counts in creation_counts.items()
            },
            has_more=has_more,
            orphan_fact_count=orphan_fact_count,
            capped_fact_count=capped_fact_count,
            partial=partial or orphan_fact_count > 0 or capped_fact_count > 0,
        )

    async def _read_legacy_patch_creation_fallback(
        self,
        run_id: str,
        *,
        after_position: int,
        patch_id: str,
    ) -> tuple[list[dict[str, Any]], tuple[int, int]]:
        """Read one legacy projector-compatible creation prefix in SQL.

        ``project_graph_patch_attempts`` attaches only immediately following
        creation rows to an accepted patch. Uncorrelated legacy rows and exact
        same-patch rows participate; the first other event or foreign patch
        correlation ends the prefix. A SQLite window evaluates that boundary;
        only the cap plus one selected payloads are decoded.
        """
        aggregate_id = graph_aggregate_id(run_id)
        valid_payload = func.json_valid(EventV2Model.payload) == 1
        creation_type = EventV2Model.event_type.in_(("node_created", "edge_created"))
        payload_patch_id = case(
            (valid_payload, func.json_extract(EventV2Model.payload, "$.payload.patch_id")),
            else_=None,
        )
        is_legacy_creation = creation_type & valid_payload & payload_patch_id.is_(None)
        is_same_patch_creation = creation_type & valid_payload & (payload_patch_id == patch_id)
        is_contiguous_creation = is_legacy_creation | is_same_patch_creation
        prefix = (
            select(
                EventV2Model.position.label("position"),
                EventV2Model.event_type.label("event_type"),
                is_legacy_creation.label("is_legacy_creation"),
                func.sum(case((is_contiguous_creation, 0), else_=1))
                .over(order_by=EventV2Model.version)
                .label("boundary_count"),
            )
            .where(EventV2Model.aggregate_id == aggregate_id)
            .where(EventV2Model.version > after_position)
            .subquery()
        )
        count_result = await self._session.execute(
            select(prefix.c.event_type, func.count().label("count"))
            .where(prefix.c.boundary_count == 0)
            .where(prefix.c.is_legacy_creation)
            .group_by(prefix.c.event_type)
        )
        counts = {"node_created": 0, "edge_created": 0}
        for row in count_result.mappings():
            event_type = row.get("event_type")
            if event_type in counts:
                counts[cast(str, event_type)] = int(cast(int, row["count"]))
        payload_json = func.json_extract(EventV2Model.payload, "$.payload")
        payload_size = _json_utf8_byte_length(payload_json)
        result = await self._session.execute(
            select(
                EventV2Model.event_type,
                EventV2Model.version,
                func.json_extract(EventV2Model.payload, "$.event_id").label("event_id"),
                case(
                    (payload_size <= GRAPH_EVENT_PAYLOAD_BYTES, payload_json),
                    else_=None,
                ).label("bounded_payload"),
            )
            .join(prefix, EventV2Model.position == prefix.c.position)
            .where(prefix.c.boundary_count == 0)
            .order_by(EventV2Model.version)
            .limit(MAX_GRAPH_PATCH_FACTS_PER_ATTEMPT + 1)
        )
        facts: list[dict[str, Any]] = []
        for row in result:
            if row.bounded_payload is None:
                continue
            try:
                payload = cast(dict[str, Any], json.loads(str(row.bounded_payload)))
            except json.JSONDecodeError:
                continue
            facts.append(
                {
                    "event_id": row.event_id,
                    "event_type": row.event_type,
                    "position": row.version,
                    "payload": payload,
                }
            )
        return facts, (counts["node_created"], counts["edge_created"])

    async def read_bounded_node_evidence(
        self,
        run_id: str,
        node_ids: tuple[str, ...],
        *,
        per_node_cap: int = MAX_EVIDENCE_DIGEST_EVENTS_PER_NODE,
    ) -> BoundedNodeEvidence:
        """Read at most ``per_node_cap + 1`` relevant facts for each node.

        This intentionally does not use ``read_run`` or a projection rebuild.
        The SQL predicate first limits event types and then uses a guarded JSON
        extraction for the node ownership field.  Thus unrelated rows (even
        rows with malformed JSON) are never deserialized by this read path.
        """
        selected_ids = tuple(sorted(set(node_ids)))
        if not selected_ids:
            return BoundedNodeEvidence(
                events_by_node={},
                lease_ids_by_node={},
                truncated_node_ids=frozenset(),
            )
        if per_node_cap < 1:
            raise ValueError("per_node_cap must be positive")

        direct_types = frozenset(
            {
                "node_created",
                "node_state_changed",
                "lease_granted",
                "lease_renewed",
                "lease_suspended",
                "lease_released",
                "lease_revoked",
                "lease_expired",
            }
        )
        lease_lifecycle_types = frozenset(
            {
                "lease_granted",
                "lease_renewed",
                "lease_suspended",
                "lease_released",
                "lease_revoked",
                "lease_expired",
            }
        )
        producer_types = frozenset({"output_record_accepted", "file_state_accepted"})
        valid_payload = func.json_valid(EventV2Model.payload) == 1
        direct_node_id = case(
            (valid_payload, func.json_extract(EventV2Model.payload, "$.payload.node_id")),
            else_=None,
        )
        producer_node_id = case(
            (valid_payload, func.json_extract(EventV2Model.payload, "$.payload.producer_node_id")),
            else_=None,
        )
        owner_node_id = case(
            (EventV2Model.event_type.in_(direct_types), direct_node_id),
            (EventV2Model.event_type.in_(producer_types), producer_node_id),
            else_=None,
        )
        lease_id = case(
            (valid_payload, func.json_extract(EventV2Model.payload, "$.payload.lease_id")),
            else_=None,
        )
        # A node identity is required for display, but current lease facts must
        # win over old output history.  Within the bounded window, retain the
        # creation row first, then newest lifecycle rows, then chronological
        # ordinary evidence.  A truncated window is still explicitly partial.
        evidence_priority = case(
            (EventV2Model.event_type == "node_created", 0),
            (EventV2Model.event_type.in_(lease_lifecycle_types), 1),
            else_=2,
        )
        lifecycle_position = case(
            (EventV2Model.event_type.in_(lease_lifecycle_types), EventV2Model.version),
            else_=0,
        )
        events_by_node: dict[str, tuple[EventEnvelope, ...]] = {}
        lease_ids_by_node: dict[str, frozenset[str]] = {}
        truncated: set[str] = set()
        # Evidence bodies are not part of the digest read model.  Never select
        # an oversized raw envelope merely to find out later that it cannot be
        # represented.  The CASE keeps it in SQLite; a skipped body marks its
        # owning node partial below, which is the existing truthful digest
        # behavior for malformed selected facts.
        raw_payload_size = _json_utf8_byte_length(EventV2Model.payload)
        bounded_raw_payload = case(
            (raw_payload_size <= GRAPH_EVENT_PAYLOAD_BYTES, EventV2Model.payload),
            else_=None,
        ).label("bounded_payload")
        for node_id in selected_ids:
            # Terminal lifecycle payloads are allowed to omit ``node_id``.
            # Associate them through bounded canonical grant identities rather
            # than widening this read to all lease lifecycle history.
            grant_node_id = case(
                (valid_payload, func.json_extract(EventV2Model.payload, "$.payload.node_id")),
                else_=None,
            )
            lease_identity_result = await self._session.execute(
                select(lease_id.label("lease_id"), func.max(EventV2Model.version).label("position"))
                .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
                .where(EventV2Model.event_type == "lease_granted")
                .where(grant_node_id == node_id)
                .where(lease_id.is_not(None))
                .group_by(lease_id)
                .order_by(func.max(EventV2Model.version).desc(), lease_id)
                .limit(MAX_EVIDENCE_DIGEST_LEASE_IDENTITIES_PER_NODE + 1)
            )
            lease_identity_rows = list(lease_identity_result)
            if len(lease_identity_rows) > MAX_EVIDENCE_DIGEST_LEASE_IDENTITIES_PER_NODE:
                truncated.add(node_id)
                lease_identity_rows = lease_identity_rows[
                    :MAX_EVIDENCE_DIGEST_LEASE_IDENTITIES_PER_NODE
                ]
            lease_ids = tuple(
                str(row.lease_id) for row in lease_identity_rows if isinstance(row.lease_id, str)
            )
            lease_ids_by_node[node_id] = frozenset(lease_ids)
            association = owner_node_id == node_id
            if lease_ids:
                association = association | (
                    EventV2Model.event_type.in_(lease_lifecycle_types) & lease_id.in_(lease_ids)
                )
            result = await self._session.execute(
                select(EventV2Model.version, bounded_raw_payload)
                .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
                .where(EventV2Model.event_type.in_(direct_types | producer_types))
                .where(association)
                .order_by(evidence_priority, lifecycle_position.desc(), EventV2Model.version)
                .limit(per_node_cap + 1)
            )
            rows = list(result)
            if len(rows) > per_node_cap:
                truncated.add(node_id)
                rows = rows[:per_node_cap]
            parsed: list[EventEnvelope] = []
            for row in rows:
                if row.bounded_payload is None:
                    # The selected event is relevant but its body is over the
                    # hard decode cap.  Do not materialize it; make the
                    # representative evidence explicitly partial instead.
                    truncated.add(node_id)
                    continue
                try:
                    parsed.append(
                        EventEnvelope.model_validate(json.loads(str(row.bounded_payload)))
                    )
                except (json.JSONDecodeError, ValidationError):
                    # A selected corrupt fact is unavailable, rather than a
                    # reason to make the whole digest unavailable.
                    truncated.add(node_id)
            events_by_node[node_id] = tuple(parsed)
        return BoundedNodeEvidence(
            events_by_node=events_by_node,
            lease_ids_by_node=lease_ids_by_node,
            truncated_node_ids=frozenset(truncated),
        )

    async def read_evidence_digest_read_model(
        self,
        run_id: str,
        *,
        max_nodes: int,
    ) -> EvidenceDigestReadModel:
        """Return bounded digest facts without loading a projection checkpoint.

        Node rows are the current-state read model.  Deferred and lease facts
        use SQL windows over the compact event-summary table, so history may be
        scanned by SQLite but only aggregate rows and at most ``max_nodes``
        node summaries cross the database boundary.
        """
        selected_result = await self._session.execute(
            select(
                GraphNodeDetailSummaryModel.node_id,
                GraphNodeDetailSummaryModel.state,
                GraphNodeDetailSummaryModel.role,
            )
            .where(GraphNodeDetailSummaryModel.run_id == run_id)
            .order_by(GraphNodeDetailSummaryModel.node_id)
            .limit(max_nodes)
        )
        selected = list(selected_result)
        if not selected:
            selected = await self._fallback_digest_nodes_from_event_summaries(run_id, max_nodes)
        node_ids = tuple(str(row.node_id) for row in selected)
        deferred_by_node = await self._latest_digest_deferred_reasons(run_id, node_ids)
        summaries = tuple(
            EvidenceDigestNodeSummary(
                node_id=str(row.node_id),
                state=row.state if isinstance(getattr(row, "state", None), str) else None,
                role=row.role if isinstance(row.role, str) else None,
                deferred_reason=deferred_by_node.get(str(row.node_id)),
            )
            for row in selected
        )
        (
            ready_count,
            blocked_count,
            waiting_resource_count,
            waiting_gate_count,
        ) = await self._digest_scheduler_counts(run_id)
        active_lease_count, suspended_lease_count = await self._digest_lease_counts(run_id)
        blockers = await self._digest_scheduler_blockers(run_id, limit=100)
        return EvidenceDigestReadModel(
            node_summaries=summaries,
            ready_count=ready_count,
            blocked_count=blocked_count,
            waiting_resource_count=waiting_resource_count,
            waiting_gate_count=waiting_gate_count,
            active_lease_count=active_lease_count,
            suspended_lease_count=suspended_lease_count,
            blockers=blockers,
        )

    async def _fallback_digest_nodes_from_event_summaries(
        self,
        run_id: str,
        max_nodes: int,
    ) -> list[Any]:
        """Bounded compatibility path when disposable node rows are absent.

        Event summaries are compact.  The CTE first reduces repeated
        ``node_created`` enrichments to one identity row per node, preserving
        the earliest immutable creation state and first explicitly supplied
        role (the same merge direction used by ``merge_node_created``).  A
        later ``node_state_changed`` supersedes that initial state.  Only the
        final unique-node window crosses the database boundary.
        """
        node_id = func.json_extract(GraphEventSummaryModel.payload, "$.node_id")
        role = func.json_extract(GraphEventSummaryModel.payload, "$.role")
        initial_state = func.json_extract(GraphEventSummaryModel.payload, "$.state")
        creations_ranked = (
            select(
                node_id.label("node_id"),
                initial_state.label("initial_state"),
                func.row_number()
                .over(
                    partition_by=node_id,
                    order_by=(
                        GraphEventSummaryModel.position.asc(),
                        GraphEventSummaryModel.event_id.asc(),
                    ),
                )
                .label("row_number"),
            )
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(GraphEventSummaryModel.event_type == "node_created")
            .where(node_id.is_not(None))
            .subquery()
        )
        creations = (
            select(creations_ranked.c.node_id, creations_ranked.c.initial_state)
            .where(creations_ranked.c.row_number == 1)
            .subquery()
        )
        roles_ranked = (
            select(
                node_id.label("node_id"),
                role.label("role"),
                func.row_number()
                .over(
                    partition_by=node_id,
                    order_by=(
                        GraphEventSummaryModel.position.asc(),
                        GraphEventSummaryModel.event_id.asc(),
                    ),
                )
                .label("row_number"),
            )
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(GraphEventSummaryModel.event_type == "node_created")
            .where(node_id.is_not(None))
            .where(role.is_not(None))
            .subquery()
        )
        first_roles = (
            select(roles_ranked.c.node_id, roles_ranked.c.role)
            .where(roles_ranked.c.row_number == 1)
            .subquery()
        )
        changed_state = func.json_extract(GraphEventSummaryModel.payload, "$.new_state")
        states_ranked = (
            select(
                node_id.label("node_id"),
                changed_state.label("state"),
                func.row_number()
                .over(
                    partition_by=node_id,
                    order_by=(
                        GraphEventSummaryModel.position.desc(),
                        GraphEventSummaryModel.event_id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(GraphEventSummaryModel.event_type == "node_state_changed")
            .where(node_id.is_not(None))
            .subquery()
        )
        latest_states = (
            select(states_ranked.c.node_id, states_ranked.c.state)
            .where(states_ranked.c.row_number == 1)
            .subquery()
        )
        result = await self._session.execute(
            select(
                creations.c.node_id,
                func.coalesce(latest_states.c.state, creations.c.initial_state).label("state"),
                first_roles.c.role,
            )
            .select_from(creations)
            .outerjoin(first_roles, first_roles.c.node_id == creations.c.node_id)
            .outerjoin(latest_states, latest_states.c.node_id == creations.c.node_id)
            .order_by(creations.c.node_id)
            .limit(max_nodes)
        )
        return list(result)

    async def _digest_scheduler_blockers(self, run_id: str, *, limit: int) -> tuple[str, ...]:
        """Return a fixed window of deterministic scheduler blockers only."""
        node_id = func.json_extract(GraphEventSummaryModel.payload, "$.node_id")
        reason = func.json_extract(GraphEventSummaryModel.payload, "$.reason")
        ranked = (
            select(
                node_id.label("node_id"),
                reason.label("reason"),
                func.row_number()
                .over(partition_by=node_id, order_by=GraphEventSummaryModel.position.desc())
                .label("row_number"),
            )
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(GraphEventSummaryModel.event_type == "node_deferred")
            .subquery()
        )
        latest = (
            select(ranked.c.node_id, ranked.c.reason).where(ranked.c.row_number == 1).subquery()
        )
        creation_node_id = func.json_extract(GraphEventSummaryModel.payload, "$.node_id")
        creation_reason = func.json_extract(GraphEventSummaryModel.payload, "$.reason")
        creation_reasons_ranked = (
            select(
                creation_node_id.label("node_id"),
                creation_reason.label("reason"),
                func.row_number()
                .over(
                    partition_by=creation_node_id,
                    order_by=(
                        GraphEventSummaryModel.position.asc(),
                        GraphEventSummaryModel.event_id.asc(),
                    ),
                )
                .label("row_number"),
            )
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(GraphEventSummaryModel.event_type == "node_created")
            .where(creation_node_id.is_not(None))
            .where(creation_reason.is_not(None))
            .subquery()
        )
        # Node-created facts may be repeated as valid enrichments.  Reduce to
        # one identity/reason row before the blocker join so the subsequent
        # node-level LIMIT is applied to unique nodes, not enrichments.
        creations = (
            select(creation_reasons_ranked.c.node_id, creation_reasons_ranked.c.reason)
            .where(creation_reasons_ranked.c.row_number == 1)
            .subquery()
        )
        state = GraphNodeDetailSummaryModel.state
        candidate = (state.in_(("planned", "blocked", "ready"))) & ~(
            (state == "ready") & (latest.c.reason == "max_grants_reached")
        )
        blocked = candidate & ((state == "blocked") | latest.c.reason.is_not(None))
        result = await self._session.execute(
            select(
                GraphNodeDetailSummaryModel.node_id,
                GraphNodeDetailSummaryModel.kind,
                latest.c.reason,
                creations.c.reason.label("creation_reason"),
            )
            .select_from(GraphNodeDetailSummaryModel)
            .outerjoin(latest, latest.c.node_id == GraphNodeDetailSummaryModel.node_id)
            .outerjoin(creations, creations.c.node_id == GraphNodeDetailSummaryModel.node_id)
            .where(GraphNodeDetailSummaryModel.run_id == run_id)
            .where(blocked)
            .order_by(GraphNodeDetailSummaryModel.node_id)
            .limit(limit)
        )
        scheduler_blockers: list[str] = []
        review_blockers: list[str] = []
        for row in result:
            node = str(row.node_id)
            raw_reason = row.reason if isinstance(row.reason, str) else "blocked"
            bucket = (
                "waiting_resources"
                if raw_reason.startswith("resource_conflict")
                else "waiting_gates"
                if raw_reason.startswith("gate_not_approved")
                else "blocked"
            )
            scheduler_blockers.append(f"scheduler:{bucket}:{node}:{raw_reason}")
            if row.kind == "review" and isinstance(row.creation_reason, str):
                review_blockers.append(f"graph_review:{node}: {row.creation_reason}")
        # The public response has distinct scheduler/review categories encoded
        # in its string prefixes.  Each category has at most one entry per
        # node, and scheduler order (then review order) is deterministic.
        return tuple((*scheduler_blockers, *review_blockers))

    async def _latest_digest_deferred_reasons(
        self,
        run_id: str,
        node_ids: tuple[str, ...],
    ) -> dict[str, str]:
        if not node_ids:
            return {}
        node_id = func.json_extract(GraphEventSummaryModel.payload, "$.node_id")
        reason = func.json_extract(GraphEventSummaryModel.payload, "$.reason")
        ranked = (
            select(
                node_id.label("node_id"),
                reason.label("reason"),
                func.row_number()
                .over(partition_by=node_id, order_by=GraphEventSummaryModel.position.desc())
                .label("row_number"),
            )
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(GraphEventSummaryModel.event_type == "node_deferred")
            .where(node_id.in_(node_ids))
            .subquery()
        )
        result = await self._session.execute(
            select(ranked.c.node_id, ranked.c.reason).where(ranked.c.row_number == 1)
        )
        return {
            str(row.node_id): str(row.reason)
            for row in result
            if isinstance(row.node_id, str) and isinstance(row.reason, str)
        }

    async def _digest_scheduler_counts(self, run_id: str) -> tuple[int, int, int, int]:
        node_id = func.json_extract(GraphEventSummaryModel.payload, "$.node_id")
        reason = func.json_extract(GraphEventSummaryModel.payload, "$.reason")
        ranked = (
            select(
                node_id.label("node_id"),
                reason.label("reason"),
                func.row_number()
                .over(partition_by=node_id, order_by=GraphEventSummaryModel.position.desc())
                .label("row_number"),
            )
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(GraphEventSummaryModel.event_type == "node_deferred")
            .subquery()
        )
        latest = (
            select(ranked.c.node_id, ranked.c.reason).where(ranked.c.row_number == 1).subquery()
        )
        state = GraphNodeDetailSummaryModel.state
        scheduler_candidate = (state.in_(("planned", "blocked", "ready"))) & ~(
            (state == "ready") & (latest.c.reason == "max_grants_reached")
        )
        blocked = scheduler_candidate & ((state == "blocked") | latest.c.reason.is_not(None))
        waiting_resources = blocked & latest.c.reason.like("resource_conflict%")
        waiting_gates = blocked & latest.c.reason.like("gate_not_approved%")
        result = await self._session.execute(
            select(
                func.sum(case((state == "ready", 1), else_=0)),
                func.sum(case((blocked & ~waiting_resources & ~waiting_gates, 1), else_=0)),
                func.sum(case((waiting_resources, 1), else_=0)),
                func.sum(case((waiting_gates, 1), else_=0)),
            )
            .select_from(GraphNodeDetailSummaryModel)
            .outerjoin(latest, latest.c.node_id == GraphNodeDetailSummaryModel.node_id)
            .where(GraphNodeDetailSummaryModel.run_id == run_id)
        )
        row = result.one()
        return (
            int(row[0] or 0),
            int(row[1] or 0),
            int(row[2] or 0),
            int(row[3] or 0),
        )

    async def _digest_lease_counts(self, run_id: str) -> tuple[int, int]:
        # These are exactly the lease lifecycle events reduced by
        # ``_reduce_lease``.  Terminal transitions must participate in the
        # window: filtering them out before ROW_NUMBER would resurrect an old
        # grant as the apparent current lease.
        lifecycle_event_types = frozenset(
            {
                "lease_granted",
                "lease_renewed",
                "lease_suspended",
                "lease_released",
                "lease_revoked",
                "lease_expired",
            }
        )
        lease_id = func.json_extract(GraphEventSummaryModel.payload, "$.lease_id")
        ranked = (
            select(
                GraphEventSummaryModel.event_type.label("event_type"),
                lease_id.label("lease_id"),
                func.row_number()
                .over(
                    partition_by=lease_id,
                    order_by=(
                        GraphEventSummaryModel.position.desc(),
                        GraphEventSummaryModel.event_id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(GraphEventSummaryModel.event_type.in_(lifecycle_event_types))
            .where(lease_id.is_not(None))
            .subquery()
        )
        result = await self._session.execute(
            select(
                func.sum(
                    case((ranked.c.event_type.in_(("lease_granted", "lease_renewed")), 1), else_=0)
                ),
                func.sum(case((ranked.c.event_type == "lease_suspended", 1), else_=0)),
            ).where(ranked.c.row_number == 1)
        )
        row = result.one()
        return int(row[0] or 0), int(row[1] or 0)

    async def read_file_state_report_page(
        self,
        run_id: str,
        *,
        from_position: int,
        limit: int,
        path_limit: int,
    ) -> FileStateReportPage:
        """Read complete, bounded logical file-state boundary groups.

        Ordinary boundaries are deserialized only after the SQL event-type
        predicate and ``limit + 1`` bound have been applied. Oversized accepted
        boundaries instead use SQLite JSON extraction for a capped path page
        and aggregate counts, so a response stays useful without materializing
        an unbounded producer payload. Associated gatekeeper facts are fetched
        by the durable ``record_id``/``file_state_record_id`` relationship,
        capped per selected boundary, so verdict and cost facts cannot split a
        boundary across cursor pages.
        """
        payload_cap = GRAPH_READ_CONTRACTS["file_state"].byte_cap
        payload_size = _json_utf8_byte_length(EventV2Model.payload)
        result = await self._session.execute(
            select(
                EventV2Model.version,
                EventV2Model.event_type,
                EventV2Model.timestamp,
                func.json_extract(EventV2Model.payload, "$.event_id").label("event_id"),
                func.json_extract(EventV2Model.payload, "$.causation_id").label("causation_id"),
                func.json_extract(EventV2Model.payload, "$.correlation_id").label("correlation_id"),
                func.json_extract(EventV2Model.payload, "$.payload.record_id").label("record_id"),
                func.json_extract(EventV2Model.payload, "$.payload.record_kind").label(
                    "record_kind"
                ),
                func.json_extract(EventV2Model.payload, "$.payload.producer_node_id").label(
                    "producer_node_id"
                ),
                func.json_extract(EventV2Model.payload, "$.payload.snapshot_id").label(
                    "snapshot_id"
                ),
                func.json_extract(EventV2Model.payload, "$.payload.verdict").label("verdict"),
                case(
                    (payload_size <= payload_cap, EventV2Model.payload),
                    else_=None,
                ).label("bounded_payload"),
            )
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.event_type.in_(FILE_STATE_BOUNDARY_EVENT_TYPES))
            .where(EventV2Model.version >= from_position)
            .order_by(EventV2Model.version)
            .limit(limit + 1)
        )
        boundaries = tuple(
            [
                await self._decode_file_state_boundary(run_id, row, path_limit=path_limit)
                for row in result
            ]
        )
        selected_boundaries = boundaries[:limit]
        record_ids = tuple(
            record_id
            for event in selected_boundaries
            if event.event_type == "file_state_accepted"
            and isinstance((record_id := event.payload.get("record_id")), str)
        )
        facts, fact_counts = await self._read_file_state_gatekeeper_facts(run_id, record_ids)
        orphan_count = await self._count_orphan_file_state_gatekeeper_facts(run_id)
        return FileStateReportPage(
            boundaries=selected_boundaries,
            has_more=len(boundaries) > limit,
            associated_facts=facts,
            associated_fact_counts=fact_counts,
            orphan_gatekeeper_fact_count=orphan_count,
        )

    async def _decode_file_state_boundary(
        self,
        run_id: str,
        row: Any,
        *,
        path_limit: int,
    ) -> EventEnvelope:
        """Decode a boundary, extracting a bounded path view when it is oversized."""
        if row.bounded_payload is not None:
            return self._decode_selected_bounded_event(
                run_id,
                row,
                owner=GRAPH_READ_CONTRACTS["file_state"].owner_read_model_name,
            )
        if row.event_type != "file_state_accepted":
            return self._decode_selected_bounded_event(
                run_id,
                row,
                owner=GRAPH_READ_CONTRACTS["file_state"].owner_read_model_name,
            )
        record_id = row.record_id
        snapshot_id = row.snapshot_id
        if not isinstance(record_id, str) or not isinstance(snapshot_id, str):
            raise GraphReadModelUnavailable(
                run_id,
                GRAPH_READ_CONTRACTS["file_state"].owner_read_model_name,
                "oversized_boundary_missing_identity",
                current_position=int(row.version),
            )
        (
            path_entries,
            source_total,
            classification_counts,
        ) = await self._read_bounded_file_state_paths(
            run_id,
            position=int(row.version),
            path_limit=path_limit,
        )
        payload: dict[str, Any] = {
            "record_id": record_id,
            "record_kind": row.record_kind,
            "producer_node_id": row.producer_node_id,
            "snapshot_id": snapshot_id,
            "verdict": row.verdict,
            "classifications": path_entries,
            "_captured_source_entries_total": source_total,
            "_classification_counts": classification_counts,
        }
        return EventEnvelope(
            event_id=str(row.event_id or f"graph-event-{row.version}"),
            run_id=run_id,
            position=int(row.version),
            event_type="file_state_accepted",
            schema_version=1,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=row.timestamp,
            causation_id=str(row.causation_id) if row.causation_id is not None else None,
            correlation_id=str(row.correlation_id) if row.correlation_id is not None else None,
            payload=payload,
        )

    async def _read_bounded_file_state_paths(
        self,
        run_id: str,
        *,
        position: int,
        path_limit: int,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        """Read a first-page path view and exact aggregate counts without decoding its event."""
        source_keys = ("classifications", "residue", "tracked", "untracked", "ignored", "external")
        entries: list[dict[str, Any]] = []
        source_total = 0
        classification_counts: dict[str, int] = {}
        for source_key in source_keys:
            array_entries = (
                func.json_each(EventV2Model.payload, f"$.payload.{source_key}")
                .table_valued("key", "value")
                .alias(f"file_state_{source_key}")
            )
            count_rows = await self._session.execute(
                select(
                    func.count().label("entry_count"),
                    func.json_extract(array_entries.c.value, "$.classification").label(
                        "classification"
                    ),
                )
                .select_from(EventV2Model)
                .join(array_entries, true())
                .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
                .where(EventV2Model.version == position)
                .group_by(func.json_extract(array_entries.c.value, "$.classification"))
            )
            for count_row in count_rows:
                count = int(count_row.entry_count)
                source_total += count
                if isinstance(count_row.classification, str):
                    classification = str(count_row.classification)
                    classification_counts[classification] = (
                        classification_counts.get(classification, 0) + count
                    )
            if len(entries) >= path_limit:
                continue
            entry_rows = await self._session.execute(
                select(array_entries.c.value)
                .select_from(EventV2Model)
                .join(array_entries, true())
                .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
                .where(EventV2Model.version == position)
                .order_by(array_entries.c.key)
                .limit(path_limit - len(entries))
            )
            for entry_row in entry_rows:
                raw_entry = entry_row[0]
                if not isinstance(raw_entry, str):
                    continue
                try:
                    decoded = json.loads(raw_entry)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    entries.append(cast(dict[str, Any], decoded))
        return entries, source_total, classification_counts

    async def _read_file_state_gatekeeper_facts(
        self,
        run_id: str,
        record_ids: tuple[str, ...],
    ) -> tuple[tuple[EventEnvelope, ...], dict[str, int]]:
        if not record_ids:
            return (), {}
        payload_cap = GRAPH_READ_CONTRACTS["file_state"].byte_cap
        record_id_expr = func.json_extract(EventV2Model.payload, "$.payload.file_state_record_id")
        fact_count_result = await self._session.execute(
            select(record_id_expr.label("record_id"), func.count().label("fact_count"))
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.event_type.in_(FILE_STATE_GATEKEEPER_FACT_EVENT_TYPES))
            .where(record_id_expr.in_(record_ids))
            .group_by(record_id_expr)
        )
        fact_counts = {
            str(row.record_id): int(row.fact_count)
            for row in fact_count_result
            if isinstance(row.record_id, str)
        }
        row_number = (
            func.row_number()
            .over(
                partition_by=record_id_expr,
                order_by=EventV2Model.version,
            )
            .label("row_number")
        )
        ranked = (
            select(EventV2Model.position.label("position"), row_number)
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.event_type.in_(FILE_STATE_GATEKEEPER_FACT_EVENT_TYPES))
            .where(record_id_expr.in_(record_ids))
            .subquery()
        )
        payload_size = _json_utf8_byte_length(EventV2Model.payload)
        fact_result = await self._session.execute(
            select(
                EventV2Model.version,
                case(
                    (payload_size <= payload_cap, EventV2Model.payload),
                    else_=None,
                ).label("bounded_payload"),
            )
            .join(ranked, EventV2Model.position == ranked.c.position)
            .where(ranked.c.row_number <= MAX_FILE_STATE_GATEKEEPER_FACTS_PER_BOUNDARY)
            .order_by(EventV2Model.version)
        )
        return (
            tuple(
                self._decode_selected_bounded_event(
                    run_id,
                    row,
                    owner=GRAPH_READ_CONTRACTS["file_state"].owner_read_model_name,
                )
                for row in fact_result
            ),
            fact_counts,
        )

    @staticmethod
    def _decode_selected_bounded_event(
        run_id: str,
        row: Any,
        *,
        owner: str,
    ) -> EventEnvelope:
        """Decode a SQL-guarded event or report a truthful bounded-read failure."""
        if row.bounded_payload is None:
            raise GraphReadModelUnavailable(
                run_id,
                owner,
                "event_payload_exceeds_byte_cap",
                current_position=int(row.version),
            )
        try:
            return EventEnvelope.model_validate(json.loads(str(row.bounded_payload)))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise GraphReadModelUnavailable(
                run_id,
                owner,
                "malformed_event_payload",
                current_position=int(row.version),
            ) from exc

    async def _count_orphan_file_state_gatekeeper_facts(self, run_id: str) -> int:
        """Return a scalar count without materializing unassociated facts."""
        fact_record_id = func.json_extract(EventV2Model.payload, "$.payload.file_state_record_id")
        accepted = EventV2Model.__table__.alias("file_state_accepted")
        matching_boundary = (
            select(1)
            .select_from(accepted)
            .where(accepted.c.aggregate_id == graph_aggregate_id(run_id))
            .where(accepted.c.event_type == "file_state_accepted")
            .where(func.json_extract(accepted.c.payload, "$.payload.record_id") == fact_record_id)
            .exists()
        )
        result = await self._session.execute(
            select(func.count())
            .select_from(EventV2Model)
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.event_type.in_(FILE_STATE_GATEKEEPER_FACT_EVENT_TYPES))
            .where(~matching_boundary)
        )
        return int(result.scalar_one())

    async def read_run_positions(
        self,
        run_id: str,
        positions: list[int],
    ) -> list[EventEnvelope]:
        """Read bounded full graph events for exact run-local positions.

        Node-detail ``payload_mode=full`` is a public read path.  It may only
        hydrate bodies which passed the same UTF-8 byte contract as full event
        pages; an oversized retained position is a retryable unavailable read
        model, never an accidental full JSON decode.
        """
        unique_positions = sorted(
            {position for position in positions if position > 0 and not isinstance(position, bool)}
        )
        if not unique_positions:
            return []
        payload_size = _json_utf8_byte_length(EventV2Model.payload)
        result = await self._session.execute(
            select(
                EventV2Model.version,
                payload_size.label("payload_size"),
                case(
                    (payload_size <= GRAPH_EVENT_PAYLOAD_BYTES, EventV2Model.payload),
                    else_=None,
                ).label("bounded_payload"),
            )
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.version.in_(unique_positions))
            .order_by(EventV2Model.version)
        )
        events: list[EventEnvelope] = []
        for row in result:
            if row.bounded_payload is None:
                raise GraphReadModelUnavailable(
                    run_id,
                    GRAPH_READ_CONTRACTS["node_detail"].owner_read_model_name,
                    "full_event_payload_exceeds_byte_cap",
                    current_position=int(row.version),
                )
            payload = json.loads(str(row.bounded_payload))
            events.append(EventEnvelope.model_validate(payload))
        return events

    async def read_run_light(self, run_id: str, from_position: int = 0) -> list[EventEnvelope]:
        """Read graph events with only projection/search payload fields.

        This avoids selecting and validating the full JSON payload column for
        callback/output/file-state bodies. Use ``read_run`` only when an API or
        runtime path explicitly needs complete payloads.
        """
        return await self._read_run_extracting_fields(
            run_id,
            from_position,
            LIGHT_GRAPH_PAYLOAD_FIELDS,
            "light",
        )

    async def read_run_summary_rebuild(
        self,
        run_id: str,
        from_position: int = 0,
        limit: int | None = None,
    ) -> list[EventEnvelope]:
        """Read only fields needed to rebuild compact graph summaries and snapshots."""
        return await self._read_run_extracting_fields(
            run_id,
            from_position,
            SUMMARY_REBUILD_PAYLOAD_FIELDS,
            "summary",
            include_nested_value_fallbacks=False,
            limit=limit,
        )

    async def read_run_projection(
        self,
        run_id: str,
        from_position: int = 0,
        limit: int | None = None,
    ) -> list[EventEnvelope]:
        """Read only fields needed for the compact ``/graph`` projection."""
        return await self._read_run_extracting_fields(
            run_id,
            from_position,
            GRAPH_PROJECTION_PAYLOAD_FIELDS,
            "projection",
            include_nested_value_fallbacks=False,
            limit=limit,
        )

    async def read_current_bounded_projection_history(
        self,
        run_id: str,
        *,
        contract_key: Literal["topology", "final_blockers", "regions"],
    ) -> list[EventEnvelope]:
        """Return a complete, explicitly bounded projection-history view.

        These legacy derived endpoints need history facts that are not owned by
        the compact projection snapshot.  A request must therefore never fold
        an arbitrary stream merely because it happens to be available.  Read a
        one-row sentinel beyond the published contract instead; a larger
        stream is truthfully unavailable until a dedicated durable view exists.
        """
        contract = GRAPH_READ_CONTRACTS[contract_key]
        cap = contract.budget.sql_row_cap
        events = await self.read_run_projection(run_id, limit=cap + 1)
        if len(events) > cap:
            raise GraphReadModelUnavailable(
                run_id,
                contract.owner_read_model_name,
                "history_exceeds_bounded_view_cap",
                current_position=events[-1].position,
            )
        return events

    async def read_run_node_detail(
        self,
        run_id: str,
        from_position: int = 0,
        limit: int | None = None,
    ) -> list[EventEnvelope]:
        """Read fields needed for summary node detail without large payload bodies."""
        return await self._read_run_extracting_fields(
            run_id,
            from_position,
            NODE_DETAIL_PAYLOAD_FIELDS,
            "node_detail",
            limit=limit,
        )

    async def _read_run_extracting_fields(
        self,
        run_id: str,
        from_position: int,
        fields: tuple[str, ...],
        retention_mode: RetentionMode,
        *,
        include_nested_value_fallbacks: bool = True,
        limit: int | None = None,
    ) -> list[EventEnvelope]:
        payload_selects = [
            func.json_extract(EventV2Model.payload, f"$.payload.{field}").label(
                f"__payload_{field}"
            )
            for field in fields
        ]
        payload_type_selects = [
            func.json_type(EventV2Model.payload, f"$.payload.{field}").label(
                f"__payload_type_{field}"
            )
            for field in fields
        ]
        nested_payload_selects = [
            func.json_extract(EventV2Model.payload, "$.payload.value.status").label(
                "__value_status"
            ),
            func.json_extract(EventV2Model.payload, "$.payload.value.classification").label(
                "__value_classification"
            ),
            func.json_extract(EventV2Model.payload, "$.payload.value.outcome").label(
                "__value_outcome"
            ),
            func.json_extract(EventV2Model.payload, "$.payload.value.grades").label(
                "__value_grades"
            ),
            *[
                func.json_extract(EventV2Model.payload, f"$.payload.value.{field}").label(
                    f"__decision_value_{field}"
                )
                for field in DECISION_RECORD_VALUE_FIELDS
            ],
        ]
        stmt = (
            select(
                EventV2Model.event_type,
                EventV2Model.version,
                EventV2Model.timestamp,
                func.json_extract(EventV2Model.payload, "$.event_id").label("event_id"),
                func.json_extract(EventV2Model.payload, "$.causation_id").label("causation_id"),
                func.json_extract(EventV2Model.payload, "$.correlation_id").label("correlation_id"),
                *payload_selects,
                *payload_type_selects,
                *nested_payload_selects,
            )
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.version >= from_position)
            .order_by(EventV2Model.version)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)

        events: list[EventEnvelope] = []
        for row in result.mappings():
            event_type = str(row["event_type"])
            retained_fields = getattr(EVENT_PAYLOAD_SPECS[event_type], retention_mode)
            payload = {
                field: _json_extract_payload_value(field, row[f"__payload_{field}"])
                for field in retained_fields
                if row.get(f"__payload_{field}") is not None
                or (
                    row.get(f"__payload_type_{field}") == "null"
                    and EVENT_PAYLOAD_SPECS[event_type].model.model_fields[field].is_required()
                )
            }
            if (
                include_nested_value_fallbacks
                and "status" in fields
                and "status" not in payload
                and row.get("__value_status")
            ):
                payload["status"] = _json_extract_value(row["__value_status"])
            if (
                include_nested_value_fallbacks
                and "classification" in fields
                and "classification" not in payload
                and row.get("__value_classification")
            ):
                payload["classification"] = _json_extract_value(row["__value_classification"])
            if _is_verification_report_payload(payload):
                value_payload: dict[str, Any] = {}
                value_outcome = row.get("__value_outcome")
                if value_outcome is not None:
                    value_payload["outcome"] = _json_extract_value(value_outcome)
                value_grades = row.get("__value_grades")
                if value_grades is not None:
                    value_payload["grades"] = _json_extract_value(value_grades)
                if value_payload:
                    payload["value"] = value_payload
            record_type = payload.get("record_type")
            port = payload.get("port")
            if record_type in {
                "decision_record",
                "authority_decision",
                "decision_request",
                "authority_request_record",
            } or port in {
                "decision_record",
                "authority_decision",
                "decision_request",
                "authority_request_record",
            }:
                value_payload = {
                    field: _json_extract_value(row[f"__decision_value_{field}"])
                    for field in DECISION_RECORD_VALUE_FIELDS
                    if row.get(f"__decision_value_{field}") is not None
                }
                if value_payload:
                    payload["value"] = value_payload
            if event_type in {"output_record_accepted", "file_state_accepted"}:
                # These durable record-envelope fields are writer-assigned,
                # not supplied by the event's nested payload.  Projection
                # reduction needs them to preserve record identity and
                # topology record positions during a narrow rebuild.
                payload["graph_position"] = int(row["version"])
                payload["run_id"] = run_id
            events.append(
                EventEnvelope(
                    event_id=str(row.get("event_id") or f"graph-event-{row['version']}"),
                    run_id=run_id,
                    position=int(row["version"]),
                    event_type=event_type,
                    schema_version=1,
                    actor=Actor(kind=ActorKind.CONTROLLER),
                    causation_id=(
                        str(row["causation_id"]) if row.get("causation_id") is not None else None
                    ),
                    correlation_id=(
                        str(row["correlation_id"])
                        if row.get("correlation_id") is not None
                        else None
                    ),
                    timestamp=datetime.fromisoformat(str(row["timestamp"])),
                    payload=payload,
                )
            )
        return events

    async def read_run_summaries(
        self,
        run_id: str,
        from_position: int = 0,
        limit: int | None = None,
    ) -> list[GraphEventSummary]:
        """Read compact graph event rows without materializing large payloads."""
        await self.ensure_event_summaries(run_id)
        stmt = (
            select(GraphEventSummaryModel)
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(GraphEventSummaryModel.position >= from_position)
            .order_by(GraphEventSummaryModel.position)
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        summaries = [
            GraphEventSummary(
                event_id=row.event_id,
                event_type=row.event_type,
                run_id=row.run_id,
                position=row.position,
                timestamp=row.timestamp,
                payload=dict(row.payload),
            )
            for row in result.scalars()
        ]
        return summaries

    async def read_current_run_summary_page(
        self,
        run_id: str,
        *,
        from_position: int,
        limit: int,
    ) -> list[GraphEventSummary]:
        """Read a bounded current summary page without repairing it on demand.

        Public API consumers must not turn a missing or stale disposable summary
        into a request-time replay of the authoritative stream.  Explicit
        maintenance callers retain ``rebuild_read_models`` for that work.
        """
        current = await self.current_position(run_id)
        summary_state = (
            await self._session.execute(
                select(func.count(), func.max(GraphEventSummaryModel.position)).where(
                    GraphEventSummaryModel.run_id == run_id
                )
            )
        ).one()
        summary_count = int(summary_state[0] or 0)
        summary_position = int(summary_state[1] or 0)
        if summary_count != current or summary_position != current:
            raise GraphReadModelUnavailable(
                run_id,
                GRAPH_READ_CONTRACTS["events_summary"].owner_read_model_name,
                "missing_or_stale",
                current_position=current,
            )
        result = await self._session.execute(
            select(GraphEventSummaryModel)
            .where(GraphEventSummaryModel.run_id == run_id)
            .where(GraphEventSummaryModel.position >= from_position)
            .order_by(GraphEventSummaryModel.position)
            .limit(limit)
        )
        return [
            GraphEventSummary(
                event_id=row.event_id,
                event_type=row.event_type,
                run_id=row.run_id,
                position=row.position,
                timestamp=row.timestamp,
                payload=dict(row.payload),
            )
            for row in result.scalars()
        ]

    async def read_current_node_detail_summary(
        self,
        run_id: str,
        node_id: str,
    ) -> GraphNodeDetailSummary | None:
        """Read a current compact node view without a request-time rebuild."""
        current = await self.current_position(run_id)
        if current == 0:
            return None
        checkpoint = await self._session.get(GraphNodeDetailSummaryCheckpointModel, run_id)
        if checkpoint is None or checkpoint.position != current:
            raise GraphReadModelUnavailable(
                run_id,
                GRAPH_READ_CONTRACTS["node_detail"].owner_read_model_name,
                "missing_or_stale",
                current_position=current,
            )
        row = await self._session.get(
            GraphNodeDetailSummaryModel,
            {"run_id": run_id, "node_id": node_id},
        )
        if row is None and await self._node_exists_in_authoritative_events(run_id, node_id):
            # A current checkpoint says the compact owner should contain every
            # graph node.  Do not turn a corrupted individual row into a
            # request-time rebuild: that would make a GET mutate durable state
            # and replay the authority stream.  The endpoint maps this typed
            # error to a retryable 503 instead.  Unknown node IDs remain a
            # normal 404 below.
            raise GraphReadModelUnavailable(
                run_id,
                GRAPH_READ_CONTRACTS["node_detail"].owner_read_model_name,
                "missing_owner_row",
                current_position=current,
            )
        return _node_detail_summary_from_row(row) if row is not None else None

    async def _node_exists_in_authoritative_events(self, run_id: str, node_id: str) -> bool:
        """Return whether the authoritative stream created ``node_id``.

        This is a scalar existence probe, not an event replay.  Every graph
        node originates from ``node_created``; using that fact lets the public
        compact read distinguish a deleted owner row from a genuinely unknown
        node without repairing the read model on demand.
        """
        position = await self._session.scalar(
            select(EventV2Model.position)
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.event_type == "node_created")
            .where(func.json_extract(EventV2Model.payload, "$.payload.node_id") == node_id)
            .limit(1)
        )
        return position is not None

    async def read_current_projection_snapshot(
        self,
        run_id: str,
    ) -> GraphProjectionSnapshotModel | None:
        """Read a valid current projection snapshot without rebuilding history."""
        current = await self.current_position(run_id)
        if current == 0:
            return None
        snapshot = await self._session.get(GraphProjectionSnapshotModel, run_id)
        if snapshot is None or snapshot.position != current:
            raise GraphReadModelUnavailable(
                run_id,
                GRAPH_READ_CONTRACTS["graph"].owner_read_model_name,
                "missing_or_stale",
                current_position=current,
            )
        if not checkpoint_schema_is_current(_projection_schema_version_from_snapshot_row(snapshot)):
            raise GraphReadModelUnavailable(
                run_id,
                GRAPH_READ_CONTRACTS["graph"].owner_read_model_name,
                "schema_mismatch",
                current_position=current,
            )
        # The API snapshot is intentionally whole-owner packed and therefore
        # need not remain decodable as a *full* execution checkpoint once a
        # collection has been capped.  Decoding it here would falsely classify
        # a healthy bounded response as corrupt and, historically, trigger a
        # request-time full replay.  Runtime checkpoint consumers retain their
        # stricter integrity decoder in ``read_projection_checkpoint``.
        return snapshot

    async def read_node_detail_summary(
        self,
        run_id: str,
        node_id: str,
    ) -> GraphNodeDetailSummary | None:
        """Read one compact node-detail summary, rebuilding if disposable rows are stale."""
        await self.ensure_node_detail_summaries(run_id)
        row = await self._session.get(
            GraphNodeDetailSummaryModel,
            {"run_id": run_id, "node_id": node_id},
        )
        if row is None and await self.current_position(run_id) > 0:
            await self.rebuild_node_detail_summaries(run_id)
            row = await self._session.get(
                GraphNodeDetailSummaryModel,
                {"run_id": run_id, "node_id": node_id},
            )
        return _node_detail_summary_from_row(row) if row is not None else None

    async def read_projection_snapshot(
        self,
        run_id: str,
    ) -> GraphProjectionSnapshotModel | None:
        """Read the current materialized graph projection, rebuilding if stale."""
        await self.ensure_projection_snapshot(run_id)
        return await self._session.get(GraphProjectionSnapshotModel, run_id)

    async def read_projection_checkpoint(
        self,
        run_id: str,
    ) -> GraphProjectionCheckpoint | None:
        """Read a valid full-projection checkpoint without forcing a rebuild."""
        row = await self._session.get(GraphProjectionSnapshotModel, run_id)
        schema_version = _projection_schema_version_from_snapshot_row(row)
        if row is None or not checkpoint_schema_is_current(schema_version):
            return None
        try:
            projection = _projection_from_snapshot_row(row)
        except (
            ValidationError,
            ProjectionCheckpointCodecError,
            ProjectionCheckpointIntegrityError,
        ):
            return None
        if projection is None:
            return None
        return GraphProjectionCheckpoint(
            run_id=run_id,
            position=row.position,
            projection=projection,
            schema_version=schema_version,
            terminal=_projection_terminal_from_snapshot_row(row),
        )

    async def read_current_projection_view(self, run_id: str) -> GraphProjectionCheckpoint | None:
        """Return the current durable projection for a public derived view.

        Unlike runtime recovery, a public read never repairs a missing snapshot
        by replaying authority history.  The caller gets a typed unavailable
        error and can retry after the writer/recovery maintenance advances the
        durable checkpoint.
        """
        current = await self.current_position(run_id)
        if current == 0:
            return None
        checkpoint = await self.read_projection_checkpoint(run_id)
        if checkpoint is None or checkpoint.position != current:
            raise GraphReadModelUnavailable(
                run_id,
                "graph_projection_snapshot",
                "missing_or_stale",
                current_position=current,
            )
        return checkpoint

    async def read_current_materialized_view(
        self,
        run_id: str,
        view_name: Literal["topology", "final_blockers", "regions"],
    ) -> tuple[int, dict[str, Any]] | None:
        """Legacy compatibility reader for pre-archival snapshot adjuncts.

        Public routes use :meth:`read_current_archival_view_page`; retaining
        this narrow method avoids breaking internal callers while old database
        files are migrated and rebuilt.
        """
        current = await self.current_position(run_id)
        if current == 0:
            return None
        snapshot = await self._session.get(GraphProjectionSnapshotModel, run_id)
        if snapshot is None or snapshot.position != current:
            raise GraphReadModelUnavailable(
                run_id,
                f"graph_{view_name}_view",
                "missing_or_stale",
                current_position=current,
            )
        views = snapshot.decisions.get(_MATERIALIZED_VIEWS_KEY)
        typed_views = cast(dict[str, Any], views) if isinstance(views, dict) else {}
        view = typed_views.get(view_name)
        if not isinstance(view, dict):
            raise GraphReadModelUnavailable(
                run_id,
                f"graph_{view_name}_view",
                "missing_or_oversized",
                current_position=current,
            )
        return snapshot.position, cast(dict[str, Any], view)

    async def read_current_archival_view_page(
        self,
        run_id: str,
        view_name: Literal["topology", "final_blockers", "regions"],
        *,
        after_sequence: int,
        limit: int,
    ) -> tuple[int, BoundedGraphPage[dict[str, Any]]] | None:
        """Read one exact, keyset-paginated archival view without replaying events.

        The independent checkpoint is deliberately separate from the compact
        projection snapshot: an expansive topology must not consume the
        decision owner's JSON budget or make a GET silently fold history.
        """
        current = await self.current_position(run_id)
        if current == 0:
            return None
        checkpoint = await self._session.get(GraphArchivalViewCheckpointModel, run_id)
        owner = GRAPH_READ_CONTRACTS[view_name].owner_read_model_name
        if checkpoint is None or checkpoint.position != current:
            raise GraphReadModelUnavailable(
                run_id,
                owner,
                "missing_or_stale",
                current_position=current,
            )

        if view_name == "topology":
            total_known = int(
                await self._session.scalar(
                    select(func.count())
                    .select_from(GraphTopologyViewEntryModel)
                    .where(GraphTopologyViewEntryModel.run_id == run_id)
                )
                or 0
            )
            result = await self._session.execute(
                select(GraphTopologyViewEntryModel)
                .where(GraphTopologyViewEntryModel.run_id == run_id)
                .where(GraphTopologyViewEntryModel.sequence > after_sequence)
                .order_by(GraphTopologyViewEntryModel.sequence)
                .limit(limit)
            )
            rows = list(result.scalars())
            items = [{**dict(row.payload), "_entry_kind": row.entry_kind} for row in rows]
        elif view_name == "final_blockers":
            total_known = int(
                await self._session.scalar(
                    select(func.count())
                    .select_from(GraphFinalBlockerViewEntryModel)
                    .where(GraphFinalBlockerViewEntryModel.run_id == run_id)
                )
                or 0
            )
            result = await self._session.execute(
                select(GraphFinalBlockerViewEntryModel)
                .where(GraphFinalBlockerViewEntryModel.run_id == run_id)
                .where(GraphFinalBlockerViewEntryModel.sequence > after_sequence)
                .order_by(GraphFinalBlockerViewEntryModel.sequence)
                .limit(limit)
            )
            rows = list(result.scalars())
            items = [dict(row.payload) for row in rows]
        else:
            total_known = int(
                await self._session.scalar(
                    select(func.count())
                    .select_from(GraphRegionViewEntryModel)
                    .where(GraphRegionViewEntryModel.run_id == run_id)
                )
                or 0
            )
            result = await self._session.execute(
                select(GraphRegionViewEntryModel)
                .where(GraphRegionViewEntryModel.run_id == run_id)
                .where(GraphRegionViewEntryModel.sequence > after_sequence)
                .order_by(GraphRegionViewEntryModel.sequence)
                .limit(limit)
            )
            rows = list(result.scalars())
            items = [dict(row.payload) for row in rows]
        next_cursor = rows[-1].sequence if rows and rows[-1].sequence < total_known else None
        return checkpoint.position, BoundedGraphPage(
            items=tuple(items),
            truncated=next_cursor is not None,
            total_known=total_known,
            next_cursor=next_cursor,
        )

    async def load_projection_with_tail(
        self,
        run_id: str,
    ) -> tuple[GraphProjection, list[EventEnvelope], int]:
        """Load the latest valid snapshot and fold only events after it.

        If the checkpoint is missing, version-mismatched, or malformed, recover
        only from the fixed runtime replay window.  Runtime callers must never
        turn a corrupt disposable checkpoint into an unbounded database read:
        a larger recovery is an explicitly unavailable runtime read model.
        """
        checkpoint = await self.read_projection_checkpoint(run_id)
        if checkpoint is None:
            events = await self._read_runtime_event_window(run_id, from_position=0)
            projection = _projection_from_events(events)
            position = _events_position(events)
            if position > 0:
                await self.persist_projection_snapshot(run_id, projection, position)
                await self._session.commit()
            return projection, events, position

        tail = await self._read_runtime_event_window(run_id, from_position=checkpoint.position + 1)
        projection = checkpoint.projection
        for event in tail:
            projection = reduce_event(projection, _projection_event(event))
        position = max(checkpoint.position, _events_position(tail))
        if position != checkpoint.position:
            await self.persist_projection_snapshot(run_id, projection, position)
            await self._session.commit()
        return projection, tail, position

    async def _read_runtime_event_window(
        self,
        run_id: str,
        *,
        from_position: int,
    ) -> list[EventEnvelope]:
        """Read the bounded recovery tail required by the runtime contract."""
        contract = GRAPH_READ_CONTRACTS["runtime"]
        cap = contract.budget.decode_cap
        events = await self._read_bounded_event_envelopes(
            run_id,
            from_position=from_position,
            limit=cap + 1,
            owner=contract.owner_read_model_name,
        )
        if len(events) > cap:
            raise GraphReadModelUnavailable(
                run_id,
                contract.owner_read_model_name,
                "recovery_tail_exceeds_bounded_cap",
                current_position=events[-1].position,
            )
        return events

    async def _read_bounded_event_envelopes(
        self,
        run_id: str,
        *,
        from_position: int,
        limit: int,
        owner: str,
    ) -> list[EventEnvelope]:
        """Decode a fixed event window only after SQL has enforced byte caps."""
        payload_size = _json_utf8_byte_length(EventV2Model.payload)
        result = await self._session.execute(
            select(
                EventV2Model.version,
                case(
                    (payload_size <= GRAPH_EVENT_PAYLOAD_BYTES, EventV2Model.payload),
                    else_=None,
                ).label("bounded_payload"),
            )
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.version >= from_position)
            .order_by(EventV2Model.version)
            .limit(limit)
        )
        events: list[EventEnvelope] = []
        for row in result:
            if row.bounded_payload is None:
                raise GraphReadModelUnavailable(
                    run_id,
                    owner,
                    "event_payload_exceeds_byte_cap",
                    current_position=int(row.version),
                )
            try:
                events.append(EventEnvelope.model_validate(json.loads(str(row.bounded_payload))))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise GraphReadModelUnavailable(
                    run_id,
                    owner,
                    "malformed_event_payload",
                    current_position=int(row.version),
                ) from exc
        return events

    async def read_bounded_runtime_events(
        self,
        run_id: str,
        *,
        from_position: int = 0,
    ) -> list[EventEnvelope]:
        """Read execution facts only when their required window is bounded.

        Runtime consumers must use this instead of ``read_run``.  A durable
        checkpoint owns current scheduling state; this small event window is
        reserved for the few execution facts that have not yet been promoted
        into that checkpoint.  If a caller needs more than the published
        window, it must pause/retry for a dedicated read model rather than
        silently replaying the authority log.
        """
        return await self._read_runtime_event_window(run_id, from_position=from_position)

    async def read_bounded_runtime_projection_facts(
        self,
        run_id: str,
    ) -> list[EventEnvelope] | None:
        """Return complete runtime diagnostics only when they fit the tail cap.

        The execution checkpoint remains authoritative for scheduling.  The
        optional history facts only improve diagnostic reasons, so a large run
        deliberately omits them instead of performing a full replay.
        """
        contract = GRAPH_READ_CONTRACTS["runtime"]
        cap = contract.budget.decode_cap
        try:
            events = await self._read_bounded_event_envelopes(
                run_id,
                from_position=0,
                limit=cap + 1,
                owner=contract.owner_read_model_name,
            )
        except GraphReadModelUnavailable:
            return None
        return events if len(events) <= cap else None

    async def ensure_read_models(self, run_id: str) -> None:
        """Rebuild disposable graph read models if missing or behind events_v2."""
        await self.ensure_event_summaries(run_id)
        await self.ensure_projection_snapshot(run_id)
        await self.ensure_node_detail_summaries(run_id)

    async def ensure_event_summaries(self, run_id: str) -> None:
        """Rebuild compact event summaries if missing or behind events_v2."""
        current = await self.current_position(run_id)
        count = await self._session.scalar(
            select(func.count())
            .select_from(GraphEventSummaryModel)
            .where(GraphEventSummaryModel.run_id == run_id)
        )
        summary_count = int(count or 0)
        if current == 0:
            if summary_count:
                await self.delete_read_models(run_id)
            return
        if summary_count != current:
            await self.rebuild_read_models(run_id)

    async def ensure_projection_snapshot(self, run_id: str) -> None:
        """Rebuild current-state graph snapshot if missing or behind events_v2."""
        current = await self.current_position(run_id)
        snapshot = await self._session.get(GraphProjectionSnapshotModel, run_id)
        if current == 0:
            if snapshot is not None:
                await self.delete_read_models(run_id)
            return
        rebuild_required = (
            snapshot is None
            or snapshot.position != current
            or not checkpoint_schema_is_current(
                _projection_schema_version_from_snapshot_row(snapshot)
            )
        )
        if not rebuild_required:
            try:
                rebuild_required = _projection_from_snapshot_row(snapshot) is None
            except (
                ValidationError,
                ProjectionCheckpointCodecError,
                ProjectionCheckpointIntegrityError,
            ):
                rebuild_required = True
        if rebuild_required:
            await self.rebuild_read_models(run_id)

    async def ensure_node_detail_summaries(self, run_id: str) -> None:
        """Rebuild compact node-detail rows if missing or behind events_v2."""
        current = await self.current_position(run_id)
        checkpoint = await self._session.get(GraphNodeDetailSummaryCheckpointModel, run_id)
        if current == 0:
            if checkpoint is not None:
                await self.delete_node_detail_summaries(run_id)
            return
        if checkpoint is None or checkpoint.position != current:
            await self.rebuild_node_detail_summaries(run_id)

    async def append_event_summaries(
        self,
        run_id: str,
        events: list[EventEnvelope],
    ) -> None:
        """Append compact summary rows for newly stored graph events."""
        if not events:
            return
        self._session.add_all(
            [
                GraphEventSummaryModel(
                    run_id=summary.run_id,
                    position=summary.position,
                    event_id=summary.event_id,
                    event_type=summary.event_type,
                    timestamp=summary.timestamp,
                    payload=summary.payload,
                )
                for summary in (summarize_graph_event(event) for event in events)
            ]
        )
        await self._session.flush()

    async def append_node_detail_summaries(
        self,
        run_id: str,
        events: list[EventEnvelope],
        *,
        expected_position: int,
    ) -> None:
        """Incrementally maintain compact node-detail rows for newly appended events."""
        if not events:
            return

        current_position = max(event.position for event in events)
        checkpoint = await self._session.get(GraphNodeDetailSummaryCheckpointModel, run_id)
        if checkpoint is not None and checkpoint.position != expected_position:
            await self.delete_node_detail_summaries(run_id)
            return
        if checkpoint is None and expected_position != 0:
            await self.delete_node_detail_summaries(run_id)
            return

        existing_node_ids = await self._node_detail_node_ids(run_id)
        if _has_missing_preexisting_node_reference(events, existing_node_ids):
            await self.delete_node_detail_summaries(run_id)
            return
        lease_update_ids = _lease_update_ids(events)
        lease_rows = await self._node_detail_rows_for_leases(run_id, lease_update_ids)
        rows = await self._node_detail_rows_for_events(
            run_id,
            events,
            existing_node_ids | set(lease_rows),
        )
        rows.update(lease_rows)
        summaries = {node_id: _node_detail_summary_from_row(row) for node_id, row in rows.items()}
        edge_ports = await self._edge_ports_for_input_bounds(run_id, events)
        updated = _apply_node_detail_events(
            run_id,
            events,
            position=current_position,
            existing_node_ids=existing_node_ids | set(summaries),
            summaries=summaries,
            edge_ports=edge_ports,
        )
        for summary in updated.values():
            row = rows.get(summary.node_id)
            if row is None:
                row = GraphNodeDetailSummaryModel(run_id=run_id, node_id=summary.node_id)
                self._session.add(row)
            _assign_node_detail_summary(row, summary)

        if checkpoint is None:
            checkpoint = GraphNodeDetailSummaryCheckpointModel(run_id=run_id, position=0)
            self._session.add(checkpoint)
        checkpoint.position = current_position
        await self._session.flush()

    async def advance_projection_snapshot(
        self,
        run_id: str,
        events: list[EventEnvelope],
        *,
        expected_position: int,
    ) -> None:
        """Incrementally maintain the full projection checkpoint for appends."""
        if not events:
            return
        row = await self._session.get(GraphProjectionSnapshotModel, run_id)
        projection: GraphProjection | None = (
            initial_projection() if row is None and expected_position == 0 else None
        )
        if projection is None:
            invalid_cache = (
                row is None
                or row.position != expected_position
                or not checkpoint_schema_is_current(
                    _projection_schema_version_from_snapshot_row(row)
                )
            )
            if not invalid_cache:
                try:
                    projection = _projection_from_snapshot_row(row)
                except (
                    ValidationError,
                    ProjectionCheckpointCodecError,
                    ProjectionCheckpointIntegrityError,
                ):
                    invalid_cache = True
            if not invalid_cache:
                invalid_cache = projection is None
            if not invalid_cache:
                assert projection is not None
            else:
                await self._session.execute(
                    delete(GraphProjectionSnapshotModel).where(
                        GraphProjectionSnapshotModel.run_id == run_id
                    )
                )
                await self._session.flush()
                return
        for event in events:
            projection = reduce_event(projection, event)
        await self.persist_projection_snapshot(
            run_id,
            projection,
            expected_position + len(events),
        )

    async def persist_projection_snapshot(
        self,
        run_id: str,
        projection: GraphProjection,
        position: int,
    ) -> GraphProjectionSnapshotModel:
        """Persist a full projection checkpoint plus compact API columns."""
        row = await self._session.get(GraphProjectionSnapshotModel, run_id)
        if row is None:
            row = GraphProjectionSnapshotModel(run_id=run_id)
            self._session.add(row)
        _assign_projection_snapshot(row, run_id, projection, position)
        await self._sync_archival_projection_views(run_id, projection, position)
        await self._session.flush()
        return row

    async def _sync_archival_projection_views(
        self,
        run_id: str,
        projection: GraphProjection,
        position: int,
    ) -> None:
        """Synchronize exact archival read owners from one projection state.

        These owners are intentionally allowed to hold every row.  The public
        byte/page budgets apply when rendering a page, whereas persisted
        topology, blockers, and regions must stay complete for later pages.

        An event append must not delete and recreate every archival row.  In
        addition to creating needless write amplification, that briefly makes
        a committed projection look empty to another reader.  Stable sequence
        rows are therefore updated in place and only the obsolete suffix is
        removed.  A projection's entries are ordered deterministically, so a
        changed prefix naturally replaces the corresponding primary keys.
        """
        topology = cast(dict[str, Any], project_graph_topology([], projection=projection))
        topology_rows: list[tuple[int, str, str, dict[str, Any]]] = []
        sequence = 0
        for entry_kind in ("node", "edge"):
            maybe_entries = topology.get(f"{entry_kind}s", [])
            raw_entries = (
                cast(list[Mapping[str, Any]], maybe_entries)
                if isinstance(maybe_entries, list)
                else []
            )
            for raw_entry in raw_entries:
                entry: dict[str, Any] = dict(raw_entry)
                entry_id = entry.get(f"{entry_kind}_id")
                if not isinstance(entry_id, str):
                    continue
                sequence += 1
                topology_rows.append((sequence, entry_kind, entry_id, dict(entry)))
        for sequence, entry_kind, entry_id, payload in topology_rows:
            row = await self._session.get(
                GraphTopologyViewEntryModel, {"run_id": run_id, "sequence": sequence}
            )
            if row is None:
                self._session.add(
                    GraphTopologyViewEntryModel(
                        run_id=run_id,
                        sequence=sequence,
                        entry_kind=entry_kind,
                        entry_id=entry_id,
                        payload=payload,
                    )
                )
            else:
                row.entry_kind = entry_kind
                row.entry_id = entry_id
                row.payload = payload
        await self._session.execute(
            delete(GraphTopologyViewEntryModel)
            .where(GraphTopologyViewEntryModel.run_id == run_id)
            .where(GraphTopologyViewEntryModel.sequence > len(topology_rows))
        )

        blockers = project_final_invariant_blockers([], projection=projection)
        for sequence, blocker in enumerate(blockers, start=1):
            row = await self._session.get(
                GraphFinalBlockerViewEntryModel, {"run_id": run_id, "sequence": sequence}
            )
            if row is None:
                self._session.add(
                    GraphFinalBlockerViewEntryModel(
                        run_id=run_id, sequence=sequence, payload=dict(blocker)
                    )
                )
            else:
                row.payload = dict(blocker)
        await self._session.execute(
            delete(GraphFinalBlockerViewEntryModel)
            .where(GraphFinalBlockerViewEntryModel.run_id == run_id)
            .where(GraphFinalBlockerViewEntryModel.sequence > len(blockers))
        )
        task_states = task_states_view(projection)
        blockers_by_region: dict[str, list[dict[str, Any]]] = {}
        for blocker in blockers:
            region = blocker.get("task_region_id")
            if isinstance(region, str) and region:
                blockers_by_region.setdefault(region, []).append(dict(blocker))
        region_ids = sorted(set(task_states) | set(blockers_by_region))
        for sequence, region_id in enumerate(region_ids, start=1):
            payload = {
                "task_region_id": region_id,
                "state": task_states.get(region_id, "blocked"),
                "blockers": blockers_by_region.get(region_id, []),
            }
            row = await self._session.get(
                GraphRegionViewEntryModel, {"run_id": run_id, "sequence": sequence}
            )
            if row is None:
                self._session.add(
                    GraphRegionViewEntryModel(
                        run_id=run_id,
                        sequence=sequence,
                        task_region_id=region_id,
                        payload=payload,
                    )
                )
            else:
                row.task_region_id = region_id
                row.payload = payload
        await self._session.execute(
            delete(GraphRegionViewEntryModel)
            .where(GraphRegionViewEntryModel.run_id == run_id)
            .where(GraphRegionViewEntryModel.sequence > len(region_ids))
        )
        checkpoint = await self._session.get(GraphArchivalViewCheckpointModel, run_id)
        if checkpoint is None:
            checkpoint = GraphArchivalViewCheckpointModel(run_id=run_id, position=position)
            self._session.add(checkpoint)
        else:
            checkpoint.position = position

    async def commit_read_model_changes(self) -> None:
        """Persist disposable read-model rebuilds performed during API reads."""
        await self._session.commit()

    async def delete_read_models(self, run_id: str) -> None:
        """Delete disposable graph read models for a run."""
        await self._session.execute(
            delete(GraphEventSummaryModel).where(GraphEventSummaryModel.run_id == run_id)
        )
        await self._session.execute(
            delete(GraphProjectionSnapshotModel).where(
                GraphProjectionSnapshotModel.run_id == run_id
            )
        )
        await self._session.execute(
            delete(GraphTopologyViewEntryModel).where(GraphTopologyViewEntryModel.run_id == run_id)
        )
        await self._session.execute(
            delete(GraphFinalBlockerViewEntryModel).where(
                GraphFinalBlockerViewEntryModel.run_id == run_id
            )
        )
        await self._session.execute(
            delete(GraphRegionViewEntryModel).where(GraphRegionViewEntryModel.run_id == run_id)
        )
        await self._session.execute(
            delete(GraphArchivalViewCheckpointModel).where(
                GraphArchivalViewCheckpointModel.run_id == run_id
            )
        )
        await self.delete_node_detail_summaries(run_id, flush=False)
        await self._session.flush()

    async def delete_node_detail_summaries(self, run_id: str, *, flush: bool = True) -> None:
        """Delete disposable compact node-detail rows for a run."""
        await self._session.execute(
            delete(GraphNodeDetailSummaryModel).where(GraphNodeDetailSummaryModel.run_id == run_id)
        )
        await self._session.execute(
            delete(GraphNodeDetailSummaryCheckpointModel).where(
                GraphNodeDetailSummaryCheckpointModel.run_id == run_id
            )
        )
        if flush:
            await self._session.flush()

    async def rebuild_read_models(
        self,
        run_id: str,
        *,
        batch_size: int = GRAPH_READ_MODEL_REBUILD_BATCH_EVENTS,
    ) -> GraphProjectionSnapshotModel | None:
        """Rebuild disposable graph read owners in fixed-size keyset batches.

        Maintenance must not load an arbitrary run history into one Python
        list.  Each owner reads the next position window through its narrow
        extraction contract, advances the durable owner rows, and discards the
        batch before continuing.  ``from_position`` is a keyset cursor rather
        than an offset, so a caller can safely repeat this work after a
        transaction rollback without a growing scan.
        """
        if batch_size < 1:
            raise ValueError("batch_size must be positive")

        await self.delete_read_models(run_id)
        projection = initial_projection()
        from_position = 1
        position = 0
        await self.reset_run_usage_read_model(run_id)

        while True:
            projection_events = await self.read_run_projection(
                run_id, from_position=from_position, limit=batch_size
            )
            if not projection_events:
                break
            summary_events = await self.read_run_summary_rebuild(
                run_id, from_position=from_position, limit=batch_size
            )
            node_detail_events = await self.read_run_node_detail(
                run_id, from_position=from_position, limit=batch_size
            )

            # All narrow readers use the same keyset window.  Treat a partial
            # owner extraction as corruption rather than silently publishing
            # a checkpoint that skipped an authoritative position.
            batch_end = projection_events[-1].position
            if (
                not summary_events
                or not node_detail_events
                or summary_events[-1].position != batch_end
                or node_detail_events[-1].position != batch_end
            ):
                raise GraphReadModelUnavailable(
                    run_id,
                    "graph_read_model_rebuild",
                    "incomplete_keyset_batch",
                    current_position=batch_end,
                )

            await self.append_event_summaries(run_id, summary_events)
            await self.append_artifact_references(run_id, summary_events)
            await self.append_node_detail_summaries(
                run_id,
                node_detail_events,
                expected_position=position,
            )
            for event in projection_events:
                projection = reduce_event(projection, event)
            await self.apply_run_usage_events(run_id, summary_events)
            position = batch_end
            from_position = batch_end + 1

        if position == 0:
            return None
        snapshot = await self.persist_projection_snapshot(run_id, projection, position)
        return snapshot

    async def replace_run_usage_read_model(
        self,
        run_id: str,
        events: list[EventEnvelope],
    ) -> None:
        """Replace graph-run usage read fields from a caller-provided full replay."""
        await self.reset_run_usage_read_model(run_id)
        await self.apply_run_usage_events(run_id, events)

    async def reset_run_usage_read_model(self, run_id: str) -> None:
        """Remove disposable graph usage facts while preserving legacy usage."""
        run_model = await self._session.get(RunModel, run_id)
        if run_model is None:
            return
        existing = list(run_model.token_usage_by_model or [])
        graph_entries = [
            entry for entry in existing if isinstance(entry.get("graph_usage_key"), str)
        ]
        legacy_entries = [
            entry for entry in existing if not isinstance(entry.get("graph_usage_key"), str)
        ]
        graph_index_zero = [
            entry
            for entry in graph_entries
            if str(entry["graph_usage_key"]).rsplit(":", 1)[-1] == "0"
        ]
        # Runs predating R04 may contain untagged usage and rollup totals.  Only
        # tagged graph facts are disposable; remove their contribution before
        # replaying, leaving the historical baseline intact.
        run_model.token_usage_by_model = legacy_entries
        run_model.total_duration_ms = max(
            0,
            (run_model.total_duration_ms or 0)
            - sum(int(entry.get("latency_ms", 0)) for entry in graph_index_zero),
        )
        run_model.total_num_actions = max(
            0,
            (run_model.total_num_actions or 0)
            - sum(int(entry.get("graph_usage_num_actions", 0)) for entry in graph_index_zero),
        )
        await self._session.flush()

    async def apply_run_usage_events(
        self,
        run_id: str,
        events: list[EventEnvelope],
        *,
        run_model: RunModel | None = None,
    ) -> None:
        """Incrementally project newly committed graph usage facts without replaying history."""
        model = run_model or await self._session.get(RunModel, run_id)
        if model is None:
            return
        existing = list(model.token_usage_by_model or [])
        recorded_keys = {
            entry["graph_usage_key"]
            for entry in existing
            if isinstance(entry.get("graph_usage_key"), str)
        }
        for event in events:
            if event.event_type != "node_usage_recorded":
                continue
            usage = NodeUsageRecordedPayload.model_validate(event.payload)
            if usage.usage_key in recorded_keys:
                continue
            usage_record = ModelTokenUsage(
                model=usage.model,
                gen_ai_usage_input_tokens=usage.gen_ai_usage_input_tokens,
                gen_ai_usage_output_tokens=usage.gen_ai_usage_output_tokens,
                gen_ai_usage_cache_read_input_tokens=usage.gen_ai_usage_cache_read_input_tokens,
                gen_ai_usage_cache_creation_input_tokens=usage.gen_ai_usage_cache_creation_input_tokens,
                gen_ai_usage_reasoning_output_tokens=usage.gen_ai_usage_reasoning_output_tokens,
                gen_ai_response_finish_reasons=usage.gen_ai_response_finish_reasons,
                cost_usd=usage.cost_usd,
                latency_ms=usage.latency_ms,
                rate_missing=usage.rate_missing,
                graph_usage_key=usage.usage_key,
                graph_usage_num_actions=usage.num_actions if usage.usage_index == 0 else None,
            ).model_dump(mode="json")
            usage_record["graph_usage_key"] = usage.usage_key
            if usage.usage_index == 0:
                usage_record["graph_usage_num_actions"] = usage.num_actions
            graph_entry: dict[str, object] = usage_record
            existing.append(graph_entry)
            recorded_keys.add(usage.usage_key)
            if usage.usage_index == 0:
                model.total_duration_ms = (model.total_duration_ms or 0) + usage.latency_ms
                model.total_num_actions = (model.total_num_actions or 0) + usage.num_actions
        model.token_usage_by_model = existing
        await self._session.flush()

    async def rebuild_node_detail_summaries(self, run_id: str) -> None:
        """Rebuild disposable compact node-detail rows for a run from events_v2."""
        await self.delete_node_detail_summaries(run_id)
        events = await self.read_run_node_detail(run_id)
        if not events:
            return
        position = max(event.position for event in events)
        _add_node_detail_summaries(
            self._session,
            _node_detail_summaries_from_events(run_id, events, position=position),
        )
        self._session.add(GraphNodeDetailSummaryCheckpointModel(run_id=run_id, position=position))
        await self._session.flush()

    async def _node_detail_node_ids(self, run_id: str) -> set[str]:
        result = await self._session.execute(
            select(GraphNodeDetailSummaryModel.node_id).where(
                GraphNodeDetailSummaryModel.run_id == run_id
            )
        )
        return {str(node_id) for node_id in result.scalars()}

    async def _node_detail_rows_for_events(
        self,
        run_id: str,
        events: list[EventEnvelope],
        known_node_ids: set[str],
    ) -> dict[str, GraphNodeDetailSummaryModel]:
        node_ids: set[str] = set()
        for event in events:
            light_event = _node_detail_light_event(event)
            node_ids.update(_referenced_node_ids(light_event.payload, known_node_ids | node_ids))
        if not node_ids:
            return {}
        result = await self._session.execute(
            select(GraphNodeDetailSummaryModel)
            .where(GraphNodeDetailSummaryModel.run_id == run_id)
            .where(GraphNodeDetailSummaryModel.node_id.in_(sorted(node_ids)))
        )
        return {row.node_id: row for row in result.scalars()}

    async def _node_detail_rows_for_leases(
        self,
        run_id: str,
        lease_ids: set[str],
    ) -> dict[str, GraphNodeDetailSummaryModel]:
        if not lease_ids:
            return {}
        result = await self._session.execute(
            select(GraphNodeDetailSummaryModel).where(GraphNodeDetailSummaryModel.run_id == run_id)
        )
        rows: dict[str, GraphNodeDetailSummaryModel] = {}
        for row in result.scalars():
            active_lease = row.active_lease
            if isinstance(active_lease, dict) and active_lease.get("lease_id") in lease_ids:
                rows[row.node_id] = row
                continue
            for lease in row.leases:
                if (
                    isinstance(lease, dict)
                    and cast(dict[str, Any], lease).get("lease_id") in lease_ids
                ):
                    rows[row.node_id] = row
                    break
        return rows

    async def _edge_ports_for_input_bounds(
        self,
        run_id: str,
        events: list[EventEnvelope],
    ) -> dict[str, str]:
        edge_ids = _input_bound_edge_ids_needing_ports(events)
        if not edge_ids:
            return {}
        edge_id_expr = func.json_extract(EventV2Model.payload, "$.payload.edge_id")
        result = await self._session.execute(
            select(
                edge_id_expr.label("edge_id"),
                func.json_extract(EventV2Model.payload, "$.payload.to_port").label("to_port"),
            )
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.event_type == "edge_created")
            .where(edge_id_expr.in_(sorted(edge_ids)))
        )
        ports: dict[str, str] = {}
        for row in result.mappings():
            edge_id = row.get("edge_id")
            to_port = row.get("to_port")
            if isinstance(edge_id, str) and isinstance(to_port, str):
                ports[edge_id] = to_port
        return ports

    async def read_run_summaries_from_events(
        self,
        run_id: str,
        from_position: int = 0,
    ) -> list[GraphEventSummary]:
        """Legacy replay summary path retained for parity tests and fallback analysis."""
        aggregate_id = graph_aggregate_id(run_id)
        normal_result = await self._session.execute(
            select(EventV2Model)
            .where(EventV2Model.aggregate_id == aggregate_id)
            .where(EventV2Model.version >= from_position)
            .where(EventV2Model.event_type.not_in(HEAVY_GRAPH_EVENT_TYPES))
            .order_by(EventV2Model.version)
        )
        summaries = [
            _summary_from_event(EventEnvelope.model_validate(json.loads(row.payload)))
            for row in normal_result.scalars()
        ]

        heavy_selects = [
            func.json_extract(EventV2Model.payload, f"$.payload.{field}").label(field)
            for field in SUMMARY_PAYLOAD_FIELDS
        ]
        heavy_result = await self._session.execute(
            select(
                EventV2Model.event_type,
                EventV2Model.version,
                EventV2Model.timestamp,
                func.json_extract(EventV2Model.payload, "$.event_id").label("event_id"),
                *heavy_selects,
            )
            .where(EventV2Model.aggregate_id == aggregate_id)
            .where(EventV2Model.version >= from_position)
            .where(EventV2Model.event_type.in_(HEAVY_GRAPH_EVENT_TYPES))
            .order_by(EventV2Model.version)
        )
        for row in heavy_result.mappings():
            payload = {
                field: row[field] for field in SUMMARY_PAYLOAD_FIELDS if row.get(field) is not None
            }
            _compact_summary_candidate_id(payload)
            event_id = row.get("event_id")
            summaries.append(
                GraphEventSummary(
                    event_id=str(event_id or f"graph-event-{row['version']}"),
                    event_type=str(row["event_type"]),
                    run_id=run_id,
                    position=int(row["version"]),
                    timestamp=str(row["timestamp"]),
                    payload=payload,
                )
            )
        return sorted(summaries, key=lambda event: event.position)

    async def current_position(self, run_id: str) -> int:
        result = await self._session.execute(
            select(func.max(EventV2Model.version)).where(
                EventV2Model.aggregate_id == graph_aggregate_id(run_id)
            )
        )
        return int(result.scalar_one_or_none() or 0)


def summarize_graph_event(event: EventEnvelope) -> GraphEventSummary:
    if event.event_type == "edge_created":
        edge_payload = _bounded_event_payload_for_storage(
            _summarize_edge_created_payload(event.payload)
        )
        return GraphEventSummary(
            event_id=event.event_id,
            event_type=event.event_type,
            run_id=event.run_id,
            position=event.position,
            timestamp=event.timestamp.isoformat(),
            payload=edge_payload,
        )
    payload = {
        key: value
        for key, value in event.payload.items()
        if key in SUMMARY_PAYLOAD_FIELDS
        or key
        in {
            "blockers",
            "graph_verifier_grades",
            "patch_ops",
            "patch_rejection_reasons",
            "tokens_by_node",
            "tokens_by_node_kind",
        }
    }
    ops = event.payload.get("ops") or event.payload.get("operations")
    if isinstance(ops, list):
        payload["patch_ops"] = len(cast(list[Any], ops))
    value = event.payload.get("value")
    if isinstance(value, dict):
        typed_value = cast(dict[str, Any], value)
        grades = typed_value.get("grades")
        if grades is not None:
            value_summary: dict[str, Any] = {"grades": grades}
            outcome = typed_value.get("outcome")
            if isinstance(outcome, str):
                value_summary["outcome"] = outcome
            payload["value"] = value_summary
    grades = event.payload.get("grades")
    if grades is not None:
        payload["grades"] = grades
    _compact_summary_candidate_id(payload)
    payload = _bounded_event_payload_for_storage(payload)
    return GraphEventSummary(
        event_id=event.event_id,
        event_type=event.event_type,
        run_id=event.run_id,
        position=event.position,
        timestamp=event.timestamp.isoformat(),
        payload=payload,
    )


def _compact_summary_candidate_id(payload: dict[str, Any]) -> None:
    """Replace oversized candidate identities with stable compact summary metadata."""
    candidate_id = payload.get("candidate_id")
    if not isinstance(candidate_id, str):
        return
    candidate_id_bytes = candidate_id.encode()
    if len(candidate_id_bytes) <= MAX_SUMMARY_CANDIDATE_ID_BYTES:
        return
    candidate_id_sha256 = sha256(candidate_id_bytes).hexdigest()
    payload["candidate_id"] = f"sha256:{candidate_id_sha256}"
    payload["candidate_id_hashed"] = True
    payload["candidate_id_original_chars"] = len(candidate_id)
    payload["candidate_id_original_bytes"] = len(candidate_id_bytes)
    payload["candidate_id_sha256"] = candidate_id_sha256


def _bounded_health_verifier_result(row: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "node_id": str(row["node_id"]),
        "candidate_id": str(row["candidate_id"]),
        "verdict": "passed" if row["event_type"] == "verification_passed" else "failed",
    }
    if row["candidate_id_hashed"]:
        result["candidate_id_hashed"] = True
        original_chars = row["candidate_id_original_chars"]
        original_bytes = row["candidate_id_original_bytes"]
        candidate_id_sha256 = row["candidate_id_sha256"]
        if isinstance(original_chars, int):
            result["candidate_id_original_chars"] = original_chars
        if isinstance(original_bytes, int):
            result["candidate_id_original_bytes"] = original_bytes
        if isinstance(candidate_id_sha256, str):
            result["candidate_id_sha256"] = candidate_id_sha256
    return result


def _summarize_edge_created_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return only normalized, bounded edge identity facts for timelines."""
    nested = payload.get("edge")
    source = cast(dict[str, Any], nested) if isinstance(nested, dict) else payload
    summary: dict[str, Any] = {}
    partial = False
    for field in ("edge_id", "from_node_id", "to_node_id", "dependency_type", "patch_id"):
        value = source.get(field)
        if not isinstance(value, str):
            continue
        if len(value) <= MAX_SUMMARY_EDGE_STRING_CHARS:
            summary[field] = value
            continue
        partial = True
        summary[f"{field}_truncated"] = True
        summary[f"{field}_original_chars"] = len(value)
        summary[f"{field}_sha256"] = sha256(value.encode()).hexdigest()
    if partial:
        summary["summary_partial"] = True
    return summary


def _summary_from_event(event: EventEnvelope) -> GraphEventSummary:
    return summarize_graph_event(event)


def _projection_event(event: EventEnvelope) -> EventEnvelope:
    """Return the same retained event shape used by projection rebuilds.

    Appends arrive with the full authoritative payload, while rebuilds select
    only ``GRAPH_PROJECTION_PAYLOAD_FIELDS`` from SQLite.  Reducing different
    event shapes made a live compact checkpoint diverge from its bounded
    rebuild.  Keep projection state deliberately independent of discarded
    payload bodies in both paths.
    """
    retained_fields = EVENT_PAYLOAD_SPECS[event.event_type].projection
    payload = {field: event.payload[field] for field in retained_fields if field in event.payload}
    record_type = payload.get("record_type")
    port = payload.get("port")
    if record_type in {
        "decision_record",
        "authority_decision",
        "decision_request",
        "authority_request_record",
    } or port in {
        "decision_record",
        "authority_decision",
        "decision_request",
        "authority_request_record",
    }:
        nested_value = event.payload.get("value")
        if isinstance(nested_value, Mapping):
            decision_value: dict[str, Any] = {
                field: nested_value[field]
                for field in DECISION_RECORD_VALUE_FIELDS
                if field in nested_value
            }
            if decision_value:
                payload["value"] = decision_value
    if event.event_type in {"output_record_accepted", "file_state_accepted"}:
        payload["graph_position"] = event.position
        payload["run_id"] = event.run_id
    return event.model_copy(update={"payload": payload})


def _assign_projection_snapshot(
    row: GraphProjectionSnapshotModel,
    run_id: str,
    projection: GraphProjection,
    position: int,
    *,
    events: list[EventEnvelope] | None = None,
) -> None:
    row.run_id = run_id
    row.position = position
    row.run_state = query_run_state(projection)
    if events is None:
        decisions = dict(project_decision_view_from_projection(projection))
    else:
        decisions = dict(project_decision_view(events))
    bounded, metadata = _bounded_pydantic_owner_for_storage(
        {
            "node_states": dict(node_states_view(projection)),
            "task_states": dict(task_states_view(projection)),
            "leases": project_leases([], projection=projection),
            "ready_nodes": sorted(ready_nodes_view(projection)),
            "scheduler": dict(project_scheduler_view([], projection=projection)),
            "lease_view": dict(project_lease_view([], projection=projection)),
            "decisions": decisions,
        },
        _ProjectionOwnerReadModel,
        "graph",
    )
    row.node_states = cast(dict[str, str], bounded["node_states"])
    row.task_states = cast(dict[str, str], bounded["task_states"])
    row.leases = cast(dict[str, dict[str, Any]], bounded["leases"])
    row.ready_nodes = cast(list[str], bounded["ready_nodes"])
    row.scheduler = cast(dict[str, Any], bounded["scheduler"])
    row.lease_view = cast(dict[str, Any], bounded["lease_view"])
    row.decisions = _decisions_with_projection_checkpoint(
        cast(dict[str, Any], bounded["decisions"]),
        projection,
        metadata,
    )
    _pack_projection_snapshot_row(row)


def _projection_from_events(events: list[EventEnvelope]) -> GraphProjection:
    """Build a checkpoint from the same retained event shape used by appends.

    Runtime recovery may need full envelopes for command planning, but a
    durable projection must not depend on fields excluded from its bounded
    rebuild reader.
    """
    return build_projection([_projection_event(event) for event in events])


def _projection_from_snapshot_row(
    row: GraphProjectionSnapshotModel | None,
) -> GraphProjection | None:
    if row is None:
        return None
    raw_projection = row.decisions.get(_CHECKPOINT_PROJECTION_KEY)
    if not isinstance(raw_projection, dict):
        return None
    return projection_from_checkpoint(cast(dict[str, Any], raw_projection))


def _projection_schema_version_from_snapshot_row(
    row: GraphProjectionSnapshotModel | None,
) -> int | None:
    if row is None:
        return None
    schema_version = row.decisions.get(_CHECKPOINT_SCHEMA_VERSION_KEY)
    if isinstance(schema_version, int) and not isinstance(schema_version, bool):
        return schema_version
    return None


def _projection_terminal_from_snapshot_row(row: GraphProjectionSnapshotModel | None) -> bool:
    if row is None:
        return False
    terminal = row.decisions.get(_CHECKPOINT_TERMINAL_KEY)
    return bool(terminal) if isinstance(terminal, bool) else False


def _decisions_with_projection_checkpoint(
    decisions: dict[str, Any],
    projection: GraphProjection,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        **decisions,
        _CHECKPOINT_SCHEMA_VERSION_KEY: PROJECTION_SCHEMA_VERSION,
        _CHECKPOINT_TERMINAL_KEY: _is_terminal_run_state(query_run_state(projection)),
        _READ_CONTRACT_KEY: {
            "revision": GRAPH_READ_CONTRACT_REVISION,
            "collections": metadata,
        },
    }
    checkpoint = projection_to_checkpoint(projection)
    checkpoint_budget = replace(
        GRAPH_READ_CONTRACTS["runtime"].budget,
        object_entry_cap=GRAPH_FIXED_VIEW_ITEMS,
        array_item_cap=GRAPH_FIXED_VIEW_ITEMS,
        depth_cap=64,
    )
    bounded_checkpoint = bound_graph_json(checkpoint, checkpoint_budget)
    if not bounded_checkpoint["truncated"]:
        result[_CHECKPOINT_PROJECTION_KEY] = bounded_checkpoint["value"]
    else:
        result[_READ_CONTRACT_KEY]["checkpoint"] = {
            "truncated": True,
            "original_bytes": bounded_checkpoint["original_bytes"],
            "sha256": bounded_checkpoint["sha256"],
        }
    if len(_canonical_json_bytes(result)) > GRAPH_RESPONSE_BYTES:
        result.pop(_CHECKPOINT_PROJECTION_KEY, None)
        result[_READ_CONTRACT_KEY]["checkpoint"] = {
            "truncated": True,
            "original_bytes": len(_canonical_json_bytes(checkpoint)),
            "sha256": sha256(_canonical_json_bytes(checkpoint)).hexdigest(),
        }
    return result


def _events_position(events: list[EventEnvelope]) -> int:
    if not events:
        return 0
    return max(event.position for event in events)


def _is_terminal_run_state(run_state: str | None) -> bool:
    return run_state in {"completed", "failed", "cancelled"}


def _add_node_detail_summaries(
    session: AsyncSession,
    summaries: dict[str, GraphNodeDetailSummary],
) -> None:
    for summary in summaries.values():
        row = GraphNodeDetailSummaryModel(run_id=summary.run_id, node_id=summary.node_id)
        _assign_node_detail_summary(row, summary)
        session.add(row)


def _node_detail_summaries_from_events(
    run_id: str,
    events: list[EventEnvelope],
    *,
    position: int,
) -> dict[str, GraphNodeDetailSummary]:
    return _apply_node_detail_events(
        run_id,
        events,
        position=position,
        existing_node_ids=set(),
        summaries={},
        edge_ports={},
    )


def _apply_node_detail_events(
    run_id: str,
    events: list[EventEnvelope],
    *,
    position: int,
    existing_node_ids: set[str],
    summaries: dict[str, GraphNodeDetailSummary],
    edge_ports: dict[str, str],
) -> dict[str, GraphNodeDetailSummary]:
    updated: dict[str, GraphNodeDetailSummary] = {}
    known_node_ids = set(existing_node_ids)
    edge_ports = dict(edge_ports)

    for event in events:
        light_event = _node_detail_light_event(event)
        payload = light_event.payload
        if light_event.event_type == "edge_created":
            edge_id = payload.get("edge_id")
            to_port = payload.get("to_port")
            if isinstance(edge_id, str) and isinstance(to_port, str):
                edge_ports[edge_id] = to_port

        direct_node_id = payload.get("node_id")
        if light_event.event_type == "node_created" and isinstance(direct_node_id, str):
            known_node_ids.add(direct_node_id)

        referenced_node_ids = _referenced_node_ids(payload, known_node_ids)
        event_response = _node_event_response(light_event)
        for node_id in sorted(referenced_node_ids):
            summary = summaries.get(node_id)
            if summary is None:
                summary = _empty_node_detail_summary(run_id, node_id, position)
            summary = _append_node_event(
                summary,
                event_response,
                position=position,
                is_callback=_is_callback_history_event(light_event),
            )
            summaries[node_id] = summary
            updated[node_id] = summary

        event_updates = _node_detail_field_updates(light_event, edge_ports, summaries, position)
        for node_id, summary in event_updates.items():
            known_node_ids.add(node_id)
            summaries[node_id] = summary
            updated[node_id] = summary

    return dict(updated)


def _node_detail_field_updates(
    event: EventEnvelope,
    edge_ports: dict[str, str],
    summaries: dict[str, GraphNodeDetailSummary],
    position: int,
) -> dict[str, GraphNodeDetailSummary]:
    payload = event.payload
    updates: dict[str, GraphNodeDetailSummary] = {}
    if event.event_type == "node_created":
        node_id = payload.get("node_id")
        if not isinstance(node_id, str):
            return updates
        summary = summaries.get(node_id) or _empty_node_detail_summary(
            event.run_id,
            node_id,
            position,
        )
        kind = payload.get("kind")
        role = payload.get("role")
        state = payload.get("state")
        updates[node_id] = _replace_summary(
            summary,
            position=position,
            kind=kind if isinstance(kind, str) else summary.kind,
            role=role if isinstance(role, str) else summary.role,
            state=state if isinstance(state, str) else summary.state,
            task_region_id=(
                payload.get("task_region_id")
                if isinstance(payload.get("task_region_id"), str)
                else summary.task_region_id
            ),
        )
    elif event.event_type == "node_state_changed":
        node_id = payload.get("node_id")
        new_state = payload.get("new_state")
        if isinstance(node_id, str) and isinstance(new_state, str):
            summary = summaries.get(node_id) or _empty_node_detail_summary(
                event.run_id,
                node_id,
                position,
            )
            prompt_summary = payload.get("prompt_summary")
            update_fields: dict[str, Any] = {"position": position, "state": new_state}
            if isinstance(prompt_summary, dict):
                update_fields["prompt_summary"] = dict(cast(dict[str, Any], prompt_summary))
            updates[node_id] = _replace_summary(summary, **update_fields)
    elif event.event_type == "node_retired":
        node_id = payload.get("node_id")
        if isinstance(node_id, str):
            summary = summaries.get(node_id) or _empty_node_detail_summary(
                event.run_id,
                node_id,
                position,
            )
            updates[node_id] = _replace_summary(summary, position=position, state="retired")
    elif event.event_type == "input_bound":
        node_id = payload.get("to_node_id")
        if not isinstance(node_id, str):
            return updates
        port = payload.get("to_port")
        if not isinstance(port, str):
            edge_id = payload.get("edge_id")
            if isinstance(edge_id, str):
                port = edge_ports.get(edge_id)
        if not isinstance(port, str):
            legacy_input = payload.get("input")
            if isinstance(legacy_input, str):
                port = legacy_input
        if not isinstance(port, str):
            return updates
        record_ids = payload.get("record_ids")
        if not isinstance(record_ids, list):
            bound_ids: list[str] = []
        else:
            bound_ids = [
                record_id for record_id in cast(list[Any], record_ids) if isinstance(record_id, str)
            ]
        summary = summaries.get(node_id) or _empty_node_detail_summary(
            event.run_id,
            node_id,
            position,
        )
        input_ports = {key: list(value) for key, value in summary.input_ports.items()}
        input_ports[port] = merge_bound_record_ids(
            str(payload.get("binding_policy", "bind_first")),
            input_ports.get(port, []),
            bound_ids,
            supersedes_record_id=payload.get("supersedes_record_id"),
        )
        updates[node_id] = _replace_summary(summary, position=position, input_ports=input_ports)
    elif event.event_type == "lease_granted":
        node_id = payload.get("node_id")
        if isinstance(node_id, str):
            summary = summaries.get(node_id) or _empty_node_detail_summary(
                event.run_id,
                node_id,
                position,
            )
            updates[node_id] = _replace_summary(
                summary,
                position=position,
                **_lease_granted_updates(
                    summary,
                    _lease_from_grant(
                        payload,
                        summary.kind,
                        summary.task_region_id,
                    ),
                ),
            )
    elif event.event_type in {
        "lease_suspended",
        "lease_revoked",
        "lease_expired",
        "lease_released",
    }:
        lease_id = payload.get("lease_id")
        if not isinstance(lease_id, str):
            return updates
        node_id = payload.get("node_id")
        target_ids = [node_id] if isinstance(node_id, str) else list(summaries)
        for target_id in target_ids:
            summary = summaries.get(target_id)
            if summary is None:
                continue
            active_lease = summary.active_lease
            if not summary.leases and (
                not isinstance(active_lease, dict) or active_lease.get("lease_id") != lease_id
            ):
                continue
            leases: list[dict[str, Any]] = []
            matched = False
            for existing_lease in summary.leases:
                lease = dict(existing_lease)
                if lease.get("lease_id") == lease_id:
                    lease["state"] = event.event_type.removeprefix("lease_")
                    matched = True
                leases.append(lease)
            if not matched and isinstance(active_lease, dict):
                if active_lease.get("lease_id") != lease_id:
                    continue
                lease = dict(active_lease)
                lease["state"] = event.event_type.removeprefix("lease_")
                leases.append(lease)
            updates[target_id] = _replace_summary(
                summary,
                position=position,
                leases=leases,
                active_lease=_selected_lease(leases),
            )
    elif event.event_type == "output_record_accepted":
        node_id = payload.get("producer_node_id")
        record_kind = payload.get("record_kind")
        if (
            isinstance(node_id, str)
            and isinstance(record_kind, str)
            and record_kind != "file_state"
        ):
            summary = summaries.get(node_id) or _empty_node_detail_summary(
                event.run_id,
                node_id,
                position,
            )
            records = [dict(record) for record in summary.output_records]
            records.append(dict(payload))
            updates[node_id] = _replace_summary(
                summary,
                position=position,
                output_records=records,
            )
    elif event.event_type == "file_state_accepted":
        node_id = payload.get("producer_node_id")
        if isinstance(node_id, str):
            summary = summaries.get(node_id) or _empty_node_detail_summary(
                event.run_id,
                node_id,
                position,
            )
            records = [dict(record) for record in summary.file_state_records]
            record = _compact_file_state_record(payload)
            records.append(record)
            updates[node_id] = _replace_summary(
                summary,
                position=position,
                file_state_records=records,
            )
    return updates


def _replace_summary(
    summary: GraphNodeDetailSummary,
    **updates: Any,
) -> GraphNodeDetailSummary:
    return replace(summary, **updates)


def _empty_node_detail_summary(
    run_id: str,
    node_id: str,
    position: int,
) -> GraphNodeDetailSummary:
    return GraphNodeDetailSummary(
        run_id=run_id,
        node_id=node_id,
        position=position,
        kind=None,
        role=None,
        state=None,
        task_region_id=None,
        input_ports={},
        output_records=[],
        file_state_records=[],
        leases=[],
        active_lease=None,
        callback_history=[],
        events=[],
    )


def _append_node_event(
    summary: GraphNodeDetailSummary,
    event_response: dict[str, Any],
    *,
    position: int,
    is_callback: bool,
) -> GraphNodeDetailSummary:
    events = [dict(event) for event in summary.events]
    events.append(dict(event_response))
    callback_history = [dict(event) for event in summary.callback_history]
    if is_callback:
        callback_history.append(dict(event_response))
    return _replace_summary(
        summary,
        position=position,
        events=events,
        callback_history=callback_history,
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


def _node_detail_light_event(event: EventEnvelope) -> EventEnvelope:
    retained_fields = EVENT_PAYLOAD_SPECS[event.event_type].node_detail
    payload = {key: value for key, value in event.payload.items() if key in retained_fields}
    value = event.payload.get("value")
    if _is_verification_report_payload(event.payload) and isinstance(value, dict):
        typed_value = cast(dict[str, Any], value)
        compact_value: dict[str, Any] = {}
        outcome = typed_value.get("outcome")
        if isinstance(outcome, str):
            compact_value["outcome"] = outcome
        grades = typed_value.get("grades")
        if grades is not None:
            compact_value["grades"] = grades
        if compact_value:
            payload["value"] = compact_value
    return event.model_copy(update={"payload": payload})


def _node_event_response(event: EventEnvelope) -> dict[str, Any]:
    summary = summarize_graph_event(event)
    return {
        "event_id": summary.event_id,
        "event_type": summary.event_type,
        "run_id": summary.run_id,
        "position": summary.position,
        "timestamp": summary.timestamp,
        "payload": summary.payload,
    }


def _referenced_node_ids(payload: dict[str, Any], known_node_ids: set[str]) -> set[str]:
    node_ids: set[str] = set()
    _collect_node_references(payload, known_node_ids, node_ids, key=None)
    return node_ids


def _collect_node_references(
    value: Any,
    known_node_ids: set[str],
    node_ids: set[str],
    *,
    key: str | None,
) -> None:
    if isinstance(value, dict):
        for child_key, child_value in cast(dict[str, Any], value).items():
            _collect_node_references(child_value, known_node_ids, node_ids, key=child_key)
    elif isinstance(value, list):
        for item in cast(list[Any], value):
            _collect_node_references(item, known_node_ids, node_ids, key=key)
    elif isinstance(value, str):
        if value in known_node_ids or (key is not None and _looks_like_node_key(key)):
            node_ids.add(value)


def _looks_like_node_key(key: str) -> bool:
    return key == "node_id" or key.endswith("_node_id") or key.endswith("_node_ids")


def _lease_from_grant(
    payload: dict[str, Any],
    known_kind: str | None,
    known_task_region_id: str | None = None,
) -> dict[str, Any]:
    lease: dict[str, Any] = {
        "lease_id": payload["lease_id"],
        "node_id": payload["node_id"],
        "state": "active",
    }
    generation = payload.get("generation")
    if isinstance(generation, int):
        lease["generation"] = generation
    for key in (
        "session_id",
        "expires_at",
        "execution_id",
        "base_snapshot_id",
        "task_region_id",
        "cache_authority_hash",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            lease[key] = value
    if "task_region_id" not in lease and known_task_region_id is not None:
        lease["task_region_id"] = known_task_region_id
    kind = payload.get("kind")
    if isinstance(kind, str):
        lease["kind"] = kind
    elif known_kind is not None:
        lease["kind"] = known_kind
    resource_claims = payload.get("resource_claims")
    if isinstance(resource_claims, list):
        lease["resource_claims"] = resource_claims
    return lease


def _lease_granted_updates(
    summary: GraphNodeDetailSummary,
    lease: dict[str, Any],
) -> dict[str, Any]:
    leases = [dict(existing_lease) for existing_lease in summary.leases]
    leases.append(dict(lease))
    return {"leases": leases, "active_lease": _selected_lease(leases)}


def _selected_lease(leases: list[dict[str, Any]]) -> dict[str, Any] | None:
    fallback: dict[str, Any] | None = None
    for lease in leases:
        if lease.get("state") == "active":
            return dict(lease)
        if fallback is None:
            fallback = dict(lease)
    return fallback


def _lease_update_ids(events: list[EventEnvelope]) -> set[str]:
    ids: set[str] = set()
    for event in events:
        if event.event_type not in {
            "lease_suspended",
            "lease_revoked",
            "lease_expired",
            "lease_released",
        }:
            continue
        lease_id = event.payload.get("lease_id")
        if isinstance(lease_id, str):
            ids.add(lease_id)
    return ids


def _has_missing_preexisting_node_reference(
    events: list[EventEnvelope],
    existing_node_ids: set[str],
) -> bool:
    known_node_ids = set(existing_node_ids)
    created_node_ids: set[str] = set()
    for event in events:
        payload = _node_detail_light_event(event).payload
        node_id = payload.get("node_id")
        if event.event_type == "node_created" and isinstance(node_id, str):
            created_node_ids.add(node_id)
            known_node_ids.add(node_id)
            continue
        referenced_node_ids = _referenced_node_ids(payload, known_node_ids)
        if any(
            node_id not in existing_node_ids and node_id not in created_node_ids
            for node_id in referenced_node_ids
        ):
            return True
    return False


def _input_bound_edge_ids_needing_ports(events: list[EventEnvelope]) -> set[str]:
    edge_ids: set[str] = set()
    for event in events:
        if event.event_type != "input_bound":
            continue
        if isinstance(event.payload.get("to_port"), str):
            continue
        edge_id = event.payload.get("edge_id")
        if isinstance(edge_id, str):
            edge_ids.add(edge_id)
    return edge_ids


def _classification_summary(record: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "verdict": record.get("verdict"),
        "total_paths": 0,
        "needs_gatekeeper": 0,
        "classifications": {},
    }
    class_counts: dict[str, int] = {}
    entries = record.get("classifications")
    if isinstance(entries, list):
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
    summary["classifications"] = class_counts
    return summary


def _compact_file_state_record(payload: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "classification_summary": _classification_summary(payload),
    }
    for key in (
        "record_id",
        "record_kind",
        "port",
        "producer_node_id",
        "schema",
        "snapshot_id",
        "verdict",
        "patch_bundle_id",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            record[key] = value
    diff_summary = payload.get("diff_summary")
    if isinstance(diff_summary, dict):
        record["diff_summary"] = dict(cast(dict[str, Any], diff_summary))
    return record


def _node_detail_summary_from_row(
    row: GraphNodeDetailSummaryModel,
) -> GraphNodeDetailSummary:
    stored_prompt = dict(row.prompt_summary) if row.prompt_summary is not None else None
    read_contract = None
    if stored_prompt is not None:
        raw_contract = stored_prompt.pop(_READ_CONTRACT_KEY, None)
        if isinstance(raw_contract, dict):
            read_contract = dict(cast(dict[str, Any], raw_contract))
        if not stored_prompt:
            stored_prompt = None
    return GraphNodeDetailSummary(
        run_id=row.run_id,
        node_id=row.node_id,
        position=row.position,
        kind=row.kind,
        role=row.role,
        state=row.state,
        task_region_id=row.task_region_id,
        input_ports=cast(dict[str, list[str]], dict(row.input_ports)),
        output_records=[dict(record) for record in row.output_records],
        file_state_records=[dict(record) for record in row.file_state_records],
        leases=[dict(lease) for lease in row.leases],
        active_lease=dict(row.active_lease) if row.active_lease is not None else None,
        callback_history=[dict(event) for event in row.callback_history],
        events=[dict(event) for event in row.events],
        prompt_summary=stored_prompt,
        read_contract=read_contract,
    )


def _assign_node_detail_summary(
    row: GraphNodeDetailSummaryModel,
    summary: GraphNodeDetailSummary,
) -> None:
    row.position = summary.position
    row.kind = summary.kind
    row.role = summary.role
    row.state = summary.state
    row.task_region_id = summary.task_region_id
    bounded, metadata = bound_node_detail_owner(
        {
            "input_ports": {key: list(value) for key, value in summary.input_ports.items()},
            "output_records": [dict(record) for record in summary.output_records],
            "file_state_records": [dict(record) for record in summary.file_state_records],
            "leases": [dict(lease) for lease in summary.leases],
            "active_lease": (
                dict(summary.active_lease) if summary.active_lease is not None else None
            ),
            "callback_history": [dict(event) for event in summary.callback_history],
            "events": [dict(event) for event in summary.events],
            "prompt_summary": (
                dict(summary.prompt_summary) if summary.prompt_summary is not None else {}
            ),
        }
    )
    row.input_ports = cast(dict[str, list[str]], bounded["input_ports"])
    row.output_records = cast(list[dict[str, Any]], bounded["output_records"])
    row.file_state_records = cast(list[dict[str, Any]], bounded["file_state_records"])
    row.leases = cast(list[dict[str, Any]], bounded["leases"])
    row.active_lease = cast(dict[str, Any] | None, bounded["active_lease"])
    row.callback_history = cast(list[dict[str, Any]], bounded["callback_history"])
    row.events = cast(list[dict[str, Any]], bounded["events"])
    prompt_storage = cast(dict[str, Any], bounded["prompt_summary"] or {})
    prompt_storage[_READ_CONTRACT_KEY] = {
        "revision": GRAPH_READ_CONTRACT_REVISION,
        "collections": metadata,
    }
    row.prompt_summary = prompt_storage
    _pack_node_detail_row(row)


def _json_extract_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if not value:
        return value
    if value[0] not in "[{":
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _json_extract_payload_value(field: str, value: Any) -> Any:
    if field in BOOLEAN_PAYLOAD_FIELDS and value in {0, 1}:
        return bool(value)
    return _json_extract_value(value)
