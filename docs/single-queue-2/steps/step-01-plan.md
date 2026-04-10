# Step 1: Schema and State Machine

Lay the data foundation for the single-queue signal model without changing any
runtime behavior. This step restructures the `pending_signals` table (integer PK,
delivery-tracking columns), adds the `STOPPING` run state with transition guards,
and defines the `RUN_START` signal type. No consumer or sender rewiring happens
here — existing behavior is preserved throughout.

## Intent Verification
**Original Intent**: [I-07], [I-08], [I-09], [I-16], [I-22], [I-26], [I-35] — Integer
PK for FIFO ordering, `delivered_at`/`handled_at` delivery tracking columns,
`STOPPING` state with valid transitions, `RUN_START` signal type definition.

**Functionality to Produce**:
- Alembic migration in `src/orchestrator/db/migrations/versions/` that replaces
  UUID string PK with `INTEGER PRIMARY KEY AUTOINCREMENT`, renames `processed_at`
  to `handled_at`, and adds `delivered_at TIMESTAMP NULL`
- `PendingSignalModel` in `src/orchestrator/db/orm/models.py` updated to match
  the new schema (`id: int`, `handled_at`, `delivered_at`)
- `PendingSignal` dataclass in `signals.py` updated (`id: int`, `handled_at`,
  `delivered_at`); drain query uses `ORDER BY id` instead of `ORDER BY created_at`
- `RunStatus.STOPPING = "stopping"` in `src/orchestrator/config/enums.py`
- Engine guards in `src/orchestrator/workflow/engine/engine.py`:
  - `ACTIVE → STOPPING` is a valid new transition (used by consumer in later steps)
  - `STOPPING → PAUSED` and `STOPPING → FAILED` are valid transitions
  - `cancel_run()`, `pause_run()`, `resume_run()`, `start_run()` reject STOPPING runs
  - `start_task()` and `submit_for_verification()` reject STOPPING runs
- API guards in `src/orchestrator/api/routers/runs.py`: resume, cancel, pause,
  start on a STOPPING run return 409
- `WorkflowSignal.RUN_START = "run_start"` defined in `signals.py` (no handler wiring)
- Unit tests in `tests/unit/test_stopping_state.py` covering all valid/invalid
  STOPPING transitions and API 409 behavior

**Final Verification Criteria**:
- `uv run alembic upgrade head` applies cleanly on a fresh DB
- `uv run alembic downgrade -1` then `uv run alembic upgrade head` round-trips cleanly
- `grep -r "ORDER BY.*created_at" src/orchestrator/workflow/signals/` returns no hits
- All existing backend tests pass: `uv run pytest tests/ -x -q --tb=short`
- `tests/unit/test_stopping_state.py` passes with tests for every valid and invalid
  STOPPING transition

---

## Task 1: Alembic Migration — Restructure `pending_signals` Table

**Description**:
Create an Alembic migration that drops and recreates the `pending_signals` table
with an integer autoincrement PK, renamed `handled_at` column (was `processed_at`),
and new `delivered_at` column. The migration assumes a clean server stop with no
pending signals (decided in clarifications), so drop-and-recreate is safe and avoids
all SQLite constraint-name hazards.

**Implementation Plan (Do These Steps)**

The existing `pending_signals` table was created by migration `h1a2b3c4d5e6`.
We need a new migration that succeeds it in the chain. The migration drops the
existing table and index, then creates a new one with the revised schema. This is
simpler and more reliable than column-level `batch_alter_table` operations when
changing the PK type in SQLite.

- [ ] Determine the current Alembic head revision by running:
  ```bash
  cd /Users/peter/code/task-world && uv run alembic --config src/orchestrator/db/migrations/alembic.ini current 2>/dev/null || uv run alembic heads
  ```
  Note the revision ID — that becomes `down_revision` for the new migration.

