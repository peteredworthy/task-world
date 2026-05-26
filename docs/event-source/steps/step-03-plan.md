# Step 03: Command-Event Refactor of RunRepository

**Milestone:** M3 — Command-Event Refactor of RunRepository
**Plan:** [step-03-plan.md](../step-03-plan.md)
**Architecture:** [architecture.md](../architecture.md) §Command Handler Pattern, §Projector Pattern
**Intent:** [intent.md](../intent.md) — [I-24] full empty-DB rebuild from events; [I-22] Pydantic for all event and projection models
**Prerequisites:** Step 01 (SqliteEventStore) and Step 02 (projectors wired) must be complete.

Replace all `RunRepository` write methods with command handlers that emit events. Projectors from
Step 02 handle the resulting read-model updates. After this step, `RunRepository` is a read-only
query layer and the system can reconstruct full state from an empty database by replaying events.

The nine tasks build upward: new event types first, then command modules (creation, status
mutations, attempt/fan-out mutations), then WorkflowService wiring in two passes, then removing the
now-unused write methods from RunRepository, and finally tests.

## Dry-Run Hardening Applied

- Before implementing `RunCreated` and `TaskCreated`, map every non-nullable `RunModel` and
  `TaskModel` projection column to an event field or a documented deterministic default.
- Prevent double emission during the transition: each converted service method must have one source
  of event emission and tests should assert exact event counts.
- Batch logically atomic multi-event transitions in one store append, especially fan-out creation,
  fan-out retry, task completion, and grade updates.
- `AttemptUpdated.output_lines` is a delta; projector tests must prove multiple updates append
  output in order rather than replacing earlier lines.
- Update tests to use command handlers or `WorkflowService` after repository write helpers are
  removed; do not preserve write-method shims.
- Empty-DB rebuild tests must start with no run/task projection rows and recreate them solely from
  `events_v2`.

## Intent Verification

**Original Intent**: Replace `RunRepository` write methods with command handlers; make
`RunRepository` read-only; emit `RunCreated`/`TaskCreated` so projectors can rebuild full state
from an empty DB.

**Functionality to Produce**:
- New event types: `RunCreated`, `TaskCreated`, `TaskAttemptCreated`, `AttemptUpdated`,
  `ParentOversightFactsUpdated`, `FanOutChildrenCreated`, `FanOutChildrenReset`,
  `FanOutChildRetried`, `StepIndexRewound`.
- Command models (Pydantic `BaseModel`) and async handlers in `src/orchestrator/workflow/commands/`.
- `WorkflowService` calls command handlers for all state mutations; `_repo.save()` and other write
  method calls are removed.
- `RunRepository` exposes only read methods (`get`, `list_*`, `lock_run_for_coordination`,
  `get_task_model`, `count_fan_out_children`).
