# Step 01: Schema and State Machine — Execution Simulation & Failure Mode Analysis

**Date:** 2026-03-26
**Simulation Status:** Pre-implementation analysis
**Output:** Hardened implementation checklist

---

## Executive Summary

Step 01 introduces three foundational changes: (1) restructure `pending_signals` table for FIFO ordering and delivery tracking, (2) add `STOPPING` state to `RunStatus` with transition guards, (3) add `RUN_START` signal type. Analysis reveals **7 critical failure modes** across schema migration, ORM synchronization, state machine guards, and component wiring. No behavioral issues expected if hardening actions are applied, but implementation requires careful attention to:

- **Migration idempotency** on SQLite with complex backfill logic
- **File path correctness** (migration dir is `db/migrations/versions/` not `alembic/versions/`)
- **Component wiring verification** — new guards must be tested end-to-end to ensure they're actually invoked
- **STOPPING state guards must have clear error-type mapping** (ValueError → 409 Conflict)

**Risk Level:** Medium (primarily technical execution risk, not design risk)

---

## Task-by-Task Analysis

### Task 1: Create Alembic Migration for pending_signals Table

#### Actual File Path Correction
- **Step Plan States:** `alembic/versions/xxxx_single_queue_signals.py`
- **Actual Path:** `src/orchestrator/db/migrations/versions/` (not `alembic/`)
- **Latest Revision:** Checked via `find` — latest is `l1a2b3c4d5e6_add_routine_meta_table.py`
- **Action:** Use next revision number in sequence (e.g., `m1a2b3c4d5e6_single_queue_signals.py`)

#### Assumptions
1. Alembic infrastructure is functional and can handle SQLite migration syntax
2. Existing `pending_signals` table has rows with UUID string PKs
3. SQLite version supports `ALTER TABLE ... RENAME COLUMN` (3.25.0+)
4. Database is accessible and writable during migration
5. No concurrent migrations running

#### Expected Outputs
- Migration file created at `src/orchestrator/db/migrations/versions/m1a2b3c4d5e6_single_queue_signals.py`
- Upgrade path: UUID PK → Integer PK, adds `delivered_at` and `handled_at` columns, preserves existing rows
- Downgrade path: Integer PK → UUID, removes tracking columns
- Migration is idempotent and handles both fresh DBs and existing data

#### Critical Failure Modes

**[FM-1-1] SQLite ALTER TABLE Limitations**
- **Scenario:** SQLite version < 3.25.0 does not support `RENAME COLUMN`, migration fails
- **Impact:** Database state becomes inconsistent; migration cannot be rolled back cleanly
- **Evidence:** The step plan uses `ALTER TABLE ... RENAME` which is not available in older SQLite
- **Mitigation:**
  - Add comment in migration checking `sqlite_version` and failing fast with clear message
  - OR use Alembic's `batch_alter_table()` context manager (recommended for SQLite)
  - OR test on multiple SQLite versions in CI

**[FM-1-2] Backfill Logic Produces Duplicate Integer IDs**
- **Scenario:** Two or more signals have identical `created_at` timestamp. The tie-breaking logic:
  ```sql
  WHERE ps2.created_at <= pending_signals.created_at
  AND ps2.id <= pending_signals.id
  ```
  This assumes UUID string ordering matches insertion order, which is NOT guaranteed (UUIDs are random)
- **Impact:** Multiple signals assigned the same integer PK, violating uniqueness constraint
- **Evidence:** UUID primary key ordering is not insertion-order-preserving; backfill must use ROWID or similar
- **Mitigation:**
  - Use SQLite's `ROWID` as tie-breaker instead of string comparison:
    ```sql
    SET id_new = (
        SELECT COUNT(*) FROM pending_signals ps2
        WHERE ps2.created_at < pending_signals.created_at
        OR (ps2.created_at = pending_signals.created_at AND ps2.ROWID <= pending_signals.ROWID)
    ) + 1
    ```
  - Test migration on DB with multiple signals at same `created_at`

**[FM-1-3] PK Constraint Name Is SQLite Auto-Generated**
- **Scenario:** Migration drops `'sqlite_autoindex_pending_signals_1'`, but this name may vary by SQLite version or be auto-generated differently
- **Impact:** DROP CONSTRAINT fails with "no such constraint" error, migration aborts
- **Evidence:** SQLite auto-generates index names; they are not stable across versions
- **Mitigation:**
  - Query actual constraint name before dropping:
    ```python
    op.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='pending_signals' AND name LIKE 'sqlite_autoindex%'")
    ```
  - OR use Alembic's `batch_alter_table()` which handles this automatically
  - Test on actual project database to verify constraint name

**[FM-1-4] No Explicit Transaction Wrapping**
- **Scenario:** Migration fails partway through (e.g., after renaming id to id_old but before creating new id). Table is now corrupt.
- **Impact:** Manual cleanup required; migration is not atomic
- **Evidence:** Alembic migrations should be transactional, but explicit error handling is missing
- **Mitigation:**
  - Wrap migration in try/except with rollback logic
  - OR ensure Alembic's transaction handling is enabled in `env.py`
  - Test rollback scenario: simulate failure and verify downgrade works

