"""JSONL outbox observer: writes committed stored events to a JSONL file."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from orchestrator.db.access.event_store_v2 import StoredEvent

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_JOURNAL_PATH_ENV = "ORCHESTRATOR_EVENT_JOURNAL_PATH"
_ARCHIVE_NAME = re.compile(r"^(?P<stem>.+)\.(?P<first>\d+)-(?P<last>\d+)\.jsonl$")


@dataclass(frozen=True)
class JournalSegment:
    """An immutable discovered archive range for one journal file."""

    path: Path
    first_position: int
    last_position: int


def discover_journal_segments(active_path: Path) -> list[JournalSegment]:
    """Return valid archive segments ordered by their first global position."""
    segments: list[JournalSegment] = []
    prefix = f"{active_path.stem}."
    for candidate in active_path.parent.glob(f"{active_path.stem}.*.jsonl"):
        if not candidate.is_file() or not candidate.name.startswith(prefix):
            continue
        match = _ARCHIVE_NAME.match(candidate.name)
        if match is None or match.group("stem") != active_path.stem:
            continue
        first, last = int(match.group("first")), int(match.group("last"))
        if first <= last:
            segments.append(JournalSegment(candidate, first, last))
    return sorted(segments, key=lambda segment: (segment.first_position, segment.last_position))


def resolve_default_journal_path(db_path: "str | Path | None") -> "Path | None":
    """Resolve journal path for a DB path.

    Uses ``$ORCHESTRATOR_EVENT_JOURNAL_PATH`` when set. Otherwise, for a
    file-backed SQLite DB at ``<dir>/orchestrator.db``, writes journal to:
    ``<dir>/.orchestrator/state/history.jsonl``.
    """
    raw_env = os.getenv(_JOURNAL_PATH_ENV)
    if raw_env:
        path = Path(raw_env).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path

    if db_path is None:
        return None

    raw = str(db_path)
    if raw in (":memory:", "", "sqlite+aiosqlite://"):
        return None

    if raw.startswith("sqlite+aiosqlite:///"):
        raw = raw.removeprefix("sqlite+aiosqlite:///")
    elif raw.startswith("sqlite:///"):
        raw = raw.removeprefix("sqlite:///")

    db_file = Path(raw)
    if not db_file.is_absolute():
        db_file = Path.cwd() / db_file
    return db_file.parent / ".orchestrator" / "state" / "history.jsonl"


def resolve_default_journal_path_from_session(session: "AsyncSession") -> "Path | None":
    """Resolve journal path from the current SQLAlchemy session bind."""
    bind = session.get_bind()
    url = getattr(bind, "url", None)
    database = cast("str | None", getattr(url, "database", None))
    return resolve_default_journal_path(database)


class JsonlOutboxObserver:
    """Post-commit listener that writes events to JSONL keyed by position.

    Idempotent: re-calling with the same position is a no-op. JSONL write
    failures propagate to the commit helper after SQLite has committed.

    Register via: ``event_store.add_listener(observer)``
    """

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = 64 * 1024 * 1024,
        lock: asyncio.Lock | None = None,
    ) -> None:
        self._path = path
        self._max_bytes = max_bytes
        self._written: set[int] = set()
        # Callers that share a journal can inject one lock; no process-global
        # state is used. The private default keeps a standalone observer safe.
        self._lock = lock or asyncio.Lock()

    async def __call__(self, events: list[StoredEvent]) -> None:
        async with self._lock:
            await asyncio.to_thread(self._path.parent.mkdir, parents=True, exist_ok=True)
            self._written.update(await asyncio.to_thread(_read_positions, self._path))
            archived_ranges = await asyncio.to_thread(discover_journal_segments, self._path)

            if await asyncio.to_thread(_should_rotate, self._path, self._max_bytes):
                await asyncio.to_thread(_rotate, self._path)
                self._written.clear()
                archived_ranges = await asyncio.to_thread(discover_journal_segments, self._path)

            batch_positions: set[int] = set()
            new_events: list[StoredEvent] = []
            for event in events:
                if (
                    event.position in self._written
                    or event.position in batch_positions
                    or _position_in_archives(event.position, archived_ranges)
                ):
                    continue
                batch_positions.add(event.position)
                new_events.append(event)

            if not new_events:
                return

            lines = "\n".join(json.dumps(_to_record(e)) for e in new_events) + "\n"
            await asyncio.to_thread(_append_lines, self._path, lines)
            for e in new_events:
                self._written.add(e.position)


def _to_record(e: StoredEvent) -> dict[str, object]:
    return {
        "position": e.position,
        "aggregate_id": e.aggregate_id,
        "event_type": e.event_type,
        "timestamp": e.timestamp,
        "payload": json.loads(e.payload),
    }


def _append_lines(path: Path, lines: str) -> None:
    with open(path, "a") as f:
        f.write(lines)
        f.flush()
        os.fsync(f.fileno())


def _should_rotate(path: Path, max_bytes: int) -> bool:
    try:
        return path.stat().st_size >= max_bytes
    except FileNotFoundError:
        return False


def _rotate(path: Path) -> None:
    positions = _read_positions(path)
    if not positions:
        return
    archive = path.with_name(f"{path.stem}.{min(positions)}-{max(positions)}{path.suffix}")
    # Path.rename overwrites on POSIX. Refuse before rename so a retained archive
    # can never be silently replaced.
    if archive.exists():
        raise FileExistsError(f"journal archive already exists: {archive}")
    os.rename(path, archive)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _position_in_archives(position: int, segments: list[JournalSegment]) -> bool:
    """Check compact archive ranges rather than retaining their positions in RAM."""
    return any(segment.first_position <= position <= segment.last_position for segment in segments)


def _read_positions(path: Path) -> set[int]:
    positions: set[int] = set()
    try:
        with open(path) as f:
            for line in f:
                try:
                    raw_record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw_record, dict):
                    continue
                record = cast("dict[str, object]", raw_record)
                position = record.get("position")
                if type(position) is int:
                    positions.add(position)
    except FileNotFoundError:
        pass
    return positions
