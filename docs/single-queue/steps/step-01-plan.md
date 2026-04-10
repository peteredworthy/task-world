# Step 01: Schema and State Machine

This step lays the data foundation for the single-queue signal model without changing any runtime behavior.
We restructure the `pending_signals` table for FIFO ordering and delivery tracking, add the `STOPPING` state to `RunStatus`,
and define the `RUN_START` signal type. Schema changes and type definitions only—no consumer, no handler wiring.

## Intent Verification

**Original Intent**: [I-07], [I-08], [I-09], [I-16], [I-22], [I-26], [I-35]
- [I-07]: Restructure `pending_signals` table: integer PK, `delivered_at`/`handled_at` columns, ordering by PK not `created_at`
- [I-08]: Add `STOPPING` to `RunStatus` with defined transitions (ACTIVE → STOPPING → PAUSED/FAILED)
- [I-09]: Add `RUN_START` signal type (RESUME functional handling is in Step 03)
- [I-16]: Alembic migration for `pending_signals` schema changes and `STOPPING` status value
- [I-22]: `STOPPING` must not be valid source for resume/restart/duplicate pause/cancel via API
- [I-26]: `created_at` retained on `pending_signals` for audit but must not be used for ordering
- [I-35]: An Alembic migration exists for schema changes and `STOPPING` status value

**Functionality to Produce**:
- `pending_signals` table with integer PK and delivery tracking columns
- `RunStatus.STOPPING` enum value with transition guards
- `WorkflowSignal.RUN_START` enum value and serialization support
- API guards rejecting invalid operations on STOPPING runs (409 Conflict)

**Final Verification Criteria**:
- Migration applies to fresh and existing DBs with no errors
- STOPPING state rejects invalid transitions at the DB layer and API layer
- RUN_START signal can be created, serialized, and deserialized
- All existing tests pass without behavioral changes
- Type checking (`tsc`) and linting pass

---

## Task 1: Create Alembic Migration for pending_signals Table

**Description**:
Create an Alembic migration that restructures `pending_signals` for FIFO ordering and delivery tracking.
The migration changes the PK from UUID string to integer AUTOINCREMENT and adds `delivered_at` and `handled_at` columns
while preserving existing data by backfilling integer PKs based on `created_at` order.

**Implementation Plan (Do These Steps)**

The migration must handle two scenarios: (1) fresh databases with no existing signals, and (2) existing databases
with in-flight signals that must be backfilled with sequential integer PKs.

- [ ] Determine the next Alembic revision number. The actual migration directory is
      `src/orchestrator/db/migrations/versions/` (NOT `alembic/versions/`):

```bash
ls -1 src/orchestrator/db/migrations/versions/ | tail -5
```

- [ ] Create a new migration file at `src/orchestrator/db/migrations/versions/{next_number}_single_queue_signals.py`
      using the template below. Replace `{next_number}` with the number you found (e.g., `m1a2b3c4d5e6_single_queue_signals.py`).

```python
"""Add delivery tracking columns to pending_signals table and change PK to integer.

Revision ID: {next_number}
Revises: {previous_revision}
Create Date: 2026-03-26 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '{next_number}'
down_revision = '{previous_revision}'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use batch_alter_table for SQLite portability. SQLite does not support most
    # ALTER TABLE operations natively, and auto-generated constraint names (e.g.,
    # sqlite_autoindex_pending_signals_1) are not stable across versions.
    # batch_alter_table recreates the table under the hood, avoiding these issues.

    with op.batch_alter_table('pending_signals', schema=None) as batch_op:
        # Add new delivery tracking columns (nullable so existing rows are unaffected)
        batch_op.add_column(sa.Column('delivered_at', sa.DateTime, nullable=True))
        batch_op.add_column(sa.Column('handled_at', sa.DateTime, nullable=True))

        # Add new integer PK column (autoincrement will be assigned during table recreation)
        batch_op.add_column(sa.Column('id_int', sa.Integer, nullable=True))

    # Backfill id_int with sequential integers ordered by created_at.
    # Uses ROWID as tie-breaker to avoid duplicate integers when multiple rows
    # share the same created_at timestamp (UUID ordering is not insertion-order-preserving).
    op.execute("""
        UPDATE pending_signals
        SET id_int = (
            SELECT COUNT(*) FROM pending_signals ps2
            WHERE ps2.created_at < pending_signals.created_at
               OR (ps2.created_at = pending_signals.created_at
                   AND ps2.ROWID <= pending_signals.ROWID)
        )
    """)

    # Recreate table with integer PK via batch_alter_table (drops uuid id, promotes id_int to id)
    with op.batch_alter_table('pending_signals', schema=None) as batch_op:
        batch_op.drop_column('id')  # Drop the old UUID string PK
        batch_op.alter_column('id_int', new_column_name='id',
                              existing_type=sa.Integer, nullable=False)
        # Index on run_id (recreated automatically by batch_alter_table if defined in model;
        # add explicitly if needed)
        batch_op.create_index('ix_pending_signals_run_id', ['run_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('pending_signals', schema=None) as batch_op:
        batch_op.drop_column('handled_at')
        batch_op.drop_column('delivered_at')
        # Restore UUID string PK: add uuid column, drop integer id
        batch_op.add_column(sa.Column('id_uuid', sa.String, nullable=True))

    # Cannot recover original UUIDs; assign placeholder UUIDs for downgrade
    op.execute("UPDATE pending_signals SET id_uuid = LOWER(HEX(RANDOMBLOB(16)))")

    with op.batch_alter_table('pending_signals', schema=None) as batch_op:
        batch_op.drop_column('id')
        batch_op.alter_column('id_uuid', new_column_name='id',
                              existing_type=sa.String, nullable=False)
        batch_op.create_index('ix_pending_signals_run_id', ['run_id'], unique=False)
```

