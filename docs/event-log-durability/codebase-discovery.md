# Source File Signatures

## `src/orchestrator/db/access/event_store_v2.py`

- `@dataclasses.dataclass(frozen=True) class StoredEvent:` existing immutable event row DTO. Fields: `position: int`, `aggregate_id: str`, `event_type: str`, `payload: str`, `timestamp: str`, `version: int`.
- `class ActivityEventRow(TypedDict):` existing activity-feed row shape. Fields: `id: int`, `event_type: str`, `timestamp: datetime`, `payload: dict[str, Any]`.
- `@runtime_checkable class EventStore(Protocol):` existing event-store protocol.
  - `async def append(self, events: Sequence[WorkflowEvent]) -> list[StoredEvent]: ...`
  - `async def get_stream(self, aggregate_id: str) -> list[StoredEvent]: ...`
  - `async def get_all(self, after_position: int = 0) -> list[StoredEvent]: ...`
  - `async def get_events_paginated(self, run_id: str, *, after: int | None = None, limit: int = 200, event_type: str | None = None) -> list[ActivityEventRow]: ...`
- `class SqliteEventStore:` existing `events_v2` store with optimistic concurrency and listener fan-out.
  - `def __init__(self, session: AsyncSession, concurrency: ConcurrencyStrategy | None = None) -> None:`
  - `def add_listener(self, listener: EventOutboxObserver) -> None:`
  - `def add_projection_listener(self, listener: Callable[..., Awaitable[None]]) -> None:`
  - `async def append(self, events: WorkflowEvent | Sequence[WorkflowEvent]) -> list[StoredEvent]:`
  - `async def get_stream(self, aggregate_id: str) -> list[StoredEvent]:`
  - `async def get_all(self, after_position: int = 0) -> list[StoredEvent]:`
  - `async def get_events_paginated(self, run_id: str, *, after: int | None = None, limit: int = 200, event_type: str | None = None) -> list[ActivityEventRow]:`
  - `async def append_batch(self, events: Sequence[WorkflowEvent]) -> list[StoredEvent]:`
- `def create_wired_event_store_v2(session: AsyncSession, *, include_outbox: bool = True) -> SqliteEventStore:` existing helper that wires `JsonlOutboxObserver`, `ProjectionRegistry`, `RunStateProjector`, `TaskStateProjector`, and `RunLifecycleProjector`.
- `def _to_stored(m: EventV2Model) -> StoredEvent:` existing private ORM-to-DTO conversion.
- `def _to_activity_row(m: EventV2Model) -> ActivityEventRow:` existing private activity-feed conversion.

One-level imports used by this file: `ConcurrencyStrategy`, `RetryWithBackoff`, `EventOutboxObserver`, `queue_event_outbox`, `EventV2Model`, `format_utc_datetime`, `WorkflowEvent`.

## `src/orchestrator/db/access/jsonl_outbox.py`

- `def resolve_default_journal_path(db_path: str | Path | None) -> Path | None:` existing resolver. Uses `ORCHESTRATOR_EVENT_JOURNAL_PATH` when set; otherwise maps file DB directory to `.orchestrator/state/history.jsonl`; returns `None` for in-memory DBs.
- `def resolve_default_journal_path_from_session(session: AsyncSession) -> Path | None:` existing resolver from SQLAlchemy session bind.
- `class JsonlOutboxObserver:` existing post-commit JSONL secondary sink.
  - `def __init__(self, path: Path) -> None:`
  - `async def __call__(self, events: list[StoredEvent]) -> None:`
- `def _to_record(e: StoredEvent) -> dict[str, object]:` existing private JSONL record serializer.
- `def _append_lines(path: Path, lines: str) -> None:` existing private append helper.
- `def _read_positions(path: Path) -> set[int]:` existing private idempotency helper.

One-level imports used by this file: `StoredEvent`.

## `src/orchestrator/db/bootstrap.py`

- `def _parse_jsonl_record(record: dict[str, Any]) -> tuple[int | None, str, str, str, str] | None:` existing parser for outbox and legacy JSONL records.
- `async def _read_jsonl_records(path: Path) -> list[dict[str, Any]]:` existing async file reader that skips blank/malformed JSON lines.
- `async def bootstrap_from_jsonl(session: AsyncSession, journal_path: Path | str | None, projection_registry: ProjectionRegistry) -> None:` existing bootstrap path. No-ops when `events_v2` is non-empty, missing, or absent; inserts parsed records into `events_v2`, deserializes known workflow events, calls `projection_registry.rebuild_all(events, session)`, and updates projection checkpoints.

