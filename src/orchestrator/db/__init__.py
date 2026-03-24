"""Database layer for persistent storage.

Public interface — all symbols importable as ``from orchestrator.db import X``.
"""

from typing import TYPE_CHECKING

# ORM base and models (not in __all__ — use repositories for public API)
from orchestrator.db.orm.base import Base
from orchestrator.db.orm.models import (
    AttemptModel,
    AttemptRecord,
    ClarificationRequestModel,
    ClarificationResponseModel,
    EventModel,
    PendingSignalModel,
    ReplayCheckpointModel,
    RunModel,
    RunnerProfileDefaultModel,
    StepModel,
    TaskModel,
)

# Connection management
from orchestrator.db.access.connection import (
    create_engine,
    create_session_factory,
    init_db,
)

# Event journal
from orchestrator.db.recovery.event_journal import (
    JsonlEventJournal,
    make_journal_entry,
    parse_journal_timestamp,
    read_journal_entries,
    resolve_default_journal_path,
    resolve_default_journal_path_from_session,
)

# Journal replay
from orchestrator.db.recovery.journal_replay import (
    JournalReplaySummary,
    replay_journal_to_repository,
)

# Event recovery / replay
from orchestrator.db.recovery.recovery import (
    RECOVERY_MATRIX,
    replay_events,
)

# Backup utilities
from orchestrator.db.recovery.backup import (
    BackupError,
    BackupMetadata,
    create_backup,
    restore_backup,
    scan_max_sequence,
)

if TYPE_CHECKING:
    # Lazy imports to avoid circular dependencies with workflow.clarifications
    from orchestrator.db.access.event_store import EventStore
    from orchestrator.db.access.repositories import CheckpointRepository, RunRepository


def __getattr__(name: str):
    """Lazy-load repositories and event_store to avoid circular imports."""
    if name == "RunRepository":
        from orchestrator.db.access.repositories import RunRepository

        return RunRepository
    elif name == "CheckpointRepository":
        from orchestrator.db.access.repositories import CheckpointRepository

        return CheckpointRepository
    elif name == "EventStore":
        from orchestrator.db.access.event_store import EventStore

        return EventStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # access
    "create_engine",
    "create_session_factory",
    "init_db",
    "CheckpointRepository",
    "RunRepository",
    "EventStore",
    # recovery
    "JsonlEventJournal",
    "make_journal_entry",
    "parse_journal_timestamp",
    "read_journal_entries",
    "resolve_default_journal_path",
    "resolve_default_journal_path_from_session",
    "JournalReplaySummary",
    "replay_journal_to_repository",
    "RECOVERY_MATRIX",
    "replay_events",
    "BackupError",
    "BackupMetadata",
    "create_backup",
    "restore_backup",
    "scan_max_sequence",
]