- [ ] Create `src/orchestrator/db/migrations/versions/m1a2b3c4d5e6_restructure_pending_signals.py`:
  ```python
  """Restructure pending_signals: integer PK, delivered_at, rename processed_at->handled_at

  Revision ID: m1a2b3c4d5e6
  Revises: <CURRENT_HEAD_REVISION>
  Create Date: 2026-03-27 00:00:00.000000

  Drops and recreates pending_signals with:
  - INTEGER PRIMARY KEY AUTOINCREMENT (was UUID string) for FIFO ordering
  - handled_at column (renamed from processed_at) — set after handler succeeds
  - delivered_at column (new) — set before handler invocation, enables crash recovery

  Assumes clean server stop with no pending signals at migration time.
  """

  from typing import Sequence, Union

  import sqlalchemy as sa
  from alembic import op

  revision: str = "m1a2b3c4d5e6"  # pragma: allowlist secret
  down_revision: Union[str, Sequence[str], None] = "<CURRENT_HEAD_REVISION>"  # pragma: allowlist secret
  branch_labels: Union[str, Sequence[str], None] = None
  depends_on: Union[str, Sequence[str], None] = None


  def upgrade() -> None:
      """Drop and recreate pending_signals with integer PK and delivery tracking."""
      op.drop_index("ix_pending_signals_run_id", table_name="pending_signals")
      op.drop_table("pending_signals")

      op.create_table(
          "pending_signals",
          sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
          sa.Column(
              "run_id",
              sa.String(),
              sa.ForeignKey("runs.id", ondelete="CASCADE"),
              nullable=False,
          ),
          sa.Column("signal_type", sa.String(), nullable=False),
          sa.Column("payload", sa.Text(), nullable=True),
          sa.Column("created_at", sa.DateTime(), nullable=False),
          sa.Column("delivered_at", sa.DateTime(), nullable=True),
          sa.Column("handled_at", sa.DateTime(), nullable=True),
      )
      op.create_index(
          "ix_pending_signals_run_id",
          "pending_signals",
          ["run_id"],
      )


  def downgrade() -> None:
      """Restore pending_signals to original UUID PK schema."""
      op.drop_index("ix_pending_signals_run_id", table_name="pending_signals")
      op.drop_table("pending_signals")

      op.create_table(
          "pending_signals",
          sa.Column("id", sa.String(), nullable=False),
          sa.Column(
              "run_id",
              sa.String(),
              sa.ForeignKey("runs.id", ondelete="CASCADE"),
              nullable=False,
          ),
          sa.Column("signal_type", sa.String(), nullable=False),
          sa.Column("payload", sa.Text(), nullable=True),
          sa.Column("created_at", sa.DateTime(), nullable=False),
          sa.Column("processed_at", sa.DateTime(), nullable=True),
          sa.PrimaryKeyConstraint("id"),
      )
      op.create_index(
          "ix_pending_signals_run_id",
          "pending_signals",
          ["run_id"],
      )
  ```
  Replace `<CURRENT_HEAD_REVISION>` with the revision ID found in the first step.

- [ ] Verify the migration applies and round-trips:
  ```bash
  cd /Users/peter/code/task-world && uv run alembic --config src/orchestrator/db/migrations/alembic.ini upgrade head
  uv run alembic --config src/orchestrator/db/migrations/alembic.ini downgrade -1
  uv run alembic --config src/orchestrator/db/migrations/alembic.ini upgrade head
  ```

**References**
- Existing migration as structural reference: `src/orchestrator/db/migrations/versions/h1a2b3c4d5e6_add_pending_signals_table.py`
- Alembic config: `src/orchestrator/db/migrations/alembic.ini`

**Constraints**
- Do NOT use hard-coded SQLite auto-generated constraint names.
- Do NOT use `batch_alter_table` for PK type changes — drop-and-recreate is more reliable.
- The migration file MUST go in `src/orchestrator/db/migrations/versions/`, not `alembic/versions/`.