- `WorkflowEngine` stays pure; buffered emission pattern is preserved.

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_command_handlers.py -v` — all pass.
- `uv run pytest tests/integration/test_event_sourced_workflow.py -v` — all pass.
- `uv run pytest` — full suite passes with no regressions.
- `uv run pyright src/orchestrator/workflow/commands/ src/orchestrator/db/access/repositories.py` — no type errors.
- `grep -r "_repo\.save\|_repo\.update_\|_repo\.create_\|_repo\.reset_\|_repo\.retry_\|_repo\.rewind_" src/orchestrator/workflow/service.py` — returns no matches.

---

## Task 3.1: New event types for entity creation and mutations

**Description**: Add nine new Pydantic `WorkflowEvent` subclasses alongside the existing event
definitions in `types.py`. These events carry the full initial or delta state needed for projectors
to maintain read-model tables and for empty-DB rebuild to reconstruct all state without a baseline
snapshot.

**Implementation Plan (Do These Steps)**

- [ ] In `src/orchestrator/workflow/events/types.py`, add the following new event classes after
  the existing definitions. All must be Pydantic `BaseModel` subclasses (Step 00 already converted
  the base class). Include only fields that projectors will need; keep them flat — no nested
  domain objects that aren't already serializable.

  ```python
  class RunCreated(WorkflowEvent):
      """Full initial state of a new run — enables empty-DB rebuild."""
      routine_id: str = ""
      project_path: str = ""
      repo_name: str = ""
      status: RunStatus = RunStatus.DRAFT
      config: dict = Field(default_factory=dict)     # RoutineConfig.model_dump()
      parent_run_id: str | None = None
      parent_task_id: str | None = None

  class TaskCreated(WorkflowEvent):
      """Full initial state of a new task (including fan-out children)."""
      task_id: str = ""
      step_id: str = ""
      step_index: int = 0
      config_id: str = ""
      title: str = ""
      complexity: str | None = None
      order_index: int = 0
      max_attempts: int = 3
      checklist: list[dict] = Field(default_factory=list)   # ChecklistItem.model_dump() list
      parent_task_id: str | None = None

  class TaskAttemptCreated(WorkflowEvent):
      """New attempt appended to a task."""
      task_id: str = ""
      attempt_id: str = ""
      attempt_num: int = 0
      runner_type: str | None = None
      agent_model: str | None = None

  class AttemptUpdated(WorkflowEvent):
      """Partial update to the latest attempt (streaming output, metrics, outcome)."""
      task_id: str = ""
      attempt_id: str = ""
      # All fields are optional; None means "no change".
      output_lines: list[str] | None = None
      error: str | None = None
      outcome: str | None = None
      completed_at: str | None = None    # ISO 8601 or None
      tokens_read: int | None = None
      tokens_write: int | None = None
      tokens_cache: int | None = None
      duration_ms: int | None = None
      num_actions: int | None = None
      new_task_status: TaskStatus | None = None

  class ParentOversightFactsUpdated(WorkflowEvent):
      """Merged oversight fact patch for a run."""
      patch: dict = Field(default_factory=dict)

  class FanOutChildrenCreated(WorkflowEvent):
      """Fan-out children tasks created for a step."""
      step_id: str = ""
      parent_task_id: str = ""
      children: list[dict] = Field(default_factory=list)   # TaskCreated-like dicts
      parent_new_status: TaskStatus | None = None

  class FanOutChildrenReset(WorkflowEvent):
      """Non-completed fan-out children reset to PENDING; parent to FAN_OUT_RUNNING."""
      parent_task_id: str = ""

  class FanOutChildRetried(WorkflowEvent):
      """Single failed fan-out child reset to PENDING; parent set to FAN_OUT_RUNNING."""
      child_task_id: str = ""
      step_order_index: int = 0

  class StepIndexRewound(WorkflowEvent):
      """Run's current_step_index set back to target if it was higher."""
      target_step_index: int = 0
  ```

- [ ] Export all nine new classes from `src/orchestrator/workflow/events/__init__.py` (follow the
  pattern of existing exports in that file).

**Dependencies**
- [ ] Step 00 (Pydantic event conversion) must be complete — `WorkflowEvent` must already be a
  Pydantic `BaseModel`.

**Constraints**
- [ ] Do not modify any existing event class.
- [ ] `RunCreated` must capture enough state to reconstruct a `RunModel` row from scratch
  (verified by the empty-DB rebuild test in Task 3.9).
- [ ] `TaskCreated` must capture enough state to reconstruct a `TaskModel` row from scratch.
- [ ] All new fields must be JSON-serializable via `model_dump(mode="json")` — no bare `datetime`
  or enum objects; use `str | None` for datetimes (ISO 8601) and `str` for enum values where not
  already coerced by Pydantic.

**Functionality (Expected Outcomes)**
- [ ] All nine new event types import without error.
- [ ] Each round-trips through `.model_dump_json()` / `.model_validate_json()` without loss.
- [ ] Existing event types are unaffected.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `python -c "from orchestrator.workflow.events import RunCreated, TaskCreated, TaskAttemptCreated, AttemptUpdated, ParentOversightFactsUpdated, FanOutChildrenCreated, FanOutChildrenReset, FanOutChildRetried, StepIndexRewound; print('ok')"` — prints `ok`.
- [ ] `uv run pyright src/orchestrator/workflow/events/types.py` — no errors.
- [ ] `uv run pytest tests/unit/test_pydantic_events.py -v` — passes (extend this test to cover
  the new event types with round-trip assertions).

---

## Task 3.2: Command module structure + run/task creation handlers

**Description**: Create the `src/orchestrator/workflow/commands/` package. Implement
`CreateRunCommand` and `CreateTaskCommand` with their handlers. Each handler validates the command,
appends the appropriate event(s) to `SqliteEventStore`, and returns the emitted events. The
`WorkflowEngine` and `BufferingEmitter` are untouched — all I/O remains in the command layer.

**Implementation Plan (Do These Steps)**

- [ ] Create `src/orchestrator/workflow/commands/__init__.py` — re-export all command models and
  handlers from the sub-modules added in this step and the steps that follow:
  ```python
  from orchestrator.workflow.commands.run_lifecycle import (
      CreateRunCommand,
      handle_create_run,
      CreateTaskCommand,
      handle_create_task,
  )
  __all__ = ["CreateRunCommand", "handle_create_run", "CreateTaskCommand", "handle_create_task"]
  ```
  Update `__all__` incrementally as more commands are added in Tasks 3.3 and 3.4.

- [ ] Create `src/orchestrator/workflow/commands/run_lifecycle.py`:

  ```python
  """Command handlers for run and task entity creation."""
  from __future__ import annotations

  from typing import TYPE_CHECKING
  from pydantic import BaseModel, Field

  from orchestrator.config.enums import RunStatus
  from orchestrator.workflow.events import RunCreated, TaskCreated

  if TYPE_CHECKING:
      from sqlalchemy.ext.asyncio import AsyncSession
      from orchestrator.db.access.event_store_v2 import SqliteEventStore
      from orchestrator.workflow.events.types import WorkflowEvent


  class CreateRunCommand(BaseModel):
      run_id: str
      routine_id: str
      project_path: str
      repo_name: str
      status: RunStatus = RunStatus.DRAFT
      config: dict = Field(default_factory=dict)
      parent_run_id: str | None = None
      parent_task_id: str | None = None


  async def handle_create_run(
      cmd: CreateRunCommand,
      event_store: "SqliteEventStore",
      session: "AsyncSession",
  ) -> "list[WorkflowEvent]":
      event = RunCreated(
          run_id=cmd.run_id,
          routine_id=cmd.routine_id,
          project_path=cmd.project_path,
          repo_name=cmd.repo_name,
          status=cmd.status,
          config=cmd.config,
          parent_run_id=cmd.parent_run_id,
          parent_task_id=cmd.parent_task_id,
      )
      await event_store.append([event])
      return [event]


  class CreateTaskCommand(BaseModel):
      run_id: str
      task_id: str
      step_id: str
      step_index: int
      config_id: str
      title: str
      complexity: str | None = None
      order_index: int = 0
      max_attempts: int = 3
      checklist: list[dict] = Field(default_factory=list)
      parent_task_id: str | None = None


  async def handle_create_task(
      cmd: CreateTaskCommand,
      event_store: "SqliteEventStore",
      session: "AsyncSession",
  ) -> "list[WorkflowEvent]":
      event = TaskCreated(
          run_id=cmd.run_id,
          task_id=cmd.task_id,
          step_id=cmd.step_id,
          step_index=cmd.step_index,
          config_id=cmd.config_id,
          title=cmd.title,
          complexity=cmd.complexity,
          order_index=cmd.order_index,
          max_attempts=cmd.max_attempts,
          checklist=cmd.checklist,
          parent_task_id=cmd.parent_task_id,
      )
      await event_store.append([event])
      return [event]
  ```

**Dependencies**
- [ ] Task 3.1 must be complete (new event types must exist).
- [ ] Step 01 (`SqliteEventStore`) must be available.

**Constraints**
- [ ] No direct SQLAlchemy session writes in command handlers — event append is the only write;
  projectors (from Step 02) handle the read-model update.
- [ ] Use `TYPE_CHECKING` guards for `AsyncSession` and `SqliteEventStore` to avoid circular
  imports at module load time.
- [ ] `CreateRunCommand` must not embed domain objects (`RoutineConfig`, `Run`) — serialize to
  plain `dict` before constructing the command.

**Functionality (Expected Outcomes)**
- [ ] `handle_create_run` appends one `RunCreated` event and returns it.
- [ ] `handle_create_task` appends one `TaskCreated` event and returns it.
- [ ] Projector (from Step 02) handles `RunCreated` / `TaskCreated` and creates the corresponding
  read-model rows (verified in Task 3.9).

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pyright src/orchestrator/workflow/commands/run_lifecycle.py` — no errors.
- [ ] `from orchestrator.workflow.commands import CreateRunCommand, handle_create_run, CreateTaskCommand, handle_create_task` imports without error.

