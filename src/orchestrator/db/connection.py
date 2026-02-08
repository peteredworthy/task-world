"""Database connection management."""

from pathlib import Path

from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from orchestrator.db.base import Base

# Path to Alembic migration scripts (sibling directory to this file)
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


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

    return create_async_engine(f"sqlite+aiosqlite:///{db_path_str}", echo=False)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the given engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


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