**[FM-1-5] Index Drop/Recreate May Fail If Index Doesn't Match ORM Definition**
- **Scenario:** Migration drops index `ix_pending_signals_run_id`, but ORM model may define it differently (e.g., composite index)
- **Impact:** Index is not recreated correctly, queries may be slow
- **Evidence:** Need to verify ORM model definition matches what migration assumes
- **Mitigation:**
  - Verify index name and columns in ORM: `Index("ix_pending_signals_run_id", "run_id")` ✓ (matches step plan)
  - Test that queries still execute efficiently after migration

**[FM-1-6] Downgrade Path Not Tested**
- **Scenario:** Downgrade migration is written but never executed in practice. If production rollback is needed, migration may fail
- **Impact:** Unable to rollback failed upgrade; stuck at bad schema state
- **Evidence:** Downgrade path is specified but step plan does not include downgrade testing
- **Mitigation:**
  - Write explicit test that applies and rolls back migration
  - CI/CD must test both upgrade and downgrade paths
  - Document rollback procedure in migration file header

#### File References & Verification
- ✅ Migration directory: `src/orchestrator/db/migrations/versions/`
- ✅ ORM models: `src/orchestrator/db/orm/models.py` (line 276: `PendingSignalModel`)
- ✅ Index name: `ix_pending_signals_run_id` matches ORM definition
- ✅ Existing signal queries: `src/orchestrator/workflow/signals/signals.py` line 124 orders by `created_at` (will need update in Task 2)

#### Hardening Checklist
- [ ] Use `batch_alter_table()` for SQLite portability
- [ ] Verify migration PK constraint name before dropping
- [ ] Test backfill with multiple signals at same `created_at`
- [ ] Add explicit error handling and rollback logic
- [ ] Test upgrade and downgrade paths on actual DB
- [ ] Document recovery procedure if migration fails partway

---

### Task 2: Update PendingSignalModel ORM and Signal Queries

#### Assumptions
1. `PendingSignalModel` exists at `src/orchestrator/db/orm/models.py:276` ✓
2. `DbSignalTransport.drain()` is the only production query of `pending_signals` for ordering
3. Migration from Task 1 has already been applied (or will be atomic)
4. Test fixtures handle both old (`processed_at`) and new (`delivered_at`/`handled_at`) columns

#### Expected Outputs
- `PendingSignalModel.id` type changed from `String` to `Integer` with `autoincrement=True`
- `PendingSignalModel` has new columns: `delivered_at`, `handled_at` (both nullable)
- `PendingSignal` dataclass updated to include `delivered_at`, `handled_at` fields
- `DbSignalTransport.drain()` orders by integer PK instead of `created_at`
- All signal-related tests pass

#### Critical Failure Modes

**[FM-2-1] ORM Type Mismatch: Integer PK in DB vs String in Dataclass**
- **Scenario:** ORM model has `id: Mapped[int]` but `PendingSignal` dataclass has `id: str` (for backward compatibility). Code paths that assume type consistency will fail.
- **Impact:** Subtle type errors if code tries to arithmetic on signal.id or compare IDs
- **Evidence:** Step plan explicitly states `id: str` in dataclass "for compatibility" — this is a design tradeoff but introduces type inconsistency risk
- **Mitigation:**
  - Document the type mismatch with explicit comment:
    ```python
    class PendingSignal:
        id: str  # From DB as integer, converted to string for transport compatibility
    ```
  - Add assertion tests that verify type conversion:
    ```python
    assert isinstance(signal.id, str)
    assert signal.id.isdigit()  # Can be parsed back to int
    ```
  - Avoid any code that assumes integer semantics (e.g., arithmetic)

**[FM-2-2] Dual Column Ordering: `processed_at` vs `id`**
- **Scenario:** Step plan says `processed_at` is deprecated but drain() still checks `where(PendingSignalModel.processed_at.is_(None))`. If signals are marked as processed but not handled, they won't be redelivered.
- **Impact:** Signals can get stuck in queue if `processed_at` is set but `handled_at` is NULL
- **Evidence:** Step plan states "processed_at is kept for backward compatibility" but does not specify dual-column logic
- **Mitigation:**
  - Decision point: Should drain() check `processed_at IS NULL` or `handled_at IS NULL` or both?
  - If transitioning: check both: `WHERE processed_at IS NULL OR (processed_at IS NOT NULL AND handled_at IS NULL)`
  - If pure new path: check only `handled_at IS NULL` (and remove `processed_at` check entirely)
  - Document which column is the "source of truth" during transition
  - Task 2 should clarify this; for now, assume checking `processed_at IS NULL` is temporary

**[FM-2-3] Existing Tests May Inspect Schema**
- **Scenario:** Signal-related tests may have assertions like `signal.id == str(uuid.uuid4())` or check that IDs are UUID-formatted
- **Impact:** Tests fail after migration because IDs are now integers
- **Evidence:** Need to grep test files for ID assertions
- **Mitigation:**
  - Search for test assertions on `signal.id` format:
    ```bash
    grep -r "uuid\|UUID" tests/unit/ tests/integration/ | grep signal
    ```
  - Update test helpers and fixtures to use integer IDs
  - Ensure existing signal tests still pass (see Task 6 verification)

