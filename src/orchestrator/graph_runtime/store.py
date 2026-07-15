"""SQLite-backed event store for graph event envelopes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from orchestrator.db import (
    EventV2Model,
    GraphEventSummaryModel,
    GraphNodeDetailSummaryCheckpointModel,
    GraphNodeDetailSummaryModel,
    GraphProjectionSnapshotModel,
)
from orchestrator.graph import (
    AgentDiedPayload,
    AgentDispatchRequestedPayload,
    AppealOpenedPayload,
    ApprovalDecisionRecordedPayload,
    AuthorityDecisionRecordedPayload,
    CallbackAcceptedPayload,
    CallbackDuplicateReturnedPayload,
    CallbackRejectedPayload,
    CleanupAppliedPayload,
    CleanupRequestedPayload,
    CommandRejectedPayload,
    DeadInputDetectedPayload,
    GraphCatalog,
    GraphPatchAcceptedPayload,
    GraphPatchRejectedPayload,
    GraphProjection,
    HeartbeatRecordedPayload,
    HydratedEvent,
    InputBoundPayload,
    EdgeCreatedPayload,
    FileStateRejectedPayload,
    GatekeeperCostRecordedPayload,
    GatekeeperVerdictRecordedPayload,
    LeaseExpiredPayload,
    LeaseGrantedPayload,
    LeaseReleasedPayload,
    LeaseRenewedPayload,
    LeaseRevokedPayload,
    NodeCreatedPayload,
    NodeAuthorityChangedPayload,
    NodeDeferredPayload,
    NodeReadyPayload,
    NodeRetiredPayload,
    NodeStateChangedPayload,
    OutputRecordAcceptedPayload,
    OversightDecisionRecordedPayload,
    PlanRegionMarkedSuspectPayload,
    PlannerSessionStateChangedPayload,
    RequirementRevisionPayload,
    RevisionCreatedPayload,
    RunLifecycleChangedPayload,
    RuntimeRetryScheduledPayload,
    PROJECTION_SCHEMA_VERSION,
    StrictFileStateRecord,
    StoredEventEnvelope,
    SupportEvidencePayload,
    VerificationOutcomePayload,
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
from orchestrator.graph_runtime.errors import (
    EventPayloadCorruptionError,
    IncompatibleGraphPayloadGenerationError,
    InvalidGraphEventPayloadError,
    StaleProjectionError,
)

GRAPH_PAYLOAD_SCHEMA_GENERATION = 2

GRAPH_AGGREGATE_PREFIX = "graph:"
_CHECKPOINT_PROJECTION_KEY = "_projection_checkpoint"
_CHECKPOINT_SCHEMA_VERSION_KEY = "_projection_schema_version"
_CHECKPOINT_TERMINAL_KEY = "_projection_terminal"


def graph_aggregate_id(run_id: str) -> str:
    """events_v2 aggregate key for a run's graph event stream.

    Legacy workflow events use ``aggregate_id == run_id``; graph events are
    namespaced so the two streams never contend for the same
    (aggregate_id, version) sequence and never appear in each other's reads.
    """
    return f"{GRAPH_AGGREGATE_PREFIX}{run_id}"


def _payload_with_durable_graph_position(
    event: HydratedEvent,
    position: int,
    run_id: str,
) -> HydratedEvent:
    """Enrich persistence-owned fields without using a JSON decision view."""
    payload = event.payload
    if event.event_type == "output_record_accepted":
        if not isinstance(payload, OutputRecordAcceptedPayload):
            raise TypeError("output_record_accepted event has an unexpected payload type")
        record_value = getattr(payload.record, "value", None)
        durable_payload = payload.record.payload
        if durable_payload is None and isinstance(record_value, BaseModel):
            durable_payload = record_value.model_dump(mode="json")
        record = payload.record.model_copy(
            update={
                "run_id": run_id,
                "created_at": event.timestamp.isoformat(),
                "graph_position": position,
                "schema_version": payload.record.schema_version or 1,
                "producer_port": payload.record.producer_port or payload.record.port,
                "payload": durable_payload,
            }
        )
        return event.model_copy(update={"payload": payload.model_copy(update={"record": record})})
    if event.event_type == "file_state_accepted":
        if not isinstance(payload, StrictFileStateRecord):
            raise TypeError("file_state_accepted event has an unexpected payload type")
        return event.model_copy(
            update={
                "payload": payload.model_copy(
                    update={
                        "run_id": run_id,
                        "created_at": event.timestamp.isoformat(),
                        "graph_position": position,
                        "schema_version": payload.schema_version or 1,
                        "producer_port": payload.producer_port or payload.port,
                        "record_type": payload.record_type,
                        "payload": payload.payload
                        or {
                            "snapshot_id": payload.snapshot_id,
                            "base_snapshot_id": payload.base_snapshot_id,
                            "verdict": payload.verdict,
                        },
                    }
                )
            }
        )
    if event.event_type == "input_bound":
        if not isinstance(payload, InputBoundPayload):
            raise TypeError("input_bound event has an unexpected payload type")
        if payload.bound_at_position <= 0:
            return event.model_copy(
                update={"payload": payload.model_copy(update={"bound_at_position": position})}
            )
    return event


def stored_graph_event(
    catalog: GraphCatalog,
    event: object,
    *,
    run_id: str,
    position: int,
) -> HydratedEvent:
    """Assign durable metadata and rehydrate one catalog-owned event.

    This is the sole command-to-storage boundary: production callers supply an
    already hydrated generation-2 event and this helper serializes it only long
    enough to add persistence-owned fields before catalog hydration.
    """
    if not isinstance(event, HydratedEvent):
        raise TypeError("graph event append requires HydratedEvent instances")
    if event.metadata.payload_schema_generation != GRAPH_PAYLOAD_SCHEMA_GENERATION:
        raise ValueError("graph event append requires payload schema generation 2")
    specification = catalog.resolve_event(event.metadata.event_type)
    specification.serialize(event)
    metadata = event.metadata.model_copy(update={"run_id": run_id, "position": position})
    enriched = _payload_with_durable_graph_position(event, position, run_id)
    stored = specification.serialize(enriched.model_copy(update={"metadata": metadata}))
    return catalog.hydrate_event(stored)


def _stored_envelope_from_json(
    payload_json: str,
) -> StoredEventEnvelope:
    return StoredEventEnvelope.model_validate_json(payload_json)


def validate_stored_event_metadata(
    stored: StoredEventEnvelope,
    *,
    run_id: str,
    position: int,
    event_type: str,
    payload_schema_generation: int,
) -> None:
    if (
        stored.run_id != run_id
        or stored.position != position
        or stored.event_type != event_type
        or stored.payload_schema_generation != payload_schema_generation
    ):
        raise ValueError("stored envelope metadata does not match its database row")


def validate_catalog_event_payload(catalog: GraphCatalog, event: StoredEventEnvelope) -> None:
    """Validate a stored catalog-owned event payload with hydration parity.

    Validation uses the same catalog hydration path as storage readback, so a
    serialized event that appends cleanly is guaranteed to hydrate cleanly later.
    """
    specification = catalog.resolve_event(event.event_type)
    try:
        specification.hydrate(event)
    except ValueError as error:
        msg = (
            f"invalid graph event payload for event_type={event.event_type!r} "
            f"at position {event.position}: {error}"
        )
        raise InvalidGraphEventPayloadError(msg) from error


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

    def __init__(self, session: AsyncSession, catalog: GraphCatalog) -> None:
        self._session = session
        self._catalog = catalog

    async def append_events(
        self,
        run_id: str,
        expected_position: int,
        events: Sequence[HydratedEvent],
    ) -> list[HydratedEvent]:
        """Append events if the run stream is still at ``expected_position``.

        Events must already be catalog-created generation-2 hydrated events.
        Intentional storage corruption tests insert raw ``StoredEventEnvelope``
        rows directly; production append has no raw-envelope escape hatch.
        """
        if not events:
            return []

        current_position = await self.current_position(run_id)
        if current_position != expected_position:
            msg = (
                f"stale graph projection for run {run_id}: "
                f"expected {expected_position}, found {current_position}"
            )
            raise StaleProjectionError(msg)

        stored_events: list[HydratedEvent] = []
        hydrated_events: list[HydratedEvent] = []
        rows: list[EventV2Model] = []
        for offset, event in enumerate(events, start=1):
            position = expected_position + offset
            stored = stored_graph_event(self._catalog, event, run_id=run_id, position=position)
            stored_events.append(stored)
            envelope = self._catalog.resolve_event(stored.event_type).serialize(stored)
            rows.append(
                EventV2Model(
                    aggregate_id=graph_aggregate_id(run_id),
                    version=position,
                    event_type=stored.event_type,
                    payload=envelope.model_dump_json(),
                    payload_schema_generation=GRAPH_PAYLOAD_SCHEMA_GENERATION,
                    timestamp=stored.timestamp.isoformat(),
                )
            )
            hydrated_events.append(stored)

        self._session.add_all(rows)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            msg = f"stale graph projection for run {run_id}"
            raise StaleProjectionError(msg) from exc
        await self.append_event_summaries(run_id, hydrated_events)
        await self.append_node_detail_summaries(
            run_id,
            hydrated_events,
            expected_position=expected_position,
        )
        await self.advance_projection_snapshot(
            run_id,
            hydrated_events,
            expected_position=expected_position,
        )
        return stored_events

    async def read_run(self, run_id: str, from_position: int = 0) -> list[HydratedEvent]:
        """Read graph events for a run ordered by run-local position."""
        result = await self._session.execute(
            select(EventV2Model)
            .where(EventV2Model.aggregate_id == graph_aggregate_id(run_id))
            .where(EventV2Model.version >= from_position)
            .order_by(EventV2Model.version)
        )
        events: list[HydratedEvent] = []
        for row in result.scalars():
            if row.payload_schema_generation != GRAPH_PAYLOAD_SCHEMA_GENERATION:
                raise IncompatibleGraphPayloadGenerationError(
                    run_id, row.version, row.payload_schema_generation
                )
            try:
                stored = _stored_envelope_from_json(row.payload)
                validate_stored_event_metadata(
                    stored,
                    run_id=run_id,
                    position=row.version,
                    event_type=row.event_type,
                    payload_schema_generation=row.payload_schema_generation,
                )
                event = self._catalog.hydrate_event(stored)
            except (TypeError, ValueError) as exc:
                raise EventPayloadCorruptionError(
                    run_id, row.version, row.event_type, str(exc)
                ) from exc
            events.append(event)
        return events

    async def read_run_positions(
        self,
        run_id: str,
        positions: list[int],
    ) -> list[HydratedEvent]:
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
        events: list[HydratedEvent] = []
        for row in result.scalars():
            if row.payload_schema_generation != GRAPH_PAYLOAD_SCHEMA_GENERATION:
                raise IncompatibleGraphPayloadGenerationError(
                    run_id, row.version, row.payload_schema_generation
                )
            try:
                stored = _stored_envelope_from_json(row.payload)
                validate_stored_event_metadata(
                    stored,
                    run_id=run_id,
                    position=row.version,
                    event_type=row.event_type,
                    payload_schema_generation=row.payload_schema_generation,
                )
                events.append(self._catalog.hydrate_event(stored))
            except (TypeError, ValueError) as exc:
                raise EventPayloadCorruptionError(
                    run_id, row.version, row.event_type, str(exc)
                ) from exc
        return events

    async def read_run_light(self, run_id: str, from_position: int = 0) -> list[HydratedEvent]:
        return await self.read_run(run_id, from_position)

    async def read_run_summary_rebuild(
        self,
        run_id: str,
        from_position: int = 0,
    ) -> list[HydratedEvent]:
        return await self.read_run(run_id, from_position)

    async def read_run_projection(
        self,
        run_id: str,
        from_position: int = 0,
    ) -> list[HydratedEvent]:
        return await self.read_run(run_id, from_position)

    async def read_run_node_detail(
        self,
        run_id: str,
        from_position: int = 0,
    ) -> list[HydratedEvent]:
        return await self.read_run(run_id, from_position)

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
    ) -> tuple[GraphProjection, list[HydratedEvent], int]:
        """Load the latest valid snapshot and fold only events after it.

        If the checkpoint is missing, version-mismatched, or malformed, rebuild
        from the full event stream once and persist the fresh snapshot.
        """
        checkpoint = await self.read_projection_checkpoint(run_id)
        if checkpoint is None:
            events = await self.read_run(run_id)
            projection = _projection_from_events(self._catalog, events)
            position = _events_position(events)
            if position > 0:
                await self.persist_projection_snapshot(run_id, projection, position)
                await self._session.commit()
            return projection, events, position

        tail = await self.read_run(run_id, checkpoint.position + 1)
        projection = checkpoint.projection
        for event in tail:
            projection = reduce_event(self._catalog, projection, event)
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
        events: Sequence[HydratedEvent],
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
                for summary in (
                    _complete_graph_event_summary(self._catalog, event) for event in events
                )
            ]
        )
        await self._session.flush()

    async def append_node_detail_summaries(
        self,
        run_id: str,
        events: Sequence[HydratedEvent],
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
        if _has_missing_preexisting_node_reference(self._catalog, events, existing_node_ids):
            await self.delete_node_detail_summaries(run_id)
            return
        lease_update_ids: set[str] = set()
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
            self._catalog,
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
        events: Sequence[HydratedEvent],
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
            projection = reduce_event(self._catalog, projection, event)
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
        _assign_projection_snapshot(self._catalog, row, run_id, projection, position)
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
                for summary in (
                    _complete_graph_event_summary(self._catalog, event) for event in events
                )
            ]
        )
        snapshot = _projection_snapshot_from_events(self._catalog, run_id, events)
        self._session.add(snapshot)
        _add_node_detail_summaries(
            self._session,
            _node_detail_summaries_from_events(
                self._catalog,
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
            _node_detail_summaries_from_events(
                self._catalog,
                run_id,
                events,
                position=position,
            ),
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
        events: Sequence[HydratedEvent],
        known_node_ids: set[str],
    ) -> dict[str, GraphNodeDetailSummaryModel]:
        node_ids: set[str] = set()
        for event in events:
            node_ids.update(_referenced_node_ids(event, known_node_ids | node_ids))
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
        events: Sequence[HydratedEvent],
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
        return [
            _complete_graph_event_summary(self._catalog, event)
            for event in await self.read_run(run_id, from_position)
        ]

    async def current_position(self, run_id: str) -> int:
        result = await self._session.execute(
            select(func.max(EventV2Model.version)).where(
                EventV2Model.aggregate_id == graph_aggregate_id(run_id)
            )
        )
        return int(result.scalar_one_or_none() or 0)


def _complete_graph_event_summary(catalog: GraphCatalog, event: HydratedEvent) -> GraphEventSummary:
    return GraphEventSummary(
        event_id=event.event_id,
        event_type=event.event_type,
        run_id=event.run_id,
        position=event.position,
        timestamp=event.timestamp.isoformat(),
        payload=_serialized_event_payload(catalog, event),
    )


def _require_catalog_payload(catalog: GraphCatalog, event: HydratedEvent) -> None:
    specification = catalog.resolve_event(event.event_type)
    if type(event.payload) is not specification.payload_type:
        raise TypeError(f"{event.event_type} event has an unexpected payload type")


def _serialized_event_payload(catalog: GraphCatalog, event: HydratedEvent) -> dict[str, Any]:
    """Serialize only after catalog validation at a read-model presentation boundary."""
    _require_catalog_payload(catalog, event)
    return catalog.resolve_event(event.event_type).serialize(event).payload


def _projection_snapshot_from_events(
    catalog: GraphCatalog,
    run_id: str,
    events: Sequence[HydratedEvent],
) -> GraphProjectionSnapshotModel:
    row = GraphProjectionSnapshotModel(run_id=run_id)
    _assign_projection_snapshot(
        catalog,
        row,
        run_id,
        _projection_from_events(catalog, events),
        _events_position(events),
        events=events,
    )
    return row


def _assign_projection_snapshot(
    catalog: GraphCatalog,
    row: GraphProjectionSnapshotModel,
    run_id: str,
    projection: GraphProjection,
    position: int,
    *,
    events: Sequence[HydratedEvent] | None = None,
) -> None:
    row.run_id = run_id
    row.position = position
    row.run_state = projection["run_state"]
    row.node_states = dict(projection["node_states"])
    row.task_states = dict(projection["task_states"])
    row.leases = project_leases(catalog, [], projection=projection)
    row.ready_nodes = list(projection["ready_nodes"])
    if events is None:
        row.scheduler = _scheduler_view_from_projection(projection)
        row.lease_view = _lease_view_from_projection(catalog, projection)
        decisions = dict(project_decision_view_from_projection(projection))
    else:
        row.scheduler = dict(project_scheduler_view(catalog, events))
        row.lease_view = dict(project_lease_view(catalog, events))
        decisions = dict(project_decision_view(catalog, events))
    row.decisions = _decisions_with_projection_checkpoint(decisions, projection)


def _projection_from_events(
    catalog: GraphCatalog,
    events: Sequence[HydratedEvent],
) -> GraphProjection:
    projection = initial_projection()
    for event in events:
        projection = reduce_event(catalog, projection, event)
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


def _events_position(events: Sequence[HydratedEvent]) -> int:
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


def _lease_view_from_projection(
    catalog: GraphCatalog,
    projection: GraphProjection,
) -> dict[str, Any]:
    return dict(project_lease_view(catalog, [], projection=projection))


def _add_node_detail_summaries(
    session: AsyncSession,
    summaries: dict[str, GraphNodeDetailSummary],
) -> None:
    for summary in summaries.values():
        row = GraphNodeDetailSummaryModel(run_id=summary.run_id, node_id=summary.node_id)
        _assign_node_detail_summary(row, summary)
        session.add(row)


def _node_detail_summaries_from_events(
    catalog: GraphCatalog,
    run_id: str,
    events: Sequence[HydratedEvent],
    *,
    position: int,
) -> dict[str, GraphNodeDetailSummary]:
    return _apply_node_detail_events(
        catalog,
        run_id,
        events,
        position=position,
        existing_node_ids=set(),
        summaries={},
        edge_ports={},
    )


def _apply_node_detail_events(
    catalog: GraphCatalog,
    run_id: str,
    events: Sequence[HydratedEvent],
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
        _require_catalog_payload(catalog, event)
        if event.event_type == "edge_created":
            if not isinstance(event.payload, EdgeCreatedPayload):
                raise TypeError("edge_created event has an unexpected payload type")
            edge_ports[event.payload.edge_id] = event.payload.to_port

        if event.event_type == "node_created":
            if not isinstance(event.payload, NodeCreatedPayload):
                raise TypeError("node_created event has an unexpected payload type")
            known_node_ids.add(event.payload.node_id)

        referenced_node_ids = _referenced_node_ids(event, known_node_ids)
        event_response = _present_node_event(event)
        for node_id in sorted(referenced_node_ids):
            summary = summaries.get(node_id)
            if summary is None:
                summary = _empty_node_detail_summary(run_id, node_id, position)
            summary = _append_node_event(
                summary,
                event_response,
                position=position,
                is_callback=_is_callback_history_event(event),
            )
            summaries[node_id] = summary
            updated[node_id] = summary

        event_updates = _node_detail_field_updates(event, edge_ports, summaries, position)
        for node_id, summary in event_updates.items():
            known_node_ids.add(node_id)
            summaries[node_id] = summary
            updated[node_id] = summary

    return dict(updated)


def _node_detail_field_updates(
    event: HydratedEvent,
    edge_ports: dict[str, str],
    summaries: dict[str, GraphNodeDetailSummary],
    position: int,
) -> dict[str, GraphNodeDetailSummary]:
    updates: dict[str, GraphNodeDetailSummary] = {}
    if event.event_type == "node_created":
        if not isinstance(event.payload, NodeCreatedPayload):
            raise TypeError("node_created event has an unexpected payload type")
        payload = event.payload
        node_id = payload.node_id
        summary = summaries.get(node_id) or _empty_node_detail_summary(
            event.run_id,
            node_id,
            position,
        )
        updates[node_id] = _replace_summary(
            summary,
            position=position,
            kind=payload.kind,
            role=payload.role or summary.role,
            state=payload.state or summary.state,
            task_region_id=payload.task_region_id or summary.task_region_id,
        )
    elif event.event_type == "node_state_changed":
        if not isinstance(event.payload, NodeStateChangedPayload):
            raise TypeError("node_state_changed event has an unexpected payload type")
        payload = event.payload
        summary = summaries.get(payload.node_id) or _empty_node_detail_summary(
            event.run_id, payload.node_id, position
        )
        update_fields: dict[str, Any] = {"position": position, "state": payload.new_state}
        if payload.prompt_summary is not None:
            update_fields["prompt_summary"] = dict(payload.prompt_summary)
        updates[payload.node_id] = _replace_summary(summary, **update_fields)
    elif event.event_type == "node_retired":
        if not isinstance(event.payload, NodeRetiredPayload):
            raise TypeError("node_retired event has an unexpected payload type")
        payload = event.payload
        summary = summaries.get(payload.node_id) or _empty_node_detail_summary(
            event.run_id, payload.node_id, position
        )
        updates[payload.node_id] = _replace_summary(summary, position=position, state="retired")
    elif event.event_type == "input_bound":
        if not isinstance(event.payload, InputBoundPayload):
            raise TypeError("input_bound event has an unexpected payload type")
        payload = event.payload
        port = payload.to_port or edge_ports.get(payload.edge_id)
        if not port:
            return updates
        summary = summaries.get(payload.to_node_id) or _empty_node_detail_summary(
            event.run_id, payload.to_node_id, position
        )
        input_ports = {key: list(value) for key, value in summary.input_ports.items()}
        input_ports[port] = merge_bound_record_ids(
            payload.binding_policy or "bind_first",
            input_ports.get(port, []),
            payload.record_ids,
            supersedes_record_id=payload.supersedes_record_id,
        )
        updates[payload.to_node_id] = _replace_summary(
            summary, position=position, input_ports=input_ports
        )
    elif event.event_type == "lease_granted":
        if not isinstance(event.payload, LeaseGrantedPayload):
            raise TypeError("lease_granted event has an unexpected payload type")
        payload = event.payload
        node_id = payload.node_id
        if node_id:
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
        "lease_revoked",
        "lease_expired",
        "lease_released",
    }:
        if not isinstance(
            event.payload, (LeaseRevokedPayload, LeaseExpiredPayload, LeaseReleasedPayload)
        ):
            raise TypeError(f"{event.event_type} event has an unexpected payload type")
        payload = event.payload
        lease_id = payload.lease_id
        target_ids = [payload.node_id]
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
        if not isinstance(event.payload, OutputRecordAcceptedPayload):
            raise TypeError("output_record_accepted event has an unexpected payload type")
        record = event.payload.record
        if record.record_kind != "file_state":
            node_id = record.producer_node_id
            summary = summaries.get(node_id) or _empty_node_detail_summary(
                event.run_id,
                node_id,
                position,
            )
            records = [dict(record) for record in summary.output_records]
            records.append(record.model_dump(mode="json", by_alias=True, exclude_none=True))
            updates[node_id] = _replace_summary(
                summary,
                position=position,
                output_records=records,
            )
    elif event.event_type == "file_state_accepted":
        if not isinstance(event.payload, StrictFileStateRecord):
            raise TypeError("file_state_accepted event has an unexpected payload type")
        record = event.payload
        node_id = record.producer_node_id
        if node_id:
            summary = summaries.get(node_id) or _empty_node_detail_summary(
                event.run_id,
                node_id,
                position,
            )
            records = [dict(record) for record in summary.file_state_records]
            records.append(record.model_dump(mode="json", by_alias=True, exclude_none=True))
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


def _is_callback_history_event(event: HydratedEvent) -> bool:
    if event.event_type in {
        "callback_accepted",
        "callback_rejected_stale",
        "callback_rejected_conflict",
        "callback_duplicate_returned",
        "agent_died",
    }:
        return True
    if event.event_type != "node_state_changed":
        return False
    if not isinstance(event.payload, NodeStateChangedPayload):
        raise TypeError("node_state_changed event has an unexpected payload type")
    return event.payload.trigger == "runtime_start_acknowledged"


def _present_node_event(event: HydratedEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "run_id": event.run_id,
        "position": event.position,
        "timestamp": event.timestamp.isoformat(),
        "payload": event.payload.model_dump(mode="json", by_alias=True, exclude_none=True),
    }


_NODE_DETAIL_EVENT_PAYLOAD_TYPES: dict[str, type[BaseModel]] = {
    "agent_died": AgentDiedPayload,
    "agent_dispatch_requested": AgentDispatchRequestedPayload,
    "appeal_opened": AppealOpenedPayload,
    "approval_decision_recorded": ApprovalDecisionRecordedPayload,
    "authority_decision_recorded": AuthorityDecisionRecordedPayload,
    "callback_accepted": CallbackAcceptedPayload,
    "callback_duplicate_returned": CallbackDuplicateReturnedPayload,
    "callback_rejected_conflict": CallbackRejectedPayload,
    "callback_rejected_stale": CallbackRejectedPayload,
    "cleanup_applied": CleanupAppliedPayload,
    "cleanup_requested": CleanupRequestedPayload,
    "command_rejected": CommandRejectedPayload,
    "dead_input_detected": DeadInputDetectedPayload,
    "edge_created": EdgeCreatedPayload,
    "file_state_accepted": StrictFileStateRecord,
    "file_state_rejected": FileStateRejectedPayload,
    "gatekeeper_cost_recorded": GatekeeperCostRecordedPayload,
    "gatekeeper_verdict_recorded": GatekeeperVerdictRecordedPayload,
    "graph_patch_accepted": GraphPatchAcceptedPayload,
    "graph_patch_rejected": GraphPatchRejectedPayload,
    "heartbeat_recorded": HeartbeatRecordedPayload,
    "input_bound": InputBoundPayload,
    "lease_expired": LeaseExpiredPayload,
    "lease_granted": LeaseGrantedPayload,
    "lease_released": LeaseReleasedPayload,
    "lease_renewed": LeaseRenewedPayload,
    "lease_revoked": LeaseRevokedPayload,
    "node_authority_changed": NodeAuthorityChangedPayload,
    "node_created": NodeCreatedPayload,
    "node_deferred": NodeDeferredPayload,
    "node_ready": NodeReadyPayload,
    "node_retired": NodeRetiredPayload,
    "node_state_changed": NodeStateChangedPayload,
    "output_record_accepted": OutputRecordAcceptedPayload,
    "oversight_decision_recorded": OversightDecisionRecordedPayload,
    "plan_region_marked_suspect": PlanRegionMarkedSuspectPayload,
    "requirement_revision_recorded": RequirementRevisionPayload,
    "revision_created": RevisionCreatedPayload,
    "run_lifecycle_changed": RunLifecycleChangedPayload,
    "runtime_retry_scheduled": RuntimeRetryScheduledPayload,
    "session_state_changed": PlannerSessionStateChangedPayload,
    "support_evidence_recorded": SupportEvidencePayload,
    "verification_failed": VerificationOutcomePayload,
    "verification_passed": VerificationOutcomePayload,
}


def _referenced_node_ids(event: HydratedEvent, known_node_ids: set[str]) -> set[str]:
    """Project only the node references declared by the event's typed payload class."""
    del known_node_ids
    expected_payload_type = _NODE_DETAIL_EVENT_PAYLOAD_TYPES.get(event.event_type)
    if expected_payload_type is None or type(event.payload) is not expected_payload_type:
        raise TypeError(f"{event.event_type} event has an unexpected payload type")
    return _declared_node_references(event.payload)