---

## Task 3.3: Status mutation command handlers

**Description**: Implement command models and handlers for status mutations:
`UpdateRunStatusCommand`, `UpdateTaskStatusCommand`, and `RewindStepIndexCommand`. These emit
existing event types (`RunStatusChanged`, `TaskStatusChanged`) plus the new `StepIndexRewound`.

**Implementation Plan (Do These Steps)**

- [ ] Create `src/orchestrator/workflow/commands/status_mutations.py`:

  ```python
  """Command handlers for run/task status transitions and step-index rewind."""
  from __future__ import annotations

  from typing import TYPE_CHECKING
  from pydantic import BaseModel

  from orchestrator.config.enums import RunStatus, TaskStatus
  from orchestrator.workflow.events import RunStatusChanged, TaskStatusChanged, StepIndexRewound

  if TYPE_CHECKING:
      from sqlalchemy.ext.asyncio import AsyncSession
      from orchestrator.db.access.event_store_v2 import SqliteEventStore
      from orchestrator.workflow.events.types import WorkflowEvent


  class UpdateRunStatusCommand(BaseModel):
      run_id: str
      old_status: RunStatus
      new_status: RunStatus
      pause_reason: str | None = None
      last_error: str | None = None


  async def handle_update_run_status(
      cmd: UpdateRunStatusCommand,
      event_store: "SqliteEventStore",
      session: "AsyncSession",
  ) -> "list[WorkflowEvent]":
      event = RunStatusChanged(
          run_id=cmd.run_id,
          old_status=cmd.old_status,
          new_status=cmd.new_status,
          pause_reason=cmd.pause_reason,
          last_error=cmd.last_error,
      )
      await event_store.append([event])
      return [event]


  class UpdateTaskStatusCommand(BaseModel):
      run_id: str
      task_id: str
      old_status: TaskStatus
      new_status: TaskStatus


  async def handle_update_task_status(
      cmd: UpdateTaskStatusCommand,
      event_store: "SqliteEventStore",
      session: "AsyncSession",
  ) -> "list[WorkflowEvent]":
      event = TaskStatusChanged(
          run_id=cmd.run_id,
          task_id=cmd.task_id,
          old_status=cmd.old_status,
          new_status=cmd.new_status,
      )
      await event_store.append([event])
      return [event]


  class RewindStepIndexCommand(BaseModel):
      run_id: str
      target_step_index: int


  async def handle_rewind_step_index(
      cmd: RewindStepIndexCommand,
      event_store: "SqliteEventStore",
      session: "AsyncSession",
  ) -> "list[WorkflowEvent]":
      event = StepIndexRewound(
          run_id=cmd.run_id,
          target_step_index=cmd.target_step_index,
      )
      await event_store.append([event])
      return [event]
  ```