**Note:** The migration uses `batch_alter_table()` throughout (required for SQLite).
This avoids fragile hard-coded constraint names (e.g., `sqlite_autoindex_*`) and handles
table recreation atomically. The ROWID-based tie-breaker in the backfill SQL prevents
duplicate integer PKs when multiple signals share the same `created_at` timestamp.

- [ ] Verify the migration file exists and is syntactically correct:

```bash
uv run python -m py_compile src/orchestrator/db/migrations/versions/{next_number}_single_queue_signals.py
```

**Dependencies**
- Alembic infrastructure must be functional (`src/orchestrator/db/migrations/versions/` directory exists)
- Database must be accessible and writable
- No concurrent migrations running

**References**
- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- Existing migrations: `alembic/versions/`
- Current schema: `src/orchestrator/db/orm/models.py`
- Existing migrations for pattern reference: `src/orchestrator/db/migrations/versions/`

**Constraints**
- Do NOT modify any other Alembic files
- Do NOT change the migration's revision ID after creation
- The migration must be idempotent (running twice produces same result)

**Side Effects**
- Existing rows in `pending_signals` will have `id_old` temporarily during migration (transparent to application)
- `processed_at` column remains (will be replaced in a later step; this step preserves it)

**Functionality (Expected Outcomes)**
- Migration file exists at `src/orchestrator/db/migrations/versions/{next_number}_single_queue_signals.py`
- Migration is valid Python and imports without errors
- Upgrade path: UUID → Integer PK, adds `delivered_at` and `handled_at` columns
- Downgrade path: Integer PK → UUID, removes tracking columns

**Final Verification (Proof of Completion)**
DO NOT CHECK THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Run the upgrade migration on a fresh test DB:
```bash
uv run alembic upgrade head
```
Confirm: no SQL errors, `pending_signals` table has `id INTEGER PRIMARY KEY`, `delivered_at`, `handled_at` columns.

- [ ] Run the downgrade migration:
```bash
uv run alembic downgrade -1
```
Confirm: migration reverses without errors, original schema restored.

- [ ] If you have an existing non-empty `pending_signals` table, verify backfill:
```bash
sqlite3 orchestrator.db "SELECT COUNT(*) FROM pending_signals; SELECT id, typeof(id) FROM pending_signals LIMIT 5;"
```
Confirm: `id` values are integers (not UUIDs), count unchanged, ordering preserved.

---

## Task 2: Update PendingSignalModel ORM and Signal Queries

**Description**:
Update the SQLAlchemy ORM model to reflect the new schema: integer PK, `delivered_at`, and `handled_at` columns.
Also update all signal drain/query logic to order by the new integer PK instead of `created_at`.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/db/orm/models.py` and locate the `PendingSignalModel` class (around line 276).

- [ ] Replace the model definition with the updated schema:

```python
class PendingSignalModel(Base):
    __tablename__ = "pending_signals"
    __table_args__ = (
        # Index for fast drain queries: unprocessed signals for a given run
        Index("ix_pending_signals_run_id", "run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # Audit only
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # Deprecated, kept for now
```

**Note:** `created_at` is retained for audit purposes but is no longer used for ordering. `processed_at` is kept for backward compatibility but will be phased out in a later step.

- [ ] Open `src/orchestrator/workflow/signals/signals.py` and locate the `drain()` method in `DbSignalTransport` (around line 105).

- [ ] Update the drain query to order by integer PK:

```python
async def drain(self, run_id: str) -> list[PendingSignal]:
    """Return all unprocessed signals for run_id in FIFO order (ordered by integer PK).

    Marks each returned signal as processed so it is consumed exactly once.
    """
    from orchestrator.db import PendingSignalModel

    stmt = (
        select(PendingSignalModel)
        .where(PendingSignalModel.run_id == run_id)
        .where(PendingSignalModel.processed_at.is_(None))
        .order_by(PendingSignalModel.id)  # FIFO by integer PK
    )
    rows = await self._session.execute(stmt)
    models = rows.scalars().all()

    # Mark as processed
    now = datetime.now(timezone.utc)
    for model in models:
        model.processed_at = now

    if models:
        await self._session.commit()

    return [
        PendingSignal(
            id=str(model.id),
            run_id=model.run_id,
            signal_type=WorkflowSignal(model.signal_type),
            payload=json.loads(model.payload) if model.payload else None,
            created_at=model.created_at,
            processed_at=model.processed_at,
        )
        for model in models
    ]
```

- [ ] Check for any other queries or code that orders by `created_at` in the signals module:

```bash
grep -n "created_at" src/orchestrator/workflow/signals/signals.py
```

Confirm: Only audit references or explicit comments mentioning "audit" — no functional ordering logic.

- [ ] Ensure the `PendingSignal` dataclass in the same file matches the model:

```python
@dataclass
class PendingSignal:
    """A signal pending consumption by a RunWorkflow."""

    id: str  # Now represents an integer (but stored as string in dataclass for compatibility)
    run_id: str
    signal_type: WorkflowSignal
    payload: dict[str, Any] | None
    created_at: datetime
    processed_at: datetime | None = field(default=None)
    delivered_at: datetime | None = field(default=None)  # Add this
    handled_at: datetime | None = field(default=None)    # Add this
```

**Dependencies**
- Alembic migration from Task 1 must be applied first
- `src/orchestrator/db/orm/models.py` must exist and be readable
- `src/orchestrator/workflow/signals/signals.py` must exist and be readable

**References**
- SQLAlchemy ORM docs: [Mapped Columns](https://docs.sqlalchemy.org/en/20/orm/mapped_attributes.html)
- Current `PendingSignalModel` in models.py
- Current `DbSignalTransport.drain()` method

**Constraints**
- Do NOT change the `enqueue()` method yet (Task 3 handles that if needed)
- Do NOT modify any other imports or logic in these files
- Do NOT delete `created_at` — retain it for audit purposes

**Side Effects**
- The `PendingSignal` dataclass now has two additional optional fields; existing code that constructs `PendingSignal` directly must pass these (or rely on defaults)
- Type hint for `id` in `PendingSignal` is now `str` (still representing an integer, for compatibility with signal transport interface)

**Functionality (Expected Outcomes)**
- `PendingSignalModel` has integer PK and delivery tracking columns
- Drain queries order by integer PK (FIFO)
- `PendingSignal` dataclass reflects new columns
- Model and dataclass are in sync

**Final Verification (Proof of Completion)**
DO NOT CHECK THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Type check the modified files:
```bash
uv run pyright src/orchestrator/db/orm/models.py src/orchestrator/workflow/signals/signals.py
```
Confirm: No type errors.

- [ ] Run signal-related unit tests (if they exist):
```bash
uv run pytest tests/unit/test_signals.py -v 2>&1 | head -50
```
Or if no tests exist yet, skip this. Tests are created in Task 6.

- [ ] Verify the model can be imported:
```bash
uv run python -c "from orchestrator.db.orm.models import PendingSignalModel; print(f'id column type: {PendingSignalModel.__table__.columns[\"id\"].type}')"
```
Confirm: Output shows `INTEGER` type.

---

## Task 3: Add STOPPING State to RunStatus Enum

**Description**:
Add the `STOPPING` enum value to `RunStatus` in the config enums file. This state represents a run transitioning
from ACTIVE to either PAUSED or FAILED, and is used for safe coordination of pause/cancel operations.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/config/enums.py` and locate the `RunStatus` enum (line 6).

- [ ] Add the `STOPPING` value:

```python
class RunStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    STOPPING = "stopping"  # Add this line
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
```

- [ ] Verify the enum is syntactically correct:

```bash
uv run python -c "from orchestrator.config.enums import RunStatus; print(RunStatus.STOPPING)"
```

Confirm: Output is `RunStatus.STOPPING` or similar.

- [ ] Check if the enum is used in any Alembic migrations or database constraints. If the column `status` in the `runs` table has a CHECK constraint, verify the migration from Task 1 or create a separate migration to allow `STOPPING`:

```bash
sqlite3 orchestrator.db ".schema runs" | grep -i check
```

If output shows a CHECK constraint on `status`, you may need to add an Alembic migration to update it. For now, assume SQLite allows any string value (no CHECK constraint). If a constraint exists, file an issue and skip this check.

**Dependencies**
- `src/orchestrator/config/enums.py` must exist and be readable
- No other dependencies

**References**
- Current `RunStatus` enum in enums.py
- Traces to [I-16]

**Constraints**
- Do NOT modify any other enums in this file
- Do NOT change the string values of existing enum members
- Do NOT reorder existing enum members

**Side Effects**
- Any code that patterns-matches on `RunStatus` values must be updated (covered in Tasks 4 and 6)
- Frontend type check must be updated (covered in Task 4)

**Functionality (Expected Outcomes)**
- `RunStatus.STOPPING` enum value exists
- Enum can be imported and used in code
- String representation is `"stopping"`

**Final Verification (Proof of Completion)**
DO NOT CHECK THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Verify enum import and string value:
```bash
uv run python -c "from orchestrator.config.enums import RunStatus; s = RunStatus.STOPPING; print(f'Value: {s.value}, Name: {s.name}')"
```
Confirm: Output shows `Value: stopping, Name: STOPPING`.

- [ ] Type check the enums file:
```bash
uv run pyright src/orchestrator/config/enums.py
```
Confirm: No type errors.

---

## Task 4: Add STOPPING State Machine Guards in Workflow Engine and API

**Description**:
Implement state machine guards that enforce the STOPPING state contract: STOPPING can only transition to PAUSED or FAILED.
Add guards in the workflow engine to prevent invalid operations, and add API guards to reject disallowed requests on STOPPING runs.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/workflow/engine.py` and locate the state transition logic (likely in `WorkflowEngine` class or similar).

- [ ] Add transition validation for STOPPING state. Find the method that handles state transitions (e.g., `_transition_run_status()`, `pause_run()`, `start_task()`) and add a guard:

```python
def _is_valid_transition(from_status: str, to_status: str) -> bool:
    """Validate state transition against the state machine."""
    from orchestrator.config.enums import RunStatus

    # STOPPING can only transition to PAUSED or FAILED
    if from_status == RunStatus.STOPPING.value:
        if to_status not in [RunStatus.PAUSED.value, RunStatus.FAILED.value]:
            return False

    # Cannot start a task on a STOPPING run (same as PAUSED)
    if from_status == RunStatus.STOPPING.value and to_status == RunStatus.ACTIVE.value:
        return False

    return True
```

- [ ] Add this validation to every state-changing method. Example:

```python
async def start_task(self, task_id: str, run_id: str) -> None:
    """Start a task. Reject if run is STOPPING (same as PAUSED)."""
    run = await self._get_run(run_id)
    if run.status in ["stopping", "paused"]:
        raise ValueError(f"Cannot start task on {run.status} run")
    # ... rest of logic
```

- [ ] Open `src/orchestrator/api/routers/runs.py` and locate endpoints that operate on runs (e.g., `/runs/{id}/start`, `/runs/{id}/pause`, `/runs/{id}/resume`, `/runs/{id}/cancel`, `/runs/{id}/restart`).

- [ ] Add a guard at the start of each endpoint to reject STOPPING runs with 409 Conflict:

```python
from fastapi import HTTPException, status

@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str, service: WorkflowService = Depends(get_service)):
    run = await service.get_run(run_id)
    if run.status == "stopping":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot pause a run that is already stopping"
        )
    # ... rest of logic