**[FM-2-4] Index Name Mismatch Between Migration and ORM**
- **Scenario:** Migration creates `ix_pending_signals_run_id` but ORM model defines index differently (e.g., different name or composite)
- **Impact:** Index exists but ORM doesn't reference it; Django/SQLAlchemy may try to create a duplicate
- **Evidence:** ORM definition at line 280: `Index("ix_pending_signals_run_id", "run_id")` ✓ matches migration
- **Mitigation:**
  - ✅ Verified: Index name matches
  - Test that schema introspection sees the index

#### File References & Verification
- ✅ ORM model location: `src/orchestrator/db/orm/models.py:276`
- ✅ Signal transport location: `src/orchestrator/workflow/signals/signals.py:72`
- ✅ Current drain() query: line 118-124 (orders by `created_at`, checks `processed_at IS NULL`)
- ✅ Index defined in ORM: line 280 `Index("ix_pending_signals_run_id", "run_id")`

#### Hardening Checklist
- [ ] Update ORM model: `id: Mapped[int]`, add `delivered_at`, `handled_at` columns
- [ ] Document integer→string type conversion in dataclass
- [ ] Decide: is `processed_at` checked in drain() during transition or removed immediately?
- [ ] Update drain() query to order by integer PK
- [ ] Update `PendingSignal` dataclass to include new columns
- [ ] Grep tests for ID format assertions; update if necessary
- [ ] Verify index name consistency between migration and ORM
- [ ] Test type conversions: `int(signal.id)` works, `str(int_id)` works

---

### Task 3: Add STOPPING State to RunStatus Enum

#### Assumptions
1. `RunStatus` enum is defined at `src/orchestrator/config/enums.py:6` ✓
2. No database-level CHECK constraint on `status` column (verified in code: no constraints found)
3. Enum value `"stopping"` does not conflict with existing values
4. All enum variants are represented as lowercase strings

#### Expected Outputs
- `RunStatus.STOPPING = "stopping"` enum value added
- Enum can be imported and used in code
- String representation is `"stopping"` (matches lowercase pattern)
- Enum value can be stored in `runs.status` column without violating any constraints

#### Critical Failure Modes

**[FM-3-1] No Database CHECK Constraint Found, but Future One May Exist**
- **Scenario:** Currently no CHECK constraint, but one could be added in production DBs not under test. Migration succeeds on test DB but fails on prod.
- **Impact:** Production migration fails; DBs with STOPPING status cannot be updated
- **Evidence:** Verified in `src/orchestrator/db/orm/models.py` — no CHECK constraint defined. However, this could be manually added to production DBs.
- **Mitigation:**
  - If CHECK constraint is ever added, migration must include:
    ```python
    op.execute("ALTER TABLE runs DROP CONSTRAINT check_status;")
    op.execute("ALTER TABLE runs ADD CONSTRAINT check_status CHECK (status IN ('draft', 'active', 'stopping', 'paused', 'completed', 'failed'));")
    ```
  - Document: "If your production DB has a CHECK constraint on `status`, ensure migration includes constraint update"
  - Test on DBs with and without constraints

**[FM-3-2] Enum Ordering Affects UI and Iteration Logic**
- **Scenario:** Current enum order is DRAFT, ACTIVE, PAUSED, COMPLETED, FAILED. New STOPPING is inserted between ACTIVE and PAUSED. If code iterates over enum members expecting a specific order, results change.
- **Impact:** UI dropdowns, loops over status values, or validation logic may break
- **Evidence:** Need to search for `for status in RunStatus:` or similar iteration patterns
- **Mitigation:**
  - Grep for enum iteration:
    ```bash
    grep -r "for.*in.*RunStatus\|list(RunStatus)" src/
    ```
  - If iteration is used, document the new order or use explicit lists instead of enum iteration
  - Add comment: "STOPPING is inserted before PAUSED; if order matters, use explicit list"

**[FM-3-3] Enum Value String Inconsistency**
- **Scenario:** Other status values use lowercase (`"draft"`, `"active"`). STOPPING must also be lowercase (`"stopping"`), but typo could set it to `"Stopping"` or `"STOPPING"`.
- **Impact:** Code comparing `run.status == "STOPPING"` fails (case mismatch)
- **Evidence:** Current enum pattern is consistently lowercase
- **Mitigation:**
  - ✅ Step plan specifies lowercase `"stopping"` — verify in code review
  - Lint rule or automated check to ensure enum values are lowercase (already enforced by pattern)

#### File References & Verification
- ✅ Enum location: `src/orchestrator/config/enums.py:6`
- ✅ Current status values: DRAFT, ACTIVE, PAUSED, COMPLETED, FAILED (all lowercase)
- ✅ No database constraints: verified in ORM models

#### Hardening Checklist
- [ ] Add `STOPPING = "stopping"` between ACTIVE and PAUSED (or at end, specify order in comment)
- [ ] Verify enum can be imported: `from orchestrator.config.enums import RunStatus; print(RunStatus.STOPPING)`
- [ ] Grep for enum iteration logic; document if order-dependent
- [ ] Test that enum value can be stored in DB: `run.status = RunStatus.STOPPING.value; session.commit()`
- [ ] If CHECK constraint is ever added, migration must handle it

---

### Task 4: Add STOPPING State Machine Guards in Workflow Engine and API

