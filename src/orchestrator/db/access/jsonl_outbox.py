"""JSONL outbox observer: writes committed stored events to a JSONL file."""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Protocol, TextIO, cast

from orchestrator.db.access.event_store_v2 import StoredEvent
from orchestrator.db.access.event_outbox import EventOutboxObserver

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from orchestrator.db.access.event_store_v2 import SqliteEventStore

_JOURNAL_PATH_ENV = "ORCHESTRATOR_EVENT_JOURNAL_PATH"
_ARCHIVE_NAME = re.compile(r"^(?P<stem>.+)\.(?P<first>\d+)-(?P<last>\d+)\.jsonl$")
_TAIL_SCAN_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class JournalSegment:
    """An immutable discovered archive range for one journal file."""

    path: Path
    first_position: int
    last_position: int


class JournalFileOperations(Protocol):
    """Bounded binary operations used to repair an active JSONL tail."""

    def read_final_byte(self, path: Path) -> bytes: ...

    def read_final_fragment(self, path: Path, chunk_size: int) -> tuple[int, bytes]: ...

    def append_delimiter(self, path: Path) -> None: ...

    def truncate(self, path: Path, length: int) -> None: ...


class SystemJournalFileOperations:
    """Production binary file operations for bounded active-tail inspection."""

    def read_final_byte(self, path: Path) -> bytes:
        try:
            with open(path, "rb") as file:
                if file.seek(0, os.SEEK_END) == 0:
                    return b""
                file.seek(-1, os.SEEK_END)
                return file.read(1)
        except FileNotFoundError:
            return b""

    def read_final_fragment(self, path: Path, chunk_size: int) -> tuple[int, bytes]:
        chunks: list[bytes] = []
        with open(path, "rb") as file:
            offset = file.seek(0, os.SEEK_END)
            while offset:
                start = max(0, offset - chunk_size)
                file.seek(start)
                chunk = file.read(offset - start)
                newline = chunk.rfind(b"\n")
                if newline >= 0:
                    chunks.append(chunk[newline + 1 :])
                    return start + newline + 1, b"".join(reversed(chunks))
                chunks.append(chunk)
                offset = start
        return 0, b"".join(reversed(chunks))

    def append_delimiter(self, path: Path) -> None:
        with open(path, "ab") as file:
            file.write(b"\n")
            file.flush()
            os.fsync(file.fileno())

    def truncate(self, path: Path, length: int) -> None:
        with open(path, "r+b") as file:
            file.truncate(length)
            file.flush()
            os.fsync(file.fileno())


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
        segment_reader: Callable[[Path], set[int]] | None = None,
        file_operations: JournalFileOperations | None = None,
    ) -> None:
        self._path = path
        self._max_bytes = max_bytes
        self._written: set[int] = set()
        # Callers that share a journal can inject one lock; no process-global
        # state is used. The private default keeps a standalone observer safe.
        self._lock = lock or asyncio.Lock()
        self._rotation_operations = rotation_operations or SystemRotationOperations()
        self._segment_reader = segment_reader or _read_positions
        self._file_operations = file_operations or SystemJournalFileOperations()

    async def __call__(self, events: list[StoredEvent]) -> None:
        async with self._lock:
            self._written = await asyncio.to_thread(
                _write_events_under_lock,
                self._path,
                self._max_bytes,
                events,
                self._rotation_operations,
                self._segment_reader,
                self._file_operations,
            )

    async def reconcile(
        self,
        store: "SqliteEventStore",
        *,
        batch_size: int,
    ) -> int:
        """Reconcile DB pages with one exact-position set per journal segment.

        The advisory lock spans this startup-only operation so a concurrent
        writer cannot invalidate a segment set between its scan and append.
        """
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with _advisory_lock(self._path):
                _recover_linked_rotation(self._path, self._rotation_operations)
                cursor = 0
                observed = 0
                # The active file can contain positions which belong to sparse
                # archive ranges. Retain its one bounded set throughout this
                # pass so those positions never get appended as archive gaps.
                initial_active_positions = self._segment_reader(self._path)
                for segment in discover_journal_segments(self._path):
                    observed += await self._reconcile_page_range(
                        store,
                        cursor,
                        segment.first_position - 1,
                        batch_size,
                        initial_active_positions,
                    )
                    cursor = max(cursor, segment.first_position - 1)
                    segment_positions = self._segment_reader(segment.path)
                    existing_positions = initial_active_positions | segment_positions
                    observed += await self._reconcile_page_range(
                        store,
                        cursor,
                        segment.last_position,
                        batch_size,
                        existing_positions,
                    )
                    cursor = max(cursor, segment.last_position)

                # Archives are chronological journal prefixes. Only the
                # initial active positions filter the whole pass; DB cursor
                # advancement makes newly appended positions irrelevant.
                observed += await self._reconcile_page_range(
                    store,
                    cursor,
                    None,
                    batch_size,
                    initial_active_positions,
                )
                self._written = self._segment_reader(self._path)
                return observed

    async def _reconcile_page_range(
        self,
        store: "SqliteEventStore",
        cursor: int,
        through_position: int | None,
        batch_size: int,
        existing_positions: set[int],
    ) -> int:
        observed = 0
        while True:
            page = await store.get_page_after_position(
                cursor,
                limit=batch_size,
                through_position=through_position,
            )
            if not page:
                return observed
            observed += len(page)
            new_events = [event for event in page if event.position not in existing_positions]
            _append_events_under_held_lock(
                self._path,
                self._max_bytes,
                new_events,
                self._rotation_operations,
                self._file_operations,
            )
            cursor = page[-1].position