One-level imports used by this file: `EventV2Model`, `ProjectionCheckpointModel`, `format_utc_datetime`, `WorkflowEvent`, `deserialize_event`, `ProjectionRegistry`.

## `src/orchestrator/db/orm/models.py`

- `class EventV2Model(Base):` existing SQLAlchemy ORM model for authoritative DB event log. No custom methods.
- `class ProjectionCheckpointModel(Base):` existing SQLAlchemy ORM model for projector cursors. No custom methods.
- Run/task projection tables touched by projectors also exist here: `class RunModel(Base):`, `class StepModel(Base):`, `class TaskModel(Base):`, `class AttemptModel(Base):`.

## `src/orchestrator/db/projections/registry.py`

- `def _expand_events_for_projection(events: Sequence[WorkflowEvent]) -> list[WorkflowEvent]:` existing private expansion helper. Expands `RunCreated` events with `run_snapshot` via `expand_run_snapshot_for_projection`.
- `@runtime_checkable class Projector(Protocol):` existing projector contract.
  - `handled_events: frozenset[type]`
  - `async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None: ...`
  - `async def rebuild(self, events: Sequence[WorkflowEvent], session: AsyncSession) -> None: ...`
- `class ProjectionRegistry:` existing dispatcher/rebuild coordinator.
  - `def __init__(self) -> None:`
  - `def register(self, projector: Projector) -> None:`
  - `@property def projector_count(self) -> int:`
  - `async def __call__(self, stored_events: list[Any], session: AsyncSession, workflow_events: list[WorkflowEvent]) -> None:`
  - `async def rebuild_all(self, all_events: Sequence[WorkflowEvent], session: AsyncSession) -> None:`

One-level imports used by this file: `ProjectionCheckpointModel`, `format_utc_datetime`, `RunCreated`, `WorkflowEvent`, `expand_run_snapshot_for_projection`.

## `src/orchestrator/db/projections/run_lifecycle.py`

- `class RunLifecycleProjector:` existing in-memory lifecycle projector.
  - `handled_events: frozenset[type] = frozenset({RunStatusChanged})`
  - `def __init__(self) -> None:`
  - `def is_active(self, run_id: str) -> bool:`
  - `def is_terminal(self, run_id: str) -> bool:`
  - `async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None:`
  - `async def rebuild(self, events: Sequence[WorkflowEvent], session: AsyncSession) -> None:`

One-level imports used by this file: `RunStatus`, `RunStatusChanged`, `WorkflowEvent`.

## `src/orchestrator/db/projections/run_state.py`

- `def _parse_datetime(value: Any) -> datetime | str | None:` existing private datetime parser.
- `def _json_dump(value: Any) -> str:` existing private JSON serializer.
- `def _merge_token_usage_by_model(existing: list[dict[str, Any]] | None, delta: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:` existing private token usage merge helper.
- `def merge_oversight_patch(state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:` existing append/set-aware oversight merge helper.
- `class RunStateProjector:` existing `runs`/`steps` read-model projector.
  - `handled_events: frozenset[type] = frozenset({...})`
  - `async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None:`
  - `async def _insert_run_from_snapshot(self, event: RunCreated, session: AsyncSession) -> None:`
  - `async def rebuild(self, events: Sequence[WorkflowEvent], session: AsyncSession) -> None:`

Relevant handled events: `RunCreated`, `StepCreated`, `RunStatusChanged`, `RunWorktreeCreationRequested`, `RunWorktreeCreationFailed`, `RunWorktreeUpdated`, `RunMetadataUpdated`, `AgentChangedEvent`, `AttemptUpdated`, `TaskStatusChanged`, `StepCompleted`, `StepHumanApprovalRecorded`, `StepSkipped`, `RunStepBackward`, `GradesEvaluated`, `AutoVerifyCompleted`, `ChecklistGateEvaluated`, `ClarificationResponded`, `HealthCheckEvent`, `StepIndexRewound`, `ParentOversightFactsUpdated`, `RunDeleted`.

## `src/orchestrator/db/projections/task_state.py`