- [ ] Re-export all six new symbols from `src/orchestrator/workflow/commands/__init__.py`.

**Dependencies**
- [ ] Task 3.1 (`StepIndexRewound` event) must be complete.
- [ ] Existing `RunStatusChanged` and `TaskStatusChanged` from Step 00.

**Constraints**
- [ ] The `old_status` field must be populated by the caller (read current state before invoking
  the command); the handler does not re-read state — it trusts the caller.
- [ ] No validation of the transition legality in this handler — the existing
  `InvalidTransitionError` raised by `WorkflowEngine` enforces legal transitions before the
  command is dispatched.

**Functionality (Expected Outcomes)**
- [ ] `handle_update_run_status` appends `RunStatusChanged`; projector updates the `runs` table.
- [ ] `handle_update_task_status` appends `TaskStatusChanged`; projector updates the `tasks` table.
- [ ] `handle_rewind_step_index` appends `StepIndexRewound`; projector updates
  `runs.current_step_index` when the event's target is lower than the current value.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pyright src/orchestrator/workflow/commands/status_mutations.py` — no errors.
- [ ] All six symbols importable from `orchestrator.workflow.commands`.

---

## Task 3.4: Attempt and fan-out mutation command handlers

**Description**: Implement command models and handlers for the remaining write operations:
`CreateTaskAttemptCommand`, `UpdateLatestAttemptCommand`, `UpdateParentOversightFactsCommand`,
`CreateFanOutChildrenCommand`, `ResetFanOutChildrenCommand`, and `RetryFanOutChildCommand`.

**Implementation Plan (Do These Steps)**

- [ ] Create `src/orchestrator/workflow/commands/attempt_and_fanout.py`:

  ```python
  """Command handlers for task attempts, oversight facts, and fan-out operations."""
  from __future__ import annotations

  from typing import TYPE_CHECKING, Any
  from pydantic import BaseModel, Field

  from orchestrator.config.enums import TaskStatus
  from orchestrator.workflow.events import (
      TaskAttemptCreated,
      AttemptUpdated,
      ParentOversightFactsUpdated,
      FanOutChildrenCreated,
      FanOutChildrenReset,
      FanOutChildRetried,
      StepIndexRewound,
  )

  if TYPE_CHECKING:
      from sqlalchemy.ext.asyncio import AsyncSession
      from orchestrator.db.access.event_store_v2 import SqliteEventStore
      from orchestrator.workflow.events.types import WorkflowEvent


  class CreateTaskAttemptCommand(BaseModel):
      run_id: str
      task_id: str
      attempt_id: str
      attempt_num: int
      runner_type: str | None = None
      agent_model: str | None = None
      new_task_status: TaskStatus = TaskStatus.BUILDING


  async def handle_create_task_attempt(
      cmd: CreateTaskAttemptCommand,
      event_store: "SqliteEventStore",
      session: "AsyncSession",
  ) -> "list[WorkflowEvent]":
      event = TaskAttemptCreated(
          run_id=cmd.run_id,
          task_id=cmd.task_id,
          attempt_id=cmd.attempt_id,
          attempt_num=cmd.attempt_num,
          runner_type=cmd.runner_type,
          agent_model=cmd.agent_model,
      )
      await event_store.append([event])
      return [event]


  class UpdateLatestAttemptCommand(BaseModel):
      run_id: str
      task_id: str
      attempt_id: str
      output_lines: list[str] | None = None
      error: str | None = None
      outcome: str | None = None
      completed_at: str | None = None
      tokens_read: int | None = None
      tokens_write: int | None = None
      tokens_cache: int | None = None
      duration_ms: int | None = None
      num_actions: int | None = None
      new_task_status: TaskStatus | None = None


  async def handle_update_latest_attempt(
      cmd: UpdateLatestAttemptCommand,
      event_store: "SqliteEventStore",
      session: "AsyncSession",
  ) -> "list[WorkflowEvent]":
      event = AttemptUpdated(
          run_id=cmd.run_id,
          task_id=cmd.task_id,
          attempt_id=cmd.attempt_id,
          output_lines=cmd.output_lines,
          error=cmd.error,
          outcome=cmd.outcome,
          completed_at=cmd.completed_at,
          tokens_read=cmd.tokens_read,
          tokens_write=cmd.tokens_write,
          tokens_cache=cmd.tokens_cache,
          duration_ms=cmd.duration_ms,
          num_actions=cmd.num_actions,
          new_task_status=cmd.new_task_status,
      )
      await event_store.append([event])
      return [event]


  class UpdateParentOversightFactsCommand(BaseModel):
      run_id: str
      patch: dict[str, Any] = Field(default_factory=dict)


  async def handle_update_parent_oversight_facts(
      cmd: UpdateParentOversightFactsCommand,
      event_store: "SqliteEventStore",
      session: "AsyncSession",
  ) -> "list[WorkflowEvent]":
      event = ParentOversightFactsUpdated(
          run_id=cmd.run_id,
          patch=cmd.patch,
      )
      await event_store.append([event])
      return [event]


  class CreateFanOutChildrenCommand(BaseModel):
      run_id: str
      step_id: str
      parent_task_id: str
      children: list[dict] = Field(default_factory=list)
      parent_new_status: TaskStatus | None = None


  async def handle_create_fan_out_children(
      cmd: CreateFanOutChildrenCommand,
      event_store: "SqliteEventStore",
      session: "AsyncSession",
  ) -> "list[WorkflowEvent]":
      event = FanOutChildrenCreated(
          run_id=cmd.run_id,
          step_id=cmd.step_id,
          parent_task_id=cmd.parent_task_id,
          children=cmd.children,
          parent_new_status=cmd.parent_new_status,
      )
      await event_store.append([event])
      return [event]


  class ResetFanOutChildrenCommand(BaseModel):
      run_id: str
      parent_task_id: str


  async def handle_reset_fan_out_children(
      cmd: ResetFanOutChildrenCommand,
      event_store: "SqliteEventStore",
      session: "AsyncSession",
  ) -> "list[WorkflowEvent]":
      event = FanOutChildrenReset(
          run_id=cmd.run_id,
          parent_task_id=cmd.parent_task_id,
      )
      await event_store.append([event])
      return [event]


  class RetryFanOutChildCommand(BaseModel):
      run_id: str
      child_task_id: str
      step_order_index: int


  async def handle_retry_fan_out_child(
      cmd: RetryFanOutChildCommand,
      event_store: "SqliteEventStore",
      session: "AsyncSession",
  ) -> "list[WorkflowEvent]":
      events: list[WorkflowEvent] = [
          FanOutChildRetried(
              run_id=cmd.run_id,
              child_task_id=cmd.child_task_id,
              step_order_index=cmd.step_order_index,
          ),
          StepIndexRewound(
              run_id=cmd.run_id,
              target_step_index=cmd.step_order_index,
          ),
      ]
      await event_store.append(events)
      return events
  ```

