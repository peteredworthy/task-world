"""JSONL outbox observer: writes committed stored events to a JSONL file."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
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
_ARCHIVE_NAME = re.compile(
    r"^(?P<stem>.+)\.(?P<first>\d+)-(?P<last>\d+)"
    r"(?:\.(?P<content_hash>[0-9a-f]{16})(?:\.(?P<collision>\d+))?)?\.jsonl$"
)
_TAIL_SCAN_CHUNK_SIZE = 64 * 1024
_CHECKPOINT_VERSION = 2


@dataclass(frozen=True)
class JournalSegment:
    """An immutable discovered archive range for one journal file."""

    path: Path
    first_position: int
    last_position: int


@dataclass(frozen=True)
class JournalDeliveryCheckpoint:
    """Truthful journal delivery state across legacy adoption and new writes.

    ``verified_through_position`` is the contiguous prefix whose journal
    coverage has been established.  ``tail_through_position`` is the SQL
    frontier already handled by normal startup delivery.  The frontiers may
    differ only while ``unverified_legacy_through_position`` preserves the
    bounded legacy range that still requires an explicit audit.
    """

    verified_through_position: int
    tail_through_position: int
    unverified_legacy_through_position: int | None


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
    """Return valid archive segments ordered by their first global position.

    Archives written by current versions include a content hash and, when
    necessary, a collision ordinal.  The optional suffix keeps older
    range-only archive names readable during upgrades and recovery.
    """
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
    return sorted(
        segments,
        key=lambda segment: (segment.first_position, segment.last_position, segment.path.name),
    )


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
        after_position: int = 0,
        through_position: int | None = None,
    ) -> int:
        """Reconcile DB pages against exact coverage across every journal segment.

        The advisory lock spans this startup-only operation so a concurrent
        writer cannot invalidate a segment set between its scan and append.
        """
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with _advisory_lock(self._path):
                _recover_linked_rotation(self._path, self._rotation_operations)
                cursor = after_position
                observed = 0
                # A segment's advertised range is only a candidate index.  Old
                # journals may contain sparse and overlapping ranges, so only
                # the union of exact positions is authoritative.  Build that
                # union before asking SQL for any gap and extend it after each
                # append.  Tail reconciliation skips archives wholly below the
                # durable checkpoint and therefore remains bounded on restart.
                existing_positions = set(self._segment_reader(self._path))
                for segment in discover_journal_segments(self._path):
                    if segment.last_position > after_position:
                        existing_positions.update(self._segment_reader(segment.path))
                observed += await self._reconcile_page_range(
                    store,
                    cursor,
                    through_position,
                    batch_size,
                    existing_positions,
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
            existing_positions.update(event.position for event in new_events)
            cursor = page[-1].position


async def drain_committed_events_to_journal(
    session: "AsyncSession",
    path: Path,
    *,
    batch_size: int = 200,
    max_bytes: int = 64 * 1024 * 1024,
    observer: EventOutboxObserver | None = None,
    use_checkpoint: bool = False,
    defer_untrusted_legacy_audit: bool = False,
) -> int:
    """Write committed DB events absent from the journal in bounded batches.

    The event table is authoritative after a post-commit observer failure, so
    this intentionally reconstructs retry work after a process boundary rather
    than relying on the failed observer's in-memory batch.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    from orchestrator.db.access.event_store_v2 import SqliteEventStore

    store = SqliteEventStore(session)
    journal_observer = observer or JsonlOutboxObserver(path, max_bytes=max_bytes)
    after_position = 0
    through_position: int | None = None
    checkpoint: JournalDeliveryCheckpoint | None = None
    checkpoint_after_success: JournalDeliveryCheckpoint | None = None
    checkpoint_path = _journal_checkpoint_path(path)
    if use_checkpoint:
        through_position = await _current_sql_head(session)
        checkpoint = await asyncio.to_thread(_read_journal_checkpoint, checkpoint_path)
        if checkpoint is not None:
            checkpoint = _clamp_journal_checkpoint(checkpoint, through_position)
            if (
                not defer_untrusted_legacy_audit
                and checkpoint.unverified_legacy_through_position is not None
            ):
                # The audit is intentionally bounded by the head captured when
                # legacy history was adopted.  New SQL tail delivery remains
                # independent and can continue on normal startup.
                after_position = checkpoint.verified_through_position
                through_position = checkpoint.unverified_legacy_through_position
                checkpoint_after_success = JournalDeliveryCheckpoint(
                    verified_through_position=checkpoint.tail_through_position,
                    tail_through_position=checkpoint.tail_through_position,
                    unverified_legacy_through_position=None,
                )
            else:
                after_position = checkpoint.tail_through_position
                checkpoint_after_success = JournalDeliveryCheckpoint(
                    verified_through_position=(
                        through_position
                        if checkpoint.unverified_legacy_through_position is None
                        else checkpoint.verified_through_position
                    ),
                    tail_through_position=through_position,
                    unverified_legacy_through_position=(
                        checkpoint.unverified_legacy_through_position
                    ),
                )
        elif defer_untrusted_legacy_audit and _has_existing_journal_history(path):
            # Adopting a pre-checkpoint journal must not make readiness depend
            # on a full legacy audit.  The skipped range remains explicit debt;
            # unlike the v1 checkpoint, it is never described as verified.
            adopted = JournalDeliveryCheckpoint(
                verified_through_position=0,
                tail_through_position=through_position,
                unverified_legacy_through_position=(through_position or None),
            )
            await asyncio.to_thread(_write_journal_checkpoint, checkpoint_path, adopted)
            return 0
        else:
            checkpoint_after_success = JournalDeliveryCheckpoint(
                verified_through_position=through_position,
                tail_through_position=through_position,
                unverified_legacy_through_position=None,
            )
    if isinstance(journal_observer, JsonlOutboxObserver):
        observed = await journal_observer.reconcile(
            store,
            batch_size=batch_size,
            after_position=after_position,
            through_position=through_position,
        )
        if use_checkpoint and checkpoint_after_success is not None:
            await asyncio.to_thread(
                _write_journal_checkpoint, checkpoint_path, checkpoint_after_success
            )
        return observed
    cursor = after_position
    observed = 0
    while True:
        page = await store.get_page_after_position(
            cursor, limit=batch_size, through_position=through_position
        )
        if not page:
            if use_checkpoint and checkpoint_after_success is not None:
                await asyncio.to_thread(
                    _write_journal_checkpoint, checkpoint_path, checkpoint_after_success
                )
            return observed
        # The observer checks active and archive candidates exactly under the
        # journal lock, so no journal-position set is retained in memory.
        await journal_observer(page)
        observed += len(page)
        cursor = page[-1].position


