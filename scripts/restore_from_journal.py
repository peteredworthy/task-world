"""Restore an empty database from a JSONL event journal.

This is the maintained operational wrapper around the events_v2 bootstrap path.
It supports both JSONL outbox records and the older history.jsonl shape; parsed
events are inserted into events_v2 and projections are rebuilt from those events.

Usage:
    uv run python scripts/restore_from_journal.py
    uv run python scripts/restore_from_journal.py --db orchestrator.db --journal path/to/history.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from orchestrator.db import (
    ProjectionRegistry,
    RunLifecycleProjector,
    RunStateProjector,
    TaskStateProjector,
    bootstrap_from_jsonl,
    create_engine,
    create_session_factory,
    init_db,
)

DEFAULT_DB_PATH = Path("orchestrator.db")
DEFAULT_JOURNAL_PATH = Path(".orchestrator/state/history.jsonl")


def build_projection_registry() -> ProjectionRegistry:
    """Create the standard projection registry used for restore/bootstrap."""
    registry = ProjectionRegistry()
    registry.register(RunStateProjector())
    registry.register(TaskStateProjector())
    registry.register(RunLifecycleProjector())
    return registry


async def restore_from_journal(
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    journal_path: Path | str = DEFAULT_JOURNAL_PATH,
) -> None:
    """Initialize the DB and restore JSONL events through events_v2 projections."""
    engine = create_engine(db_path)
    try:
        await init_db(engine)
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            await bootstrap_from_jsonl(session, journal_path, build_projection_registry())
            await session.commit()
    finally:
        await engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        dest="db_path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="SQLite DB path to initialize and restore into.",
    )
    parser.add_argument(
        "--journal",
        dest="journal_path",
        type=Path,
        default=DEFAULT_JOURNAL_PATH,
        help="JSONL journal path. Supports outbox and legacy history formats.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    await restore_from_journal(db_path=args.db_path, journal_path=args.journal_path)
    print(f"Restore complete: {args.db_path} from {args.journal_path}")


if __name__ == "__main__":
    asyncio.run(main())