- [ ] Re-export all twelve new symbols from `src/orchestrator/workflow/commands/__init__.py`.

**Dependencies**
- [ ] Task 3.1 (all new event types) must be complete.

**Constraints**
- [ ] `UpdateParentOversightFactsCommand.patch` carries the already-sanitized patch dict (the
  merge logic that previously lived in `_merge_oversight_patch_locked` moves to the
  `ParentOversightFactsUpdated` projector handler in Step 02's `RunStateProjector` — confirm
  that projector is implemented before cutting over in Task 3.6).
- [ ] `RetryFanOutChildCommand` emits two events atomically (both or neither). The event store
  appends them as a batch under the same version sequence.

**Functionality (Expected Outcomes)**
- [ ] Each handler appends the correct event(s) and returns them.
- [ ] Projectors from Step 02 handle all eight new event types and update read-model tables
  accordingly.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pyright src/orchestrator/workflow/commands/attempt_and_fanout.py` — no errors.
- [ ] All twelve symbols importable from `orchestrator.workflow.commands`.

---

## Task 3.5: Wire WorkflowService — entity creation paths

**Description**: Update `WorkflowService` to call command handlers for the three entity-creation
write paths (`_repo.save()` on initial run creation, `_repo.create_task_attempt()`, and
initial task creation). The legacy `_repo.save()` call on update paths is addressed in Task 3.6.

**Implementation Plan (Do These Steps)**

- [ ] In `src/orchestrator/workflow/service.py`, inject `SqliteEventStore` alongside the existing
  `EventStore` parameter. The constructor already receives `session`; construct the store inside
  `WorkflowService.__init__` or accept it as an optional parameter mirroring `RunRepository`:

  ```python
  from orchestrator.db.access.event_store_v2 import SqliteEventStore

  class WorkflowService:
      def __init__(self, session, ..., event_store_v2: SqliteEventStore | None = None):
          ...
          self._event_store_v2 = event_store_v2 or SqliteEventStore(session)
  ```

- [ ] Replace the initial `_repo.save(run)` call (the path that creates a brand-new run record)
  with a call to `handle_create_run`. Identify this call by the context where a `Run` object is
  first built and persisted — typically inside `start_run()` or `create_run()`. Extract the
  `CreateRunCommand` fields from the `Run` object before the save:

  ```python
  from orchestrator.workflow.commands import CreateRunCommand, handle_create_run

  cmd = CreateRunCommand(
      run_id=run.id,
      routine_id=run.routine_id,
      project_path=str(run.project_path),
      repo_name=run.repo_name,
      status=run.status,
      config=run.config.model_dump() if run.config else {},
      parent_run_id=run.parent_run_id,
      parent_task_id=run.parent_task_id,
  )
  await handle_create_run(cmd, self._event_store_v2, self._session)
  # Remove the old: await self._repo.save(run)
  ```

- [ ] Replace `_repo.create_task_attempt(task_id, attempt, status=TaskStatus.BUILDING)` (line
  ~1602) with `handle_create_task_attempt`:

  ```python
  from orchestrator.workflow.commands import CreateTaskAttemptCommand, handle_create_task_attempt

  cmd = CreateTaskAttemptCommand(
      run_id=run_id,
      task_id=task_id,
      attempt_id=attempt.id,
      attempt_num=attempt.attempt_num,
      runner_type=attempt.agent_runner_type.value if attempt.agent_runner_type else None,
      agent_model=attempt.agent_model,
      new_task_status=TaskStatus.BUILDING,
  )
  await handle_create_task_attempt(cmd, self._event_store_v2, self._session)
  ```

- [ ] Update `src/orchestrator/api/deps.py` — pass `SqliteEventStore` when constructing
  `WorkflowService` so it uses the session-bound store (follow the pattern established in
  Task 1.4's `get_event_store_v2`).

**Dependencies**
- [ ] Tasks 3.2 and 3.3 must be complete (handlers must exist).
- [ ] Step 02 projectors must handle `RunCreated` and `TaskAttemptCreated` events.

**Constraints**
- [ ] Do not remove `_repo.save()` from update paths yet — that is Task 3.6.
- [ ] `WorkflowEngine` must not receive `SqliteEventStore`; only `WorkflowService` (the I/O
  boundary) holds a reference to the store.
- [ ] Keep the existing `PersistentEventEmitter` wiring untouched — it handles
  `AgentOutputEvent` and other engine-emitted events; command handlers add a parallel write
  path for state mutations.

**Functionality (Expected Outcomes)**
- [ ] Creating a new run via the API results in a `RunCreated` event in `events_v2`.
- [ ] Starting a task attempt results in a `TaskAttemptCreated` event in `events_v2`.
- [ ] `uv run pytest` full suite passes (no regressions from the partial wiring).

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pytest` — full suite passes.
- [ ] `uv run pyright src/orchestrator/workflow/service.py` — no new type errors.
- [ ] After creating a run in an integration test, `SqliteEventStore.get_stream(run_id)` returns
  a `RunCreated` event as the first event.