**Functionality (Expected Outcomes)**
- [ ] New migration file exists in `src/orchestrator/db/migrations/versions/`
- [ ] `pending_signals` table has `id INTEGER PRIMARY KEY AUTOINCREMENT`, `delivered_at`, and `handled_at`
- [ ] `processed_at` column no longer exists after upgrade
- [ ] Downgrade restores the original UUID PK schema

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run alembic upgrade head` exits 0 with no errors
- [ ] `uv run alembic downgrade -1 && uv run alembic upgrade head` exits 0 (round-trip)
- [ ] Run `uv run python -c "from orchestrator.db import PendingSignalModel"` — no import errors (model not yet updated, but migration applies cleanly)

---

## Task 2: Update `PendingSignalModel` and `PendingSignal` Dataclass

**Description**:
Sync the SQLAlchemy ORM model and the `PendingSignal` dataclass with the new
schema. Change the `id` field from `str` (UUID) to `int`, replace `processed_at`
with `handled_at`, and add `delivered_at`. Also update `DbSignalTransport.enqueue()`
and `drain()` to work with the new types, and fix `ORDER BY` to use `id` instead
of `created_at`.

**Implementation Plan (Do These Steps)**

Two files change: `src/orchestrator/db/orm/models.py` (ORM model) and
`src/orchestrator/workflow/signals/signals.py` (dataclass + transport).

- [ ] In `src/orchestrator/db/orm/models.py`, update `PendingSignalModel`:
  ```python
  class PendingSignalModel(Base):
      __tablename__ = "pending_signals"
      __table_args__ = (
          Index("ix_pending_signals_run_id", "run_id"),
      )

      id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
      run_id: Mapped[str] = mapped_column(
          String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
      )
      signal_type: Mapped[str] = mapped_column(String, nullable=False)
      payload: Mapped[str | None] = mapped_column(Text, nullable=True)
      created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
      delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
      handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
  ```
  Verify `Integer` is already imported in that file (it is, used by `ReplayCheckpointModel`).

- [ ] In `src/orchestrator/workflow/signals/signals.py`, update the `PendingSignal` dataclass:
  ```python
  @dataclass
  class PendingSignal:
      """A signal pending consumption by a RunWorkflow."""

      id: int
      run_id: str
      signal_type: WorkflowSignal
      payload: dict[str, Any] | None
      created_at: datetime
      delivered_at: datetime | None = field(default=None)
      handled_at: datetime | None = field(default=None)
  ```

- [ ] In `DbSignalTransport.enqueue()`, update the model construction (no longer
  sets `id` explicitly — it's autoincrement; also `processed_at` → `handled_at`):
  ```python
  async def enqueue(
      self,
      run_id: str,
      signal_type: WorkflowSignal,
      payload: dict[str, Any] | None = None,
  ) -> PendingSignal:
      from orchestrator.db import PendingSignalModel

      now = datetime.now(timezone.utc)
      model = PendingSignalModel(
          run_id=run_id,
          signal_type=signal_type.value,
          payload=json.dumps(payload) if payload is not None else None,
          created_at=now,
          delivered_at=None,
          handled_at=None,
      )
      self._session.add(model)
      await self._session.flush()
      return PendingSignal(
          id=model.id,
          run_id=run_id,
          signal_type=signal_type,
          payload=payload,
          created_at=now,
          delivered_at=None,
          handled_at=None,
      )
  ```
  Remove the `signal_id = str(uuid.uuid4())` line and the `uuid` import if it's
  no longer used elsewhere in the file.

- [ ] In `DbSignalTransport.drain()`, change `ORDER BY` and field references:
  ```python
  async def drain(self, run_id: str) -> list[PendingSignal]:
      from sqlalchemy import select

      from orchestrator.db import PendingSignalModel

      now = datetime.now(timezone.utc)
      stmt = (
          select(PendingSignalModel)
          .where(
              PendingSignalModel.run_id == run_id,
              PendingSignalModel.handled_at.is_(None),
          )
          .order_by(PendingSignalModel.id)  # integer PK guarantees insertion order
      )
      result = await self._session.execute(stmt)
      models = list(result.scalars().all())

      signals: list[PendingSignal] = []
      for model in models:
          model.handled_at = now
          payload = json.loads(model.payload) if model.payload is not None else None
          signals.append(
              PendingSignal(
                  id=model.id,
                  run_id=model.run_id,
                  signal_type=WorkflowSignal(model.signal_type),
                  payload=payload,
                  created_at=model.created_at,
                  delivered_at=model.delivered_at,
                  handled_at=now,
              )
          )

      if models:
          await self._session.flush()

      return signals
  ```

- [ ] Update `InMemorySignalTransport` to match: `id` should be an auto-incrementing
  integer. Add a counter `self._next_id: int = 1` and assign `id=self._next_id` then
  increment. Replace `processed_at` with `handled_at` in the drain logic.

- [ ] Run tests to confirm nothing is broken:
  ```bash
  cd /Users/peter/code/task-world && uv run pytest tests/ -x -q --tb=short -k "signal"
  ```

**Dependencies**
- [ ] Task 1 (migration) must be applied before this task's tests run, so the DB schema matches the model.

**Constraints**
- Do NOT change the `SignalQueue` public interface — callers must not need updating.
- Do NOT remove `created_at` from the model or dataclass — it remains as an audit field.

**Side Effects**
- Any test that constructs a `PendingSignal` directly with `id=str(...)` will need updating.
  Search: `grep -rn "PendingSignal(" tests/` to find these.

**Functionality (Expected Outcomes)**
- [ ] `PendingSignalModel.id` is `Mapped[int]` (autoincrement)
- [ ] `PendingSignalModel` has `delivered_at` and `handled_at`; no `processed_at`
- [ ] `PendingSignal` dataclass has `id: int`, `delivered_at`, `handled_at`; no `processed_at`
- [ ] `drain()` filters by `handled_at IS NULL` and orders by `id`
- [ ] `uuid` import removed from `signals.py` if no longer needed

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "ORDER BY.*created_at" src/orchestrator/workflow/signals/` returns no hits
- [ ] `grep -r "processed_at" src/orchestrator/workflow/signals/ src/orchestrator/db/orm/models.py` returns no hits
- [ ] `uv run pytest tests/ -x -q --tb=short` passes (all existing tests)

