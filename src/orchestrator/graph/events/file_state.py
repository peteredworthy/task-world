"""Strict file-state, gatekeeper, and cleanup event specifications."""

from typing import Any, Literal, TypeAlias, cast

from pydantic import Field

from orchestrator.graph.models import (
    CleanupRequestedProjection,
    ExternalFileEntry,
    FileEntry,
    FileStateRecord,
    StrictFileEntry,
    StrictFileStateRecord,
)
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import (
    EventMetadata,
    EventSpecification,
    ProjectionParticipation,
)


FileStateAcceptedPayload: TypeAlias = StrictFileStateRecord


def _empty_file_entries() -> list[StrictFileEntry]:
    return []


class FileStateRejectedPayload(StrictPayload):
    record_kind: Literal["file_state_rejected"] | None = None
    node_id: str
    run_id: str
    execution_id: str = Field(min_length=1)
    lease_id: str
    lease_generation: int = Field(ge=0)
    base_snapshot_id: str | None = None
    verdict: Literal["rejected"] = "rejected"
    reason: str | None = None
    classifications: list[StrictFileEntry]
    rejected_paths: list[StrictFileEntry]
    residue: list[StrictFileEntry] = Field(default_factory=_empty_file_entries)


class GatekeeperVerdict(StrictPayload):
    path: str
    classification: Literal[
        "tool_cache",
        "build_output",
        "test_artifact",
        "secret",
        "external_artifact",
        "unknown_ignored",
    ]
    confidence: float = Field(ge=0, le=1)
    rationale: str
    model_id: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cache_write_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    wall_time_ms: int = Field(ge=0)


class GatekeeperVerdictRecordedPayload(StrictPayload):
    file_state_record_id: str
    execution_id: str = Field(min_length=1)
    producer_node_id: str | None = None
    verdicts: tuple[GatekeeperVerdict, ...]
    resolved_count: int = Field(ge=0)


class GatekeeperCostRecordedPayload(StrictPayload):
    file_state_record_id: str
    execution_id: str = Field(min_length=1)
    consult_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cache_write_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    wall_time_ms: int = Field(ge=0)
    item_count: int = Field(ge=0)


class CleanupRequestedPayload(StrictPayload):
    cleanup_id: str
    file_state_record_id: str
    snapshot_id: str | None = None
    paths: tuple[str, ...]
    authority: str = Field(min_length=1)
    reason: str | None = None
    execution_id: str = Field(min_length=1)
    producer_node_id: str | None = None


class CleanupAppliedPayload(StrictPayload):
    cleanup_id: str
    file_state_record_id: str
    superseding_record_id: str
    old_snapshot_id: str | None
    new_snapshot_id: str | None
    paths: tuple[str, ...]
    authority: str = Field(min_length=1)
    reason: str | None
    execution_id: str = Field(min_length=1)
    deleted_snapshot_ref: bool
    resolved_count: int = Field(ge=0)


def reduce_file_state_accepted(
    state: Any, payload: StrictFileStateRecord, metadata: EventMetadata
) -> Any:
    from orchestrator.graph.projections import copy_projection, refresh_derived_topology_state

    next_state = copy_projection(state)
    record = FileStateRecord.model_validate(
        {
            **payload.model_dump(mode="json"),
            "run_id": metadata.run_id,
            "position": metadata.position,
        }
    )
    next_state["file_state_records"][record.record_id] = record
    if record.producer_node_id is not None:
        ports = next_state["node_output_ports"].setdefault(record.producer_node_id, {})
        records = ports.setdefault(record.port, [])
        if record.record_id not in records:
            records.append(record.record_id)
    summary = {
        "record_id": record.record_id,
        "record_kind": record.record_kind,
        "schema": record.schema_,
        "producer_port": record.port,
        "record_type": "file_state",
    }
    if record.producer_node_id:
        summary["producer_node_id"] = record.producer_node_id
    next_state["accepted_record_summaries_by_id"][record.record_id] = cast(Any, summary)
    refresh_derived_topology_state(next_state)
    return next_state


def reduce_file_state_rejected(
    state: Any, payload: FileStateRejectedPayload, metadata: EventMetadata
) -> Any:
    del payload, metadata
    return state


def reduce_gatekeeper_verdict_recorded(
    state: Any, payload: GatekeeperVerdictRecordedPayload, metadata: EventMetadata
) -> Any:
    from orchestrator.graph.projections import copy_projection, refresh_derived_topology_state

    del metadata
    next_state = copy_projection(state)
    record = next_state["file_state_records"].get(payload.file_state_record_id)
    if record is None:
        return next_state
    verdicts = {verdict.path: verdict for verdict in payload.verdicts}
    for field_name in ("classifications", "residue", "untracked", "ignored", "external"):
        entries = getattr(record, field_name)
        setattr(record, field_name, [_resolved_file_entry(entry, verdicts) for entry in entries])
    refresh_derived_topology_state(next_state)
    return next_state