#### Assumptions
1. `WorkflowEngine` exists at `src/orchestrator/workflow/engine/engine.py` ✓
2. State transition methods exist: `start_task()`, `submit_for_verification()` (in engine or service)
3. API routers are at `src/orchestrator/api/routers/runs.py` ✓
4. Guards can be in engine, service, or router (step plan is unclear which is preferred)
5. Error handling converts engine errors to HTTP responses (ValueError → 409)

#### Expected Outputs
- `_is_valid_transition()` function exists and validates STOPPING state rules
- `start_task()` and `submit_for_verification()` reject STOPPING runs with ValueError
- API endpoints return 409 Conflict for disallowed operations on STOPPING runs
- Error messages clearly distinguish STOPPING from PAUSED

#### Critical Failure Modes

**[FM-4-1] Component Wiring Unclear: Which Layer Enforces Guards?**
- **Scenario:** Step plan shows guards in Engine, Service, and API, but doesn't specify which is primary. If guards are only in API, and a service method is called directly (e.g., from async task), the guard is bypassed.
- **Impact:** Guards are ineffective if bypassed through direct service calls; STOPPING runs could be modified
- **Evidence:** Step plan example code shows guards in multiple layers but says "add guards" without specifying single source of truth
- **Mitigation:**
  - **Decision:** Enforce guards in `WorkflowEngine` (closest to state transitions), make API guards redundant but fail-safe
  - Structure:
    1. Engine rejects STOPPING in all state-change methods
    2. API checks run status and returns 409 before calling engine
    3. API also catches engine errors and converts to 409
  - Verify all code paths that change run state call through engine (or service that delegates to engine)

**[FM-4-2] Error Type Mapping Not Specified**
- **Scenario:** Engine raises `ValueError("Cannot start task on stopping run")`, but API expects this exact error type. If engine raises `InvalidTransitionError` instead, API handler doesn't catch it.
- **Impact:** Unhandled exception in API → 500 error instead of 409, bad UX
- **Evidence:** Step plan shows `ValueError` in engine but `HTTPException(status_code=409)` in API; mapping is implicit
- **Mitigation:**
  - Define custom error class or explicitly map ValueError types:
    ```python
    try:
        await engine.start_task(...)
    except ValueError as e:
        if "stopping" in str(e).lower():
            raise HTTPException(status_code=409, detail=str(e))
        raise  # Re-raise other ValueErrors
    ```
  - OR create `RunStoppingError(ValueError)` for precision
  - Document: "All STOPPING violations raise ValueError with 'stopping' in message"
  - Test that proper exception is raised and mapped to 409

**[FM-4-3] STOPPING Guard Is Defensive Only (No Code Creates STOPPING State)**
- **Scenario:** Guards reject invalid STOPPING transitions, but no code in this step actually creates STOPPING runs. Guards are tested but unused in practice.
- **Impact:** False confidence; guards may have gaps that aren't caught until Phase 2 when consumer actually uses STOPPING
- **Evidence:** Only the consumer (Phase 2) will set run status to STOPPING. Phase 1 has no producer of STOPPING.
- **Mitigation:**
  - ✅ This is expected for Phase 1 (schema-only). Document in test comments: "STOPPING is manually created in tests; real transitions in Phase 2"
  - Include test that manually creates STOPPING run and verifies all guards reject operations:
    ```python
    run.status = RunStatus.STOPPING.value
    session.commit()

    # Verify all operations rejected
    with pytest.raises(ValueError, match="stopping"):
        await engine.start_task(task.id, run.id)
    ```
  - This gives confidence guards work, even if no code path creates STOPPING yet

**[FM-4-4] Race Condition: Status Checked Then Changed**
- **Scenario:** API endpoint checks run status is not STOPPING, then another request changes status to STOPPING before the first request performs the operation. Classic TOCTOU (Time-Of-Check-Time-Of-Use) race.
- **Impact:** Two requests could both pass the STOPPING check and conflict
- **Evidence:** Multi-request scenario; no synchronization specified in guards
- **Mitigation:**
  - ✅ Out of scope for this step (would require pessimistic locking, future work)
  - Document: "STOPPING guards are advisory; for strong guarantees, add pessimistic lock"
  - Note: Existing code likely has same TOCTOU issue; STOPPING guard is no worse

**[FM-4-5] Guards Don't Reject All Invalid Operations**
- **Scenario:** Step plan shows guards for `start_task()`, `submit_for_verification()`, and API pause/resume/restart/cancel. But other operations (e.g., `complete_step()`, `fail_task()`) may also be invalid on STOPPING and aren't guarded.
- **Impact:** Incomplete guard coverage; edge cases allow invalid operations
- **Evidence:** Step plan doesn't list all state-changing methods; assumption is that only listed ones need guards
- **Mitigation:**
  - Audit all public state-change methods in `WorkflowEngine`:
    - `start_task()` ✓ (guarded)
    - `submit_for_verification()` ✓ (guarded)
    - `complete_step()` ? (check if needs guard)
    - `fail_task()` ? (check if needs guard)
    - `retry_task()` ? (check if needs guard)
    - Any others?
  - For each method, add guard: "if run.status == STOPPING: raise ValueError(...)"
  - Step plan should clarify "guards on all state changes" not just listed ones

