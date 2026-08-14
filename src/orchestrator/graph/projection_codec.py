"""Small disposable checkpoint codec for :class:`GraphProjection`.

Graph events are authoritative.  This module only transports a bounded cache
of grouped projection state and verifies enough local structure to decide
whether that cache can be used.  Relationship correctness belongs to event
acceptance and reducer/index writes, where the originating event is still
available for a useful diagnostic.
"""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from json import dumps
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator
from pydantic_core import PydanticSerializationError

from orchestrator.graph.models import (
    FileStateRecord,
    RoutineSnapshotRecord,
    freeze_canonical_record,
)

from orchestrator.graph.cache_authority import (
    POLICY_VERSION,
    CacheAuthorityPolicy,
    cache_authority_hash,
    canonicalize_cache_authority,
    has_cache_authority_carrier,
)
from orchestrator.graph.projection_models import GraphProjection


class ProjectionCheckpointCodecError(ValueError):
    """A serialization failure while writing a disposable checkpoint."""


PROJECTION_CHECKPOINT_SCHEMA_VERSION = 15


class ProjectionCheckpointEnvelope(BaseModel):
    """The complete disposable checkpoint contract."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: StrictInt
    position: StrictInt = Field(ge=0)
    state: dict[str, Any]
    checksum: StrictStr = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @field_validator("state", mode="before")
    @classmethod
    def state_is_exact_object(cls, value: object) -> object:
        if type(value) is not dict:
            raise ValueError("checkpoint state must be an exact JSON object")
        return cast(dict[str, Any], value)


class ProjectionIntegrityDiagnostic(BaseModel):
    """One local cache invariant failure."""

    model_config = ConfigDict(frozen=True)

    path: str
    reason: str


class ProjectionCheckpointIntegrityError(ValueError):
    """Local cache invariants failed; replay must rebuild the checkpoint."""

    def __init__(self, diagnostics: tuple[ProjectionIntegrityDiagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__("; ".join(f"{item.path}: {item.reason}" for item in diagnostics))


def _projection_state_to_checkpoint(projection: GraphProjection) -> dict[str, Any]:
    """Serialize grouped state without adding codec metadata to the state."""
    try:
        state = projection.model_dump(
            mode="json",
            exclude_unset=True,
            exclude_none=True,
            exclude={"records"},
        )
        records = projection.records
        if records.by_id or records.ids_by_node_port or records.summaries_by_id:
            state["records"] = {
                "by_id": {
                    record_id: record.model_dump(mode="json", exclude_unset=True, exclude_none=True)
                    for record_id, record in records.by_id.items()
                },
                "ids_by_node_port": {
                    node_id: {port: list(record_ids) for port, record_ids in ports.items()}
                    for node_id, ports in records.ids_by_node_port.items()
                },
                "summaries_by_id": {
                    record_id: summary.model_dump(
                        mode="json", exclude_unset=True, exclude_none=True
                    )
                    for record_id, summary in records.summaries_by_id.items()
                },
            }
        for group in GraphProjection.model_fields:
            state.setdefault(group, {})
        return state
    except PydanticSerializationError as error:
        raise ProjectionCheckpointCodecError("immutable projection serialization failed") from error


def _canonical_checkpoint_bytes(
    schema_version: int,
    position: int,
    state: dict[str, Any],
) -> bytes:
    try:
        return dumps(
            {"schema_version": schema_version, "position": position, "state": state},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ProjectionCheckpointCodecError("checkpoint is not canonical JSON") from error


def _checkpoint_checksum(schema_version: int, position: int, state: dict[str, Any]) -> str:
    return sha256(_canonical_checkpoint_bytes(schema_version, position, state)).hexdigest()


def projection_to_checkpoint(
    projection: GraphProjection,
    *,
    position: int = 0,
) -> dict[str, Any]:
    """Return the checksummed disposable checkpoint envelope."""
    if type(position) is not int or position < 0:
        raise ValueError("checkpoint position must be a non-negative integer")
    state = _projection_state_to_checkpoint(projection)
    envelope = ProjectionCheckpointEnvelope(
        schema_version=PROJECTION_CHECKPOINT_SCHEMA_VERSION,
        position=position,
        state=state,
        checksum=_checkpoint_checksum(PROJECTION_CHECKPOINT_SCHEMA_VERSION, position, state),
    )
    return envelope.model_dump(mode="json")


def _validate_envelope_checksum(envelope: ProjectionCheckpointEnvelope) -> None:
    expected = _checkpoint_checksum(envelope.schema_version, envelope.position, envelope.state)
    if envelope.checksum != expected:
        raise ValueError("projection checkpoint checksum does not verify")


def projection_from_checkpoint(raw: object) -> GraphProjection:
    """Validate and load a disposable envelope; callers rebuild on any error."""
    envelope = ProjectionCheckpointEnvelope.model_validate(raw)
    if envelope.schema_version != PROJECTION_CHECKPOINT_SCHEMA_VERSION:
        raise ValueError(f"unsupported projection checkpoint schema {envelope.schema_version!r}")
    _validate_envelope_checksum(envelope)
    expected_groups = set(GraphProjection.model_fields)
    actual_groups = set(envelope.state)
    if actual_groups != expected_groups:
        raise ValueError(
            "projection checkpoint state groups must exactly match the projection "
            f"(missing={sorted(expected_groups - actual_groups)!r}, "
            f"unexpected={sorted(actual_groups - expected_groups)!r})"
        )
    projection = GraphProjection.model_validate(
        envelope.state,
        context={"canonical_checkpoint": True},
    )
    for record in projection.records.by_id.values():
        freeze_canonical_record(record)
    validate_projection_critical_invariants(projection)
    return projection


def validate_projection_critical_invariants(projection: GraphProjection) -> None:
    """Check only local cache invariants that Pydantic cannot express.

    These checks are intentionally limited to map-key identity, duplicate or
    dangling derived indexes, canonical record summaries, adjacency indexes,
    lease order, and the reducer-owned ready-node order.  They do not discover
    identifier paths or compile a relationship policy.
    """
    diagnostics: list[ProjectionIntegrityDiagnostic] = []

    def fail(path: str, reason: str) -> None:
        diagnostics.append(ProjectionIntegrityDiagnostic(path=path, reason=reason))

    # Cache-authority facts are a small immutable carrier invariant, not a
    # relationship policy.  Keep this check local because a mismatched hash
    # would make a cached runner decision unsafe even when all indexes agree.
    has_carrier = has_cache_authority_carrier(
        any(node.spec.cache_authority_hash is not None for node in projection.nodes.values()),
        (lease.cache_authority_hash for lease in projection.execution.leases.values()),
    )
    snapshot = projection.records.by_id.get("routine-snapshot-record")
    if isinstance(snapshot, RoutineSnapshotRecord):
        value = snapshot.value
        version = value.cache_authority_version
        preimage = value.cache_authority_preimage
        digest = value.cache_authority_hash
        if version is None and preimage is None and digest is None:
            if has_carrier:
                fail(
                    "records.routine-snapshot-record.value",
                    "legacy cache authority metadata must not have authority carriers",
                )
        elif not (
            isinstance(version, str) and isinstance(preimage, str) and isinstance(digest, str)
        ):
            fail(
                "records.routine-snapshot-record.value",
                "cache authority format must be all absent or all present",
            )
        elif version != POLICY_VERSION:
            fail(
                "records.routine-snapshot-record.value",
                "new cache authority snapshot is incomplete",
            )
        else:
            try:
                policy = CacheAuthorityPolicy.model_validate_json(preimage)
                if (
                    canonicalize_cache_authority(policy) != preimage
                    or cache_authority_hash(policy) != digest
                ):
                    fail(
                        "records.routine-snapshot-record.value",
                        "cache authority hash does not verify",
                    )
                else:
                    expected_hash = digest
                    for node_id, node in projection.nodes.items():
                        if node.spec.cache_authority_hash != expected_hash:
                            fail(
                                f"nodes.{node_id}.spec.cache_authority_hash",
                                "must equal routine cache authority hash",
                            )
                    for lease_id, lease in projection.execution.leases.items():
                        if lease.cache_authority_hash != expected_hash:
                            fail(
                                f"execution.leases.{lease_id}.cache_authority_hash",
                                "must equal routine cache authority hash",
                            )
            except ValueError:
                fail(
                    "records.routine-snapshot-record.value",
                    "cache authority preimage is invalid",
                )
    elif snapshot is not None or has_carrier:
        fail(
            "records.routine-snapshot-record",
            "is required by routine snapshot graph structure",
        )

    for node_id, node in projection.nodes.items():
        if node.spec.node_id != node_id:
            fail(f"nodes.{node_id}.spec.node_id", "must equal map key")
    for edge_id, edge in projection.topology.edges.items():
        if edge.edge_id != edge_id:
            fail(f"topology.edges.{edge_id}.edge_id", "must equal map key")
    for lease_id, lease in projection.execution.leases.items():
        if lease.lease_id != lease_id:
            fail(f"execution.leases.{lease_id}.lease_id", "must equal map key")
    for revision_id, revision in projection.requirements.revisions_by_id.items():
        if revision.version_id != revision_id:
            fail(f"requirements.revisions_by_id.{revision_id}.version_id", "must equal map key")
    for support_id, support in projection.requirements.support_by_id.items():
        if support.support_id != support_id:
            fail(f"requirements.support_by_id.{support_id}.support_id", "must equal map key")
    for cleanup_id, cleanup in projection.execution.cleanup_requests_by_id.items():
        if cleanup.cleanup_id != cleanup_id:
            fail(f"execution.cleanup_requests_by_id.{cleanup_id}.cleanup_id", "must equal map key")

    candidate_ids: set[str] = set()
    for task_id, task in projection.tasks.items():
        for index, candidate in enumerate(task.candidates):
            if candidate.candidate_id in candidate_ids:
                fail(
                    f"tasks.{task_id}.candidates[{index}].candidate_id",
                    "must identify one canonical candidate",
                )
            candidate_ids.add(candidate.candidate_id)

    records = projection.records.by_id
    for record_id, record in records.items():
        if record.record_id != record_id:
            fail(f"records.by_id.{record_id}.record_id", "must equal map key")
    expected_record_index: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for record_id, record in records.items():
        if record.producer_node_id is not None:
            expected_record_index[record.producer_node_id][record.port].add(record_id)
    for node_id, ports in projection.records.ids_by_node_port.items():
        for port, record_ids in ports.items():
            if len(record_ids) != len(set(record_ids)):
                fail(
                    f"records.ids_by_node_port.{node_id}.{port}",
                    "must not contain duplicate record IDs",
                )
            if not set(record_ids).issubset(records):
                fail(
                    f"records.ids_by_node_port.{node_id}.{port}",
                    "must contain only known record IDs",
                )
            if set(record_ids) != expected_record_index.get(node_id, {}).get(port, set()):
                fail(
                    f"records.ids_by_node_port.{node_id}.{port}",
                    "must exactly index records by producer and port",
                )
    for node_id, ports in expected_record_index.items():
        for port in ports:
            if port not in projection.records.ids_by_node_port.get(node_id, {}):
                fail(
                    f"records.ids_by_node_port.{node_id}.{port}",
                    "must contain the canonical record index",
                )
    if set(projection.records.summaries_by_id) != set(records):
        fail("records.summaries_by_id", "must cover exactly the canonical records")
    for record_id, summary in projection.records.summaries_by_id.items():
        if summary.record_id != record_id:
            fail(f"records.summaries_by_id.{record_id}.record_id", "must equal map key")
        record = records.get(record_id)
        if record is None:
            continue
        expected = (
            record.record_id,
            record.record_type,
            record.record_kind,
            record.schema_,
            record.producer_node_id,
            record.port,
            record.position if isinstance(record, FileStateRecord) else record.graph_position,
        )
        actual = (
            summary.record_id,
            summary.record_type,
            summary.record_kind,
            summary.schema_,
            summary.producer_node_id,
            summary.producer_port,
            summary.position,
        )
        if actual != expected:
            fail(f"records.summaries_by_id.{record_id}", "must derive from canonical record")

    expected_inbound: dict[str, set[str]] = defaultdict(set)
    expected_outbound: dict[str, set[str]] = defaultdict(set)
    for edge_id, edge in projection.topology.edges.items():
        expected_inbound[edge.to_node_id].add(edge_id)
        expected_outbound[edge.from_node_id].add(edge_id)
    for field, expected in (
        ("inbound_edge_ids", expected_inbound),
        ("outbound_edge_ids", expected_outbound),
    ):
        actual = getattr(projection.topology, field)
        for node_id in set(actual) | set(expected):
            if set(actual.get(node_id, ())) != expected.get(node_id, set()):
                fail(f"topology.{field}.{node_id}", "must index exactly the canonical edges")

    lease_order = projection.execution.lease_ids_in_grant_order
    if len(lease_order) != len(set(lease_order)) or not set(lease_order).issubset(
        projection.execution.leases
    ):
        fail(
            "execution.lease_ids_in_grant_order",
            "must contain each known lease at most once",
        )
    ready = projection.scheduling.ready_node_ids
    expected_ready = tuple(
        sorted(
            (
                node_id
                for node_id, node in projection.nodes.items()
                if node.runtime.state == "ready"
            ),
            key=lambda node_id: (projection.nodes[node_id].spec.creation_position, node_id),
        )
    )
    if ready != expected_ready:
        fail("scheduling.ready_node_ids", "must exactly match ready nodes in canonical order")
    if diagnostics:
        raise ProjectionCheckpointIntegrityError(
            tuple(sorted(diagnostics, key=lambda item: (item.path, item.reason)))
        )