- `def _parse_datetime(value: Any) -> datetime | None:` existing private datetime parser.
- `def _attempt_from_snapshot(task_id: str, snapshot: dict[str, Any]) -> AttemptModel:` existing private attempt materializer.
- `def _attempt_values_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:` existing private attempt value extractor.
- `async def _upsert_attempt_snapshots(session: AsyncSession, task_id: str, snapshots: list[dict[str, Any]]) -> None:` existing private attempt upsert helper.
- `class TaskStateProjector:` existing `tasks`/`attempts` read-model projector.
  - `handled_events: frozenset[type] = frozenset({...})`
  - `async def handle(self, event: WorkflowEvent, session: AsyncSession) -> None:`
  - `async def rebuild(self, events: Sequence[WorkflowEvent], session: AsyncSession) -> None:`

Relevant handled events: `TaskCreated`, `TaskStatusChanged`, `ChecklistItemGraded`, `ChecklistItemUpdated`, `AutoVerifyCompleted`, `ClarificationRequested`, `ClarificationResponded`, `ApprovalRequested`, `ApprovalDecision`, `TaskReverted`, `FanOutSpawned`, `ChildSpawned`, `ChildCompleted`, `ChildFailed`, `FanOutCompleted`, `TaskAttemptCreated`, `AttemptUpdated`, `FanOutChildrenCreated`, `FanOutChildrenReset`, `FanOutChildRetried`, `RunStepBackward`.

## `src/orchestrator/workflow/events/logger.py`

- `class PersistentEventEmitter:` existing emitter that persists through an event store and notifies in-memory listeners after persistence.
  - `def __init__(self, event_store: Any) -> None:`
  - `def add_listener(self, listener: Callable[[WorkflowEvent], None]) -> None:`
  - `async def emit(self, event: WorkflowEvent) -> None:`
  - `def notify_persisted(self, event: WorkflowEvent) -> None:`
  - `async def emit_batch(self, events: Sequence[WorkflowEvent]) -> None:`
  - `def notify_persisted_batch(self, events: Sequence[WorkflowEvent]) -> None:`

One-level imports used by this file: `WorkflowEvent`.

## `src/orchestrator/workflow/events/types.py`

- `class WorkflowEvent(BaseModel):` existing base event. Fields: `timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))`, `run_id: str`, `event_type: str = ""`.
- `class RunStatusChanged(WorkflowEvent):` existing run status event. Fields: `old_status: RunStatus | str = RunStatus.DRAFT`, `new_status: RunStatus | str = RunStatus.DRAFT`, `pause_reason: str | None = None`, `last_error: str | None = None`.
- `class TaskStatusChanged(WorkflowEvent):` existing task status event. Fields: `task_id: str = ""`, `old_status: TaskStatus | str = TaskStatus.PENDING`, `new_status: TaskStatus | str = TaskStatus.PENDING`, `start_commit: str | None = None`, `end_commit: str | None = None`, `current_attempt: int | None = None`, `attempt_snapshots: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])`.
- `class RunCreated(WorkflowEvent):` existing run creation snapshot event. Key fields include `event_type: str = "run_created"`, `routine_id: str`, `project_path: str`, `repo_name: str`, `status: RunStatus = RunStatus.DRAFT`, `config: dict[str, Any]`, `runner_type: str | None`, `runner_config: dict[str, Any]`, worktree/source/merge/env metadata, totals, `transition_tracker: dict[str, Any] | None`, and `run_snapshot: dict[str, Any]`.
- `class StepCreated(WorkflowEvent):` existing step creation event. Fields: `event_type: str = "step_created"`, `step_id: str`, `config_id: str`, `title: str`, `order_index: int`, `condition: dict[str, Any] | None`, `step_index: int | None`, `completed: bool`, `human_approval: dict[str, Any] | None`, `skipped: bool`, `skip_reason: str | None`.
- `class TaskCreated(WorkflowEvent):` existing task creation event. Fields include `event_type: str = "task_created"`, `task_id: str`, `step_id: str`, `step_index: int`, `config_id: str`, `title: str`, `complexity: str | None`, `order_index: int`, `max_attempts: int`, `checklist: list[dict[str, Any]]`, parent/fan-out fields, `status: TaskStatus = TaskStatus.PENDING`, `current_attempt: int`, `has_verification: bool`, pending action fields.
- `class SignalEnqueued(WorkflowEvent):` existing signal event. Fields: `event_type: str = "signal_enqueued"`, `signal_type: str = ""`, `payload: dict[str, Any] | None = None`.
- `class SignalProcessed(WorkflowEvent):` existing signal event. Fields: `event_type: str = "signal_processed"`, `enqueued_position: int = 0`.
- `class BufferingEmitter:` existing in-memory emitter.
  - `def __init__(self) -> None:`
  - `def emit(self, event: WorkflowEvent) -> None:`
  - `def drain(self) -> list[WorkflowEvent]:`

