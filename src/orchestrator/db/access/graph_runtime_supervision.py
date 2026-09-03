"""Durable repositories for graph liveness and submission-gate provenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.orm.models import (
    GraphRuntimeSupervisionModel,
    GraphSubmissionGateAuditModel,
    EventV2Model,
)


@dataclass(frozen=True)
class GraphRuntimeSupervisionRecord:
    run_id: str
    observed_position: int
    progress_fingerprint: str
    last_progress_at: datetime
    last_reconciled_at: datetime
    no_progress_attempts: int
    driver_generation: int
    driver_state: str
    last_action: str
    stalled_execution_id: str | None
    stall_deadline_at: datetime | None
    staged_count: int
    witnessed_count: int
    finalized_count: int
    active_lease_count: int
    expired_lease_count: int
    disposition_counts: dict[str, int]
    root_error: str | None


@dataclass(frozen=True)
class GraphSubmissionGateAuditRecord:
    id: int
    run_id: str
    node_id: str
    execution_id: str
    phase: str
    base_snapshot_id: str
    base_tree_sha: str
    candidate_tree_sha: str | None
    status: str
    failure_fingerprint: str | None
    report: dict[str, Any]
    created_at: datetime


def _supervision_record(row: GraphRuntimeSupervisionModel) -> GraphRuntimeSupervisionRecord:
    return GraphRuntimeSupervisionRecord(
        run_id=row.run_id,
        observed_position=row.observed_position,
        progress_fingerprint=row.progress_fingerprint,
        last_progress_at=row.last_progress_at,
        last_reconciled_at=row.last_reconciled_at,
        no_progress_attempts=row.no_progress_attempts,
        driver_generation=row.driver_generation,
        driver_state=row.driver_state,
        last_action=row.last_action,
        stalled_execution_id=row.stalled_execution_id,
        stall_deadline_at=row.stall_deadline_at,
        staged_count=row.staged_count,
        witnessed_count=row.witnessed_count,
        finalized_count=row.finalized_count,
        active_lease_count=row.active_lease_count,
        expired_lease_count=row.expired_lease_count,
        disposition_counts=dict(row.disposition_counts),
        root_error=row.root_error,
    )


def _audit_record(row: GraphSubmissionGateAuditModel) -> GraphSubmissionGateAuditRecord:
    return GraphSubmissionGateAuditRecord(
        id=row.id,
        run_id=row.run_id,
        node_id=row.node_id,
        execution_id=row.execution_id,
        phase=row.phase,
        base_snapshot_id=row.base_snapshot_id,
        base_tree_sha=row.base_tree_sha,
        candidate_tree_sha=row.candidate_tree_sha,
        status=row.status,
        failure_fingerprint=row.failure_fingerprint,
        report=dict(row.report),
        created_at=row.created_at,
    )


class GraphRuntimeSupervisionRepository:
    """Persist a disposable liveness projection per graph run.

    Retry-budget changes are also recorded as canonical workflow events.  This
    row is only the continuously refreshed observation cache used to avoid an
    unbounded event scan on each supervisor tick.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, run_id: str) -> GraphRuntimeSupervisionRecord | None:
        row = await self._session.get(GraphRuntimeSupervisionModel, run_id)
        if row is not None:
            return _supervision_record(row)
        event = await self._session.scalar(
            select(EventV2Model)
            .where(
                EventV2Model.aggregate_id == run_id,
                EventV2Model.event_type == "graph_runtime_reconciled",
            )
            .order_by(EventV2Model.position.desc())
            .limit(1)
        )
        if event is None:
            return None
        payload = json.loads(event.payload)
        timestamp = _parse_datetime(payload.get("timestamp", event.timestamp))
        return GraphRuntimeSupervisionRecord(
            run_id=run_id,
            observed_position=int(payload["graph_position"]),
            progress_fingerprint=str(payload["progress_fingerprint"]),
            last_progress_at=timestamp,
            last_reconciled_at=timestamp,
            no_progress_attempts=int(payload["no_progress_attempts"]),
            driver_generation=int(payload["driver_generation"]),
            driver_state=str(payload["driver_state"]),
            last_action=str(payload["action"]),
            stalled_execution_id=payload.get("stalled_execution_id"),
            stall_deadline_at=_parse_optional_datetime(payload.get("stall_deadline_at")),
            staged_count=int(payload.get("staged_count", 0)),
            witnessed_count=int(payload.get("witnessed_count", 0)),
            finalized_count=int(payload.get("finalized_count", 0)),
            active_lease_count=int(payload.get("active_lease_count", 0)),
            expired_lease_count=int(payload.get("expired_lease_count", 0)),
            disposition_counts=dict(payload.get("disposition_counts", {})),
            root_error=payload.get("root_error"),
        )

    async def put(self, record: GraphRuntimeSupervisionRecord) -> None:
        row = await self._session.get(GraphRuntimeSupervisionModel, record.run_id)
        values = {
            field: getattr(record, field)
            for field in GraphRuntimeSupervisionRecord.__dataclass_fields__
            if field != "run_id"
        }
        if row is None:
            self._session.add(GraphRuntimeSupervisionModel(run_id=record.run_id, **values))
        else:
            for field, value in values.items():
                setattr(row, field, value)
        await self._session.flush()


