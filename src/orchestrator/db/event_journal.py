"""Append-only JSONL event journal for DB-loss recovery."""

from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import aiofiles
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.time_utils import ensure_utc, format_utc_datetime

EVENT_JOURNAL_PATH_ENV = "ORCHESTRATOR_EVENT_JOURNAL_PATH"


def _resolve_env_override() -> Path | None:
    raw = os.getenv(EVENT_JOURNAL_PATH_ENV)
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def resolve_default_journal_path(db_path: str | Path | None) -> Path | None:
    """Resolve journal path for a DB path.

    Uses ``$ORCHESTRATOR_EVENT_JOURNAL_PATH`` when set. Otherwise, for a
    file-backed SQLite DB at ``<dir>/orchestrator.db``, writes journal to:
    ``<dir>/.orchestrator/state/history.jsonl``.
    """
    env_override = _resolve_env_override()
    if env_override is not None:
        return env_override

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


def resolve_default_journal_path_from_session(session: AsyncSession) -> Path | None:
    """Resolve journal path from the current SQLAlchemy session bind."""
    bind = session.get_bind()
    url = getattr(bind, "url", None)
    database = cast(str | None, getattr(url, "database", None))
    return resolve_default_journal_path(database)


def parse_journal_timestamp(value: str) -> datetime:
    """Parse ISO timestamp string and normalize to UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ensure_utc(parsed)


def make_journal_entry(
    *,
    run_id: str,
    event_type: str,
    timestamp: datetime,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Build a normalized JSONL record."""
    return {
        "schema_version": 1,
        "logged_at": format_utc_datetime(datetime.now(timezone.utc)),
        "run_id": run_id,
        "event_type": event_type,
        "timestamp": format_utc_datetime(timestamp),
        "payload": payload,
    }


class JsonlEventJournal:
    """Async append-only JSONL journal writer."""

    _locks: dict[Path, asyncio.Lock] = defaultdict(asyncio.Lock)

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    async def append_events(self, entries: list[dict[str, Any]]) -> None:
        """Append entries as JSONL lines atomically per journal path."""
        if not entries:
            return

        def _default_json(obj: object) -> str:
            if isinstance(obj, datetime):
                return format_utc_datetime(obj)
            if hasattr(obj, "value"):
                return obj.value  # type: ignore[return-value]
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        lines = [
            json.dumps(entry, default=_default_json, separators=(",", ":")) for entry in entries
        ]
        payload = "\n".join(lines) + "\n"

        lock = self._locks[self._path]
        async with lock:
            await asyncio.to_thread(self._path.parent.mkdir, parents=True, exist_ok=True)
            async with aiofiles.open(self._path, "a") as f:
                await f.write(payload)


async def read_journal_entries(path: Path) -> list[dict[str, Any]]:
    """Read all JSONL journal entries from disk."""
    if not path.exists():
        return []

    entries: list[dict[str, Any]] = []
    async with aiofiles.open(path, "r") as f:
        async for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries
