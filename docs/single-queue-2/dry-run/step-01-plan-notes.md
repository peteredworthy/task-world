# Step 1 Dry-Run Analysis: Schema and State Machine

**Analyzed against codebase state:** 2026-03-26
**Step file:** `docs/single-queue-2/steps/step-01-plan.md`

---

## Overview

Step 1 is a foundational, behavior-preserving change. It restructures the
`pending_signals` table, adds `RunStatus.STOPPING` and `WorkflowSignal.RUN_START`,
guards engine transitions, and wires API 409 responses. No consumer or sender
rewiring happens here. The analysis below walks through each task and flags
concrete failure modes with hardening actions.

---

## Task 1: Alembic Migration

### Assumptions Verified

- **Migration directory:** The step correctly identifies `src/orchestrator/db/migrations/versions/` as the target. Confirmed.
- **Alembic config:** `src/orchestrator/db/migrations/alembic.ini` is confirmed correct.
- **Current head revision:** The alphabetical revision naming pattern (`h1a2b3c4d5e6` → `l1a2b3c4d5e6`) suggests the current head is `l1a2b3c4d5e6` (`add_routine_meta_table`). The step's command to discover this is correct procedure.
- **Index name:** `ix_pending_signals_run_id` is confirmed in both `h1a2b3c4d5e6` and the ORM model.
- **Drop-and-recreate strategy:** Appropriate for SQLite PK type changes. Avoids all constraint-name hazards.

### Failure Modes

**FM-1A: Wrong `down_revision` placeholder**
The step uses `<CURRENT_HEAD_REVISION>` as a literal placeholder and instructs the
implementer to discover the real value. If this substitution is skipped or wrong,
the migration will fail to chain correctly (Alembic will see a revision with an
unknown parent). The existing test suite running `uv run alembic upgrade head`
will catch this, but only if the implementer runs the verification step.

*Hardening:* Before implementing, the implementer MUST run the discovery command
and confirm the current head is `l1a2b3c4d5e6`. Add this as an explicit check in
a note on the migration file: `# Verify with: uv run alembic heads`.

**FM-1B: Duplicate revision ID**
The revision ID `m1a2b3c4d5e6` follows the project's alphabetical naming pattern
and does not conflict with any existing migration. No action needed — this is fine.

**FM-1C: `op.create_table` inline ForeignKey syntax**
The existing migration `h1a2b3c4d5e6` uses `sa.ForeignKey(...)` directly in
`sa.Column(...)` inside `op.create_table()`. The new migration copies this pattern.
SQLAlchemy/Alembic supports this for SQLite. No issue.

**FM-1D: Test DBs are not affected by this migration**
Per MEMORY.md: tests use `create_all` (in-memory SQLite), not Alembic migrations.
The migration in Task 1 only affects file-backed DBs. Test isolation is not broken
by this task. The model update (Task 2) is what affects test DBs via `create_all`.

### Expected Outputs
- New file: `src/orchestrator/db/migrations/versions/m1a2b3c4d5e6_restructure_pending_signals.py`
- `pending_signals` table: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `delivered_at DATETIME NULL`, `handled_at DATETIME NULL`, no `processed_at`
- Round-trip verified

---

## Task 2: Update `PendingSignalModel` and `PendingSignal` Dataclass

### Assumptions Verified

- **`PendingSignalModel` current state:** Confirmed `id: Mapped[str]`, `processed_at: Mapped[datetime | None]`. No `delivered_at` or `handled_at`.
- **`PendingSignal` dataclass current state:** `id: str`, `processed_at: datetime | None = field(default=None)`. Confirmed in `signals.py:34–43`.
- **`uuid` import:** Used in both `DbSignalTransport.enqueue()` (`str(uuid.uuid4())`) and `InMemorySignalTransport.enqueue()`. If `InMemorySignalTransport` also switches to integer IDs, `uuid` is no longer needed and can be removed. The step correctly handles this.
- **`Integer` already imported in models.py:** Confirmed — used by `ReplayCheckpointModel`.
- **No tests directly construct `PendingSignal` with `id=str(...)`:** Confirmed by searching `tests/`. Integration tests use `InMemorySignalTransport` through `drain_signals()` helper without inspecting signal IDs.

### Failure Modes

**FM-2A: `InMemorySignalTransport.drain()` mutates `processed_at` on returned objects**
Current code: `signal.processed_at = now`. After the dataclass change, `processed_at`
no longer exists. The drain method must be updated to set `handled_at = now` instead.
If overlooked, `drain()` will raise `AttributeError: 'PendingSignal' object has no attribute 'processed_at'`.

*Hardening:* The step describes this update but doesn't call it out as a failure risk.
Add explicit note: after updating the dataclass, grep for all `processed_at` references
in `signals.py` and fix all occurrences before running tests.