---

## Task 3.6: Wire WorkflowService — mutation paths

**Description**: Replace the remaining `RunRepository` write calls in `WorkflowService` with
command handler invocations. After this task, `WorkflowService` no longer calls any repository
write methods.

**Implementation Plan (Do These Steps)**

- [ ] Replace `_repo.update_run_status(run_id, status, pause_reason=...)` calls with
  `handle_update_run_status`. Pass the current status as `old_status` (read from the projection
  immediately before the call using `_repo.get(run_id)`). Affected call sites: lines ~861–874
  pattern in service.py; search with `grep -n "update_run_status" src/orchestrator/workflow/service.py`.

- [ ] Replace `_repo.update_task_status(task_id, status)` calls with `handle_update_task_status`.
  Read the current task status from the task model before replacing. Affected call sites: lines
  ~1205, ~1552 in service.py.

- [ ] Replace `_repo.rewind_step_index_if_needed(run_id, target)` (line ~1474) with
  `handle_rewind_step_index`. The guard logic (`if current_step_index > target`) moves into the
  `StepIndexRewound` projector handler rather than the command; the command always emits the event
  and the projector applies it conditionally.

- [ ] Replace `_repo.update_parent_oversight_facts(run_id, patch)` (line ~303) with
  `handle_update_parent_oversight_facts`. The `_merge_oversight_patch_locked` logic (append-only
  list merging) moves to the `RunStateProjector.handle(ParentOversightFactsUpdated)` in Step 02.
  Confirm the projector handles the merge correctly before cutting this over.

- [ ] Replace `_repo.update_latest_attempt(task_id, ...)` (line ~1654) with
  `handle_update_latest_attempt`. Map the keyword arguments to `UpdateLatestAttemptCommand`
  fields; `_UNSET` sentinel values translate to `None` (no change).

- [ ] Replace `_repo.create_fan_out_children(step_id, children, parent_status=...)` (line ~1199)
  with `handle_create_fan_out_children`. Serialize each `TaskState` child to a `dict` for the
  `children` field.

- [ ] Replace `_repo.reset_fan_out_children(parent_task_id)` (line ~1445) with
  `handle_reset_fan_out_children`.

- [ ] Replace the `_repo.retry_fan_out_child(child_task_id)` + `_repo.rewind_step_index_if_needed`
  pair (lines ~1470–1474) with a single `handle_retry_fan_out_child` call (which emits both
  events atomically).

- [ ] Replace all remaining `_repo.save(run)` calls (the update paths, not the creation path
  handled in Task 3.5) with the appropriate targeted command handler. The `save()` pattern updates
  a `Run` domain object in memory then merges it — map each distinct `save()` context to the
  correct specific event (e.g., a `save()` that only changes `pause_reason` → `UpdateRunStatusCommand`).

