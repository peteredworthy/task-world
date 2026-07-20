"""JSONL outbox observer: writes committed stored events to a JSONL file."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TextIO, cast

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
        rotation_operations: RotationOperations | None = None,
    ) -> None:
        self._path = path
        self._max_bytes = max_bytes
        self._written: set[int] = set()
        # Callers that share a journal can inject one lock; no process-global
        # state is used. The private default keeps a standalone observer safe.
        self._lock = lock or asyncio.Lock()
        self._rotation_operations = rotation_operations or SystemRotationOperations()

    async def __call__(self, events: list[StoredEvent]) -> None:
        async with self._lock:
            self._written = await asyncio.to_thread(
                _write_events_under_lock,
                self._path,
                self._max_bytes,
                events,
                self._rotation_operations,
            )


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
    _fsync_directory(path.parent)


def _write_events_under_lock(
    path: Path,
    max_bytes: int,
    events: list[StoredEvent],
    rotation_operations: RotationOperations,
) -> set[int]:
    """Serialize the complete journal read/rotate/write transaction by path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _advisory_lock(path):
        _recover_linked_rotation(path)
        active_positions = _read_positions(path)
        archive_segments = discover_journal_segments(path)
        if _should_rotate(path, max_bytes):
            _rotate(path, rotation_operations)
            active_positions: set[int] = set()
            archive_segments = discover_journal_segments(path)

        batch_positions: set[int] = set()
        new_events: list[StoredEvent] = []
        for event in events:
            if (
                event.position in active_positions
                or event.position in batch_positions
                or _position_in_archives(event.position, archive_segments)
            ):
                continue
            batch_positions.add(event.position)
            new_events.append(event)
        if new_events:
            lines = "\n".join(json.dumps(_to_record(event)) for event in new_events) + "\n"
            _append_lines(path, lines)
            active_positions.update(event.position for event in new_events)
        return active_positions


class _advisory_lock:
    """A process-safe lock file held for one complete journal mutation."""

    def __init__(self, journal_path: Path) -> None:
        self._path = journal_path.with_name(f"{journal_path.name}.lock")
        self._file: TextIO | None = None

    def __enter__(self) -> None:
        self._file = open(self._path, "a+")
        fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)

    def __exit__(self, *_: object) -> None:
        if self._file is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()


def _should_rotate(path: Path, max_bytes: int) -> bool:
    try:
        return path.stat().st_size >= max_bytes
    except FileNotFoundError:
        return False


class RotationOperations(Protocol):
    """Durable filesystem operations required to rotate a journal segment."""

    def link(self, active: Path, archive: Path) -> None: ...

    def fsync_parent(self, path: Path) -> None: ...

    def unlink(self, active: Path) -> None: ...


class SystemRotationOperations:
    """Production implementation of the journal rotation filesystem operations."""

    def link(self, active: Path, archive: Path) -> None:
        os.link(active, archive)

    def fsync_parent(self, path: Path) -> None:
        _fsync_directory(path.parent)

    def unlink(self, active: Path) -> None:
        os.unlink(active)


def _rotate(path: Path, operations: RotationOperations) -> None:
    positions = _read_positions(path)
    if not positions:
        return
    archive = path.with_name(f"{path.stem}.{min(positions)}-{max(positions)}{path.suffix}")
    # link is an atomic no-clobber install: EEXIST leaves the destination intact.
    operations.link(path, archive)
    operations.fsync_parent(path)
    operations.unlink(path)
    operations.fsync_parent(path)


def _recover_linked_rotation(path: Path) -> None:
    """Finish an interrupted link/unlink rotation before any new append."""
    if not path.exists():
        return
    for segment in discover_journal_segments(path):
        try:
            if path.samefile(segment.path):
                os.unlink(path)
                _fsync_directory(path.parent)
                return
        except FileNotFoundError:
            continue


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _position_in_archives(position: int, segments: list[JournalSegment]) -> bool:
    """Use ranges as an index, then confirm candidates by streaming the archive."""
    return any(
        segment.first_position <= position <= segment.last_position
        and _archive_contains_position(segment.path, position)
        for segment in segments
    )


def _archive_contains_position(path: Path, position: int) -> bool:
    try:
        with open(path) as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(record, dict)
                    and cast("dict[str, object]", record).get("position") == position
                    and type(cast("dict[str, object]", record).get("position")) is int
                ):
                    return True
    except FileNotFoundError:
        return False
    return False


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