---

## Task 3: Add `RunStatus.STOPPING` and `WorkflowSignal.RUN_START`

**Description**:
Add two new enum values — `RunStatus.STOPPING` in `config/enums.py` and
`WorkflowSignal.RUN_START` in `signals.py`. No handler wiring or state machine
guards yet (those are in Tasks 4 and 5). This task only adds the type definitions.

**Implementation Plan (Do These Steps)**

Both changes are small additions to existing enums. Keep them together because
they are both pure type-definition additions with no behavioral impact.

- [ ] In `src/orchestrator/config/enums.py`, add `STOPPING` to `RunStatus`:
  ```python
  class RunStatus(str, Enum):
      DRAFT = "draft"
      ACTIVE = "active"
      STOPPING = "stopping"
      PAUSED = "paused"
      COMPLETED = "completed"
      FAILED = "failed"
  ```

- [ ] In `src/orchestrator/workflow/signals/signals.py`, add `RUN_START` to
  `WorkflowSignal`:
  ```python
  class WorkflowSignal(enum.Enum):
      """Control signals that can be sent to an active RunWorkflow."""

      RUN_START = "run_start"
      PAUSE = "pause"
      RESUME = "resume"
      CANCEL = "cancel"
      ACTIVITY_COMPLETED = "activity_completed"
      ACTIVITY_VERIFIED = "activity_verified"
  ```

- [ ] Verify no existing test breaks by running:
  ```bash
  cd /Users/peter/code/task-world && uv run pytest tests/ -x -q --tb=short
  ```

**Constraints**
- No handler wiring for `RUN_START` in this task — just the enum value.
- No state machine guards for `STOPPING` in this task — just the enum value.

**Functionality (Expected Outcomes)**
- [ ] `RunStatus.STOPPING` exists and has value `"stopping"`
- [ ] `WorkflowSignal.RUN_START` exists and has value `"run_start"`
- [ ] Both can be imported and serialized without error

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.config.enums import RunStatus; assert RunStatus.STOPPING.value == 'stopping'"` exits 0
- [ ] `uv run python -c "from orchestrator.workflow.signals.signals import WorkflowSignal; assert WorkflowSignal.RUN_START.value == 'run_start'"` exits 0
- [ ] `uv run pytest tests/ -x -q --tb=short` passes

---

## Task 4: Engine State Machine Guards for `STOPPING`

**Description**:
Add transition guards in `src/orchestrator/workflow/engine/engine.py` so that
`STOPPING` behaves correctly in the state machine. Specifically: add a
`transition_to_stopping()` method (used by the consumer in later steps), update
`cancel_run()` / `pause_run()` / `resume_run()` to reject STOPPING runs, and add
guards in `start_task()` / `submit_for_verification()`.