async def _current_sql_head(session: "AsyncSession") -> int:
    from sqlalchemy import func, select

    from orchestrator.db.orm.models import EventV2Model

    value = await session.scalar(select(func.max(EventV2Model.position)))
    return int(value or 0)


def _journal_checkpoint_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.checkpoint")


def _has_existing_journal_history(path: Path) -> bool:
    try:
        if path.stat().st_size:
            return True
    except FileNotFoundError:
        pass
    return bool(discover_journal_segments(path))


def _read_journal_checkpoint(path: Path) -> JournalDeliveryCheckpoint | None:
    try:
        raw = json.loads(path.read_text())
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    payload = cast(dict[str, object], raw)
    if payload.get("version") != _CHECKPOINT_VERSION:
        return None
    verified = payload.get("verified_through_position")
    tail = payload.get("tail_through_position")
    legacy = payload.get("unverified_legacy_through_position")
    if type(verified) is not int or verified < 0:
        return None
    if type(tail) is not int or tail < verified:
        return None
    if legacy is not None and (type(legacy) is not int or legacy <= verified or legacy > tail):
        return None
    return JournalDeliveryCheckpoint(
        verified_through_position=verified,
        tail_through_position=tail,
        unverified_legacy_through_position=legacy,
    )


def _clamp_journal_checkpoint(
    checkpoint: JournalDeliveryCheckpoint,
    sql_head: int,
) -> JournalDeliveryCheckpoint:
    """Clamp valid persisted frontiers to the current authoritative SQL head."""
    tail = min(checkpoint.tail_through_position, sql_head)
    verified = min(checkpoint.verified_through_position, tail)
    legacy = checkpoint.unverified_legacy_through_position
    if legacy is not None:
        legacy = min(legacy, tail)
        if legacy <= verified:
            legacy = None
    return JournalDeliveryCheckpoint(
        verified_through_position=verified,
        tail_through_position=tail,
        unverified_legacy_through_position=legacy,
    )


def _write_journal_checkpoint(path: Path, checkpoint: JournalDeliveryCheckpoint) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(
        {
            "version": _CHECKPOINT_VERSION,
            "verified_through_position": checkpoint.verified_through_position,
            "tail_through_position": checkpoint.tail_through_position,
            "unverified_legacy_through_position": (checkpoint.unverified_legacy_through_position),
        },
        sort_keys=True,
    )
    try:
        with open(temporary, "w") as file:
            file.write(payload + "\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


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
    operations.fsync_active(path)
    _link_unique_archive(path, positions, operations)
    operations.fsync_parent(path)
    operations.unlink(path)
    operations.fsync_parent(path)


def _link_unique_archive(
    path: Path,
    positions: set[int],
    operations: RotationOperations,
) -> Path:
    """Hard-link ``path`` to a new immutable archive without ever replacing one.

    Position ranges are not unique: recovery, retries, and manually repaired
    journals can all rotate a second active file covering an earlier range.
    Include a content-derived identity in every new archive name and reserve a
    numeric ordinal only for distinct/invalid occupied candidates. ``link`` is
    the no-clobber reservation, so a racing writer cannot overwrite an archive
    between selecting a candidate and installing it.
    """
    content_hash = _archive_content_hash(path)
    prefix = f"{path.stem}.{min(positions)}-{max(positions)}.{content_hash}"
    ordinal = 0
    while True:
        collision_suffix = "" if ordinal == 0 else f".{ordinal}"
        archive = path.with_name(f"{prefix}{collision_suffix}{path.suffix}")
        try:
            operations.link(path, archive)
        except FileExistsError:
            if archive.is_file() and _files_equal(path, archive):
                return archive
            ordinal += 1
            continue
        return archive


def _files_equal(left: Path, right: Path) -> bool:
    """Compare candidate archives without loading either file into memory."""
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
        with open(left, "rb") as left_file, open(right, "rb") as right_file:
            while True:
                left_chunk = left_file.read(64 * 1024)
                right_chunk = right_file.read(64 * 1024)
                if left_chunk != right_chunk:
                    return False
                if not left_chunk:
                    return True
    except (FileNotFoundError, IsADirectoryError, OSError):
        return False


def _archive_content_hash(path: Path) -> str:
    """Return a compact identity for the exact bytes about to be archived."""
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


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