async def drain_committed_events_to_journal(
    session: "AsyncSession",
    path: Path,
    *,
    batch_size: int = 200,
    max_bytes: int = 64 * 1024 * 1024,
    observer: EventOutboxObserver | None = None,
) -> int:
    """Write committed DB events absent from the journal in bounded batches.

    The event table is authoritative after a post-commit observer failure, so
    this intentionally reconstructs retry work after a process boundary rather
    than relying on the failed observer's in-memory batch.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    from orchestrator.db.access.event_store_v2 import SqliteEventStore

    journal_observer = observer or JsonlOutboxObserver(path, max_bytes=max_bytes)
    store = SqliteEventStore(session)
    if isinstance(journal_observer, JsonlOutboxObserver):
        return await journal_observer.reconcile(store, batch_size=batch_size)
    cursor = 0
    observed = 0
    while True:
        page = await store.get_page_after_position(cursor, limit=batch_size)
        if not page:
            return observed
        # The observer checks active and archive candidates exactly under the
        # journal lock, so no journal-position set is retained in memory.
        await journal_observer(page)
        observed += len(page)
        cursor = page[-1].position


def _to_record(e: StoredEvent) -> dict[str, object]:
    return {
        "position": e.position,
        "aggregate_id": e.aggregate_id,
        "event_type": e.event_type,
        "timestamp": e.timestamp,
        "payload": json.loads(e.payload),
    }


def _append_lines(path: Path, lines: str, operations: RotationOperations) -> None:
    with open(path, "a") as f:
        f.write(lines)
        f.flush()
    operations.fsync_active(path)
    operations.fsync_parent(path)


def _repair_active_append_boundary(
    path: Path,
    operations: RotationOperations,
    file_operations: JournalFileOperations,
) -> None:
    """Make a nonempty active journal safe for a complete JSONL append.

    A valid final record merely lacks its delimiter after an interrupted write,
    so preserve it and durably add the delimiter. An invalid final fragment is
    not an authoritative record and is truncated back to the preceding newline.
    """
    final_byte = file_operations.read_final_byte(path)
    if not final_byte or final_byte == b"\n":
        return

    final_line_start, final_line = file_operations.read_final_fragment(path, _TAIL_SCAN_CHUNK_SIZE)
    try:
        json.loads(final_line)
    except json.JSONDecodeError:
        file_operations.truncate(path, final_line_start)
    else:
        file_operations.append_delimiter(path)
    operations.fsync_active(path)
    operations.fsync_parent(path)


def _write_events_under_lock(
    path: Path,
    max_bytes: int,
    events: list[StoredEvent],
    rotation_operations: RotationOperations,
    segment_reader: Callable[[Path], set[int]],
    file_operations: JournalFileOperations,
) -> set[int]:
    """Serialize the complete journal read/rotate/write transaction by path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _advisory_lock(path):
        _recover_linked_rotation(path, rotation_operations)
        active_positions = segment_reader(path)
        archive_segments = discover_journal_segments(path)
        if _should_rotate(path, max_bytes):
            _rotate(path, rotation_operations)
            active_positions: set[int] = set()
            archive_segments = discover_journal_segments(path)

        if any(event.position in active_positions for event in events):
            rotation_operations.fsync_active(path)
            rotation_operations.fsync_parent(path)

        batch_positions: set[int] = set()
        new_events: list[StoredEvent] = []
        for event in events:
            if event.position in active_positions or event.position in batch_positions:
                continue
            batch_positions.add(event.position)
            new_events.append(event)
        for segment in archive_segments:
            if not any(
                segment.first_position <= event.position <= segment.last_position
                for event in new_events
            ):
                continue
            segment_positions = segment_reader(segment.path)
            new_events = [
                event
                for event in new_events
                if not (
                    segment.first_position <= event.position <= segment.last_position
                    and event.position in segment_positions
                )
            ]
        if new_events:
            lines = "\n".join(json.dumps(_to_record(event)) for event in new_events) + "\n"
            _repair_active_append_boundary(path, rotation_operations, file_operations)
            _append_lines(path, lines, rotation_operations)
            active_positions.update(event.position for event in new_events)
            # Rotation is a postcondition of every durable append.  A batch
            # larger than the limit is archived as one segment and leaves a
            # fresh active file for the next writer.
            if _should_rotate(path, max_bytes):
                _rotate(path, rotation_operations)
                path.touch()
                rotation_operations.fsync_active(path)
                rotation_operations.fsync_parent(path)
                active_positions = set()
        return active_positions


