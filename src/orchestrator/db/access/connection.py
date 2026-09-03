"""Database connection management."""

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from orchestrator.db.orm.base import Base

logger = logging.getLogger(__name__)


def create_engine(db_path: Path | str = ":memory:") -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    Args:
        db_path: Path to the SQLite database file. Use ":memory:" for in-memory.
    """
    db_path_str = str(db_path)
    if db_path_str == ":memory:":
        # StaticPool ensures all connections share the same in-memory database
        return create_async_engine(
            "sqlite+aiosqlite://",
            echo=False,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    # NullPool creates a fresh connection per session and closes it immediately
    # after use.  SQLite is a local file — there is no network round-trip cost
    # to reconnecting — and pooling causes stale-connection errors
    # ("no active connection") on shutdown and after external DB writes.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path_str}",
        echo=False,
        poolclass=NullPool,
    )
    _harden_sqlite_connection(engine)
    return engine


# Write concurrency mitigations for the file-backed engine. Multiple writers —
# the graph drive loop, agent REST callbacks, heartbeat renewals — contend on
# one database file. Without these, a concurrent writer raises
# ``sqlite3.OperationalError: database is locked`` immediately, which (see the
# db-locked driver-crash incident) killed the drive loop.
#   * WAL journal mode lets readers run concurrently with a writer and reduces
#     writer-vs-writer contention.
#   * busy_timeout makes a blocked writer wait (retrying internally) up to the
#     timeout for the lock instead of failing instantly.
_SQLITE_BUSY_TIMEOUT_MS = 5000


def _harden_sqlite_connection(engine: AsyncEngine) -> None:
    """Establish persistent WAL once and busy_timeout on every new connection."""

    wal_lock = threading.Lock()
    wal_initialized = False

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(  # pyright: ignore[reportUnusedFunction]
        dbapi_connection: Any, _record: object
    ) -> None:
        nonlocal wal_initialized
        cursor = dbapi_connection.cursor()
        try:
            # WAL mode is persistent database state. Reissuing the mode-changing
            # pragma on every NullPool connection takes the SQLite schema lock
            # and dominates short graph command transactions. Establish it once
            # per injected engine, while retaining the per-connection busy
            # timeout required for writer contention.
            with wal_lock:
                if not wal_initialized:
                    cursor.execute("PRAGMA journal_mode=WAL")
                    wal_initialized = True
            cursor.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()


class _ResilientAsyncSession(AsyncSession):
    """AsyncSession that tolerates dead connections during close().

    With NullPool + aiosqlite, the underlying connection can already be gone
    by the time close() tries to rollback.  This happens in two scenarios:

    1. **Server shutdown/reload**: ``engine.dispose()`` races with background
       tasks that still hold sessions.  The rollback inside ``close()`` hits a
       dead aiosqlite connection → ``OperationalError``.

    2. **CancelledError during close**: ``asyncio.CancelledError`` interrupts
       ``await session.close()`` mid-rollback, leaving the session half-closed.
       SQLAlchemy's GC later schedules ``close()`` as a fire-and-forget
       ``asyncio.Task``.  That task fails → "Task exception was never
       retrieved".

    Catching both ``OperationalError`` and ``CancelledError`` here silences
    these harmless but noisy warnings.
    """

    async def close(self) -> None:
        try:
            await super().close()
        except (OperationalError, asyncio.CancelledError):
            logger.debug("Suppressed error during session close (connection gone or cancelled)")


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=_ResilientAsyncSession)


async def init_db(engine: AsyncEngine | str) -> None:
    """Create the current database schema when its tables do not exist.

    Accepts either an ``AsyncEngine`` or a SQLite database path string. When a
    string is passed a temporary engine is created and disposed after use.

    The application has no schema-upgrade contract. Both file-backed and
    in-memory databases are initialized directly from the current ORM
    metadata; existing tables are left untouched and are never rewritten or
    deleted implicitly.
    """
    if isinstance(engine, str):
        tmp_engine = create_engine(engine)
        await init_db(tmp_engine)
        await tmp_engine.dispose()
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