**FM-2B: `InMemorySignalTransport` drain filter uses `processed_at` as sentinel**
Current filter: `[s for s in self._queue if s.run_id == run_id and s.processed_at is None]`.
After renaming, this must become `s.handled_at is None`. If not updated alongside the
dataclass, drain returns an empty list (treats all as already-handled).

*Hardening:* Same as FM-2A. One grep sweep for `processed_at` catches both.

**FM-2C: `SignalQueue.drain()` docstring mentions `processed_at`**
Minor: the `SignalQueue.drain()` docstring at line 207 references `processed_at`. After
renaming, this is stale documentation. Not a runtime failure but misleading.

*Hardening:* Update the docstring when updating the method.

**FM-2D: Task ordering dependency on the migration**
Task 2 must be implemented AFTER the migration (Task 1) has been applied to the dev DB.
If the model is updated before the migration runs, `init_db()` for file-backed DBs will
try to run Alembic against a DB with old schema but new model. This is harmless (Alembic
handles it), but test DBs use `create_all` which will create the new schema correctly.
No blocker, but the step correctly notes this dependency.

### Expected Outputs
- `PendingSignalModel.id` is `Mapped[int]` with `autoincrement=True`
- `PendingSignalModel` has `delivered_at`, `handled_at`; no `processed_at`
- `PendingSignal.id: int`, `delivered_at`, `handled_at`; no `processed_at`
- `drain()` orders by `PendingSignalModel.id`, filters by `handled_at.is_(None)`
- No `uuid` import in `signals.py`

---

## Task 3: Add `RunStatus.STOPPING` and `WorkflowSignal.RUN_START`

### Assumptions Verified

- Both are simple enum additions with no behavioral impact.
- `RunStatus` is in `src/orchestrator/config/enums.py`. Confirmed.
- `WorkflowSignal` is in `src/orchestrator/workflow/signals/signals.py`. Confirmed.

### Failure Modes

**FM-3A: Exhaustive pattern matches on `RunStatus` elsewhere**
Any code using `if/elif` chains or `match` statements on all `RunStatus` values
without a fallback will silently miss `STOPPING`. This is low risk in Python (no
compiler exhaustiveness check), but any code that serializes `RunStatus` to a
fixed set of strings (e.g., TypeScript frontend types, Pydantic discriminators)
may need updating. For this step alone the risk is low since `STOPPING` is added
but nothing yet transitions to it.

*Hardening:* The step's final `grep` verification and test run are sufficient. No
additional action needed here — exhaustive-match issues will surface in Phase 3.

**FM-3B: Frontend `RunStatus` type out of sync**
The architecture doc defers frontend updates. For Phase 1, the frontend will never
observe STOPPING (since nothing transitions to it yet), so this is deferred correctly.

### Expected Outputs
- `RunStatus.STOPPING = "stopping"` defined in `config/enums.py`
- `WorkflowSignal.RUN_START = "run_start"` defined in `signals.py`

---

## Task 4: Engine State Machine Guards for `STOPPING`

### Assumptions Verified — Critical Discrepancy Found

**FM-4A: `start_task()` has NO existing run status check**
The step plan says:
> "In start_task(), near the top where run status is checked: `if run.status in (...)`"

This is **incorrect**. Reading `engine.py:253–325` confirms that `start_task()` has
**zero run-status checks**. It acquires a lock, finds the task's step index, advances
`current_step_index`, checks if the task belongs to a future step, then delegates to
`transition_to_building()`. There is no `run.status` guard.

If the implementer looks for "the existing run status check in start_task()" they will
not find it and may be confused or skip the guard entirely.

*Hardening:* The guard must be added as **new code from scratch**, not as a modification
to an existing check. Insert it after `run = self._state.get_run(run_id)` (line 271):
```python
if run.status in (RunStatus.PAUSED, RunStatus.STOPPING, RunStatus.COMPLETED, RunStatus.FAILED):
    raise InvalidTransitionError(
        run.status.value, f"start_task (run must be ACTIVE, got {run.status.value})"
    )
```
The step plan should be explicit: "Add a new run-status guard — this does NOT exist yet."

**FM-4B: `submit_for_verification()` has NO existing run status check**
Same issue. `submit_for_verification()` (lines 327–383) has no run-status check. It
only operates on task state. The STOPPING guard must be added as new code.

*Hardening:* Insert after `task = self._state.get_task(run_id, task_id)`:
```python
run = self._state.get_run(run_id)
if run.status == RunStatus.STOPPING:
    raise InvalidTransitionError(run.status.value, "submit_for_verification")
```
Note: `get_run` is not currently called in `submit_for_verification`. Adding the guard
requires a new `get_run` call. This has a minor performance cost (one extra state lookup)
but is otherwise benign.