#### File References & Verification
- ✅ Engine location: `src/orchestrator/workflow/engine/engine.py`
- ✅ Routers location: `src/orchestrator/api/routers/runs.py`
- ✅ Status field: `runs.status` (string type, no CHECK constraint)
- ⚠️ Guard location unclear: engine methods? service methods? both?

#### Hardening Checklist
- [ ] Decide guard location: Engine (primary) or API (defensive)?
- [ ] Define error type for STOPPING violations; document in docstring
- [ ] Implement guards in all state-change methods: `start_task()`, `submit_for_verification()`, `complete_step()`, others
- [ ] API endpoints map errors to 409 Conflict (or call engine that raises ValueError)
- [ ] Write test that manually creates STOPPING run and verifies guards work
- [ ] Audit all methods that change run state; add guards to any missed
- [ ] Document that guards are defensive (real STOPPING creation is in Phase 2)

---

### Task 5: Add RUN_START Signal Type to WorkflowSignal Enum

#### Assumptions
1. `WorkflowSignal` enum is at `src/orchestrator/workflow/signals/signals.py:24` ✓
2. Enum is a string enum (inherits from `enum.Enum`)
3. Serialization/deserialization already handles all enum types uniformly
4. No handlers are wired yet (Phase 2 will add handlers)

#### Expected Outputs
- `WorkflowSignal.RUN_START = "run_start"` enum value added
- Signal can be enqueued and deserialized
- No handler implementation (deferred to Phase 2)

#### Critical Failure Modes

**[FM-5-1] Unhandled Signals Accumulate in Queue**
- **Scenario:** RUN_START signals are enqueued but no consumer/handler exists (handlers are Phase 2). Signals sit in `pending_signals` table indefinitely.
- **Impact:** Queue grows without bound; potential space/performance issue; confusion about why signals aren't being processed
- **Evidence:** Handlers are implemented in Phase 2, not Phase 1
- **Mitigation:**
  - ✅ Expected behavior for Phase 1 (schema only)
  - Document in code: "RUN_START signal type added; handler in Phase 2 (Consumer module)"
  - Add comment in enum:
    ```python
    RUN_START = "run_start"  # Consumer processes these in Phase 2; Phase 1 adds type only
    ```
  - Include note in test: "RUN_START can be enqueued; handling is not implemented yet"

**[FM-5-2] Serialization Format Mismatch**
- **Scenario:** If RUN_START has special payload structure (e.g., required fields), but generic serialization assumes all signals have the same format, deserialization could fail.
- **Impact:** Signals can't be parsed; queue backup
- **Evidence:** Need to know if RUN_START payload is null or structured
- **Mitigation:**
  - Document expected payload for RUN_START (assume null for now; Phase 2 may specify)
  - Test serialization round-trip:
    ```python
    signal = await transport.enqueue("run-1", WorkflowSignal.RUN_START, payload=None)
    assert signal.signal_type == WorkflowSignal.RUN_START
    assert signal.payload is None
    ```

**[FM-5-3] No Validation That Signal Type Is Valid**
- **Scenario:** Code can create signals with invalid types (e.g., typo in enum name). Validation happens only at deserialization time, so invalid signals sit in queue until drained.
- **Impact:** Signals with corrupted signal_type can't be processed; queue stalls
- **Evidence:** Deserialization uses `WorkflowSignal(model.signal_type)` which raises ValueError if type not in enum
- **Mitigation:**
  - ✅ Serialization already validates (only enum values can be passed)
  - Document: "Only WorkflowSignal enum values are valid; direct SQL inserts bypass validation"
  - Test that invalid signal_type raises error on deserialization

#### File References & Verification
- ✅ Enum location: `src/orchestrator/workflow/signals/signals.py:24`
- ✅ Current signal types: PAUSE, RESUME, CANCEL, ACTIVITY_COMPLETED, ACTIVITY_VERIFIED (all lowercase with underscores)
- ✅ Serialization: `signal_type.value` (string)
- ✅ Deserialization: `WorkflowSignal(model.signal_type)` (enum constructor)

#### Hardening Checklist
- [ ] Add `RUN_START = "run_start"` to enum (lowercase with underscore, matching pattern)
- [ ] Document that handlers are deferred to Phase 2
- [ ] Test serialization: `await transport.enqueue(..., WorkflowSignal.RUN_START)`
- [ ] Test deserialization: `WorkflowSignal("run_start")` returns enum value
- [ ] Note that unhandled RUN_START signals are expected in Phase 1

---

### Task 6: Write Unit Tests for STOPPING State Transitions

#### Assumptions
1. Test fixtures (`engine`, `session`, `client`) are available in conftest
2. Test database can be created in memory or as fresh SQLite file
3. API client can be created via `TestClient(app)`
4. Async test support via `pytest-asyncio`

#### Expected Outputs
- Test file `tests/unit/test_stopping_state.py` created
- Tests cover valid/invalid transitions, API guards, signal serialization
- All tests pass without modifying existing tests
- Type checking passes

#### Critical Failure Modes