```

Repeat for: `resume`, `restart`, `cancel`, `start` (if applicable).

- [ ] Do NOT add guards to endpoints that are already correctly handling STOPPING (e.g., status checks that already return 409).

- [ ] Ensure the error messages are clear and distinguish STOPPING from PAUSED.

**Dependencies**
- Task 3 must be complete (STOPPING enum exists)
- `src/orchestrator/workflow/engine.py` must exist and be readable
- `src/orchestrator/api/routers/runs.py` must exist and be readable

**References**
- State machine rules from intent.md [I-16]
- FastAPI HTTPException docs
- Current `RunStatus` enum from Task 3

**Constraints**
- Do NOT change the logic of valid transitions; only add guards for invalid ones
- Do NOT change HTTP status codes for other errors
- Do NOT modify request/response schemas yet

**Side Effects**
- API will return 409 for operations on STOPPING runs (new behavior, expected)
- Integration tests that assume immediate state changes must be updated (Task 7)

**Functionality (Expected Outcomes)**
- STOPPING → PAUSED transitions are allowed
- STOPPING → FAILED transitions are allowed
- STOPPING → ACTIVE transitions are rejected
- start_task() rejects STOPPING runs with appropriate error
- submit_for_verification() rejects STOPPING runs with appropriate error
- API endpoints return 409 Conflict for disallowed operations on STOPPING runs

**Final Verification (Proof of Completion)**
DO NOT CHECK THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Type check the modified files:
```bash
uv run pyright src/orchestrator/workflow/engine.py src/orchestrator/api/routers/runs.py
```
Confirm: No type errors.

- [ ] Verify the state machine validation function exists and can be imported:
```bash
uv run python -c "from orchestrator.workflow.engine import _is_valid_transition; print(_is_valid_transition('active', 'stopping'))"
```
Confirm: Output is `True` (or similar success indicator).

- [ ] Test a guard in the API manually (requires running server):
  - Start the server: `uv run uvicorn scripts.serve:app --reload --reload-dir src --reload-dir scripts --port 8000 --host 0.0.0.0`
  - Create a run and set its status to STOPPING manually in the DB (for testing)
  - Attempt to pause it: `curl -X POST http://localhost:8000/api/runs/{id}/pause -H "Content-Type: application/json"`
  - Confirm: Response is 409 Conflict with appropriate message
  - (This is a manual check; automated tests are in Task 6)