def _declared_node_references(payload: BaseModel) -> set[str]:
    """Enumerate every node-reference field declared in graph event payload models."""
    if isinstance(payload, NodeCreatedPayload):
        return _node_ids(
            payload.node_id,
            payload.recovery_of_node_id,
            payload.guarded_planner_node_id,
            payload.appealed_node_id,
            *(payload.predecessor_node_ids or []),
        )
    if isinstance(payload, EdgeCreatedPayload):
        return _node_ids(payload.from_node_id, payload.to_node_id)
    if isinstance(payload, DeadInputDetectedPayload):
        return _node_ids(
            payload.node_id,
            payload.from_node_id,
            payload.to_node_id,
            payload.source_node_id,
        )
    if isinstance(payload, PlanRegionMarkedSuspectPayload):
        return _node_ids(*payload.region_node_ids)
    if isinstance(payload, GraphPatchAcceptedPayload):
        return _node_ids(payload.proposed_by_node_id, *payload.successor_planner_node_ids)
    if isinstance(payload, GraphPatchRejectedPayload):
        return _node_ids(payload.proposed_by_node_id)
    if isinstance(payload, (AppealOpenedPayload, OversightDecisionRecordedPayload)):
        return _node_ids(payload.node_id, payload.appealed_node_id)
    if isinstance(payload, (ApprovalDecisionRecordedPayload, AuthorityDecisionRecordedPayload)):
        return _node_ids(payload.node_id, payload.appeal_node_id)
    if isinstance(payload, VerificationOutcomePayload):
        return _node_ids(payload.node_id, payload.verifier_node_id)
    if isinstance(payload, OutputRecordAcceptedPayload):
        return _node_ids(payload.record.producer_node_id)
    if isinstance(
        payload,
        (
            StrictFileStateRecord,
            GatekeeperVerdictRecordedPayload,
            CleanupRequestedPayload,
        ),
    ):
        return _node_ids(payload.producer_node_id)
    if isinstance(payload, RunLifecycleChangedPayload):
        return _node_ids(payload.node_id, payload.recovery_of_node_id)
    if isinstance(payload, CommandRejectedPayload):
        return _node_ids(payload.proposed_by_node_id)
    if isinstance(
        payload,
        (
            InputBoundPayload,
            PlannerSessionStateChangedPayload,
            LeaseGrantedPayload,
            LeaseRenewedPayload,
            LeaseReleasedPayload,
            LeaseRevokedPayload,
            LeaseExpiredPayload,
            NodeAuthorityChangedPayload,
            NodeDeferredPayload,
            NodeReadyPayload,
            NodeRetiredPayload,
            NodeStateChangedPayload,
            CallbackAcceptedPayload,
            CallbackDuplicateReturnedPayload,
            CallbackRejectedPayload,
            RuntimeRetryScheduledPayload,
            HeartbeatRecordedPayload,
            AgentDiedPayload,
            AgentDispatchRequestedPayload,
            FileStateRejectedPayload,
        ),
    ):
        return _node_ids(
            payload.node_id if not isinstance(payload, InputBoundPayload) else payload.to_node_id
        )
    return set()