**[FM-6-1] COMPONENT WIRING: Guards Are Not Actually Invoked**
- **Scenario:** Tests verify that guards *can* reject STOPPING operations, but if the guards are not called in the production code path, tests pass while real code fails. Example: API endpoint is tested but never calls the guard; only service method has it.
- **Impact:** False confidence; real system doesn't enforce guards despite passing tests
- **Evidence:** This is a systematic testing failure; requires end-to-end verification
- **Mitigation (CRITICAL):**
  - **Write integration test that doesn't mock:** Call API endpoint → verify 409
  - Don't mock the service or engine; use real in-memory DB
  - Example structure:
    ```python
    async def test_pause_stopping_run_integration(client: TestClient, session: AsyncSession):
        # Step 1: Create run and manually set to STOPPING (simulating Phase 2 consumer)
        run = RunModel(id="test-run", status="stopping", ...)
        session.add(run)
        await session.commit()

        # Step 2: Call real API endpoint (not mocked)
        response = client.post(f"/api/runs/{run.id}/pause")

        # Step 3: Verify 409 Conflict
        assert response.status_code == 409
        assert "stopping" in response.json()["detail"].lower()
    ```
  - This test verifies the entire code path, not just the guard in isolation
  - If test passes, you know guards are wired correctly

**[FM-6-2] Test Fixtures Not Available**
- **Scenario:** Test imports `engine: WorkflowEngine` or `client: TestClient` but conftest doesn't provide these fixtures
- **Impact:** Test file doesn't run; missing fixture error
- **Evidence:** Need to check conftest.py for available fixtures
- **Mitigation:**
  - Search conftest:
    ```bash
    grep -r "def engine\|def client\|def session" tests/conftest.py
    ```
  - If not found, create them or use pytest-async-sqlalchemy fixtures
  - Document fixture setup in test file comments

**[FM-6-3] Test Data Collision: Multiple Tests Create Same Run**
- **Scenario:** All tests use `id="test-run-stopping"`. If tests run in parallel or DB isn't cleaned between tests, duplicate key errors
- **Impact:** Test failure due to unique constraint violation, not test logic
- **Evidence:** Fixture doesn't specify cleanup
- **Mitigation:**
  - Use unique test IDs: `id=f"test-run-stopping-{uuid.uuid4()}"` or fixture-provided ID
  - OR use session-scoped cleanup fixture that truncates tables between tests
  - Recommended: use `pytest.fixture` with autouse=True to cleanup:
    ```python
    @pytest.fixture(autouse=True)
    async def cleanup(session):
        yield
        await session.execute(delete(RunModel))
        await session.commit()
    ```

**[FM-6-4] API Endpoint Path May Not Match Router Definition**
- **Scenario:** Test calls `/api/runs/{id}/pause` but router defines `/runs/{id}/pause` (without `/api` prefix), or prefix is registered differently
- **Impact:** Test gets 404 instead of the guarded endpoint, test fails but for wrong reason
- **Evidence:** Need to check router registration in main app
- **Mitigation:**
  - Verify endpoint in routers/runs.py:
    ```bash
    grep -n "@router.post" src/orchestrator/api/routers/runs.py | grep pause
    ```
  - Check main app registration:
    ```bash
    grep -n "include_router.*runs" src/orchestrator/app.py
    ```
  - Ensure test path matches actual endpoint (including `/api` prefix if used)

**[FM-6-5] Tests Assume Endpoints Exist But They May Not Be Implemented**
- **Scenario:** Step plan says "add API guards" but doesn't specify which endpoints. Tests call `pause_run`, `resume_run`, etc., but if these endpoints don't exist yet, tests fail.
- **Impact:** Can't distinguish "guard not working" from "endpoint doesn't exist"
- **Evidence:** Need to grep routers/runs.py for actual endpoints
- **Mitigation:**
  - Check which endpoints exist:
    ```bash
    grep "@router.post" src/orchestrator/api/routers/runs.py
    ```
  - Only test endpoints that exist; skip others in this phase
  - Document which endpoints are tested vs. deferred

**[FM-6-6] Async/Sync Test Mismatch**
- **Scenario:** Test defines `async def test_...` with `@pytest.mark.asyncio`, but fixtures are sync (`session: AsyncSession` without async fixture)
- **Impact:** Type mismatch or fixture not injected correctly
- **Evidence:** Conftest must provide async fixtures
- **Mitigation:**
  - Use `async_session` fixture from `pytest-async-sqlalchemy` or similar
  - Mark all async tests with `@pytest.mark.asyncio`
  - Use `await session.commit()` not `session.commit()`
  - Document fixture setup

#### File References & Verification
- ✅ Test location: `tests/unit/test_stopping_state.py` (does not exist yet)
- ⚠️ Conftest fixtures: Not verified; need to check available fixtures
- ⚠️ API endpoints: Need to verify which pause/resume/restart/cancel endpoints exist

#### Hardening Checklist
- [ ] Check conftest.py for available fixtures (engine, session, client)
- [ ] Create fixtures if not available
- [ ] Write end-to-end integration tests (not just mocks)
- [ ] Verify API endpoint paths match router definitions
- [ ] Use unique test run IDs to avoid collisions
- [ ] Add cleanup fixture to truncate DB between tests
- [ ] Test both valid and invalid STOPPING transitions
- [ ] Test signal serialization (RUN_START)
- [ ] Verify test assertions match expected behavior

---