**Implementation Plan (Do These Steps)**

The engine currently handles ACTIVE/PAUSED/DRAFT states. We need to add STOPPING
as a valid intermediate state between ACTIVE and PAUSED/FAILED.

- [ ] In `src/orchestrator/workflow/engine/engine.py`, add `transition_to_stopping()`:
  ```python
  def transition_to_stopping(self, run_id: str) -> Run:
      """Transition a run from ACTIVE to STOPPING.

      Called by the consumer when a PAUSE or CANCEL signal is received for
      an active run. The consumer will complete the transition to PAUSED or
      FAILED after the RunWorkflow acknowledges.
      """
      run = self._state.get_run(run_id)
      if run.status != RunStatus.ACTIVE:
          raise InvalidTransitionError(run.status.value, RunStatus.STOPPING.value)

      old_status = run.status
      run.status = RunStatus.STOPPING
      self._state.update_run(run)

      self._emitter.emit(
          RunStatusChanged(
              timestamp=self._clock.now(),
              run_id=run_id,
              event_type="run_status_changed",
              old_status=old_status,
              new_status=RunStatus.STOPPING,
          )
      )
      return run
  ```

- [ ] Update `cancel_run()` to reject STOPPING runs (add `RunStatus.STOPPING` as
  an invalid source state):
  ```python
  def cancel_run(self, run_id: str, reason: str | None = None) -> Run:
      """Cancel a run - move from ACTIVE/PAUSED to FAILED."""
      run = self._state.get_run(run_id)
      cancellable = (RunStatus.ACTIVE, RunStatus.PAUSED)
      if run.status not in cancellable:
          raise InvalidTransitionError(run.status.value, RunStatus.FAILED.value)
      # ... rest unchanged
  ```
  The existing code already only allows ACTIVE/PAUSED, so STOPPING is already
  rejected. Verify this is the case; no change needed if so.

- [ ] Update `pause_run()` to reject STOPPING (add a check before the idempotent
  PAUSED check):
  ```python
  def pause_run(self, run_id: str, reason: str = "manual_pause", error_detail: str | None = None) -> Run:
      """Pause a run - move from ACTIVE to PAUSED. Idempotent if already PAUSED."""
      run = self._state.get_run(run_id)
      if run.status == RunStatus.PAUSED:
          return run
      if run.status == RunStatus.STOPPING:
          raise InvalidTransitionError(run.status.value, RunStatus.PAUSED.value)
      if run.status != RunStatus.ACTIVE:
          raise InvalidTransitionError(run.status.value, RunStatus.PAUSED.value)
      # ... rest unchanged
  ```

- [ ] Update `resume_run()` — the existing check `if run.status != RunStatus.PAUSED`
  already rejects STOPPING. Verify and leave as-is.

- [ ] Add `start_task()` guard for STOPPING. **NOTE (FM-4A):** `start_task()` has NO
  existing run-status check. Read the method first (around line 253 in `engine.py`) to
  confirm there is no status guard, then add one as NEW code after
  `run = self._state.get_run(run_id)`:
  ```python
  # In start_task(), after loading the run — ADD THIS NEW GUARD (does not exist yet):
  if run.status in (RunStatus.PAUSED, RunStatus.STOPPING, RunStatus.COMPLETED, RunStatus.FAILED):
      raise InvalidTransitionError(
          run.status.value, f"start_task (run must be ACTIVE, got {run.status.value})"
      )
  ```
  This is a **new guard added from scratch**, not a modification to an existing one.

- [ ] Add `submit_for_verification()` guard for STOPPING. **NOTE (FM-4B):**
  `submit_for_verification()` has NO existing run-status check. Read the method first
  (around line 327) to confirm, then add a NEW guard after loading the task. This
  requires adding a `get_run()` call that does not currently exist in the method:
  ```python
  # In submit_for_verification(), after get_task() call — ADD THIS NEW GUARD:
  run = self._state.get_run(run_id)
  if run.status == RunStatus.STOPPING:
      raise InvalidTransitionError(run.status.value, "submit_for_verification")
  ```
  This is **new code from scratch** — `get_run()` is not currently called here.

