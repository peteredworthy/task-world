"""SQLite-backed event store for graph event envelopes."""

from __future__ import annotations

import json

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db import (
    EventV2Model,
    GraphEventSummaryModel,
    GraphNodeDetailSummaryCheckpointModel,
    GraphNodeDetailSummaryModel,
    GraphProjectionSnapshotModel,
)
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    GraphProjection,
    GRAPH_PROJECTION_PAYLOAD_FIELDS,
    PROJECTION_SCHEMA_VERSION,
    initial_projection,
    merge_bound_record_ids,
    project_decision_view,
    project_decision_view_from_projection,
    project_leases,
    project_lease_view,
    projection_from_checkpoint,
    projection_to_checkpoint,
    project_scheduler_view,
    reduce_event,
)
from orchestrator.graph_runtime.errors import StaleProjectionError

GRAPH_AGGREGATE_PREFIX = "graph:"
_CHECKPOINT_PROJECTION_KEY = "_projection_checkpoint"
_CHECKPOINT_SCHEMA_VERSION_KEY = "_projection_schema_version"
_CHECKPOINT_TERMINAL_KEY = "_projection_terminal"
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
    "execution_id",
    "generation",
    "grade",
    "kind",
    "lease_generation",
    "lease_id",
    "new_state",
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
)
LIGHT_GRAPH_PAYLOAD_FIELDS = (
    "accepted_record_selector",
    "active",
    "allowed_actions",
    "appeal_node_id",
    "appeal_type",
    "appealed_node_id",
    "approved",
    "authority",
    "authority_required_reason",
    "base_snapshot_id",
    "binding_policy",
    "behavior_change",
    "blocker",
    "bound_at_position",
    "cache_read_tokens",
    "cache_write_tokens",
    "candidate_record_id",
    "candidate_record_ids",
    "candidate_id",
    "change_classification",
    "classification",
    "cleanup_id",
    "command_binding",
    "command_definition",
    "command_definition_id",
    "confidence",
    "decision",
    "deleted_snapshot_ref",
    "dependency_type",
    "edge_id",
    "evidence_id",
    "execution_id",
    "evaluated_record_ids",
    "expires_at",
    "explicit_authority_required",
    "failed_candidate_id",
    "file_state_record_ids",
    "file_state_record_id",
    "from_node_kind",
    "from_node_id",
    "from_port",
    "from_node_role",
    "from_state",
    "gate_id",
    "gate_type",
    "generation",
    "generation_index",
    "freshness_policy",
    "input",
    "input_tokens",
    "id",
    "kind",
    "lease_generation",
    "lease_id",
    "membership",
    "metadata",
    "model_id",
    "new_behavior",
    "new_state",
    "node_id",
    "operation",
    "outcome",
    "output_tokens",
    "path",
    "port",
    "patch_id",
    "planner_chain",
    "planner_generation_budget",
    "proposal_id",
    "previous_version_id",
    "priority",
    "prompt",
    "prompt_hydration_policy",
    "producer_node_id",
    "proposed_by_node_id",
    "reason",
    "record_id",
    "record_ids",
    "record_kind",
    "record_type",
    "region_id",
    "region_label",
    "rejected_patches",
    "required",
    "requirement",
    "requirement_id",
    "requirement_version_id",
    "requires_authority",
    "resource_claims",
    "revision_index",
    "revision_id",
    "revision_type",
    "retry_not_before",
    "role",
    "schema",
    "semantic_change",
    "session_id",
    "stale_only",
    "stale_reason",
    "state",
    "status",
    "supersedes_record_id",
    "supersedes_task_region_id",
    "supersedes_task_region_ids",
    "successor_planner_node_ids",
    "superseding_record_id",
    "support_id",
    "supported",
    "task_region_id",
    "to_node_id",
    "to_port",
    "to_state",
    "trigger",
    "unsupported",
    "validation_strengthening",
    "verdict",
    "verdicts",
    "version_id",
    "approval_prompt",
    "approval_type",
    "attempt_number",
    "authority_request",
    "authority_request_record",
    "authority_request_record_id",
    "blocker_reason",
    "decision_request",
    "decision_request_record_id",
    "guarded_planner_node_id",
    "human_prompt",
    "hidden_oracle_command",
    "inputs",
    "message",
    "outputs",
    "preconditions",
    "recovery_of_node_id",
    "recovery_of_record_id",
    "recovery_reason",
    "rejected_patch_id",
)
DECISION_RECORD_VALUE_FIELDS = (
    "consequence_summary",
    "default_option",
    "expires_at",
    "options",
    "requested_authority",
    "target_node_id",
    "target_region_id",
)
SUMMARY_REBUILD_PAYLOAD_FIELDS = tuple(
    dict.fromkeys(
        [
            *LIGHT_GRAPH_PAYLOAD_FIELDS,
            *SUMMARY_PAYLOAD_FIELDS,
            "attempt_number",
            "blockers",
            "decider",
            "decision_type",
            "graph_verifier_grades",
            "grades",
            "idempotency_key",
            "operations",
            "ops",
            "payload",
            "patch_ops",
            "patch_rejection_reasons",
            "provenance",
            "record_ids",
            "run_id",
            "schema",
            "snapshot_id",
            "tokens_by_node",
            "tokens_by_node_kind",
            "value",
        ]
    )
)
NODE_DETAIL_PAYLOAD_FIELDS = (
    "accepted_record_selector",
    "allowed_actions",
    "authority",
    "base_snapshot_id",
    "binding_policy",
    "candidate_record_id",
    "candidate_record_ids",
    "candidate_id",
    "command_binding",
    "command_definition",
    "edge_id",
    "evaluated_record_ids",
    "execution_id",
    "expires_at",
    "from_node_kind",
    "from_node_id",
    "from_port",
    "from_node_role",
    "file_state_record_ids",
    "generation",
    "input",
    "kind",
    "lease_generation",
    "lease_id",
    "new_state",
    "node_id",
    "outcome",
    "port",
    "producer_node_id",
    "prompt_summary",
    "record_id",
    "record_ids",
    "record_kind",
    "resource_claims",
    "preconditions",
    "role",
    "retry_not_before",
    "schema",
    "session_id",
    "state",
    "supersedes_record_id",
    "task_region_id",
    "to_node_id",
    "to_port",
    "trigger",
    "verdict",
    "classifications",
    "diff_summary",
    "patch_bundle_id",
    "approval_prompt",
    "approval_type",
    "attempt_number",
    "authority_request",
    "authority_request_record",
    "authority_request_record_id",
    "blocker",
    "blocker_reason",
    "command_definition_id",
    "decision_request",
    "decision_request_record_id",
    "failed_candidate_id",
    "gate_type",
    "generation_index",
    "guarded_planner_node_id",
    "human_prompt",
    "hidden_oracle_command",
    "id",
    "inputs",
    "membership",
    "message",
    "outputs",
    "planner_chain",
    "planner_generation_budget",
    "priority",
    "prompt",
    "reason",
    "recovery_of_node_id",
    "recovery_of_record_id",
    "recovery_reason",
    "region_label",
    "rejected_patch_id",
    "requirement",
    "requirement_id",
)
BOOLEAN_PAYLOAD_FIELDS = frozenset(
    {
        "active",
        "approved",
        "behavior_change",
        "explicit_authority_required",
        "new_behavior",
        "required",
        "requires_authority",
        "semantic_change",
        "stale_only",
        "supported",
        "unsupported",
        "validation_strengthening",
    }
)


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
    if port == "verification_result":
        return "verification_report"
    return port