def _append_events_under_held_lock(
    path: Path,
    max_bytes: int,
    events: list[StoredEvent],
    rotation_operations: RotationOperations,
    file_operations: JournalFileOperations,
) -> None:
    """Append already-reconciled events while the caller holds the journal lock."""
    unique_events: list[StoredEvent] = []
    positions: set[int] = set()
    for event in events:
        if event.position not in positions:
            positions.add(event.position)
            unique_events.append(event)
    if not unique_events:
        return
    lines = "\n".join(json.dumps(_to_record(event)) for event in unique_events) + "\n"
    _repair_active_append_boundary(path, rotation_operations, file_operations)
    _append_lines(path, lines, rotation_operations)
    if _should_rotate(path, max_bytes):
        _rotate(path, rotation_operations)
        path.touch()
        rotation_operations.fsync_active(path)
        rotation_operations.fsync_parent(path)


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

    def fsync_active(self, path: Path) -> None: ...

    def unlink(self, active: Path) -> None: ...


class SystemRotationOperations:
    """Production implementation of the journal rotation filesystem operations."""

    def link(self, active: Path, archive: Path) -> None:
        os.link(active, archive)

    def fsync_parent(self, path: Path) -> None:
        _fsync_directory(path.parent)

    def fsync_active(self, path: Path) -> None:
        with open(path) as file:
            os.fsync(file.fileno())

    def unlink(self, active: Path) -> None:
        os.unlink(active)


def _rotate(path: Path, operations: RotationOperations) -> None:
    positions = _read_positions(path)
    if not positions:
        return
    archive = path.with_name(f"{path.stem}.{min(positions)}-{max(positions)}{path.suffix}")
    # link is an atomic no-clobber install: EEXIST leaves the destination intact.
    operations.fsync_active(path)
    operations.link(path, archive)
    operations.fsync_parent(path)
    operations.unlink(path)
    operations.fsync_parent(path)


def _recover_linked_rotation(path: Path, operations: RotationOperations) -> None:
    """Finish an interrupted link/unlink rotation before any new append."""
    if not path.exists():
        return
    for segment in discover_journal_segments(path):
        try:
            if path.samefile(segment.path):
                operations.fsync_parent(path)
                operations.unlink(path)
                operations.fsync_parent(path)
                return
        except FileNotFoundError:
            continue


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