**FM-4C: `pause_run()` already rejects STOPPING via fallthrough**
The current code:
```python
if run.status == RunStatus.PAUSED: return run  # idempotent
if run.status != RunStatus.ACTIVE: raise InvalidTransitionError(...)
```
After adding `STOPPING` to the enum, STOPPING is already rejected by the second check.
The step proposes adding an explicit STOPPING check between these two. This is correct
and defensively readable, but NOT required for correctness. No failure risk here.

**FM-4D: `cancel_run()` already rejects STOPPING**
`cancellable = (RunStatus.ACTIVE, RunStatus.PAUSED)` — STOPPING is not in the tuple,
so it already raises. The step's note "verify and leave as-is" is correct.

**FM-4E: `resume_run()` already rejects STOPPING**
`if run.status != RunStatus.PAUSED: raise` — already rejects STOPPING. Confirmed.

**FM-4F: `transition_to_stopping()` emits `RunStatusChanged` correctly**
The event constructor pattern in the step matches the existing pattern exactly
(confirmed by comparing with `cancel_run()` at lines 124–131).

### Expected Outputs
- `engine.transition_to_stopping()` exists, transitions ACTIVE→STOPPING, emits `RunStatusChanged`
- `pause_run()`, `cancel_run()`, `resume_run()` reject STOPPING (pause explicitly, others via existing logic)
- `start_task()` rejects STOPPING (new guard added from scratch)
- `submit_for_verification()` rejects STOPPING (new guard added from scratch)

---

## Task 5: API Guards — 409 for STOPPING

### Assumptions Verified

- `recover_run()` already has the pattern: `except InvalidTransitionError as exc: raise HTTPException(status_code=409, ...)` at lines 536–537. Confirmed.
- `InvalidTransitionError` is already imported in `runs.py` (used by `recover_run`). Confirm with grep before the step to avoid double-import.
- None of `start_run`, `pause_run`, `resume_run`, `cancel_run` currently have `InvalidTransitionError` catch blocks. Confirmed.

### Failure Modes