## `src/orchestrator/workflow/events/__init__.py`

- `def deserialize_event(event_type: str, payload: str) -> WorkflowEvent:` existing event deserializer. Uses `_EVENT_TYPE_MAP`; raises `ValueError` for unknown event types.
- `_EVENT_TYPE_MAP: dict[str, type[WorkflowEvent]]` existing map. Relevant keys include `run_created`, `step_created`, `task_created`, `run_status_changed`, `task_status_changed`, `signal_enqueued`, `signal_processed`, plus runtime aliases such as `agent_changed_event` and `health_check_event`.

## `scripts/restore_from_journal.py`

- `DEFAULT_DB_PATH = Path("orchestrator.db")` existing default DB path.
- `DEFAULT_JOURNAL_PATH = Path(".orchestrator/state/history.jsonl")` existing default journal path.
- `def build_projection_registry() -> ProjectionRegistry:` existing restore helper; registers `RunStateProjector`, `TaskStateProjector`, `RunLifecycleProjector`.
- `async def restore_from_journal(*, db_path: Path | str = DEFAULT_DB_PATH, journal_path: Path | str = DEFAULT_JOURNAL_PATH) -> None:` existing operational restore wrapper around `init_db`, `create_session_factory`, `bootstrap_from_jsonl`, and `session.commit()`.
- `def parse_args() -> argparse.Namespace:` existing CLI parser.
- `async def main() -> None:` existing CLI entrypoint.

## New Symbols Likely Needed By The Step

- `tests/integration/test_event_log_durability.py`: new proof test file likely needed. No current symbol exists for an end-to-end durability drill that creates workflow activity, clears disposable run/task projections, rebuilds from `events_v2`, and validates retry/idempotency evidence in one focused slice.

# Test Coverage Map

## `src/orchestrator/db/access/event_store_v2.py`

- `tests/unit/test_event_store_v2.py`: fixtures `async_session`; helpers `_run_event`, `_task_event`; patterns: real in-memory SQLite via `create_engine(":memory:")`, `init_db`, real `AsyncSession`, no `patch`/`MagicMock`/`monkeypatch`; local `AlwaysConflictStrategy(RetryWithBackoff)` class injects conflict behavior.
- `tests/unit/test_event_store.py`: fixtures `session`, `store`; covers `PersistentEventEmitter` compatibility with `SqliteEventStore`; uses simple listener lists and a local failing store object, no mocking library.
- `tests/integration/test_event_store_wiring.py`: fixtures `session`, `jsonl_path`; covers store + `JsonlOutboxObserver` + `PersistentEventEmitter` together using real DB/session/temp JSONL.
- `tests/integration/test_database.py`: fixture `session`; directly inserts/queries `EventV2Model`.

## `src/orchestrator/db/access/jsonl_outbox.py`

- `tests/unit/test_jsonl_outbox.py`: fixture `session`; helpers `_stored`, `_event`; uses `tmp_path`, real files, real event store/outbox commit helper; no mock library. Failure pattern uses invalid/unwritable path behavior and projection failure callbacks rather than `patch`.
- `tests/integration/test_event_store_wiring.py`: fixtures `session`, `jsonl_path`; covers committed JSONL lines and idempotency across observer restart.

## `src/orchestrator/db/bootstrap.py` and `scripts/restore_from_journal.py`

- `tests/integration/test_jsonl_bootstrap.py`: fixture `session`; helpers `_write_fixture_jsonl`, `_write_legacy_fixture_jsonl`; covers outbox/legacy JSONL import, no-op when populated, missing journal warnings via `caplog`, and restore script import/invocation against real temp file DB. No mock library.

## `src/orchestrator/db/projections/registry.py`