def reduce_gatekeeper_cost_recorded(
    state: Any, payload: GatekeeperCostRecordedPayload, metadata: EventMetadata
) -> Any:
    del payload, metadata
    return state


def reduce_cleanup_requested(
    state: Any, payload: CleanupRequestedPayload, metadata: EventMetadata
) -> Any:
    from orchestrator.graph.projections import copy_projection, refresh_derived_topology_state

    next_state = copy_projection(state)
    next_state["cleanup_requested_events"].setdefault(
        payload.cleanup_id,
        CleanupRequestedProjection(
            cleanup_id=payload.cleanup_id,
            position=metadata.position,
            file_state_record_id=payload.file_state_record_id,
            snapshot_id=payload.snapshot_id,
            paths=list(payload.paths),
            authority=payload.authority,
            reason=payload.reason,
            execution_id=payload.execution_id,
            producer_node_id=payload.producer_node_id,
        ),
    )
    record = next_state["file_state_records"].get(payload.file_state_record_id)
    if record is not None:
        record.compromised = True
        record.superseded_pending = True
        record.cleanup_id = payload.cleanup_id
        record.cleanup_reason = payload.reason
        record.compromised_paths = list(payload.paths)
    refresh_derived_topology_state(next_state)
    return next_state


def reduce_cleanup_applied(
    state: Any, payload: CleanupAppliedPayload, metadata: EventMetadata
) -> Any:
    from orchestrator.graph.projections import copy_projection, refresh_derived_topology_state

    next_state = copy_projection(state)
    next_state["cleanup_applied_ids"][payload.cleanup_id] = True
    record = next_state["file_state_records"].get(payload.file_state_record_id)
    if record is not None:
        record.compromised = True
        record.superseded_pending = False
        record.superseded_by_record_id = payload.superseding_record_id
        record.cleanup_applied_event_id = metadata.event_id
        record.compromised_snapshot_deleted = payload.deleted_snapshot_ref
    refresh_derived_topology_state(next_state)
    return next_state


def _resolved_file_entry(
    entry: FileEntry | ExternalFileEntry,
    verdicts: dict[str, GatekeeperVerdict],
) -> FileEntry | ExternalFileEntry:
    verdict = verdicts.get(entry.path)
    if verdict is None:
        return entry
    values = entry.model_dump(mode="json")
    values.update(
        classification=verdict.classification,
        matched_rule=f"gatekeeper:{verdict.model_id}",
        needs_gatekeeper=False,
        gatekeeper_confidence=verdict.confidence,
        gatekeeper_rationale=verdict.rationale,
    )
    if isinstance(entry, ExternalFileEntry):
        return ExternalFileEntry.model_validate(values)
    return FileEntry.model_validate(values)


def file_entry_values(entry: FileEntry) -> dict[str, Any]:
    """Serialize one already-typed file entry for read-model presentation."""
    return entry.model_dump(mode="json")


FILE_STATE_ACCEPTED = EventSpecification(
    "file_state_accepted",
    StrictFileStateRecord,
    reduce_file_state_accepted,
    ProjectionParticipation.MUTATES,
)
FILE_STATE_REJECTED = EventSpecification(
    "file_state_rejected",
    FileStateRejectedPayload,
    reduce_file_state_rejected,
    ProjectionParticipation.NEUTRAL,
)
GATEKEEPER_VERDICT_RECORDED = EventSpecification(
    "gatekeeper_verdict_recorded",
    GatekeeperVerdictRecordedPayload,
    reduce_gatekeeper_verdict_recorded,
    ProjectionParticipation.MUTATES,
)
GATEKEEPER_COST_RECORDED = EventSpecification(
    "gatekeeper_cost_recorded",
    GatekeeperCostRecordedPayload,
    reduce_gatekeeper_cost_recorded,
    ProjectionParticipation.NEUTRAL,
)
CLEANUP_REQUESTED = EventSpecification(
    "cleanup_requested",
    CleanupRequestedPayload,
    reduce_cleanup_requested,
    ProjectionParticipation.MUTATES,
)
CLEANUP_APPLIED = EventSpecification(
    "cleanup_applied",
    CleanupAppliedPayload,
    reduce_cleanup_applied,
    ProjectionParticipation.MUTATES,
)
EVENT_SPECIFICATIONS = (
    FILE_STATE_ACCEPTED,
    FILE_STATE_REJECTED,
    GATEKEEPER_VERDICT_RECORDED,
    GATEKEEPER_COST_RECORDED,
    CLEANUP_REQUESTED,
    CLEANUP_APPLIED,
)