class GraphSubmissionGateAuditRepository:
    """Project canonical gate-audit events into a bounded query table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        canonical_position: int,
        run_id: str,
        node_id: str,
        execution_id: str,
        phase: str,
        base_snapshot_id: str,
        base_tree_sha: str,
        candidate_tree_sha: str | None,
        status: str,
        failure_fingerprint: str | None,
        report: dict[str, Any],
        created_at: datetime,
    ) -> GraphSubmissionGateAuditRecord:
        existing = await self._session.get(GraphSubmissionGateAuditModel, canonical_position)
        if existing is not None:
            return _audit_record(existing)
        row = GraphSubmissionGateAuditModel(
            id=canonical_position,
            run_id=run_id,
            node_id=node_id,
            execution_id=execution_id,
            phase=phase,
            base_snapshot_id=base_snapshot_id,
            base_tree_sha=base_tree_sha,
            candidate_tree_sha=candidate_tree_sha,
            status=status,
            failure_fingerprint=failure_fingerprint,
            report=report,
            created_at=created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _audit_record(row)

    async def latest_baseline(
        self, run_id: str, execution_id: str
    ) -> GraphSubmissionGateAuditRecord | None:
        row = await self._session.scalar(
            select(GraphSubmissionGateAuditModel)
            .where(
                GraphSubmissionGateAuditModel.run_id == run_id,
                GraphSubmissionGateAuditModel.execution_id == execution_id,
                GraphSubmissionGateAuditModel.phase == "baseline",
            )
            .order_by(GraphSubmissionGateAuditModel.id.desc())
            .limit(1)
        )
        if row is not None:
            return _audit_record(row)
        event = await self._session.scalar(
            select(EventV2Model)
            .where(
                EventV2Model.aggregate_id == run_id,
                EventV2Model.event_type == "graph_submission_gate_audited",
                func.json_extract(EventV2Model.payload, "$.execution_id") == execution_id,
                func.json_extract(EventV2Model.payload, "$.phase") == "baseline",
            )
            .order_by(EventV2Model.position.desc())
            .limit(1)
        )
        if event is None:
            return None
        record = _audit_record_from_event(event)
        return (
            record if record.execution_id == execution_id and record.phase == "baseline" else None
        )

    async def list_for_run(
        self, run_id: str, *, after_id: int = 0, limit: int = 20
    ) -> tuple[GraphSubmissionGateAuditRecord, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        rows = list(
            await self._session.scalars(
                select(GraphSubmissionGateAuditModel)
                .where(
                    GraphSubmissionGateAuditModel.run_id == run_id,
                    GraphSubmissionGateAuditModel.id > after_id,
                )
                .order_by(GraphSubmissionGateAuditModel.id)
                .limit(limit + 1)
            )
        )
        if rows:
            return tuple(_audit_record(row) for row in rows[:limit])
        events = list(
            await self._session.scalars(
                select(EventV2Model)
                .where(
                    EventV2Model.aggregate_id == run_id,
                    EventV2Model.event_type == "graph_submission_gate_audited",
                    EventV2Model.position > after_id,
                )
                .order_by(EventV2Model.position)
                .limit(limit)
            )
        )
        return tuple(_audit_record_from_event(event) for event in events)


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("canonical supervision event has invalid timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _parse_optional_datetime(value: object) -> datetime | None:
    return None if value is None else _parse_datetime(value)


def _audit_record_from_event(event: EventV2Model) -> GraphSubmissionGateAuditRecord:
    payload = json.loads(event.payload)
    return GraphSubmissionGateAuditRecord(
        id=event.position,
        run_id=event.aggregate_id,
        node_id=str(payload["node_id"]),
        execution_id=str(payload["execution_id"]),
        phase=str(payload["phase"]),
        base_snapshot_id=str(payload["base_snapshot_id"]),
        base_tree_sha=str(payload["base_tree_sha"]),
        candidate_tree_sha=payload.get("candidate_tree_sha"),
        status=str(payload["status"]),
        failure_fingerprint=payload.get("failure_fingerprint"),
        report=dict(payload["report"]),
        created_at=_parse_datetime(payload.get("timestamp", event.timestamp)),
    )


__all__ = [
    "GraphRuntimeSupervisionRecord",
    "GraphRuntimeSupervisionRepository",
    "GraphSubmissionGateAuditRecord",
    "GraphSubmissionGateAuditRepository",
]