- `tests/unit/test_projection_rebuild.py`: fixture `session`; helpers `_make_run`, `_status_changed`; local `_NeverCalledProjector` verifies dispatch filtering; real DB/session, no mocks.
- `tests/unit/test_projectors.py`: fixtures `session`, `populated_session`; exercises registry expansion of `RunCreated.run_snapshot`.
- `tests/integration/test_projection_recovery.py`: fixture `session`; helper `_store_and_project`; rebuilds read models from stored events.
- `tests/integration/test_event_sourced_workflow.py`: fixture `api_fixture`; uses ASGI app/client and command handlers to verify empty-DB rebuild.

## `src/orchestrator/db/projections/run_lifecycle.py`

- `tests/unit/test_run_lifecycle_projector.py`: helper `_status_event`; no DB fixture required for most tests; covers active/terminal state, rebuild, stale signal checks. No mocking patterns.
- `tests/unit/test_projection_rebuild.py`: fixture `session`; rebuild through `ProjectionRegistry`.

## `src/orchestrator/db/projections/run_state.py` and `src/orchestrator/db/projections/task_state.py`

- `tests/unit/test_projectors.py`: fixtures `session`, `populated_session`; helpers `_get_run`, `_get_step`, `_get_task`, `_get_task_model`, `_get_attempts`, `_snapshot_run_created_event`; comprehensive event projection tests with real in-memory SQLite; no mocking library.
- `tests/integration/test_projection_recovery.py`: fixture `session`; exercises full lifecycle rebuild, idempotent rebuild, multiple runs, delete tombstones, runtime event aliases.
- `tests/integration/test_workflow_service.py`: fixtures `session`, `service`; validates workflow commands project into DB and can replay from `events_v2`; no mocking library.

## `src/orchestrator/workflow/events/logger.py`

- `tests/unit/test_event_store.py`: fixtures `session`, `store`; covers `emit`, `emit_batch`, listener notification, and listener blocking on store failure using local objects/lists.
- `tests/integration/test_event_store_wiring.py`: fixtures `session`, `jsonl_path`; covers persistence to `events_v2` and JSONL through real store.

## `src/orchestrator/workflow/events/types.py` and `src/orchestrator/workflow/events/__init__.py`

- `tests/integration/test_projection_recovery.py`: fixture `session`; covers `deserialize_event` round-trips and accepted runtime aliases.
- `tests/unit/test_pydantic_events.py`: covers Pydantic event serialization/validation.
- `tests/integration/test_jsonl_bootstrap.py`: fixture `session`; exercises deserialization through bootstrap.

# Import Reference Table

| Symbol | Import statement |
|---|---|
| `SqliteEventStore` | `from orchestrator.db import SqliteEventStore` |
| `StoredEvent` | `from orchestrator.db import StoredEvent` |
| `EventV2Model` | `from orchestrator.db import EventV2Model` |
| `ProjectionCheckpointModel` | `from orchestrator.db import ProjectionCheckpointModel` |
| `JsonlOutboxObserver` | `from orchestrator.db import JsonlOutboxObserver` |
| `bootstrap_from_jsonl` | `from orchestrator.db import bootstrap_from_jsonl` |
| `ProjectionRegistry` | `from orchestrator.db import ProjectionRegistry` |
| `RunStateProjector` | `from orchestrator.db import RunStateProjector` |
| `TaskStateProjector` | `from orchestrator.db import TaskStateProjector` |
| `RunLifecycleProjector` | `from orchestrator.db import RunLifecycleProjector` |
| `create_engine` | `from orchestrator.db import create_engine` |
| `create_session_factory` | `from orchestrator.db import create_session_factory` |
| `init_db` | `from orchestrator.db import init_db` |
| `PersistentEventEmitter` | `from orchestrator.workflow import PersistentEventEmitter` |
| `WorkflowEvent` | `from orchestrator.workflow import WorkflowEvent` |
| `RunCreated` | `from orchestrator.workflow import RunCreated` |
| `StepCreated` | `from orchestrator.workflow import StepCreated` |
| `TaskCreated` | `from orchestrator.workflow import TaskCreated` |
| `RunStatusChanged` | `from orchestrator.workflow import RunStatusChanged` |
| `TaskStatusChanged` | `from orchestrator.workflow import TaskStatusChanged` |
| `SignalEnqueued` | `from orchestrator.workflow import SignalEnqueued` |
| `SignalProcessed` | `from orchestrator.workflow import SignalProcessed` |
| `deserialize_event` | `from orchestrator.workflow import deserialize_event` |
| `RunStatus` | `from orchestrator.config import RunStatus` |
| `TaskStatus` | `from orchestrator.config import TaskStatus` |
| `restore_from_journal` | `from scripts.restore_from_journal import restore_from_journal` |
| `build_projection_registry` | `from scripts.restore_from_journal import build_projection_registry` |