**Dependencies**
- [ ] Tasks 3.3 and 3.4 (all command handlers) must be complete.
- [ ] Step 02 projectors must handle all the new event types emitted by these handlers.

**Constraints**
- [ ] After this task, `grep -r "_repo\.save\|_repo\.update_\|_repo\.create_\|_repo\.reset_\|_repo\.retry_\|_repo\.rewind_" src/orchestrator/workflow/service.py` must return no matches.
- [ ] Read-before-write (loading current state to pass `old_status`) uses `_repo.get()` — that
  read method remains; only write methods are eliminated.

**Functionality (Expected Outcomes)**
- [ ] All status changes, attempt updates, and fan-out operations produce events in `events_v2`.
- [ ] Projectors maintain read-model table state correctly for all mutation types.
- [ ] `uv run pytest` full suite passes.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `grep -rn "_repo\.save\|_repo\.update_\|_repo\.create_task_attempt\|_repo\.create_fan\|_repo\.reset_\|_repo\.retry_\|_repo\.rewind_" src/orchestrator/workflow/service.py` — returns no matches.
- [ ] `uv run pytest` — full suite passes.
- [ ] `uv run pyright src/orchestrator/workflow/service.py` — no new type errors.

---

## Task 3.7: Remove write methods from RunRepository

**Description**: Delete all write methods from `RunRepository`, making it a pure read-only query
layer. Pyright validates that no callers reference the removed methods.

**Implementation Plan (Do These Steps)**

- [ ] In `src/orchestrator/db/access/repositories.py`, delete the following methods from
  `RunRepository` (confirm each is unreferenced after Task 3.6):
  - `save(run)` — full-run upsert
  - `update_parent_oversight_facts(run_id, patch)` and `_merge_oversight_patch_locked(...)`
  - `create_task_attempt(task_id, attempt, status)`
  - `create_fan_out_children(step_id, children, parent_status)`
  - `update_task_status(task_id, status)`
  - `rewind_step_index_if_needed(run_id, target_step_index)`
  - `update_run_status(run_id, status, pause_reason)`
  - `reset_fan_out_children(parent_task_id)`
  - `retry_fan_out_child(child_task_id)` and `update_latest_attempt(task_id, ...)`
  - `delete(run_id)` — if deletion is now handled via an event (add `RunDeleted` event if
    needed, or retain `delete` if it remains a non-event operation; document the decision).

- [ ] Remove any imports that are only used by the deleted methods (check `APPEND_ONLY_OVERSIGHT_LIST_KEYS`, `_UNSET` sentinel, `ModelTokenUsage` if unused elsewhere).

- [ ] Update `src/orchestrator/db/__init__.py` if any of the removed methods were re-exported.

- [ ] Add a docstring to `RunRepository` class: `"""Read-only query layer for run state. All mutations occur via command handlers in workflow/commands/."""`

**Dependencies**
- [ ] Task 3.6 must be complete (all callers replaced with command handlers).

**Constraints**
- [ ] Do not remove read methods: `get`, `lock_run_for_coordination`, `list_all`, `list_by_repo`,
  `list_by_status`, `list_child_runs`, `list_by_repo_and_status`, `list_recent`, `list_repo_names`,
  `get_task_model`, `count_fan_out_children`.
- [ ] If `delete(run_id)` is used by a non-service caller (e.g., a test fixture), retain it or
  replace with a `RunDeleted` event — document the decision inline.

**Functionality (Expected Outcomes)**
- [ ] `RunRepository` has no methods that write to the database.
- [ ] `uv run pyright src/orchestrator/db/access/repositories.py` — no errors.
- [ ] `uv run pytest` — full suite passes.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `grep -n "async def save\|async def update_\|async def create_task_attempt\|async def create_fan\|async def reset_\|async def retry_\|async def rewind_\|_merge_oversight" src/orchestrator/db/access/repositories.py` — returns no matches for `RunRepository`'s write methods.
- [ ] `uv run pyright src/orchestrator/db/access/repositories.py` — no errors.
- [ ] `uv run pytest` — full suite passes.

---

## Task 3.8: Unit tests for command handlers

**Description**: Write focused unit tests for each command handler. Tests use a real in-memory
`SqliteEventStore` (with in-memory SQLite) and assert both the events emitted and the read-model
state after the projectors run.

**Implementation Plan (Do These Steps)**