def _node_ids(*values: str | None) -> set[str]:
    return {value for value in values if value is not None}


def _lease_from_grant(
    payload: LeaseGrantedPayload,
    known_kind: str | None,
    known_task_region_id: str | None = None,
) -> dict[str, Any]:
    lease: dict[str, Any] = {
        "lease_id": payload.lease_id,
        "node_id": payload.node_id,
        "state": "active",
        "generation": payload.generation,
        "execution_id": payload.execution_id,
        "base_snapshot_id": payload.base_snapshot_id,
        "expires_at": payload.expires_at.isoformat(),
        "resource_claims": [claim.model_dump(mode="json") for claim in payload.resource_claims],
    }
    if payload.session_id is not None:
        lease["session_id"] = payload.session_id
    if "task_region_id" not in lease and known_task_region_id is not None:
        lease["task_region_id"] = known_task_region_id
    if known_kind is not None:
        lease["kind"] = known_kind
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


def _has_missing_preexisting_node_reference(
    catalog: GraphCatalog,
    events: Sequence[HydratedEvent],
    existing_node_ids: set[str],
) -> bool:
    created_node_ids: set[str] = set()
    for event in events:
        _require_catalog_payload(catalog, event)
        if event.event_type == "node_created":
            if type(event.payload) is not NodeCreatedPayload:
                raise TypeError("node_created event has an unexpected payload type")
            created_node_ids.add(event.payload.node_id)

    for event in events:
        if event.event_type == "node_created":
            continue
        referenced_node_ids = _referenced_node_ids(event, existing_node_ids | created_node_ids)
        if any(
            node_id not in existing_node_ids and node_id not in created_node_ids
            for node_id in referenced_node_ids
        ):
            return True
    return False


def _input_bound_edge_ids_needing_ports(events: Sequence[HydratedEvent]) -> set[str]:
    edge_ids: set[str] = set()
    for event in events:
        if event.event_type != "input_bound":
            continue
        if not isinstance(event.payload, InputBoundPayload):
            raise TypeError("input_bound event has an unexpected payload type")
        if event.payload.to_port:
            continue
        edge_ids.add(event.payload.edge_id)
    return edge_ids


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