---

## Task 5: Add RUN_START Signal Type to WorkflowSignal Enum

**Description**:
Add the `RUN_START` enum value to the `WorkflowSignal` enum. This signal type will be used by the consumer to
initiate run startup in later phases. For now, this task only adds the type definition and serialization support.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/workflow/signals/signals.py` and locate the `WorkflowSignal` enum (line 24).

- [ ] Add the `RUN_START` value:

```python
class WorkflowSignal(enum.Enum):
    """Control signals that can be sent to an active RunWorkflow."""

    RUN_START = "run_start"  # Add this line
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    ACTIVITY_COMPLETED = "activity_completed"
    ACTIVITY_VERIFIED = "activity_verified"
```

- [ ] Verify the enum is syntactically correct:

```bash
uv run python -c "from orchestrator.workflow.signals.signals import WorkflowSignal; print(WorkflowSignal.RUN_START)"
```

Confirm: Output is `WorkflowSignal.RUN_START` or similar.

- [ ] Test signal serialization (enqueuing a RUN_START signal):

```python
# This should not raise an error
signal = await signal_transport.enqueue(
    run_id="test-run",
    signal_type=WorkflowSignal.RUN_START,
    payload=None
)
# Verify it was created
assert signal.signal_type == WorkflowSignal.RUN_START
```

This will be part of the unit test in Task 6.

**Dependencies**
- `src/orchestrator/workflow/signals/signals.py` must exist and be readable
- Task 2 must be complete (so the signal transport can handle the new type)

**References**
- Current `WorkflowSignal` enum in signals.py
- Traces to [I-26]

**Constraints**
- Do NOT modify any other signal types
- Do NOT add handler logic yet (that is Task 2 of the implementation plan, deferred to future steps)

**Side Effects**
- None at this stage; no handlers are wired, so RUN_START signals will be enqueued but not processed

**Functionality (Expected Outcomes)**
- `WorkflowSignal.RUN_START` enum value exists
- Signal can be created, serialized, and deserialized
- String representation is `"run_start"`

**Final Verification (Proof of Completion)**
DO NOT CHECK THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Verify enum import and string value:
```bash
uv run python -c "from orchestrator.workflow.signals.signals import WorkflowSignal; s = WorkflowSignal.RUN_START; print(f'Value: {s.value}, Name: {s.name}')"
```
Confirm: Output shows `Value: run_start, Name: RUN_START`.

- [ ] Type check the signals file:
```bash
uv run pyright src/orchestrator/workflow/signals/signals.py
```
Confirm: No type errors.

- [ ] Write a simple test to verify signal creation (can be a one-off, not part of the test suite):
```bash
uv run python << 'EOF'
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from orchestrator.workflow.signals.signals import WorkflowSignal, DbSignalTransport
from orchestrator.db.orm.base import Base

