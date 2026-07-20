"""JSONL bootstrap for empty-DB startup.

Reads history.jsonl (written by JsonlOutboxObserver) on first startup when
events_v2 is empty.  Both the outbox format and the legacy journal format are
supported so that deployments upgrading from the pre-event-sourced schema can
recover state without re-running the original workload.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db.orm.models import EventV2Model, ProjectionCheckpointModel
from orchestrator.db.access.jsonl_outbox import discover_journal_segments
from orchestrator.time_utils import format_utc_datetime
from orchestrator.workflow import WorkflowEvent, deserialize_event

if TYPE_CHECKING:
    from orchestrator.db.projections import ProjectionRegistry

logger = logging.getLogger(__name__)


def _parse_jsonl_record(
    record: dict[str, Any],
) -> tuple[int | None, str, str, str, str] | None:
    """Parse a JSONL record to (position, aggregate_id, event_type, timestamp, payload_json).

    Handles two formats:

    *Outbox format* (written by ``JsonlOutboxObserver``):
        ``{"position": int, "aggregate_id": str, "event_type": str,
           "timestamp": str, "payload": dict}``

    *Legacy format* (written by ``JsonlEventJournal``):
        ``{"sequence_number": int, "run_id": str, "event_type": str,
           "timestamp": str, "payload": dict}``

    Returns ``None`` when required fields are absent or the format is unknown.
    """
    event_type = record.get("event_type")
    timestamp = record.get("timestamp")
    payload = record.get("payload")

    if not isinstance(event_type, str) or not event_type or not isinstance(timestamp, str):
        return None
    if not isinstance(payload, dict):
        return None

    if "aggregate_id" in record:
        # Outbox format — payload is already the full model-dumped dict
        position: int | None = record.get("position")
        aggregate_id = record["aggregate_id"]
        if type(position) is not int or not isinstance(aggregate_id, str) or not aggregate_id:
            return None
        payload_json = json.dumps(payload)
    elif "run_id" in record:
        # Legacy format — reconstruct a full payload that WorkflowEvent.model_validate_json
        # can parse by merging the top-level run_id/event_type/timestamp into the payload dict
        position = record.get("sequence_number")
        aggregate_id = record["run_id"]
        if (
            (position is not None and type(position) is not int)
            or not isinstance(aggregate_id, str)
            or not aggregate_id
        ):
            return None
        full_payload: dict[str, Any] = {
            "run_id": aggregate_id,
            "event_type": event_type,
            "timestamp": timestamp,
        }
        full_payload.update(cast(dict[str, Any], payload))
        payload_json = json.dumps(full_payload)
    else:
        return None

    return (position, aggregate_id, event_type, timestamp, payload_json)


async def _read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    """Read all valid JSON lines from a file, skipping blank/malformed lines."""

    def _sync_read() -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        try:
            with open(path) as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        raw_record = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "bootstrap_from_jsonl: skipping malformed JSONL line in %s", path
                        )
                        continue
                    if not isinstance(raw_record, dict):
                        logger.warning(
                            "bootstrap_from_jsonl: skipping malformed journal record in %s", path
                        )
                        continue
                    records.append(cast("dict[str, Any]", raw_record))
        except OSError as exc:
            logger.warning("bootstrap_from_jsonl: failed to read journal file %s: %s", path, exc)
        return records

    return await asyncio.to_thread(_sync_read)


async def bootstrap_from_jsonl(
    session: AsyncSession,
    journal_path: "Path | str | None",
    projection_registry: "ProjectionRegistry",
) -> None:
    """Seed ``events_v2`` from a JSONL journal file and rebuild projections.

    Rules:
    - If ``events_v2`` is non-empty: return immediately (no-op).
    - If ``journal_path`` is ``None`` or the file does not exist: log WARNING
      and return without raising.
    - Otherwise: read the file line by line, insert each valid record into
      ``events_v2`` (idempotent via ``INSERT OR IGNORE`` on primary-key
      conflict), then call ``projection_registry.rebuild_all(events, session)``
      and set projection checkpoints to the last inserted position.
    """
    # Guard: skip if events_v2 already has data
    count_result = await session.execute(select(func.count()).select_from(EventV2Model))
    if (count_result.scalar_one() or 0) > 0:
        logger.info("bootstrap_from_jsonl: events_v2 is non-empty, skipping bootstrap")
        return

    # Guard: validate journal path
    if journal_path is None:
        logger.warning("bootstrap_from_jsonl: journal_path is None, skipping bootstrap")
        return

    path = Path(journal_path)
    paths = [segment.path for segment in discover_journal_segments(path)]
    if path.exists():
        paths.append(path)
    if not paths:
        logger.warning("bootstrap_from_jsonl: journal file %s not found, skipping bootstrap", path)
        return

    # Archive names are ordered ranges, but individual records are sorted below
    # too, so recovery remains correct after a manually reordered segment.
    raw_records: list[dict[str, Any]] = []
    for segment_path in paths:
        raw_records.extend(await _read_jsonl_records(segment_path))
    if not raw_records:
        logger.info("bootstrap_from_jsonl: journal file is empty, nothing to bootstrap")
        return

    # Parse into (position | None, aggregate_id, event_type, timestamp, payload_json)
    parsed: list[tuple[int | None, str, str, str, str]] = []
    for raw in raw_records:
        result = _parse_jsonl_record(raw)
        if result is not None:
            parsed.append(result)
        else:
            logger.warning("bootstrap_from_jsonl: skipping malformed journal record in %s", path)

    if not parsed:
        logger.warning("bootstrap_from_jsonl: no valid records found in %s", path)
        return

    # Partition into records with explicit positions and those without
    with_pos = [(pos, agg, et, ts, pay) for pos, agg, et, ts, pay in parsed if pos is not None]
    without_pos = [(pos, agg, et, ts, pay) for pos, agg, et, ts, pay in parsed if pos is None]

    with_pos.sort(key=lambda x: x[0])

    # Assign sequential positions to records that lack one (legacy format fallback)
    next_pos: int = (max(p for p, *_ in with_pos) + 1) if with_pos else 0
    all_records: list[tuple[int, str, str, str, str]] = list(with_pos)
    for _, agg, et, ts, pay in without_pos:
        all_records.append((next_pos, agg, et, ts, pay))
        next_pos += 1

    all_records.sort(key=lambda x: x[0])
    deduplicated: list[tuple[int, str, str, str, str]] = []
    seen_positions: set[int] = set()
    for record in all_records:
        if record[0] not in seen_positions:
            deduplicated.append(record)
            seen_positions.add(record[0])

    # Insert into events_v2 with per-aggregate version counter
    versions: dict[str, int] = {}
    for position, aggregate_id, event_type, timestamp, payload_json in deduplicated:
        versions[aggregate_id] = versions.get(aggregate_id, 0) + 1
        version = versions[aggregate_id]

        await session.execute(
            text(
                "INSERT OR IGNORE INTO events_v2"
                " (position, aggregate_id, event_type, payload, timestamp, version)"
                " VALUES (:position, :aggregate_id, :event_type,"
                " :payload, :timestamp, :version)"
            ),
            {
                "position": position,
                "aggregate_id": aggregate_id,
                "event_type": event_type,
                "payload": payload_json,
                "timestamp": timestamp,
                "version": version,
            },
        )

    await session.flush()

    # Query all inserted events in position order for projection rebuild
    events_result = await session.execute(select(EventV2Model).order_by(EventV2Model.position))
    stored_models = list(events_result.scalars())

    # Deserialize to WorkflowEvents (skip unknown event types)
    workflow_events: list[WorkflowEvent] = []
    for model in stored_models:
        try:
            workflow_events.append(deserialize_event(model.event_type, model.payload))
        except ValueError:
            logger.debug(
                "bootstrap_from_jsonl: skipping unknown event type %s at position %s",
                model.event_type,
                model.position,
            )

    # Full projection rebuild
    await projection_registry.rebuild_all(workflow_events, session)

    # Set projection checkpoints to last inserted position so consumers know
    # they are up-to-date without re-reading all events
    if stored_models:
        last_position = stored_models[-1].position
        now_str = format_utc_datetime(datetime.now(timezone.utc))
        projectors = getattr(projection_registry, "_projectors", [])
        for projector in projectors:
            name = type(projector).__name__
            existing = await session.get(ProjectionCheckpointModel, name)
            if existing is None:
                session.add(
                    ProjectionCheckpointModel(
                        projector_name=name,
                        last_position=last_position,
                        updated_at=now_str,
                    )
                )
            else:
                existing.last_position = last_position
                existing.updated_at = now_str

        await session.flush()

    logger.info(
        "bootstrap_from_jsonl: seeded %d events into events_v2, rebuilt projections",
        len(stored_models),
    )