- [ ] Create `tests/unit/test_command_handlers.py`:

  - **Fixture**: `async_session` — in-memory SQLite with `events_v2` and read-model tables
    created via `Base.metadata.create_all`. Initialize `SqliteEventStore` and `ProjectionRegistry`
    (from Step 02) bound to the session.

  - **`test_handle_create_run`**: Call `handle_create_run` with a `CreateRunCommand`. Assert:
    - One `RunCreated` event returned.
    - `SqliteEventStore.get_stream(run_id)` returns the event.
    - Run row exists in `runs` table with correct `status` and `routine_id`.

  - **`test_handle_create_task`**: Call `handle_create_task`. Assert `TaskCreated` event in store
    and task row in `tasks` table.

  - **`test_handle_update_run_status`**: Call `handle_update_run_status`. Assert `RunStatusChanged`
    event and `runs.status` updated.

  - **`test_handle_update_task_status`**: Assert `TaskStatusChanged` event and `tasks.status`
    updated.

  - **`test_handle_rewind_step_index_no_op_when_lower`**: Call `handle_rewind_step_index` with a
    target higher than current. Assert event emitted but `runs.current_step_index` unchanged
    (projector applies the conditional guard).

  - **`test_handle_create_task_attempt`**: Assert `TaskAttemptCreated` event and new attempt row.

  - **`test_handle_update_latest_attempt_output_lines`**: Call with `output_lines=["line1"]`.
    Assert `AttemptUpdated` event and attempt row's `agent_output` contains the line.

  - **`test_handle_update_parent_oversight_facts`**: Call with a patch dict. Assert
    `ParentOversightFactsUpdated` event and run's `oversight_state` contains the patched key.

  - **`test_handle_create_fan_out_children`**: Assert `FanOutChildrenCreated` event and child
    task rows created.

  - **`test_handle_reset_fan_out_children`**: Set up children in various statuses. Assert
    `FanOutChildrenReset` event and non-completed children are `PENDING`.

  - **`test_handle_retry_fan_out_child`**: Assert both `FanOutChildRetried` and `StepIndexRewound`
    events emitted atomically (both appear in one `get_stream` call).

  - **`test_invalid_status_transition_raises`**: Attempt a logically invalid transition where the
    engine guard would reject it (simulated by constructing the command with invalid old/new
    combination) — verify that the projector does not corrupt state if an invalid event somehow
    arrives.

**Dependencies**
- [ ] Tasks 3.1–3.4 (all command handlers and event types) must be complete.
- [ ] Step 02 projectors must be wired into the `ProjectionRegistry` used in the fixture.

**Constraints**
- [ ] No mocking of SQLAlchemy — use real in-memory SQLite.
- [ ] All tests must be runnable in isolation: `uv run pytest tests/unit/test_command_handlers.py -v`.
- [ ] `pytest-asyncio` in `asyncio` mode (confirm `asyncio_mode` setting in `pyproject.toml`).

**Functionality (Expected Outcomes)**
- [ ] All test functions collected and passing.
- [ ] Each test asserts both the event in the store and the resulting read-model state.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pytest tests/unit/test_command_handlers.py -v` — all pass, none skipped.
- [ ] `uv run pytest tests/unit/test_command_handlers.py --collect-only` — shows at least 12 test items.
- [ ] `uv run pytest` — full suite passes.

---

## Task 3.9: Integration test and empty-DB rebuild test

**Description**: Write two integration tests. The first covers the full API → command → event →
projection → API round-trip. The second validates empty-DB rebuild: emit all creation events,
clear read-model tables, run `rebuild-projections`, and assert that API responses are identical
to the pre-clear state.

**Implementation Plan (Do These Steps)**

- [ ] Create `tests/integration/test_event_sourced_workflow.py`:

  - **`test_full_workflow_round_trip`**:
    1. Call the run-creation API endpoint.
    2. Assert the API returns a run with the correct `status`.
    3. Query `SqliteEventStore.get_stream(run_id)` directly; assert `RunCreated` is the first
       event and subsequent status-change events are present.
    4. Call the run-detail API endpoint; assert response matches the projection state.

  - **`test_empty_db_rebuild`**:
    1. Use `handle_create_run`, `handle_create_task`, and a status-change command to build a
       representative event log in `events_v2`.
    2. Capture the current API response for the run (serialized to dict).
    3. Truncate the `runs` and `tasks` read-model tables directly via SQL.
    4. Call `ProjectionRegistry.rebuild_all(event_store)` (the same operation as the CLI
       `rebuild-projections` command from Step 02).
    5. Re-fetch the API response; assert it matches the pre-truncation snapshot field-by-field.

  - **`test_parity_run_status_update`**:
    - Emit `UpdateRunStatusCommand` and assert both `events_v2` contains the event and
      `GET /api/runs/{run_id}` returns the updated status. This is a parity test confirming
      the projection and the API agree — remove in Step 05 when legacy write paths are deleted.

**Dependencies**
- [ ] Tasks 3.1–3.8 must be complete.
- [ ] Step 02 `rebuild-projections` CLI (or `ProjectionRegistry.rebuild_all`) must exist.

**Constraints**
- [ ] Integration tests must use the same DB setup as existing integration tests in `tests/integration/`.
- [ ] Do not test implementation details of the event store (that is covered in Task 3.8 unit
  tests) — test observable API behavior.

**Functionality (Expected Outcomes)**
- [ ] Full round-trip test passes: creating a run via API produces correct API response and correct
  `events_v2` entries.
- [ ] Empty-DB rebuild test passes: after clearing read-model tables and replaying events, API
  responses are identical.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `uv run pytest tests/integration/test_event_sourced_workflow.py -v` — all pass.
- [ ] `uv run pytest` — full suite passes with no regressions.
- [ ] `uv run pyright src/orchestrator/workflow/commands/ src/orchestrator/db/access/repositories.py` — no type errors.