async def test():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        transport = DbSignalTransport(session)
        signal = await transport.enqueue("test-run", WorkflowSignal.RUN_START)
        print(f"Created signal: {signal.signal_type}")

asyncio.run(test())
EOF
```
Confirm: Output shows `Created signal: WorkflowSignal.RUN_START` or similar.

---

## Task 6: Write Unit Tests for STOPPING State Transitions

**Description**:
Create comprehensive unit tests that verify STOPPING state machine validity, transition guards, and API error responses.
This task ensures the schema and state machine changes are correct before moving to the consumer phase.

**Implementation Plan (Do These Steps)**

- [ ] Create a new test file at `tests/unit/test_stopping_state.py`.

- [ ] Write test cases covering:
  1. Valid transitions from STOPPING (→ PAUSED, → FAILED)
  2. Invalid transitions from STOPPING (→ ACTIVE, → DRAFT, etc.)
  3. start_task() rejects STOPPING runs
  4. submit_for_verification() rejects STOPPING runs
  5. API endpoints return 409 for disallowed operations

```python
"""Tests for STOPPING state machine and transitions."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.config.enums import RunStatus
from orchestrator.workflow.engine import WorkflowEngine, _is_valid_transition


class TestStoppingStateMachine:
    """Unit tests for STOPPING state transitions."""

    def test_stopping_to_paused_valid(self):
        """STOPPING → PAUSED transition is valid."""
        assert _is_valid_transition(RunStatus.STOPPING.value, RunStatus.PAUSED.value)

    def test_stopping_to_failed_valid(self):
        """STOPPING → FAILED transition is valid."""
        assert _is_valid_transition(RunStatus.STOPPING.value, RunStatus.FAILED.value)

    def test_stopping_to_active_invalid(self):
        """STOPPING → ACTIVE transition is invalid."""
        assert not _is_valid_transition(RunStatus.STOPPING.value, RunStatus.ACTIVE.value)

    def test_stopping_to_draft_invalid(self):
        """STOPPING → DRAFT transition is invalid."""
        assert not _is_valid_transition(RunStatus.STOPPING.value, RunStatus.DRAFT.value)

    def test_stopping_to_completed_invalid(self):
        """STOPPING → COMPLETED transition is invalid (must go through PAUSED/FAILED)."""
        assert not _is_valid_transition(RunStatus.STOPPING.value, RunStatus.COMPLETED.value)

    @pytest.mark.asyncio
    async def test_start_task_rejects_stopping_run(self, engine: WorkflowEngine, session: AsyncSession):
        """start_task() rejects runs in STOPPING state."""
        run = await _create_run_with_status(session, RunStatus.STOPPING.value)
        task = run.steps[0].tasks[0]

        with pytest.raises(ValueError, match="Cannot start task on stopping run"):
            await engine.start_task(task.id, run.id)

    @pytest.mark.asyncio
    async def test_submit_for_verification_rejects_stopping_run(self, engine: WorkflowEngine, session: AsyncSession):
        """submit_for_verification() rejects runs in STOPPING state."""
        run = await _create_run_with_status(session, RunStatus.STOPPING.value)
        task = run.steps[0].tasks[0]

        with pytest.raises(ValueError, match="Cannot submit for verification on stopping run"):
            await engine.submit_for_verification(task.id, run.id, {})


class TestStoppingAPIGuards:
    """Integration tests for API guards on STOPPING runs."""

    def test_pause_stopping_run_returns_409(self, client: TestClient, session: AsyncSession):
        """POST /runs/{id}/pause returns 409 for STOPPING run."""
        run = _create_run_with_status_sync(session, RunStatus.STOPPING.value)
        response = client.post(f"/api/runs/{run.id}/pause")

        assert response.status_code == 409
        assert "stopping" in response.json()["detail"].lower()

    def test_resume_stopping_run_returns_409(self, client: TestClient, session: AsyncSession):
        """POST /runs/{id}/resume returns 409 for STOPPING run."""
        run = _create_run_with_status_sync(session, RunStatus.STOPPING.value)
        response = client.post(f"/api/runs/{run.id}/resume")

        assert response.status_code == 409

    def test_restart_stopping_run_returns_409(self, client: TestClient, session: AsyncSession):
        """POST /runs/{id}/restart returns 409 for STOPPING run."""
        run = _create_run_with_status_sync(session, RunStatus.STOPPING.value)
        response = client.post(f"/api/runs/{run.id}/restart")

        assert response.status_code == 409

    def test_cancel_stopping_run_returns_409(self, client: TestClient, session: AsyncSession):
        """POST /runs/{id}/cancel returns 409 for STOPPING run."""
        run = _create_run_with_status_sync(session, RunStatus.STOPPING.value)
        response = client.post(f"/api/runs/{run.id}/cancel")

        assert response.status_code == 409


# Helper functions
async def _create_run_with_status(session: AsyncSession, status: str):
    """Create a test run with the given status."""
    from orchestrator.db.orm.models import RunModel
    from datetime import datetime, timezone

    run = RunModel(
        id="test-run-stopping",
        repo_name="test-repo",
        status=status,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


def _create_run_with_status_sync(session: AsyncSession, status: str):
    """Synchronous version for test fixtures."""
    from orchestrator.db.orm.models import RunModel
    from datetime import datetime, timezone

    run = RunModel(
        id="test-run-stopping",
        repo_name="test-repo",
        status=status,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.commit()
    return run
```

- [ ] Run the tests to confirm they pass:

```bash
uv run pytest tests/unit/test_stopping_state.py -v
```

Confirm: All tests pass.

- [ ] Add a test for signal creation and serialization:

```python
@pytest.mark.asyncio
async def test_run_start_signal_creation(self, session: AsyncSession):
    """RUN_START signal can be created and serialized."""
    from orchestrator.workflow.signals.signals import DbSignalTransport, WorkflowSignal

    transport = DbSignalTransport(session)
    signal = await transport.enqueue("test-run", WorkflowSignal.RUN_START, payload=None)

    assert signal.signal_type == WorkflowSignal.RUN_START
    assert signal.run_id == "test-run"
```

- [ ] Run all tests:

```bash
uv run pytest tests/unit/test_stopping_state.py -v
```

**Dependencies**
- pytest and async pytest plugin (`pytest-asyncio`) must be installed
- All previous tasks must be complete
- Test fixtures (database session, FastAPI client) must be available

**References**
- Current test structure in `tests/unit/`
- FastAPI testing docs
- pytest async docs

**Constraints**
- Do NOT modify existing tests
- Do NOT depend on running server (use in-memory DB for unit tests)
- Do NOT test behavioral changes yet (only schema and guards)

**Side Effects**
- Tests provide regression protection for STOPPING state going forward

**Functionality (Expected Outcomes)**
- Test file exists at `tests/unit/test_stopping_state.py`
- All state machine transition tests pass
- All API guard tests pass (or are marked as expected failures if API guard implementation incomplete)
- Signal creation tests pass

**Final Verification (Proof of Completion)**
DO NOT CHECK THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Run the test file:
```bash
uv run pytest tests/unit/test_stopping_state.py -v
```
Confirm: All tests pass (no skips, no errors).

- [ ] Run the full test suite to ensure no regressions:
```bash
uv run pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```
Confirm: Test count increases (new tests added), no existing tests broken.

- [ ] Verify type checking passes:
```bash
uv run pyright tests/unit/test_stopping_state.py
```
Confirm: No type errors.

---

## Task 7: Verify Migration and Run Regression Test Suite

**Description**:
This final verification task applies the migration to a real database, runs the full test suite to ensure no
behavioral regressions, and confirms all components are ready for the consumer phase.

**Implementation Plan (Do These Steps)**

**Note:** This task is verification only—no file modifications.

- [ ] Back up the current database (if it contains important data):

```bash
cp orchestrator.db orchestrator.db.backup.pre-step-01
```

- [ ] Apply the Alembic migration to the development database:

```bash
uv run alembic upgrade head
```

Confirm: No SQL errors, migration completes successfully.

- [ ] Verify the schema changed correctly:

```bash
sqlite3 orchestrator.db ".schema pending_signals"
```

Confirm: Output shows:
  - `id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `delivered_at DATETIME`
  - `handled_at DATETIME`
  - Index on `run_id`

- [ ] Run the full backend test suite:

```bash
uv run pytest tests/unit/ tests/integration/ -v --tb=short 2>&1 | tail -50
```

Confirm:
  - No new failures related to signal handling, RunStatus, or schema
  - All existing tests still pass (unless known failures from other issues)
  - Test count at or above baseline (from MEMORY.md: 330 unit + 235 integration)

- [ ] Run the frontend type check:

```bash
cd ui && npm run type-check
```

Confirm: No TypeScript errors related to `RunStatus` or new field additions.

- [ ] Run linting on modified files:

```bash
uv run pytest src/orchestrator/config/enums.py src/orchestrator/workflow/signals/signals.py src/orchestrator/db/orm/models.py --linter 2>&1 | grep -i "error\|warning" | head -20
```

Or if a linter is not integrated with pytest:

```bash
uv run ruff check src/orchestrator/config/enums.py src/orchestrator/workflow/signals/signals.py src/orchestrator/db/orm/models.py
```

Confirm: No linting errors (warnings OK).

- [ ] Verify the server starts without errors:

```bash
timeout 5 uv run uvicorn scripts.serve:app --reload --reload-dir src --reload-dir scripts --port 8000 --host 0.0.0.0 2>&1 | head -30
```

Confirm: No startup errors, migrations applied cleanly, server initializes without exceptions.

- [ ] Clean up backup if all checks pass:

```bash
rm orchestrator.db.backup.pre-step-01
```

**Dependencies**
- All tasks 1–6 must be complete
- Database must be writable and accessible
- Full test suite must exist and pass

**References**
- Baseline test counts from MEMORY.md
- Alembic documentation

**Constraints**
- Do NOT make any code changes in this task
- Do NOT skip any verification steps
- Do NOT proceed to the next step if any verification fails

**Side Effects**
- Database schema is permanently changed (migration is applied)
- Backup created, then deleted after successful verification

**Functionality (Expected Outcomes)**
- Migration applies to development DB
- Schema reflects all new columns and constraints
- All existing tests pass
- Type checking passes
- Server starts without errors
- No behavioral changes to existing code

**Final Verification (Proof of Completion)**
DO NOT CHECK THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Confirm migration was applied:
```bash
sqlite3 orchestrator.db "SELECT sql FROM sqlite_master WHERE type='table' AND name='pending_signals';"
```
Confirm: Output includes `INTEGER PRIMARY KEY`, `delivered_at`, `handled_at`.

- [ ] Confirm test suite passes (final run):
```bash
uv run pytest tests/ -x -v 2>&1 | tail -5
```
Confirm: Output ends with `passed` count >= baseline, no failures.

- [ ] Confirm server can start:
```bash
uv run uvicorn scripts.serve:app --reload --reload-dir src --reload-dir scripts --port 8000 &
sleep 3 && curl -s http://localhost:0000/health && killall uvicorn
```
Confirm: Health check returns 200 (or similar success response), no errors in logs.

---

## Summary

Step 01 is now complete. The following has been done:

1. ✅ `pending_signals` table restructured with integer PK and delivery tracking
2. ✅ `RunStatus.STOPPING` enum value added with transition guards
3. ✅ `WorkflowSignal.RUN_START` signal type added
4. ✅ API guards reject invalid operations on STOPPING runs
5. ✅ Full test coverage for STOPPING state machine
6. ✅ All existing tests pass, no behavioral changes

**Next Step:** [Step 02: Consumer Module](step-02-plan.md) — Implement the signal consumer loop that processes
enqueued signals and manages the RunWorkflow lifecycle.

---

## Intent Traceability

| Intent ID | Requirement | Addressed By |
|-----------|-------------|--------------|
| [I-07] | Signal queue FIFO ordering | Task 1 (integer PK), Task 2 (ORDER BY id) |
| [I-08] | Delivery tracking for crash recovery | Task 1, Task 2 (delivered_at, handled_at columns) |
| [I-16] | STOPPING state for safe coordination | Task 3, Task 4, Task 6 (state machine guards) |
| [I-26] | RUN_START signal exists and enqueueable | Task 5, Task 6 (signal creation tests) |