**FM-5A: `start_run` calls `executor.start_run_with_agent()`, not engine directly**
The route calls `executor.start_run_with_agent()` → `service.start_run()` → `engine.start_run()`.
The `engine.start_run()` already rejects non-DRAFT status (raises `InvalidTransitionError`
for STOPPING). This exception propagates up through `service.start_run()` and is NOT
caught in `executor.start_run_with_agent()` (confirmed by reading the method — it
doesn't wrap `service.start_run()` in a try/except). So the `try/except InvalidTransitionError`
in the router WILL correctly catch it.

**FM-5B: `delete_run` accepts STOPPING runs**
The current `delete_run` guard: `if run.status in (RunStatus.ACTIVE, RunStatus.PAUSED): reject`.
After adding `STOPPING`, a run in STOPPING state could be deleted. This is a logical error
since a STOPPING run has an active RunWorkflow (after Phase 2). The step does not address this.

*Hardening:* Add `RunStatus.STOPPING` to the delete guard:
```python
if run.status in (RunStatus.ACTIVE, RunStatus.PAUSED, RunStatus.STOPPING):
    raise HTTPException(status_code=409, ...)
```
This is a one-line addition that prevents a consistency hole.

**FM-5C: Router imports are not audited for double-import**
If `InvalidTransitionError` is added as a new import but already exists, this causes a
lint error in strict environments. The step says "check if already imported" — this is
correct procedure.

### Expected Outputs
- All four endpoints (`start`, `pause`, `resume`, `cancel`) return 409 for STOPPING runs
- `delete_run` returns 409 for STOPPING runs (if FM-5B hardening applied)

---

## Task 6: Unit Tests for STOPPING

### Assumptions Verified

- `CollectingEmitter`, `FakeClock` are in `tests/conftest.py`. Confirmed.
- `SessionStateManager` is in `src/orchestrator/state/session.py`. Confirmed.
- `WorkflowEngine`, `InvalidTransitionError` are exported from `src/orchestrator/workflow/__init__.py`. Confirmed.
- The test pattern (`_make_run`, `_engine`) matches exactly the pattern in `test_workflow_engine.py`. Confirmed.
- `RunStatusChanged` can be imported from `orchestrator.workflow.events`. Confirmed (used in `engine.py`).

### Failure Modes

**FM-6A: Missing `test_submit_for_verification_rejects_stopping` test**
The step's "Functionality (Expected Outcomes)" says:
> "`start_task` and `submit_for_verification` guards are tested"

But the provided test code only contains `test_start_task_rejects_stopping`. There
is no test for `submit_for_verification`. The count requirement ("8 or higher tests")
can be met without this test, creating a coverage gap.

*Hardening:* Add `test_submit_for_verification_rejects_stopping` explicitly:
```python
def test_submit_for_verification_rejects_stopping() -> None:
    run = _make_active_run()
    engine, manager, _, _ = _engine(run)
    engine.transition_to_stopping("run-1")

    with pytest.raises(InvalidTransitionError):
        engine.submit_for_verification("run-1", "task-1")
```
This requires `task-1` to be in VERIFYING state for the guard to be reachable.
However, since the guard is checked before task state, a PENDING task in a STOPPING
run should also be rejected. Verify by reading the proposed guard location.

**FM-6B: `_make_active_run` constructs tasks without `checklist`**
The existing `_make_run` in `test_workflow_engine.py` includes a `ChecklistItem` on
the task. The new `_make_active_run` omits it. This could cause `submit_for_verification`
to fail on `transition_to_verifying` before the STOPPING guard fires (if the gate check
runs first). However, since the STOPPING guard is added BEFORE the task state transition,
this is not an issue for `test_submit_for_verification_rejects_stopping` — the guard
fires before any task state is inspected. For other tests, the missing checklist is fine
since STOPPING guards fire immediately without inspecting task state.

**FM-6C: Tests 4 and 5 use `engine.transition_to_stopping()` which itself is being added**
The test file requires Task 4 to be complete before the tests can run. The step notes
this dependency correctly.

**FM-6D: `test_stopping_to_paused_via_pause_run` directly mutates state manager**
The test sets `stored.status = RunStatus.PAUSED; manager.update_run(stored)`. This
bypasses the engine. This is intentional (simulating consumer behavior) but the
`SessionStateManager.update_run()` method needs to accept this mutation. Confirmed:
`SessionStateManager` is an in-memory dict-based manager with no validation.

### Expected Outputs
- `tests/unit/test_stopping_state.py` with ≥ 8 test functions
- All valid/invalid STOPPING transitions covered
- `start_task` guard tested (needs the new guard from FM-4A to pass)
- `submit_for_verification` guard tested (FM-6A hardening)

---

## Cross-Cutting Concerns

### Will Existing Tests Break?

| Change | Impact on existing tests |
|--------|--------------------------|
| Migration (Task 1) | None — tests use `create_all`, not Alembic |
| `PendingSignalModel.id: str → int` | None — no tests construct `PendingSignalModel` directly |
| `PendingSignal.id: str → int` | None — no tests construct `PendingSignal` directly |
| `processed_at → handled_at` in dataclass | BREAKS if `signal.processed_at` accessed in tests — confirmed NOT accessed anywhere in test files |
| `RunStatus.STOPPING` added | None — existing tests never set status to STOPPING |
| `WorkflowSignal.RUN_START` added | None — purely additive |
| `engine.pause_run()` explicit STOPPING guard | None — existing tests never call `pause_run` with STOPPING state |
| `engine.start_task()` STOPPING guard | None — existing tests never start tasks on STOPPING runs |

**Verdict:** No existing tests should break, provided FM-2A and FM-2B are correctly handled.

### Component Wiring

This step is purely additive. No existing call sites are replaced. The new
`transition_to_stopping()` method is added to the engine but not wired to any call site
yet (that happens in Phase 3). The STOPPING guards only reject invalid states — they
don't change the behavior for valid states. Existing tests remain on valid state paths
and are unaffected. There is no "wiring gap" risk in Phase 1.

### DB Schema Consistency

After Task 1 (migration) and Task 2 (model update), the SQLAlchemy ORM model and the
DB schema will be in sync for both file-backed DBs (via migration) and test DBs (via
`create_all`). The ordering change from `created_at` to `id` is safe since tests don't
depend on signal ordering semantics.

---

## Summary of Required Hardening Actions

| ID | Priority | Action |
|----|----------|--------|
| FM-4A | **Critical** | Rewrite Task 4 start_task guard instructions: "add new guard from scratch" not "modify existing" |
| FM-4B | **Critical** | Rewrite Task 4 submit_for_verification guard instructions: "add new guard from scratch, requires new `get_run` call" |
| FM-6A | **High** | Add `test_submit_for_verification_rejects_stopping` to the test file |
| FM-2A/2B | **High** | Grep for all `processed_at` in `signals.py` after dataclass change; verify all occurrences updated |
| FM-5B | **Medium** | Add `RunStatus.STOPPING` to `delete_run` guard in router |
| FM-2C | **Low** | Update `SignalQueue.drain()` docstring to reference `handled_at` |
| FM-1A | **Low** | Verify `down_revision` is set to `l1a2b3c4d5e6` before writing migration |