def _typed_record_payload(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("value")
    if isinstance(value, dict):
        typed_value = dict(cast(dict[str, Any], value))
        if _is_verification_report_payload(payload):
            outcome = payload.get("outcome")
            if isinstance(outcome, str):
                typed_value.setdefault("outcome", outcome)
        return typed_value
    return {
        key: value
        for key, value in payload.items()
        if key not in _RECORD_PAYLOAD_BASE_FIELDS and key not in _LEGACY_RECORD_METADATA_FIELDS
    }


def _is_verification_report_payload(payload: dict[str, Any]) -> bool:
    return (
        payload.get("record_type") == "verification_report"
        or payload.get("record_kind") == "verification"
        or payload.get("port") in {"verification_report", "verification_result"}
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


@dataclass(frozen=True)
class GraphProjectionCheckpoint:
    run_id: str
    position: int
    projection: GraphProjection
    schema_version: int
    terminal: bool


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

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        await self.append_event_summaries(run_id, stored_events)
        await self.append_node_detail_summaries(
            run_id,
            stored_events,
            expected_position=expected_position,
        )
        await self.advance_projection_snapshot(
            run_id,
            stored_events,
            expected_position=expected_position,
        )
        return stored_events

    async def read_run(self, run_id: str, from_position: int = 0) -> list[EventEnvelope]:
        """Read graph events for a run ordered by run-local position."""
        result = await self._session.execute(
            select(EventV2Model)
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.version >= from_position)
            .order_by(EventV2Model.version)
        )
        events: list[EventEnvelope] = []
        for row in result.scalars():
            payload = json.loads(row.payload)
            events.append(EventEnvelope.model_validate(payload))
        return events

    async def read_run_positions(
        self,
        run_id: str,
        positions: list[int],
    ) -> list[EventEnvelope]:
        """Read full graph events for exact run-local positions."""
        unique_positions = sorted(
            {position for position in positions if position > 0 and not isinstance(position, bool)}
        )
        if not unique_positions:
            return []
        result = await self._session.execute(
            select(EventV2Model)
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.version.in_(unique_positions))
            .order_by(EventV2Model.version)
        )
        events: list[EventEnvelope] = []
        for row in result.scalars():
            payload = json.loads(row.payload)
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
        )

    async def read_run_summary_rebuild(
        self,
        run_id: str,
        from_position: int = 0,
    ) -> list[EventEnvelope]:
        """Read only fields needed to rebuild compact graph summaries and snapshots."""
        return await self._read_run_extracting_fields(
            run_id,
            from_position,
            SUMMARY_REBUILD_PAYLOAD_FIELDS,
            include_nested_value_fallbacks=False,
        )

    async def read_run_projection(
        self,
        run_id: str,
        from_position: int = 0,
    ) -> list[EventEnvelope]:
        """Read only fields needed for the compact ``/graph`` projection."""
        return await self._read_run_extracting_fields(
            run_id,
            from_position,
            GRAPH_PROJECTION_PAYLOAD_FIELDS,
        )

    async def read_run_node_detail(
        self,
        run_id: str,
        from_position: int = 0,
    ) -> list[EventEnvelope]:
        """Read fields needed for summary node detail without large payload bodies."""
        return await self._read_run_extracting_fields(
            run_id,
            from_position,
            NODE_DETAIL_PAYLOAD_FIELDS,
        )

    async def _read_run_extracting_fields(
        self,
        run_id: str,
        from_position: int,
        fields: tuple[str, ...],
        *,
        include_nested_value_fallbacks: bool = True,
    ) -> list[EventEnvelope]:
        payload_selects = [
            func.json_extract(EventV2Model.payload, f"$.payload.{field}").label(field)
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
        result = await self._session.execute(
            select(
                EventV2Model.event_type,
                EventV2Model.version,
                EventV2Model.timestamp,
                func.json_extract(EventV2Model.payload, "$.event_id").label("event_id"),
                func.json_extract(EventV2Model.payload, "$.causation_id").label("causation_id"),
                func.json_extract(EventV2Model.payload, "$.correlation_id").label("correlation_id"),
                *payload_selects,
                *nested_payload_selects,
            )
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.version >= from_position)
            .order_by(EventV2Model.version)
        )

        events: list[EventEnvelope] = []
        for row in result.mappings():
            payload = {
                field: _json_extract_payload_value(field, row[field])
                for field in fields
                if row.get(field) is not None
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
            if record_type in {"decision_request", "authority_request_record"} or port in {
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
            events.append(
                EventEnvelope(
                    event_id=str(row.get("event_id") or f"graph-event-{row['version']}"),
                    run_id=run_id,
                    position=int(row["version"]),
                    event_type=str(row["event_type"]),
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
        if row is None or schema_version != PROJECTION_SCHEMA_VERSION:
            return None
        projection = _projection_from_snapshot_row(row)
        if projection is None:
            return None
        return GraphProjectionCheckpoint(
            run_id=run_id,
            position=row.position,
            projection=projection,
            schema_version=schema_version,
            terminal=_projection_terminal_from_snapshot_row(row),
        )

    async def load_projection_with_tail(
        self,
        run_id: str,
    ) -> tuple[GraphProjection, list[EventEnvelope], int]:
        """Load the latest valid snapshot and fold only events after it.

        If the checkpoint is missing, version-mismatched, or malformed, rebuild
        from the full event stream once and persist the fresh snapshot.
        """
        checkpoint = await self.read_projection_checkpoint(run_id)
        if checkpoint is None:
            events = await self.read_run(run_id)
            projection = _projection_from_events(events)
            position = _events_position(events)
            if position > 0:
                await self.persist_projection_snapshot(run_id, projection, position)
                await self._session.commit()
            return projection, events, position

        tail = await self.read_run(run_id, checkpoint.position + 1)
        projection = checkpoint.projection
        for event in tail:
            projection = reduce_event(projection, event)
        position = max(checkpoint.position, _events_position(tail))
        if position != checkpoint.position:
            await self.persist_projection_snapshot(run_id, projection, position)
            await self._session.commit()
        return projection, tail, position

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
        if (
            snapshot is None
            or snapshot.position != current
            or _projection_schema_version_from_snapshot_row(snapshot) != PROJECTION_SCHEMA_VERSION
            or _projection_from_snapshot_row(snapshot) is None
        ):
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
        projection = _projection_from_snapshot_row(row)
        if row is None and expected_position == 0:
            projection = initial_projection()
        elif (
            row is None
            or row.position != expected_position
            or _projection_schema_version_from_snapshot_row(row) != PROJECTION_SCHEMA_VERSION
            or projection is None
        ):
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
        await self._session.flush()
        return row

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

    async def rebuild_read_models(self, run_id: str) -> GraphProjectionSnapshotModel | None:
        """Rebuild disposable graph read models for a run from events_v2."""
        await self.delete_read_models(run_id)
        events = await self.read_run(run_id)
        if not events:
            return None

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
        snapshot = _projection_snapshot_from_events(run_id, events)
        self._session.add(snapshot)
        _add_node_detail_summaries(
            self._session,
            _node_detail_summaries_from_events(
                run_id,
                events,
                position=snapshot.position,
            ),
        )
        self._session.add(
            GraphNodeDetailSummaryCheckpointModel(
                run_id=run_id,
                position=snapshot.position,
            )
        )
        await self._session.flush()
        return snapshot

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
    return GraphEventSummary(
        event_id=event.event_id,
        event_type=event.event_type,
        run_id=event.run_id,
        position=event.position,
        timestamp=event.timestamp.isoformat(),
        payload=payload,
    )


def _summary_from_event(event: EventEnvelope) -> GraphEventSummary:
    return summarize_graph_event(event)


def _projection_snapshot_from_events(
    run_id: str,
    events: list[EventEnvelope],
) -> GraphProjectionSnapshotModel:
    row = GraphProjectionSnapshotModel(run_id=run_id)
    _assign_projection_snapshot(
        row,
        run_id,
        _projection_from_events(events),
        _events_position(events),
        events=events,
    )
    return row


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
    row.run_state = projection["run_state"]
    row.node_states = dict(projection["node_states"])
    row.task_states = dict(projection["task_states"])
    row.leases = project_leases([], projection=projection)
    row.ready_nodes = list(projection["ready_nodes"])
    if events is None:
        row.scheduler = _scheduler_view_from_projection(projection)
        row.lease_view = _lease_view_from_projection(projection)
        decisions = dict(project_decision_view_from_projection(projection))
    else:
        row.scheduler = dict(project_scheduler_view(events))
        row.lease_view = dict(project_lease_view(events))
        decisions = dict(project_decision_view(events))
    row.decisions = _decisions_with_projection_checkpoint(decisions, projection)


def _projection_from_events(events: list[EventEnvelope]) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(projection, event)
    return projection


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
) -> dict[str, Any]:
    return {
        **decisions,
        _CHECKPOINT_SCHEMA_VERSION_KEY: PROJECTION_SCHEMA_VERSION,
        _CHECKPOINT_PROJECTION_KEY: projection_to_checkpoint(projection),
        _CHECKPOINT_TERMINAL_KEY: _is_terminal_run_state(projection["run_state"]),
    }


def _events_position(events: list[EventEnvelope]) -> int:
    if not events:
        return 0
    return max(event.position for event in events)


def _is_terminal_run_state(run_state: str | None) -> bool:
    return run_state in {"completed", "failed", "cancelled"}


def _scheduler_view_from_projection(projection: GraphProjection) -> dict[str, Any]:
    view: dict[str, Any] = {
        "ready": sorted(projection["ready_nodes"]),
        "blocked": [],
        "waiting_resources": [],
        "waiting_gates": [],
    }
    for node_id, state in sorted(projection["node_states"].items()):
        reason = projection.get("last_deferred_reasons", {}).get(node_id)
        if state == "ready" and reason is None:
            continue
        if state not in {"planned", "blocked"}:
            if state != "ready":
                continue
        if reason is None and state != "blocked":
            continue
        if reason is None:
            reason = "blocked"
        entry = {"node_id": node_id, "reason": reason}
        if reason.startswith("resource_") or reason.startswith("invalid_claim:"):
            view["waiting_resources"].append(entry)
        elif (
            reason.startswith("gate_")
            or reason.startswith("waiting_gate")
            or reason.startswith("authority_")
        ):
            view["waiting_gates"].append(entry)
        else:
            view["blocked"].append(entry)
    return view


def _lease_view_from_projection(projection: GraphProjection) -> dict[str, Any]:
    return dict(project_lease_view([], projection=projection))


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
    payload = {
        key: value for key, value in event.payload.items() if key in NODE_DETAIL_PAYLOAD_FIELDS
    }
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
    for key in ("session_id", "expires_at", "execution_id", "base_snapshot_id", "task_region_id"):
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
        prompt_summary=dict(row.prompt_summary) if row.prompt_summary is not None else None,
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
    row.input_ports = {key: list(value) for key, value in summary.input_ports.items()}
    row.output_records = [dict(record) for record in summary.output_records]
    row.file_state_records = [dict(record) for record in summary.file_state_records]
    row.leases = [dict(lease) for lease in summary.leases]
    row.active_lease = dict(summary.active_lease) if summary.active_lease is not None else None
    row.callback_history = [dict(event) for event in summary.callback_history]
    row.events = [dict(event) for event in summary.events]
    row.prompt_summary = (
        dict(summary.prompt_summary) if summary.prompt_summary is not None else None
    )


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
