"""SQLite-backed event store for graph event envelopes."""

from __future__ import annotations

import json

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db import EventV2Model, GraphEventSummaryModel, GraphProjectionSnapshotModel
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    project_decision_view,
    project_leases,
    project_lease_view,
    project_node_states,
    project_ready_nodes,
    project_run_state,
    project_scheduler_view,
    project_task_states,
)
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
    "port",
    "producer_node_id",
    "proposed_by_node_id",
    "reason",
    "record_id",
    "record_kind",
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
SUMMARY_REBUILD_PAYLOAD_FIELDS = tuple(
    dict.fromkeys(
        [
            *LIGHT_GRAPH_PAYLOAD_FIELDS,
            *SUMMARY_PAYLOAD_FIELDS,
            "blockers",
            "graph_verifier_grades",
            "grades",
            "operations",
            "ops",
            "patch_ops",
            "patch_rejection_reasons",
            "tokens_by_node",
            "tokens_by_node_kind",
            "value",
        ]
    )
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
NODE_DETAIL_PAYLOAD_FIELDS = (
    "accepted_record_selector",
    "base_snapshot_id",
    "candidate_id",
    "edge_id",
    "execution_id",
    "expires_at",
    "from_node_id",
    "from_port",
    "generation",
    "input",
    "kind",
    "lease_generation",
    "lease_id",
    "new_state",
    "node_id",
    "port",
    "producer_node_id",
    "record_id",
    "record_ids",
    "record_kind",
    "role",
    "schema",
    "session_id",
    "state",
    "task_region_id",
    "to_node_id",
    "to_port",
    "trigger",
    "verdict",
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
        await self.append_event_summaries(run_id, stored_events)
        await self.invalidate_projection_snapshot(run_id)
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

    async def read_projection_snapshot(
        self,
        run_id: str,
    ) -> GraphProjectionSnapshotModel | None:
        """Read the current materialized graph projection, rebuilding if stale."""
        await self.ensure_projection_snapshot(run_id)
        return await self._session.get(GraphProjectionSnapshotModel, run_id)

    async def ensure_read_models(self, run_id: str) -> None:
        """Rebuild disposable graph read models if missing or behind events_v2."""
        await self.ensure_event_summaries(run_id)
        await self.ensure_projection_snapshot(run_id)

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
        if snapshot is None or snapshot.position != current:
            await self.rebuild_read_models(run_id)

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

    async def invalidate_projection_snapshot(self, run_id: str) -> None:
        """Drop the disposable projection snapshot after appending new events."""
        await self._session.execute(
            delete(GraphProjectionSnapshotModel).where(
                GraphProjectionSnapshotModel.run_id == run_id
            )
        )
        await self._session.flush()

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
        await self._session.flush()

    async def rebuild_read_models(self, run_id: str) -> GraphProjectionSnapshotModel | None:
        """Rebuild disposable graph read models for a run from events_v2."""
        await self.delete_read_models(run_id)
        events = await self.read_run_summary_rebuild(run_id)
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
        await self._session.flush()
        return snapshot

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
            payload["value"] = {"grades": grades}
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
    return GraphProjectionSnapshotModel(
        run_id=run_id,
        position=max(event.position for event in events),
        run_state=project_run_state(events),
        node_states=project_node_states(events),
        task_states=project_task_states(events),
        leases=project_leases(events),
        ready_nodes=project_ready_nodes(events),
        scheduler=project_scheduler_view(events),
        lease_view=project_lease_view(events),
        decisions=project_decision_view(events),
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
