"""Database layer for persistent storage.

Public interface — all symbols importable as ``from orchestrator.db import X``.
"""

from typing import TYPE_CHECKING

# ORM base and models (not in __all__ — use repositories for public API)
# Imported here for backward compatibility with existing code that imports from db
from orchestrator.db.orm.base import Base
from orchestrator.db.orm.models import (  # noqa: F401
    AgentRunnerModelProfileDefaultModel,
    AttemptModel,
    ClarificationRequestModel,
    ClarificationResponseModel,
    CostRecordModel,
    EventV2Model,
    GraphArtifactReferenceModel,
    GraphArchivalViewCheckpointModel,
    GraphEventSummaryModel,
    GraphFinalBlockerViewEntryModel,
    GraphNodeDetailCollectionFactModel,
    GraphNodeDetailSummaryCheckpointModel,
    GraphNodeDetailSummaryModel,
    GraphProjectionCheckpointModel,
    GraphProjectionSnapshotModel,
    GraphRegionViewEntryModel,
    GraphTopologyViewEntryModel,
    GraphOutboxModel,
    InteractionLogArtifactModel,
    ProjectionCheckpointModel,
    RunModel,
    RoutineMetaModel,
    StepModel,
    TaskModel,
)

# Connection management
from orchestrator.db.access.connection import (
    create_engine,
    create_session_factory,
    init_db,
)
from orchestrator.db.access.concurrency import is_retriable_sqlite_write_conflict

# JSONL outbox: path helpers + observer
from orchestrator.db.access.jsonl_outbox import (
    JsonlOutboxObserver,
    RotationOperations,
    SystemRotationOperations,
    JournalSegment,
    discover_journal_segments,
    drain_committed_events_to_journal,
    resolve_default_journal_path,
    resolve_default_journal_path_from_session,
)
from orchestrator.db.access.event_outbox import (
    EventOutboxBatch,
    EventOutboxObserver,
    CommittedSecondaryOutputError,
    clear_event_outbox,
    commit_with_event_outbox,
    flush_event_outbox,
    queue_event_outbox,
    rollback_with_event_outbox,
    retry_committed_secondary_output,
)

# Backup utilities
from orchestrator.db.recovery.backup import (
    BackupError,
    BackupMetadata,
    create_backup,
    restore_backup,
    scan_max_sequence,
)

from orchestrator.db.bootstrap import bootstrap_from_jsonl

if TYPE_CHECKING:
    # Lazy imports to avoid circular dependencies with workflow.clarifications
    from orchestrator.db.access.concurrency import ConcurrencyConflictError, RetryWithBackoff
    from orchestrator.db.access.event_store_v2 import (
        SqliteEventStore,
        StoredEvent,
        create_wired_event_store_v2,
    )
    from orchestrator.db.access.event_outbox import (
        EventOutboxBatch,
        EventOutboxObserver,
    )
    from orchestrator.db.projections import (
        ProjectionRegistry,
        RunLifecycleProjector,
        RunStateProjector,
        TaskStateProjector,
        merge_token_usage_by_model,
    )
    from orchestrator.db.access.repositories import (
        RunLivenessRecord,
        RunRepository,
    )
    from orchestrator.db.access.mutations import (
        create_clarification_request,
        delete_run,
        merge_token_usage_into_run,
        persist_clarification_response,
        save_run,
        update_latest_attempt,
    )


