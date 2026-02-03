"""Database connection management."""

from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from orchestrator.db.base import Base


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


async def init_db(engine: AsyncEngine) -> None:
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