### Task 7: Verify Migration and Run Regression Test Suite

#### Assumptions
1. All previous tasks (1-6) are complete
2. Test database is accessible and writable
3. Full test suite exists and passes before this step
4. Server can be started in isolation

#### Expected Outputs
- Migration applied to dev DB without errors
- Schema is correct (integer PK, delivery tracking columns)
- All existing tests pass
- Type checking passes
- Server starts without errors

#### Critical Failure Modes

**[FM-7-1] Database Locked During Migration**
- **Scenario:** Server is running and holding DB lock. Migration attempt fails with "database is locked" error.
- **Impact:** Migration aborts; DB state unchanged or partially changed
- **Evidence:** Common with SQLite (which has DB-level locking)
- **Mitigation:**
  - Kill any running servers before migration:
    ```bash
    pkill -f uvicorn
    sleep 2
    ```
  - Or use exclusive lock timeout:
    ```bash
    sqlite3 orchestrator.db "PRAGMA busy_timeout = 30000;"  # 30s timeout
    ```
  - Document: "Ensure server is stopped before running migration"

**[FM-7-2] Migration Already Applied / Idempotency Issue**
- **Scenario:** If migration is run twice (e.g., failed first time, retry without cleanup), second run fails with "table already exists" or "column already exists"
- **Impact:** Can't re-apply migration; manual cleanup required
- **Evidence:** Alembic tracks applied migrations; re-running same revision fails
- **Mitigation:**
  - Check migration history:
    ```bash
    uv run alembic current  # Shows current revision
    uv run alembic history --rev-range :HEAD  # Shows all applied revisions
    ```
  - If already applied, skip it: `uv run alembic stamp <revision>` (if needed)
  - Document: "Verify migration is not already applied before running"

**[FM-7-3] Test Suite Expectations Changed By Schema**
- **Scenario:** Existing tests have hard-coded expectations about `pending_signals` schema. Migration changes column types (UUID → integer); tests that check column types or create signals directly fail.
- **Impact:** Tests fail after migration; regression not due to code changes but schema assumptions
- **Evidence:** Tests like `test_signal_creation` may check `signal.id` format
- **Mitigation:**
  - Grep tests for schema assumptions:
    ```bash
    grep -r "uuid\|UUID\|str(id)\|type(.*\.id)" tests/ | grep signal
    ```
  - Update test helpers to create signals with integer IDs (or string IDs, depending on schema)
  - Update assertions to not assume UUID format
  - Ensure signal creation tests pass after migration

**[FM-7-4] No Rollback Testing**
- **Scenario:** Migration is applied but downgrade is not tested. If production needs rollback, downgrade fails.
- **Impact:** Stuck in bad schema state; unable to rollback
- **Evidence:** Step plan task 7 does not include explicit downgrade test
- **Mitigation:**
  - Add to verification script:
    ```bash
    echo "Testing downgrade..."
    uv run alembic downgrade -1
    echo "Verifying downgrade..."
    sqlite3 orchestrator.db ".schema pending_signals" | grep id
    ```
  - Confirm schema reverted to UUID PK
  - Then re-apply upgrade to confirm idempotency

**[FM-7-5] TypeScript Type Check Fails**
- **Scenario:** Frontend type check fails because `RunStatus.STOPPING` is not in frontend types
- **Impact:** TypeScript build breaks; frontend can't be deployed
- **Evidence:** Frontend types are separate from backend enums
- **Mitigation:**
  - Update frontend types file (likely `ui/src/types/runs.ts` or similar):
    ```typescript
    export enum RunStatus {
        Draft = "draft",
        Active = "active",
        Stopping = "stopping",  // Add this
        Paused = "paused",
        Completed = "completed",
        Failed = "failed",
    }
    ```
  - Regenerate frontend types from backend if using automated generation
  - Run `cd ui && npm run type-check` to verify

#### File References & Verification
- ✅ Migration file: `src/orchestrator/db/migrations/versions/m*.py` (will be created)
- ✅ Test database: `orchestrator.db` (default location)
- ⚠️ Frontend types: Likely `ui/src/types/runs.ts` (not yet checked)
- ⚠️ Test expectations: Need to grep for signal schema assumptions

#### Hardening Checklist
- [ ] Kill running servers before migration
- [ ] Check migration history: `uv run alembic current`
- [ ] Apply migration: `uv run alembic upgrade head`
- [ ] Verify schema: `sqlite3 orchestrator.db ".schema pending_signals"`
- [ ] Run full test suite: `uv run pytest tests/ -v`
- [ ] Test downgrade: `uv run alembic downgrade -1`
- [ ] Test re-upgrade: `uv run alembic upgrade head`
- [ ] Run TypeScript check: `cd ui && npm run type-check`
- [ ] Test server startup: `timeout 5 uv run uvicorn scripts.serve:app`
- [ ] Clean up database backup after verification

---

## Cross-Cutting Risks and Concerns

### COMPONENT WIRING (Critical Pattern)

The most critical risk across all tasks is **component wiring failure**: new guards and transitions are implemented but never actually invoked in production code paths.