- [ ] Run tests:
  ```bash
  cd /Users/peter/code/task-world && uv run pytest tests/unit/test_workflow_engine.py tests/unit/test_task_transitions.py -x -q --tb=short
  ```

**References**
- Engine file: `src/orchestrator/workflow/engine/engine.py` (lines 112–250 cover the state transition methods)
- Test patterns: `tests/unit/test_workflow_engine.py`

**Constraints**
- Only add guards; do NOT change the behavior for non-STOPPING runs.
- `transition_to_stopping()` is only callable by the consumer (added here for engine
  completeness; the consumer wires it in Step 3).

**Functionality (Expected Outcomes)**
- [ ] `engine.transition_to_stopping(run_id)` transitions ACTIVE → STOPPING and emits `RunStatusChanged`
- [ ] `engine.transition_to_stopping()` raises `InvalidTransitionError` if run is not ACTIVE
- [ ] `engine.pause_run()` raises `InvalidTransitionError` for STOPPING runs
- [ ] `engine.cancel_run()` raises `InvalidTransitionError` for STOPPING runs
- [ ] `engine.resume_run()` raises `InvalidTransitionError` for STOPPING runs (already true)
- [ ] `engine.start_task()` raises for STOPPING runs
- [ ] `engine.submit_for_verification()` raises for STOPPING runs

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/test_workflow_engine.py tests/unit/test_task_transitions.py -x -q --tb=short` passes
- [ ] `uv run pytest tests/ -x -q --tb=short` passes (all existing tests)

---

## Task 5: API Guards — 409 for Disallowed Operations on `STOPPING` Runs

**Description**:
Update `src/orchestrator/api/routers/runs.py` so that start, pause, resume, and
cancel endpoints return 409 when the run is in STOPPING state. The engine already
raises `InvalidTransitionError` for these cases (Task 4); the router just needs to
catch and map that exception consistently.

**Implementation Plan (Do These Steps)**

The router currently catches `InvalidTransitionError` in `recover_run()` and maps
it to 409. The same pattern needs to apply to start, pause, resume, and cancel
endpoints.

- [ ] Read the current `start_run`, `pause_run`, `resume_run`, and `cancel_run`
  router functions in `src/orchestrator/api/routers/runs.py` to see whether they
  already have `InvalidTransitionError` catch blocks. (Lines ~412–503.)

- [ ] For each of the four endpoints that does NOT already catch `InvalidTransitionError`,
  wrap the service/executor call with a try/except:
  ```python
  from orchestrator.workflow.engine.errors import InvalidTransitionError

  # Example for pause_run:
  @router.post("/{run_id}/pause", response_model=RunResponse)
  async def pause_run(
      run_id: str,
      service: Annotated[WorkflowService, Depends(get_workflow_service)],
      executor: Annotated[AgentRunnerExecutor, Depends(get_runner_executor)],
  ) -> RunResponse:
      """Pause a run (ACTIVE -> PAUSED)."""
      try:
          await executor.cancel_run(run_id)
          run = await service.pause_run(run_id)
      except InvalidTransitionError as exc:
          raise HTTPException(status_code=409, detail=str(exc)) from exc
      return _run_to_response(run)
  ```
  Apply the same pattern to `cancel_run`, `resume_run`, and `start_run`.

- [ ] Check whether `InvalidTransitionError` is already imported in `runs.py`. If
  not, add the import. Search: `grep -n "InvalidTransitionError" src/orchestrator/api/routers/runs.py`.

- [ ] **FM-5B: Add STOPPING to the `delete_run` guard.** Currently `delete_run`
  rejects only ACTIVE and PAUSED runs. A STOPPING run has an active RunWorkflow
  and must also be protected. Find the `delete_run` guard in `runs.py` and add
  `RunStatus.STOPPING`:
  ```python
  if run.status in (RunStatus.ACTIVE, RunStatus.PAUSED, RunStatus.STOPPING):
      raise HTTPException(status_code=409, detail="Cannot delete a run that is active or stopping")
  ```

- [ ] Run the full test suite:
  ```bash
  cd /Users/peter/code/task-world && uv run pytest tests/ -x -q --tb=short
  ```

**References**
- `recover_run()` in `runs.py` (lines ~506–537) as the existing 409 catch pattern.
- `src/orchestrator/workflow/engine/errors.py` for `InvalidTransitionError`.

**Constraints**
- Only add exception handling for `InvalidTransitionError` → 409.
- Do NOT change the response body structure for the success case.
- Do NOT add guards directly in the router functions — let the engine raise.

**Functionality (Expected Outcomes)**
- [ ] `POST /api/runs/{id}/start` returns 409 when run is STOPPING
- [ ] `POST /api/runs/{id}/pause` returns 409 when run is STOPPING
- [ ] `POST /api/runs/{id}/resume` returns 409 when run is STOPPING
- [ ] `POST /api/runs/{id}/cancel` returns 409 when run is STOPPING

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/ -x -q --tb=short` passes
- [ ] `grep -n "InvalidTransitionError" src/orchestrator/api/routers/runs.py` shows the import and at least one catch block in each of the four endpoint functions

