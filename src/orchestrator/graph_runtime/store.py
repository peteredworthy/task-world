"""SQLite-backed event store for graph event envelopes."""

from __future__ import annotations

import json

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db import EventV2Model
from orchestrator.graph import Actor, ActorKind, EventEnvelope
from orchestrator.graph_runtime.errors import StaleProjectionError

GRAPH_AGGREGATE_PREFIX = "graph:"
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
    "blocker",
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
    "patch_id",
    "producer_node_id",
    "proposed_by_node_id",
    "reason",
    "rejected_patches",
    "rejection_reason",
    "role",
    "state",
    "task_region_id",
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
    "behavior_change",
    "blocker",
    "cache_read_tokens",
    "cache_write_tokens",
    "candidate_id",
    "classification",
    "cleanup_id",
    "command_definition",
    "command_definition_id",
    "confidence",
    "decision",
    "deleted_snapshot_ref",
    "dependency_type",
    "edge_id",
    "evidence_id",
    "execution_id",
    "expires_at",
    "explicit_authority_required",
    "failed_candidate_id",
    "file_state_record_id",
    "from_node_id",
    "from_port",
    "from_state",
    "gate_id",
    "gate_type",
    "generation",
    "generation_index",
    "input",
    "input_tokens",
    "kind",
    "lease_generation",
    "lease_id",
    "membership",
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
    "previous_version_id",
    "priority",
    "prompt",
    "producer_node_id",
    "proposed_by_node_id",
    "reason",
    "record_id",
    "record_kind",
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
    "revision_type",
    "role",
    "semantic_change",
    "session_id",
    "stale_only",
    "stale_reason",
    "state",
    "status",
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
)
GRAPH_PROJECTION_PAYLOAD_FIELDS = (
    "attempt_number",
    "base_snapshot_id",
    "candidate_id",
    "execution_id",
    "expires_at",
    "failed_candidate_id",
    "from_state",
    "generation",
    "kind",
    "lease_id",
    "new_state",
    "node_id",
    "port",
    "producer_node_id",
    "record_id",
    "record_kind",
    "role",
    "session_id",
    "state",
    "task_region_id",
    "to_state",
)


def graph_aggregate_id(run_id: str) -> str:
    """events_v2 aggregate key for a run's graph event stream.

    Legacy workflow events use ``aggregate_id == run_id``; graph events are
    namespaced so the two streams never contend for the same
    (aggregate_id, version) sequence and never appear in each other's reads.
    """
    return f"{GRAPH_AGGREGATE_PREFIX}{run_id}"


@dataclass(frozen=True)
class GraphEventSummary:
    event_id: str
    event_type: str
    run_id: str
    position: int
    timestamp: str
    payload: dict[str, Any]


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
            stored = event.model_copy(update={"run_id": run_id, "position": position})
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

    async def _read_run_extracting_fields(
        self,
        run_id: str,
        from_position: int,
        fields: tuple[str, ...],
    ) -> list[EventEnvelope]:
        payload_selects = [
            func.json_extract(EventV2Model.payload, f"$.payload.{field}").label(field)
            for field in fields
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
            )
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.version >= from_position)
            .order_by(EventV2Model.version)
        )

        events: list[EventEnvelope] = []
        for row in result.mappings():
            payload = {
                field: _json_extract_value(row[field])
                for field in fields
                if row.get(field) is not None
            }
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
    ) -> list[GraphEventSummary]:
        """Read compact graph event rows without materializing large payloads."""
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


def _summary_from_event(event: EventEnvelope) -> GraphEventSummary:
    payload = {
        key: value
        for key, value in event.payload.items()
        if key in SUMMARY_PAYLOAD_FIELDS
        or key
        in {
            "blockers",
            "graph_verifier_grades",
            "ops",
            "operations",
            "patch_ops",
            "patch_rejection_reasons",
            "tokens_by_node",
            "tokens_by_node_kind",
            "value",
            "grades",
        }
    }
    return GraphEventSummary(
        event_id=event.event_id,
        event_type=event.event_type,
        run_id=event.run_id,
        position=event.position,
        timestamp=event.timestamp.isoformat(),
        payload=payload,
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