def __getattr__(name: str):
    """Lazy-load repositories and event_store to avoid circular imports."""
    if name == "RunRepository":
        from orchestrator.db.access.repositories import RunRepository

        return RunRepository
    elif name == "RunLivenessRecord":
        from orchestrator.db.access.repositories import RunLivenessRecord

        return RunLivenessRecord
    elif name == "delete_run":
        from orchestrator.db.access.mutations import delete_run

        return delete_run
    elif name == "merge_token_usage_into_run":
        from orchestrator.db.access.mutations import merge_token_usage_into_run

        return merge_token_usage_into_run
    elif name == "save_run":
        from orchestrator.db.access.mutations import save_run

        return save_run
    elif name == "update_latest_attempt":
        from orchestrator.db.access.mutations import update_latest_attempt

        return update_latest_attempt
    elif name == "create_clarification_request":
        from orchestrator.db.access.mutations import create_clarification_request

        return create_clarification_request
    elif name == "persist_clarification_response":
        from orchestrator.db.access.mutations import persist_clarification_response

        return persist_clarification_response
    elif name == "SqliteEventStore":
        from orchestrator.db.access.event_store_v2 import SqliteEventStore

        return SqliteEventStore
    elif name == "StoredEvent":
        from orchestrator.db.access.event_store_v2 import StoredEvent

        return StoredEvent
    elif name == "create_wired_event_store_v2":
        from orchestrator.db.access.event_store_v2 import create_wired_event_store_v2

        return create_wired_event_store_v2
    elif name == "ConcurrencyConflictError":
        from orchestrator.db.access.concurrency import ConcurrencyConflictError

        return ConcurrencyConflictError
    elif name == "RetryWithBackoff":
        from orchestrator.db.access.concurrency import RetryWithBackoff

        return RetryWithBackoff
    elif name == "ProjectionRegistry":
        from orchestrator.db.projections import ProjectionRegistry

        return ProjectionRegistry
    elif name == "RunStateProjector":
        from orchestrator.db.projections import RunStateProjector

        return RunStateProjector
    elif name == "merge_token_usage_by_model":
        from orchestrator.db.projections import merge_token_usage_by_model

        return merge_token_usage_by_model
    elif name == "TaskStateProjector":
        from orchestrator.db.projections import TaskStateProjector

        return TaskStateProjector
    elif name == "RunLifecycleProjector":
        from orchestrator.db.projections import RunLifecycleProjector

        return RunLifecycleProjector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Bootstrap
    "bootstrap_from_jsonl",
    # ORM models (backward compat re-exports)
    "AttemptModel",
    "Base",
    "ClarificationRequestModel",
    "ClarificationResponseModel",
    "CostRecordModel",
    "EventV2Model",
    "GraphArchivalViewCheckpointModel",
    "GraphArtifactReferenceModel",
    "GraphEventSummaryModel",
    "GraphFinalBlockerViewEntryModel",
    "GraphNodeDetailCollectionFactModel",
    "GraphNodeDetailSummaryCheckpointModel",
    "GraphNodeDetailSummaryModel",
    "GraphProjectionCheckpointModel",
    "GraphProjectionSnapshotModel",
    "GraphRegionViewEntryModel",
    "GraphTopologyViewEntryModel",
    "GraphOutboxModel",
    "InteractionLogArtifactModel",
    "ProjectionCheckpointModel",
    "RunModel",
    "AgentRunnerModelProfileDefaultModel",
    "RoutineMetaModel",
    "StepModel",
    "TaskModel",
    # access
    "create_engine",
    "create_session_factory",
    "init_db",
    "RunRepository",
    "RunLivenessRecord",
    "create_clarification_request",
    "delete_run",
    "merge_token_usage_into_run",
    "persist_clarification_response",
    "save_run",
    "SqliteEventStore",
    "StoredEvent",
    "create_wired_event_store_v2",
    "ConcurrencyConflictError",
    "EventOutboxBatch",
    "EventOutboxObserver",
    "CommittedSecondaryOutputError",
    "RetryWithBackoff",
    "is_retriable_sqlite_write_conflict",
    "ProjectionRegistry",
    "RunLifecycleProjector",
    "RunStateProjector",
    "TaskStateProjector",
    "update_latest_attempt",
    "merge_token_usage_by_model",
    "clear_event_outbox",
    "commit_with_event_outbox",
    "flush_event_outbox",
    "queue_event_outbox",
    "rollback_with_event_outbox",
    "retry_committed_secondary_output",
    # JSONL outbox
    "JsonlOutboxObserver",
    "RotationOperations",
    "SystemRotationOperations",
    "JournalSegment",
    "discover_journal_segments",
    "drain_committed_events_to_journal",
    "resolve_default_journal_path",
    "resolve_default_journal_path_from_session",
    # backup
    "BackupError",
    "BackupMetadata",
    "create_backup",
    "restore_backup",
    "scan_max_sequence",
]
