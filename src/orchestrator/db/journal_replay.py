"""Replay JSONL event journal onto persisted run snapshots."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from orchestrator.db.event_journal import parse_journal_timestamp, read_journal_entries
from orchestrator.db.recovery import replay_events
from orchestrator.db.repositories import CheckpointRepository, RunRepository
from orchestrator.state.errors import RunNotFoundError

logger = logging.getLogger(__name__)


@dataclass
class JournalReplaySummary:
    """Summary of a journal replay run."""

    journal_path: Path
    parsed_entries: int
    replayed_events: int
    updated_runs: int
    missing_runs: int
    checkpoint_sequence: int | None = field(default=None)
    resumed_from_sequence: int | None = field(default=None)


async def replay_journal_to_repository(
    repo: RunRepository,
    *,
    journal_path: Path,
    run_ids: set[str] | None = None,
    since: datetime | None = None,
    dry_run: bool = False,
    batch_size: int = 100,
    from_checkpoint: bool = False,
    checkpoint_repo: CheckpointRepository | None = None,
) -> JournalReplaySummary:
    """Replay journal events onto runs in the repository.

    Intended for rolling a restored DB backup forward to latest state.

    When ``from_checkpoint`` is True and a ``checkpoint_repo`` is provided,
    the replay resumes from the last committed checkpoint and processes
    events in batches of ``batch_size``, updating the checkpoint atomically
    with each batch commit for crash safety.
    """
    journal_key = str(journal_path)
    resumed_from_sequence: int | None = None
    checkpoint_last_seq: int | None = None

    # Look up existing checkpoint if resuming
    if from_checkpoint and checkpoint_repo is not None:
        existing = await checkpoint_repo.get_checkpoint(journal_key)
        if existing is not None:
            resumed_from_sequence = existing.last_applied_sequence
            checkpoint_last_seq = existing.last_applied_sequence

    # Load and filter entries
    all_entries, parsed_entries = await _load_and_filter_entries(
        journal_path=journal_path,
        run_ids=run_ids,
        since=since,
        skip_before_sequence=resumed_from_sequence,
    )

    if not all_entries:
        return JournalReplaySummary(
            journal_path=journal_path,
            parsed_entries=parsed_entries,
            replayed_events=0,
            updated_runs=0,
            missing_runs=0,
            checkpoint_sequence=checkpoint_last_seq,
            resumed_from_sequence=resumed_from_sequence,
        )

    use_batched = from_checkpoint and checkpoint_repo is not None and not dry_run

    if use_batched:
        assert checkpoint_repo is not None
        result = await _replay_batched(
            repo=repo,
            checkpoint_repo=checkpoint_repo,
            journal_key=journal_key,
            entries=all_entries,
            batch_size=batch_size,
        )
        return JournalReplaySummary(
            journal_path=journal_path,
            parsed_entries=parsed_entries,
            replayed_events=result["replayed_events"],
            updated_runs=result["updated_runs"],
            missing_runs=result["missing_runs"],
            checkpoint_sequence=result["checkpoint_sequence"],
            resumed_from_sequence=resumed_from_sequence,
        )

    # Non-batched path (original behavior, for dry_run or no checkpoint)
    replayed_events = 0
    updated_runs = 0
    missing_runs = 0
    max_seq: int | None = None
    seen_run_ids: set[str] = set()
    missing_run_ids: set[str] = set()

    # Group entries by run_id for replay_events
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in all_entries:
        grouped.setdefault(entry["run_id"], []).append(entry)

    for run_id, events in grouped.items():
        if not events:
            continue

        try:
            run = await repo.get(run_id)
        except RunNotFoundError:
            missing_run_ids.add(run_id)
            continue

        replay_events(
            run,
            [
                {"type": e["type"], "timestamp": e["timestamp"], "payload": e["payload"]}
                for e in events
            ],
        )
        replayed_events += len(events)
        seen_run_ids.add(run_id)

        if not dry_run:
            await repo.save(run)

        for e in events:
            seq = e.get("sequence_number")
            if seq is not None and (max_seq is None or seq > max_seq):
                max_seq = seq

    updated_runs = len(seen_run_ids)
    missing_runs = len(missing_run_ids)

    return JournalReplaySummary(
        journal_path=journal_path,
        parsed_entries=parsed_entries,
        replayed_events=replayed_events,
        updated_runs=updated_runs,
        missing_runs=missing_runs,
        checkpoint_sequence=max_seq if not dry_run else checkpoint_last_seq,
        resumed_from_sequence=resumed_from_sequence,
    )


async def _replay_batched(
    *,
    repo: RunRepository,
    checkpoint_repo: CheckpointRepository,
    journal_key: str,
    entries: list[dict[str, Any]],
    batch_size: int,
) -> dict[str, Any]:
    """Replay entries in batches with atomic checkpoint updates.

    Each batch is committed in a single transaction: run state changes +
    checkpoint update. On crash, the next replay picks up from the last
    committed checkpoint.
    """
    session = repo.session
    total_replayed = 0
    seen_run_ids: set[str] = set()
    missing_run_ids: set[str] = set()
    last_committed_seq: int | None = None

    for batch_start in range(0, len(entries), batch_size):
        batch = entries[batch_start : batch_start + batch_size]

        # Group batch entries by run_id
        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in batch:
            grouped.setdefault(entry["run_id"], []).append(entry)

        batch_max_seq: int | None = None
        batch_max_ts: datetime | None = None

        for run_id, events in grouped.items():
            if run_id in missing_run_ids:
                continue

            try:
                run = await repo.get(run_id)
            except RunNotFoundError:
                missing_run_ids.add(run_id)
                continue

            replay_events(
                run,
                [
                    {"type": e["type"], "timestamp": e["timestamp"], "payload": e["payload"]}
                    for e in events
                ],
            )
            total_replayed += len(events)
            seen_run_ids.add(run_id)
            await repo.save(run)

        # Find max sequence_number and its timestamp in this batch
        for entry in batch:
            seq = entry.get("sequence_number")
            if seq is not None and (batch_max_seq is None or seq > batch_max_seq):
                batch_max_seq = seq
                batch_max_ts = entry["timestamp"]

        # Atomically update checkpoint in same session, then commit
        if batch_max_seq is not None and batch_max_ts is not None:
            await CheckpointRepository.upsert_checkpoint_in_session(
                session,
                journal_path=journal_key,
                last_applied_sequence=batch_max_seq,
                last_applied_timestamp=batch_max_ts,
            )
            last_committed_seq = batch_max_seq

        await session.commit()

    return {
        "replayed_events": total_replayed,
        "updated_runs": len(seen_run_ids),
        "missing_runs": len(missing_run_ids),
        "checkpoint_sequence": last_committed_seq,
    }


async def _load_and_filter_entries(
    *,
    journal_path: Path,
    run_ids: set[str] | None,
    since: datetime | None,
    skip_before_sequence: int | None,
) -> tuple[list[dict[str, Any]], int]:
    """Load journal entries, filter, and sort by sequence_number.

    Returns (filtered_entries, total_parsed_count). Each entry in the
    returned list has keys: run_id, type, timestamp, payload, sequence_number.
    """
    raw_entries = await read_journal_entries(journal_path)

    filtered: list[dict[str, Any]] = []
    for entry in raw_entries:
        run_id = str(entry.get("run_id", ""))
        event_type = str(entry.get("event_type", ""))
        timestamp_raw = entry.get("timestamp")
        payload = entry.get("payload")
        sequence_number = entry.get("sequence_number", 0)

        if not run_id or not event_type or not isinstance(timestamp_raw, str):
            continue
        if not isinstance(payload, dict):
            continue
        if run_ids is not None and run_id not in run_ids:
            continue

        timestamp = parse_journal_timestamp(timestamp_raw)
        if since is not None and timestamp < since:
            continue

        # Skip entries already applied (at or before the checkpoint)
        if skip_before_sequence is not None and sequence_number <= skip_before_sequence:
            continue

        filtered.append(
            {
                "run_id": run_id,
                "type": event_type,
                "timestamp": timestamp,
                "payload": payload,
                "sequence_number": sequence_number,
            }
        )

    # Sort by sequence_number for deterministic replay order
    filtered.sort(key=lambda e: e["sequence_number"])

    return filtered, len(raw_entries)
