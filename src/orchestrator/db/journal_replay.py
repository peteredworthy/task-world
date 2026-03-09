"""Replay JSONL event journal onto persisted run snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.db.event_journal import parse_journal_timestamp, read_journal_entries
from orchestrator.db.recovery import replay_events
from orchestrator.db.repositories import RunRepository
from orchestrator.state.errors import RunNotFoundError


@dataclass
class JournalReplaySummary:
    """Summary of a journal replay run."""

    journal_path: Path
    parsed_entries: int
    replayed_events: int
    updated_runs: int
    missing_runs: int


async def replay_journal_to_repository(
    repo: RunRepository,
    *,
    journal_path: Path,
    run_ids: set[str] | None = None,
    since: datetime | None = None,
    dry_run: bool = False,
) -> JournalReplaySummary:
    """Replay journal events onto runs in the repository.

    Intended for rolling a restored DB backup forward to latest state.
    """
    grouped, parsed_entries = await _load_replay_events(
        journal_path=journal_path,
        run_ids=run_ids,
        since=since,
    )

    replayed_events = 0
    updated_runs = 0
    missing_runs = 0

    for run_id, events in grouped.items():
        if not events:
            continue

        try:
            run = await repo.get(run_id)
        except RunNotFoundError:
            missing_runs += 1
            continue

        replay_events(run, events)
        replayed_events += len(events)
        updated_runs += 1

        if not dry_run:
            await repo.save(run)

    return JournalReplaySummary(
        journal_path=journal_path,
        parsed_entries=parsed_entries,
        replayed_events=replayed_events,
        updated_runs=updated_runs,
        missing_runs=missing_runs,
    )


async def _load_replay_events(
    *,
    journal_path: Path,
    run_ids: set[str] | None,
    since: datetime | None,
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    raw_entries = await read_journal_entries(journal_path)
    grouped: dict[str, list[dict[str, Any]]] = {}

    for entry in raw_entries:
        run_id = str(entry.get("run_id", ""))
        event_type = str(entry.get("event_type", ""))
        timestamp_raw = entry.get("timestamp")
        payload = entry.get("payload")

        if not run_id or not event_type or not isinstance(timestamp_raw, str):
            continue
        if not isinstance(payload, dict):
            continue
        if run_ids is not None and run_id not in run_ids:
            continue

        timestamp = parse_journal_timestamp(timestamp_raw)
        if since is not None and timestamp < since:
            continue

        grouped.setdefault(run_id, []).append(
            {"type": event_type, "timestamp": timestamp, "payload": payload}
        )

    return grouped, len(raw_entries)
