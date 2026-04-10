"""Database connection management."""

import asyncio
import logging
from pathlib import Path

from sqlalchemy import Connection
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

# Path to Alembic migration scripts (two levels up from this file)
_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


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
    return create_async_engine(
        f"sqlite+aiosqlite:///{db_path_str}",
        echo=False,
        poolclass=NullPool,
    )


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


def _run_alembic_upgrade(connection: Connection) -> None:
    """Run Alembic migrations on a synchronous connection."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


async def init_db(engine: AsyncEngine) -> None:
    """Initialise the database schema.

    For file-based databases, runs Alembic migrations so the schema is always
    up-to-date with the migration history.  For in-memory databases (used in
    tests), falls back to ``metadata.create_all()`` since migration tracking
    is unnecessary.
    """
    url_str = str(engine.url)
    is_memory = url_str == "sqlite+aiosqlite://" or ":memory:" in url_str

    if is_memory:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        async with engine.begin() as conn:
            await conn.run_sync(_run_alembic_upgrade)