---

## Task 6: Unit Tests for `STOPPING` State Machine

**Description**:
Create `tests/unit/test_stopping_state.py` with unit tests that exercise every
valid and invalid STOPPING transition, the `start_task`/`submit_for_verification`
guards, and the engine's `transition_to_stopping()` method. These tests prove that
the state machine behaves correctly before any consumer wiring exists.

**Implementation Plan (Do These Steps)**

Follow the patterns in `tests/unit/test_workflow_engine.py` — use `_make_run()`,
`SessionStateManager`, `FakeClock`, and `CollectingEmitter` from `tests.conftest`.

- [ ] Create `tests/unit/test_stopping_state.py`:
  ```python
  """Tests for STOPPING run state and transition guards."""

  import pytest

  from orchestrator.config.enums import RunStatus, TaskStatus
  from orchestrator.state.models import Run, StepState, TaskState
  from orchestrator.state.session import SessionStateManager
  from orchestrator.workflow import WorkflowEngine
  from orchestrator.workflow import InvalidTransitionError
  from orchestrator.workflow.events import RunStatusChanged
  from tests.conftest import CollectingEmitter, FakeClock


  def _make_active_run(run_id: str = "run-1") -> Run:
      """Return a run already in ACTIVE state."""
      return Run(
          id=run_id,
          repo_name="proj-1",
          source_branch="main",
          status=RunStatus.ACTIVE,
          steps=[
              StepState(
                  id="step-1",
                  config_id="S-01",
                  tasks=[TaskState(id="task-1", config_id="T-01")],
              )
          ],
      )


  def _engine(run: Run) -> tuple[WorkflowEngine, SessionStateManager, FakeClock, CollectingEmitter]:
      manager = SessionStateManager()
      manager.add_run(run)
      clock = FakeClock()
      emitter = CollectingEmitter()
      engine = WorkflowEngine(manager, clock=clock, emitter=emitter)
      return engine, manager, clock, emitter


  # --- transition_to_stopping ---

  def test_transition_to_stopping_from_active() -> None:
      run = _make_active_run()
      engine, manager, clock, emitter = _engine(run)

      result = engine.transition_to_stopping("run-1")

      assert result.status == RunStatus.STOPPING
      stored = manager.get_run("run-1")
      assert stored.status == RunStatus.STOPPING
      assert len(emitter.events) == 1
      event = emitter.events[0]
      assert isinstance(event, RunStatusChanged)
      assert event.old_status == RunStatus.ACTIVE
      assert event.new_status == RunStatus.STOPPING


  def test_transition_to_stopping_rejects_non_active() -> None:
      for status in (RunStatus.DRAFT, RunStatus.PAUSED, RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.STOPPING):
          run = Run(
              id="run-1",
              repo_name="proj-1",
              source_branch="main",
              status=status,
              steps=[],
          )
          engine, _, _, _ = _engine(run)
          with pytest.raises(InvalidTransitionError):
              engine.transition_to_stopping("run-1")


  # --- STOPPING rejects other operations ---

  def test_pause_run_rejects_stopping() -> None:
      run = _make_active_run()
      engine, manager, _, _ = _engine(run)
      engine.transition_to_stopping("run-1")

      with pytest.raises(InvalidTransitionError):
          engine.pause_run("run-1")


  def test_cancel_run_rejects_stopping() -> None:
      run = _make_active_run()
      engine, manager, _, _ = _engine(run)
      engine.transition_to_stopping("run-1")

      with pytest.raises(InvalidTransitionError):
          engine.cancel_run("run-1")


  def test_resume_run_rejects_stopping() -> None:
      run = _make_active_run()
      engine, manager, _, _ = _engine(run)
      engine.transition_to_stopping("run-1")

      with pytest.raises(InvalidTransitionError):
          engine.resume_run("run-1")


  def test_start_task_rejects_stopping() -> None:
      run = _make_active_run()
      engine, manager, _, _ = _engine(run)
      engine.transition_to_stopping("run-1")

      with pytest.raises(InvalidTransitionError):
          engine.start_task("run-1", "task-1", agent_id="agent-1")


  # --- STOPPING is a valid intermediate state ---

  def test_stopping_to_paused_via_pause_run() -> None:
      """Simulate the consumer completing STOPPING → PAUSED."""
      run = _make_active_run()
      engine, manager, _, _ = _engine(run)
      engine.transition_to_stopping("run-1")

      # Directly update state to simulate consumer's STOPPING→PAUSED transition.
      # (The consumer does this after RunWorkflow acknowledges the pause signal.)
      stored = manager.get_run("run-1")
      stored.status = RunStatus.PAUSED
      manager.update_run(stored)

      assert manager.get_run("run-1").status == RunStatus.PAUSED


  def test_stopping_to_failed_via_cancel() -> None:
      """Simulate the consumer completing STOPPING → FAILED."""
      run = _make_active_run()
      engine, manager, _, _ = _engine(run)
      engine.transition_to_stopping("run-1")

      # Directly update state to simulate consumer's STOPPING→FAILED transition.
      stored = manager.get_run("run-1")
      stored.status = RunStatus.FAILED
      manager.update_run(stored)

      assert manager.get_run("run-1").status == RunStatus.FAILED


  def test_submit_for_verification_rejects_stopping() -> None:
      """FM-6A: submit_for_verification must reject STOPPING runs."""
      run = _make_active_run()
      engine, manager, _, _ = _engine(run)
      engine.transition_to_stopping("run-1")

      # The guard fires before any task state inspection — a PENDING task is fine.
      with pytest.raises(InvalidTransitionError):
          engine.submit_for_verification("run-1", "task-1")
  ```