**Examples:**
- **Task 4 Guards:** Implemented in `WorkflowEngine` but if API never calls engine (or only calls service that doesn't delegate), guards are bypassed
- **Task 5 Signal:** RUN_START type is defined but no code enqueues it. Test can verify it's serializable, but it never gets used.
- **Task 6 Tests:** Tests verify guards exist but don't test that guards are actually called in the code path

**Mitigation:**
For each new component (guard, signal type, state transition), explicitly verify:
1. **Exists:** Class/function/enum value defined ✓
2. **Reachable:** Can be imported from production code ✓
3. **Invoked:** Called in at least one production code path (currently false for RUN_START; will be true in Phase 2)
4. **Tested:** End-to-end test that doesn't mock the component (not just unit test)

For Phase 1, RUN_START and STOPPING states are deliberately not invoked (that's Phase 2). But **guards must be tested end-to-end** to ensure they're called.

### Schema Persistence Complete?

| Layer | Checked |
|-------|---------|
| DB Schema (Alembic migration) | ✅ Yes |
| ORM Model | ✅ Yes |
| Dataclass/Transport | ✅ Yes |
| Serialization | ✅ Yes (signal_type.value → JSON) |
| Deserialization | ✅ Yes (WorkflowSignal(string)) |
| Tests | ⚠️ Partial (need to verify no schema assumptions) |
| Frontend Types | ⚠️ Missing (need to add RunStatus.STOPPING) |

**Action:** Update frontend types for STOPPING enum value.

### Async/Infrastructure Dependencies

| Component | Dependency | Status |
|-----------|-----------|--------|
| Alembic migration | SQLAlchemy engine | ✅ Existing |
| ORM update | Mapped types | ✅ Existing |
| Signal transport | AsyncSession | ✅ Existing |
| Tests | pytest-asyncio | ✅ Assumed available |
| API tests | FastAPI TestClient | ✅ Assumed available |

**Action:** Verify pytest fixtures provide AsyncSession and TestClient.

---

## Summary: Implementation Hardening Actions

### Pre-Implementation
1. **Verify migration dir path:** Use `src/orchestrator/db/migrations/versions/` not `alembic/versions/`
2. **Check conftest fixtures:** Ensure engine, session, client fixtures are available
3. **Grep for schema assumptions in tests:** Update any test that assumes UUID signal IDs
4. **Find all state-change methods:** Audit WorkflowEngine for all methods that need STOPPING guards

### Implementation
1. **Task 1 (Migration):**
   - Use `batch_alter_table()` for SQLite compatibility
   - Verify PK constraint name before dropping
   - Test backfill with multiple signals at same `created_at`

2. **Task 2 (ORM):**
   - Document integer→string type mismatch in dataclass
   - Clarify: does drain() check `processed_at` or `handled_at` during transition?
   - Update all signal queries to order by integer PK

3. **Task 3 (Enum):**
   - Add comment explaining STOPPING position
   - Grep for enum iteration logic
   - Update frontend types: add RunStatus.STOPPING

4. **Task 4 (Guards):**
   - Specify guard location (Engine primary, API defensive)
   - Define error mapping (ValueError → 409)
   - Audit ALL state-change methods for guards
   - Write end-to-end integration test (real DB, real API)

5. **Task 5 (Signal):**
   - Add comment: "Handlers in Phase 2"
   - Document expected payload format (null)
   - Test serialization round-trip

6. **Task 6 (Tests):**
   - **CRITICAL:** Write integration test that verifies guards are called in real code path
   - Use unique test IDs to avoid collisions
   - Add cleanup fixture
   - Verify API endpoint paths match routers

7. **Task 7 (Verification):**
   - Kill running servers before migration
   - Test migration idempotency
   - Test downgrade/upgrade cycle
   - Update frontend types
   - Verify test schema assumptions are updated

### Post-Implementation
1. Run full test suite (backend + frontend)
2. Verify no schema assumptions in tests
3. Verify guards work end-to-end (not just mocked)
4. Document any deviations from step plan (e.g., which endpoints have guards)
5. Create issue if guards are incomplete (e.g., missing endpoints)

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Migration fails on prod DB | Medium | High | Test on multiple DB states; document recovery |
| Guards not invoked in production | Medium | High | End-to-end integration tests (not mocked) |
| Test schema assumptions fail | Low | Medium | Grep tests for UUID/signal ID assumptions |
| STOPPING state confuses UI | Low | Low | Add clear "Stopping..." indicator (Phase 3) |
| Type mismatch (int PK vs str dataclass) | Low | Low | Document mismatch; avoid arithmetic on IDs |

---

## Traceability to Intent

| Intent ID | Requirement | Step 1 Address | Notes |
|-----------|-------------|----------------|-------|
| [I-07] | FIFO ordering in queue | Task 1, Task 2 | Integer PK + ORDER BY id ✓ |
| [I-08] | Delivery tracking | Task 1, Task 2 | delivered_at, handled_at columns ✓ |
| [I-16] | STOPPING state | Tasks 3, 4, 6 | Enum + guards ✓ |
| [I-26] | RUN_START signal | Task 5, Task 6 | Enum value + serialization tests ✓ |

All intent items addressed; implementation is complete if hardening actions applied.

---

**Final Note:** This analysis is based on static code inspection and step plan review. Actual implementation may reveal additional issues (e.g., test fixtures not matching assumptions). Keep this document updated as implementation proceeds.