# Database Schema Snapshot

## `events_v2`

- `position`: `Integer`, primary key, autoincrement, not nullable by PK.
- `aggregate_id`: `String`, nullable `False`.
- `event_type`: `String`, nullable `False`.
- `payload`: `Text`, nullable `False`, JSON string.
- `timestamp`: `String`, nullable `False`, ISO 8601.
- `version`: `Integer`, nullable `False`.
- Constraints/indexes: `UniqueConstraint("aggregate_id", "version", name="uq_events_v2_aggregate_version")`; `Index("idx_events_v2_aggregate", "aggregate_id", "position")`; `Index("idx_events_v2_type", "event_type", "position")`.
- Current gap for the step contract: no separate stable event identity column exists; idempotency is currently by DB position in JSONL and by aggregate/version uniqueness in `events_v2`.

## `projection_checkpoints`

- `projector_name`: `String`, primary key.
- `last_position`: `Integer`, nullable `False`, default `0`.
- `updated_at`: `String`, nullable `False`, ISO 8601.

## Read-Model Tables Touched By Rebuild

- `runs`: projected by `RunStateProjector`; key fields touched include `id`, `repo_name`, `status`, `pause_reason`, `last_error`, routine metadata, runner/worktree/source/merge/env fields, `current_step_index`, `transition_tracker`, aggregate token/action totals, timestamps, and `token_usage_by_model`.
- `steps`: projected by `RunStateProjector`; key fields touched include `id`, `run_id`, `config_id`, `title`, `order_index`, `condition`, `completed`, `human_approval`, `skipped`, `skip_reason`.
- `tasks`: projected by `TaskStateProjector`; key fields touched include `id`, `step_id`, `config_id`, `title`, `complexity`, `order_index`, `status`, `checklist`, `current_attempt`, `max_attempts`, `version`, `has_verification`, pending action fields, parent/fan-out fields, `child_id`.
- `attempts`: projected by `TaskStateProjector`; key fields touched include `id`, `task_id`, `attempt_num`, `attempt_id`, timestamps, prompts/comments/outcome, token/action metrics, grade/auto-verify snapshots, runner/model/settings, output/error, action log, `start_commit`, `end_commit`.

# Constants & Enums

- `_JOURNAL_PATH_ENV = "ORCHESTRATOR_EVENT_JOURNAL_PATH"` in `src/orchestrator/db/access/jsonl_outbox.py`.
- `DEFAULT_DB_PATH = Path("orchestrator.db")` in `scripts/restore_from_journal.py`.
- `DEFAULT_JOURNAL_PATH = Path(".orchestrator/state/history.jsonl")` in `scripts/restore_from_journal.py`.
- `_ACTIVE_STATUSES: frozenset[RunStatus] = frozenset({RunStatus.ACTIVE, RunStatus.PAUSED})` in `src/orchestrator/db/projections/run_lifecycle.py`.
- `_TERMINAL_STATUSES: frozenset[RunStatus] = frozenset({RunStatus.COMPLETED, RunStatus.FAILED})` in `src/orchestrator/db/projections/run_lifecycle.py`.
- `_LIST_LIMIT = 100` in `src/orchestrator/db/projections/run_state.py`.
- `RunStatus`: imported from `orchestrator.config`; relevant values used here include `DRAFT`, `ACTIVE`, `PAUSED`, `STOPPING`, `COMPLETED`, `FAILED`.
- `TaskStatus`: imported from `orchestrator.config`; relevant values used here include `PENDING`, `BUILDING`, `VERIFYING`, and terminal/failure states used by workflow/projector tests.
- Event type string constants are Pydantic field defaults on event classes: `run_created`, `step_created`, `task_created`, `run_status_changed`, `task_status_changed`, `signal_enqueued`, `signal_processed`, plus many projection-handled workflow event names in `_EVENT_TYPE_MAP`.