- [ ] Run the new tests to confirm they pass:
  ```bash
  cd /Users/peter/code/task-world && uv run pytest tests/unit/test_stopping_state.py -v --tb=short
  ```

- [ ] Run the full suite to confirm no regressions:
  ```bash
  cd /Users/peter/code/task-world && uv run pytest tests/ -x -q --tb=short
  ```

**Dependencies**
- [ ] Task 3 (RunStatus.STOPPING defined) must be complete.
- [ ] Task 4 (engine guards) must be complete.

**References**
- Pattern reference: `tests/unit/test_workflow_engine.py`
- `tests/conftest.py` for `CollectingEmitter` and `FakeClock`

**Constraints**
- Do NOT test API 409 behavior here — that belongs in integration tests.
- The `STOPPING → PAUSED` and `STOPPING → FAILED` tests use direct state mutation
  to simulate consumer actions (the consumer doesn't exist yet). This is intentional.

**Functionality (Expected Outcomes)**
- [ ] `test_stopping_state.py` contains at least 9 test functions
- [ ] Every valid STOPPING transition has a test confirming it succeeds
- [ ] Every invalid transition from STOPPING has a test confirming `InvalidTransitionError`
- [ ] `start_task` guard is tested (FM-4A: this is a new guard, not a modification)
- [ ] `submit_for_verification` guard is tested (FM-4B + FM-6A: new guard, test provided)

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/test_stopping_state.py -v` shows all tests passing (not just collected)
- [ ] `uv run pytest tests/ -x -q --tb=short` passes (full suite, no regressions)
- [ ] `grep -c "def test_" tests/unit/test_stopping_state.py` outputs `9` or higher
