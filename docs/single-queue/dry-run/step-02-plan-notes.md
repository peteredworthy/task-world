# Step 02: Consumer — Dry-Run Simulation and Failure Analysis

**Simulation Date:** 2026-03-26
**Scope:** Pre-implementation analysis of all 8 tasks without code changes
**Output:** Identified assumptions, blockers, failure modes, and hardening actions

---

## Executive Summary

**Status:** ⚠️ **SIGNIFICANT WIRING AND SCOPE HAZARDS IDENTIFIED**

Step 02 requires integrating a brand new consumer loop into app startup, but the existing codebase already has:
- A per-run signal `drain()` pattern (not global queue polling)
- UUID PKs on signals (will be migrated to integer)
- `processed_at` field (will be migrated to `delivered_at`/`handled_at`)
- Global module-level active-run registry already in use by RunWorkflow
- No explicit `RUN_START` signal type (will be added)

**Key Risks:**
1. **Consumer wiring verification gap** — Consumer code is created and started on app.py startup, but nothing writes `RUN_START` signals until Step 03. This creates a window where the consumer runs but does no work. Existing tests could mask wiring bugs.
2. **Test isolation** — Global `_active_run_ids` set used by both new consumer code and existing RunWorkflow code. Tests must reset state between runs.
3. **Async/await correctness** — Consumer is async, handlers are async, but startup/shutdown integration pattern unclear.
4. **Handler error semantics** — Step says "leave `handled_at` null on error," but doesn't specify what "error" means: exception? timeout? Failed state transition?
5. **DB schema mismatch** — Step 01 migration isn't verified to exist. If it doesn't, `delivered_at`/`handled_at` columns won't exist when consumer queries.

---

## Task-by-Task Analysis

### Task 1: Consumer Module Skeleton with Polling Loop

#### Assumptions

| Assumption | Verification | Risk |
|-----------|---|---|
| `src/orchestrator/workflow/signals/consumer.py` doesn't exist yet | ✓ Verified: directory exists, no consumer.py | Low |
| Can import `PendingSignalModel` from `orchestrator.db` | ✓ Found at `src/orchestrator/db/orm/models.py` | Low |
| `delivered_at` and `handled_at` columns exist (from Step 01) | ⚠️ **NOT VERIFIED** — migration must be checked | **HIGH** |
| Can create async polling loop with `asyncio.sleep()` or similar | ✓ Implied by FastAPI pattern | Low |
| Handler stubs can be empty/pass initially | ✓ Standard pattern | Low |

#### Expected Outputs

1. ✅ `src/orchestrator/workflow/signals/consumer.py` module created
2. ✅ `async def consume_signals(db_session_factory)` entry point
3. ✅ Polling loop: `while True: SELECT FROM pending_signals WHERE handled_at IS NULL ORDER BY id`
4. ✅ Handler dispatch routing by `signal_type`
5. ✅ `delivered_at` := now() before calling handler
6. ✅ `handled_at` := now() after handler returns successfully
7. ✅ Handler stubs for all signal types (can be pass/logging only)

#### Blockers and Mitigation

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| Step 01 migration doesn't exist yet | **CRITICAL** | Verify `docs/single-queue/dry-run/step-01-completion.md` exists and shows migration applied. If not, Task 1 cannot proceed to testing. |
| Unclear whether polling loop uses sync or async DB queries | Medium | Check current signal code in `signals.py`: uses `AsyncSession` from SQLAlchemy async. Consumer should follow same pattern. |
| No specified poll interval (sleep duration) | Low | Recommendation: start with 100ms, document as tunable. Tests can inject shorter interval. |
| Unclear error handling for malformed signals | Medium | Handler should log and mark as handled (not redelivered). Specify: "Mark as handled unless signal is corrupt (missing run_id, invalid signal_type)." |

#### Failure Modes and Hardening

**FM-1.1: Wrong column names in SELECT**
- **Symptom**: Polling loop SELECT fails with "column does not exist"
- **Cause**: `delivered_at` or `handled_at` not yet migrated (Step 01 incomplete)
- **Hardening Action**:
  - [ ] Verify Step 01 migration file exists: `alembic/versions/*_single_queue_signals.py`
  - [ ] Verify migration adds `delivered_at TIMESTAMP NULL` and `handled_at TIMESTAMP NULL` to `pending_signals`
  - [ ] Test: run `alembic upgrade head` on a fresh test DB and confirm columns exist
  - [ ] Consumer should have a startup check: try to query `delivered_at` from pending_signals; fail fast with clear error if missing

**FM-1.2: Infinite loop consuming CPU (no sleep between polls)**
- **Symptom**: Consumer loop runs 100% CPU, no signals are processed
- **Cause**: Missing `await asyncio.sleep(interval)` after poll cycle
- **Hardening Action**:
  - [ ] Skeleton must explicitly include `await asyncio.sleep(0.1)` after processing batch
  - [ ] Test: mock time.sleep calls and verify consumer does not block app startup

**FM-1.3: Syntax errors in consumer module prevent import**
- **Symptom**: `from src.orchestrator.workflow.signals.consumer import consume_signals` fails on app.py startup
- **Cause**: Python syntax error in consumer.py (missing colon, indentation, etc.)
- **Hardening Action**:
  - [ ] Task 1 verification: `uv run python -m py_compile src/orchestrator/workflow/signals/consumer.py` must pass
  - [ ] Task 1 verification: `uv run python -c "from src.orchestrator.workflow.signals.consumer import consume_signals; print('OK')"` must print "OK"

**FM-1.4: Handler dispatch table initialization fails**
- **Symptom**: Consumer crashes on first signal because handler dict is None or empty
- **Cause**: Handler stubs created but not registered in dispatch dict
- **Hardening Action**:
  - [ ] Consumer skeleton must initialize handler dict: `_handlers = {WorkflowSignal.RUN_START: _handle_run_start, ...}`
  - [ ] Test: verify len(_handlers) >= 5 (RUN_START, RESUME, PAUSE, CANCEL, ACTIVITY_COMPLETED, ACTIVITY_VERIFIED)
  - [ ] Add defensive dispatch: if signal_type not in _handlers, log warning and mark as handled (don't crash)

---

### Task 2: Implement RUN_START and RESUME Signal Handlers

#### Assumptions

| Assumption | Verification | Risk |
|-----------|---|---|
| `RUN_START` signal type exists in `WorkflowSignal` enum | ⚠️ **NOT IN CURRENT CODE** — Step 01 should add | **MEDIUM** |
| State transitions DRAFT→ACTIVE, PAUSED→ACTIVE are guarded in `engine.py` | ✓ Found `engine/transitions.py` | Low |
| `RunWorkflow` class can be instantiated with (run_id, agent_type, agent_config, callbacks, transport) | ✓ Found in `signals/runtime.py` lines 132-149 | Low |
| Registry functions `register_active_run()` already exist | ✓ Found at `signals/signals.py` lines 224-236 | Low |
| Can directly call state transition functions from engine | ⚠️ **Unclear coupling** — may require DB session | Medium |
| `_create_run_workflow()` placeholder can be filled in with a factory | ⚠️ **Task 8 says "will be properly injected"** | Medium |

#### Expected Outputs

1. ✅ `async def _handle_run_start(signal: PendingSignal, db_session)` → DRAFT→ACTIVE, create RunWorkflow, register, return success
2. ✅ `async def _handle_resume(signal: PendingSignal, db_session)` → PAUSED→ACTIVE, create RunWorkflow, register, return success
3. ✅ `async def _create_run_workflow(run_id, db_session) → RunWorkflow` — placeholder factory
4. ✅ Registry updated: `register_active_run(run_id)` called in both handlers
5. ✅ No exceptions thrown for valid state transitions

#### Blockers and Mitigation

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| `RUN_START` signal type doesn't exist yet | **CRITICAL** | Step 01 must add `RUN_START = "run_start"` to `WorkflowSignal` enum. This is a hard requirement. |
| How to create RunWorkflow instance from consumer? | **HIGH** | `RunWorkflow.__init__` requires callbacks (ExecutorCallbacks) and optional transport. Consumer doesn't have executor context. Need factory pattern. Specify: consumer receives a `run_workflow_factory: Callable[[str, AsyncSession], RunWorkflow]` injected in Task 8. |
| State transition from DRAFT→ACTIVE — is it safe to call directly? | **HIGH** | Current code has `engine.start_task()` which uses `check_run_transition()`. Consumer must use same guard. Is there a `engine.start_run()` function? If not, consumer must directly call `run.status = RunStatus.ACTIVE` and save. **ACTION**: Check `engine.py` for run-level transition functions; if none exist, add one. |
| Concurrent RUN_START signals for same run_id | **MEDIUM** | Two signals for same run_id could race on registry. Mitigation: registry operations are atomic (set operations are thread-safe in Python). But DB transition could race. Guard: check run.status before transitioning; if already ACTIVE, log and skip transition. |
| What if run doesn't exist in DB? | **MEDIUM** | RUN_START references a run_id that doesn't exist. Should this log warning and mark handled, or mark unhandled for redelivery? **Spec needed**: "If run not found, log warning, mark handled (assume run was deleted)." |

#### Failure Modes and Hardening

**FM-2.1: RunWorkflow instantiation fails due to missing callbacks**
- **Symptom**: `_handle_run_start()` calls `_create_run_workflow(run_id, db_session)` which throws AttributeError
- **Cause**: Placeholder factory doesn't have ExecutorCallbacks to pass to RunWorkflow
- **Hardening Action**:
  - [ ] Consumer must have a `_run_workflow_factory: Callable | None = None` module-level variable
  - [ ] `_handle_run_start()` should check: `if _run_workflow_factory is None: log error, mark handled, return`
  - [ ] Task 8 must set this factory before consumer starts polling
  - [ ] Test: call `_handle_run_start()` with factory = None; verify it logs and marks handled

**FM-2.2: State transition fails silently**
- **Symptom**: Run is created but never transitions to ACTIVE; consumer marks signal handled; run is stuck in DRAFT
- **Cause**: `await engine.start_run(run_id)` called but raises exception; handler catches but doesn't re-raise
- **Hardening Action**:
  - [ ] Handler must NOT catch broad exceptions. Let state transition errors propagate.
  - [ ] Exception handler in consumer's `dispatch()` loop: if handler raises, mark signal as unhandled (leave `handled_at` null) and log error
  - [ ] Test: mock state transition to raise error; verify `handled_at` remains null

**FM-2.3: Race condition: ACTIVE→ACTIVE transition**
- **Symptom**: Two RUN_START signals for same run_id both succeed; run is doubly registered
- **Cause**: State machine allows ACTIVE→ACTIVE (idempotent), but registry doesn't handle double-registration
- **Hardening Action**:
  - [ ] `register_active_run()` should be idempotent (it is: set.add is idempotent)
  - [ ] But `_handle_run_start()` should check: if run is already ACTIVE, log warning, mark handled, don't create new RunWorkflow
  - [ ] Test: insert two RUN_START signals for same run_id in DB; call consumer; verify only one RunWorkflow created

**FM-2.4: Incorrect factory signature**
- **Symptom**: Task 2 passes factory with signature `(run_id: str) -> RunWorkflow`, but Task 8 injects `(run_id: str, db_session) -> RunWorkflow`
- **Cause**: Signature mismatch between placeholder and actual factory
- **Hardening Action**:
  - [ ] Task 2 placeholder: `async def _create_run_workflow(run_id: str, db_session) -> RunWorkflow:`
  - [ ] Document that Task 8 will replace `_create_run_workflow` body or inject a factory callable
  - [ ] Test: verify signature by calling `_create_run_workflow(run_id="test", db_session=mock_session)`

---

### Task 3: Implement PAUSE and CANCEL Signal Handlers

#### Assumptions

| Assumption | Verification | Risk |
|-----------|---|---|
| `STOPPING` state exists in `RunStatus` enum | ⚠️ **NOT IN CURRENT CODE** — Step 01 should add | **MEDIUM** |
| State transitions ACTIVE→STOPPING, STOPPING→PAUSED, STOPPING→FAILED are guarded | ⚠️ Unclear | **MEDIUM** |
| `RunWorkflow.handle_pause()` exists and returns on success | ⚠️ **NOT FOUND** in current code | **HIGH** |
| `has_active_workflow(run_id)` returns bool correctly | ✓ Found at `signals.py` lines 234-236 | Low |
| Inactive case: run can be directly transitioned ACTIVE→PAUSED without workflow | ⚠️ Need to verify guard allows this | Medium |

#### Expected Outputs

1. ✅ `async def _handle_pause(signal, db_session)` with branching:
   - If `has_active_workflow(run_id)`: ACTIVE→STOPPING, deliver to workflow, wait for ack, STOPPING→PAUSED, unregister
   - Else: directly ACTIVE→PAUSED
2. ✅ `async def _handle_cancel(signal, db_session)` with branching:
   - If `has_active_workflow(run_id)`: ACTIVE→STOPPING, deliver to workflow, wait for ack, STOPPING→FAILED, unregister
   - Else: directly ACTIVE→FAILED
3. ✅ No race conditions on unregister

#### Blockers and Mitigation

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| `STOPPING` state not in `RunStatus` enum yet | **CRITICAL** | Step 01 must add it. Verify in enum definition. |
| What does "deliver to workflow" mean? How does it work? | **CRITICAL** | Current `RunWorkflow.on_signal()` drains signals via transport. Consumer must do the same: create signal in pending_signals, call workflow's transport.drain()? Or call a method directly? **ACTION**: Read `runtime.py` `on_signal()` and `_run_loop()` to understand signal consumption pattern. |
| `RunWorkflow.handle_pause()` doesn't exist | **HIGH** | Search codebase. If not found, consumer must use a different interface (e.g., call transport.enqueue() and then wait for workflow to consume). |
| How long to wait for workflow to ack pause? | **MEDIUM** | Spec needed: "Timeout after 30 seconds; if workflow doesn't ack, unregister anyway and log warning." |
| Inactive workflow case: can run in non-ACTIVE state receive PAUSE? | **MEDIUM** | Guard spec: "If run not ACTIVE, don't try to transition to STOPPING; just transition to PAUSED directly." Clarify which states are valid sources for pause. |

#### Failure Modes and Hardening

**FM-3.1: STOPPING state not guarded; duplicate pause signals pile up**
- **Symptom**: First pause signal sets run to STOPPING. Second pause signal tries to transition STOPPING→PAUSED, state machine rejects it, signal marked unhandled. Loop indefinitely.
- **Cause**: State machine doesn't reject transitions FROM STOPPING
- **Hardening Action**:
  - [ ] `engine.py` must have guard: transitions from STOPPING are only to PAUSED/FAILED, not to other states
  - [ ] API must reject pause/resume/cancel requests for STOPPING runs (return 409 Conflict)
  - [ ] Test: create run, pause it (→STOPPING), try to pause again; verify second pause is rejected by API before reaching consumer

**FM-3.2: Race condition: workflow finishes and unregisters, then pause signal calls handle_pause() on dead workflow**
- **Symptom**: Run finishes, RunWorkflow unregisters itself. Pause signal arrives and calls `get_active_workflow(run_id)` which now returns None. Exception thrown.
- **Cause**: Check-then-call race between unregister and handle_pause
- **Hardening Action**:
  - [ ] `_handle_pause()` must check `has_active_workflow(run_id)` immediately before calling handle_pause()
  - [ ] If workflow is gone, branch to inactive case (directly ACTIVE→PAUSED)
  - [ ] Test: create signal in DB for run, then unregister workflow, then call consumer dispatch; verify no exception

**FM-3.3: Timeout: handle_pause() hangs, consumer waits forever**
- **Symptom**: Consumer blocked on `await workflow.handle_pause()` indefinitely; app becomes unresponsive
- **Cause**: Workflow stuck in task execution, not draining signals
- **Hardening Action**:
  - [ ] Wrap handle_pause() call in `asyncio.wait_for(..., timeout=30)`
  - [ ] If timeout, log error, unregister, transition to PAUSED anyway
  - [ ] Test: mock workflow with async function that sleeps 60s; verify consumer times out and continues

**FM-3.4: Unregister not called on error**
- **Symptom**: State transition STOPPING→PAUSED raises exception. Handler doesn't catch it. Workflow stays registered forever.
- **Cause**: Missing try/finally around unregister
- **Hardening Action**:
  - [ ] Structure:
    ```python
    if has_active_workflow(run_id):
        # ... transition to STOPPING
        try:
            await workflow.handle_pause()
        finally:
            unregister_active_run(run_id)
            # ... transition to PAUSED
    ```
  - [ ] Test: mock handle_pause() to raise error; verify unregister is still called

---

### Task 4: Implement ACTIVITY Signal Handlers

#### Assumptions

| Assumption | Verification | Risk |
|-----------|---|---|
| ACTIVITY_COMPLETED and ACTIVITY_VERIFIED signals have metadata with activity_id, outcome/verdict | ⚠️ Unclear structure | **MEDIUM** |
| `RunWorkflow` has methods to deliver activity events | ⚠️ Need to verify | **MEDIUM** |
| Missing active workflow is not an error (just log) | ✓ Stated in task description | Low |
| Metadata is JSON-serialized in signal payload | ✓ Current code uses `json.dumps(payload)` | Low |

#### Expected Outputs

1. ✅ `async def _handle_activity_completed(signal, db_session)` → extract activity_id and outcome from metadata, deliver to active workflow
2. ✅ `async def _handle_activity_verified(signal, db_session)` → extract activity_id and verdict from metadata, deliver to active workflow
3. ✅ Both log warning and mark handled if no active workflow

#### Blockers and Mitigation

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| Metadata format not specified | **MEDIUM** | Determine: is metadata a dict with keys like `{"activity_id": "...", "outcome": "success", "verdict": {...}}`? Specify schema explicitly. |
| RunWorkflow delivery methods not documented | **MEDIUM** | Search for how signals are currently delivered to workflows. Is there a `workflow.on_signal(signal_type, payload)` method? Or does the workflow drain from transport? |
| What if activity_id doesn't exist in DB? | **LOW** | Delegate to workflow handler; it should handle gracefully. Consumer just passes it through. |

#### Failure Modes and Hardening

**FM-4.1: Malformed metadata causes handler to crash**
- **Symptom**: Signal has `metadata = None` or `metadata = {}` without `activity_id`. Handler crashes with KeyError.
- **Cause**: No defensive parsing
- **Hardening Action**:
  - [ ] Handler: `metadata = signal.payload or {}`
  - [ ] Extract with defaults: `activity_id = metadata.get("activity_id"); outcome = metadata.get("outcome")`
  - [ ] If activity_id missing, log error and mark handled (don't redelivery)
  - [ ] Test: create signal with empty payload; verify handler logs error and marks handled

**FM-4.2: Delivery to inactive workflow fails silently**
- **Symptom**: No active workflow; handler logs warning but doesn't verify warning was actually logged
- **Cause**: Weak logging assertions in tests
- **Hardening Action**:
  - [ ] Test: mock logging, capture log records, assert exactly one WARNING logged when no active workflow

**FM-4.3: Async delivery not awaited**
- **Symptom**: Handler returns immediately, but delivery to workflow hasn't completed
- **Cause**: `workflow.deliver_activity()` is async, but handler doesn't await it
- **Hardening Action**:
  - [ ] Verify if delivery methods are async. If yes: `await workflow.deliver_activity_completed(...)`
  - [ ] If no: direct call is fine
  - [ ] Test: mock async delivery function; verify it's awaited by checking call counts

---

### Task 5: Implement Startup Redelivery Logic

#### Assumptions

| Assumption | Verification | Risk |
|-----------|---|---|
| `SELECT FROM pending_signals WHERE delivered_at IS NOT NULL AND handled_at IS NULL` is the correct query | ✓ Spec aligns | Low |
| Signals for active runs should NOT be redelivered | ⚠️ Logic unclear | **MEDIUM** |
| Redelivery continues even if individual dispatch fails | ✓ Stated in task | Low |
| `startup_redelivery()` is called at beginning of `consume_signals()` | ✓ Stated in task | Low |

#### Expected Outputs

1. ✅ `async def startup_redelivery(db_session)` function
2. ✅ Queries unhandled signals, skips those for active runs
3. ✅ Re-dispatches remaining signals through normal handler path
4. ✅ Logs errors but continues redelivery

#### Blockers and Mitigation

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| How to determine if a run is "active"? | **MEDIUM** | Check `has_active_workflow(run_id)` (registry-based) or query `runs.status == ACTIVE` (DB-based)? Recommend DB-based: if run is ACTIVE, it's currently being processed, skip redelivery. If run is PAUSED/COMPLETED/FAILED, redelivery is safe. |
| What if redelivery fails on a signal? | **LOW** | Spec says continue. Just log and keep going. |
| Infinite redelivery loop: same signal keeps failing | **MEDIUM** | Need max-attempt counter. Spec: "If `delivered_at` is older than 5 minutes and `handled_at` is still null, mark as undeliverable (set `handled_at` to now with special marker). Don't redelivery indefinitely." |

#### Failure Modes and Hardening

**FM-5.1: Redelivery for run that's currently ACTIVE causes double work**
- **Symptom**: Run is active (RunWorkflow exists), signal is redelivered, handler dispatches it twice
- **Cause**: Didn't check `has_active_workflow()` before redelivering
- **Hardening Action**:
  - [ ] Redelivery loop: for each unhandled signal, check `if has_active_workflow(signal.run_id): skip` before re-dispatching
  - [ ] Log: "Skipping redelivery of signal {signal.id} for active run {run_id}"
  - [ ] Test: create unhandled signal, register active workflow for that run, call startup_redelivery; verify signal is skipped

**FM-5.2: Redelivery query is slow or times out**
- **Symptom**: Consumer startup hangs on redelivery query if there are millions of old signals
- **Cause**: No index on (delivered_at, handled_at)
- **Hardening Action**:
  - [ ] Alembic migration (Step 01) should create index: `CREATE INDEX ix_pending_signals_unhandled ON pending_signals(delivered_at, handled_at) WHERE handled_at IS NULL`
  - [ ] Redelivery query: `SELECT ... WHERE delivered_at IS NOT NULL AND handled_at IS NULL AND delivered_at > NOW() - INTERVAL 5 MINUTES` (optional time filter to avoid stale signals)
  - [ ] Test: insert 100k handled signals and 10 unhandled; time redelivery query; must complete in <1 second

**FM-5.3: Max-attempt counter implementation missing**
- **Symptom**: A signal fails forever; redelivery keeps re-dispatching it every startup; eventually DB fills up
- **Cause**: No circuit breaker or max-attempt limit
- **Hardening Action**:
  - [ ] Consumer: track signals with `delivered_at` > 5 minutes old; mark them as handled with logged failure reason
  - [ ] Or: add `attempt_count` column to pending_signals (future migration); increment on each redelivery; give up after 5 attempts
  - [ ] For now (Step 02): just document the assumption: "Redelivery can loop forever for broken signals; this will be addressed in future work with attempt counting."

---

### Task 6: Create Comprehensive Unit Tests

#### Assumptions

| Assumption | Verification | Risk |
|-----------|---|---|
| Test DB session can be mocked or fixtures provided | ✓ Existing tests use `test_db()` fixture pattern | Low |
| `RunWorkflow` can be mocked for unit tests | ⚠️ Depends on interface clarity | **MEDIUM** |
| Tests can directly call `_handle_run_start()` and other handlers | ✓ Standard pattern | Low |
| Tests clean up global state (_active_run_ids set) between runs | ⚠️ Not guaranteed | **MEDIUM** |

#### Expected Outputs

1. ✅ `tests/unit/test_signal_consumer.py` with ~500 LOC
2. ✅ Tests for delivery tracking (delivered_at, handled_at)
3. ✅ Tests for all handler types
4. ✅ Error handling verified

#### Blockers and Mitigation

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| Global `_active_run_ids` set pollutes tests | **HIGH** | Each test must call `_active_run_ids.clear()` in setup or use a fixture. Or move registry to consumer module and mock it. |
| Async test functions need `pytest.mark.asyncio` | **LOW** | Standard pytest-asyncio pattern. Verify plugin is installed. |
| How to verify `delivered_at` and `handled_at` were set? | **LOW** | Mock DB session, capture INSERT/UPDATE calls, assert timestamps were passed. |
| RunWorkflow factory doesn't exist yet | **MEDIUM** | Tests must mock `_create_run_workflow` factory function. Mock should return a Mock object with `handle_pause()` and delivery methods. |

#### Failure Modes and Hardening

**FM-6.1: Test pollution from global state**
- **Symptom**: Test A registers run_id "123"; Test B calls `has_active_workflow("123")` and gets True unexpectedly
- **Cause**: `_active_run_ids` is module-level global, not reset between tests
- **Hardening Action**:
  - [ ] Add pytest fixture:
    ```python
    @pytest.fixture(autouse=True)
    def _clear_registry():
        from orchestrator.workflow.signals.signals import _active_run_ids
        _active_run_ids.clear()
        yield
        _active_run_ids.clear()
    ```
  - [ ] Use `autouse=True` to apply to all tests in the file
  - [ ] Test: run two tests in sequence; assert no cross-contamination

**FM-6.2: Mock RunWorkflow doesn't have all required methods**
- **Symptom**: Test calls `_handle_pause()`, which calls `workflow.handle_pause()`, which doesn't exist on mock
- **Cause**: Mock created without spec or incomplete method definitions
- **Hardening Action**:
  - [ ] Create a test fixture that returns a mock with all required methods:
    ```python
    @pytest.fixture
    def mock_workflow():
        mock = AsyncMock()
        mock.handle_pause = AsyncMock(return_value=None)
        mock.deliver_activity_completed = AsyncMock(return_value=None)
        mock.deliver_activity_verified = AsyncMock(return_value=None)
        return mock
    ```
  - [ ] Test uses this fixture and patches `_get_active_workflow()` to return it

**FM-6.3: Tests don't verify idempotency**
- **Symptom**: Test calls handler once, assertions pass. But in prod, handler is called twice and breaks
- **Cause**: No test for re-dispatch or duplicate signals
- **Hardening Action**:
  - [ ] Add test: call same handler twice with same signal; verify both succeed and no errors
  - [ ] Verify: registry only has one entry after two RUN_START calls

**FM-6.4: Async/await syntax errors in tests**
- **Symptom**: Test file has syntax error because test function is `def` instead of `async def`
- **Cause**: Typo or inconsistency
- **Hardening Action**:
  - [ ] Linter check in pre-commit: `pytest --collect-only tests/unit/test_signal_consumer.py` must succeed (verifies syntax)

---

### Task 7: Create Redelivery Unit Tests

#### Assumptions

| Assumption | Verification | Risk |
|-----------|---|---|
| Test DB can have signals manually inserted with specific timestamps | ✓ Standard pattern | Low |
| Can verify query order by checking returned signals | ✓ Standard pattern | Low |

#### Expected Outputs

1. ✅ `tests/unit/test_signal_redelivery.py` with ~250 LOC
2. ✅ Tests for redelivery query, FIFO order, idempotency

#### Blockers and Mitigation

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| Test DB setup/teardown timing | **LOW** | Use existing test DB fixture pattern |

#### Failure Modes and Hardening

**FM-7.1: Redelivery signals not in correct order**
- **Symptom**: Test inserts signals with IDs 1, 2, 3. Redelivery dispatches them out of order (e.g., 3, 1, 2)
- **Cause**: Query doesn't ORDER BY id
- **Hardening Action**:
  - [ ] Test: insert signals with created_at times spaced 1 second apart; verify redelivery processes in PK order
  - [ ] Verify consumer query: `SELECT ... WHERE delivered_at IS NOT NULL AND handled_at IS NULL ORDER BY id ASC`

**FM-7.2: Fully handled signals incorrectly redelivered**
- **Symptom**: Signal with `handled_at IS NOT NULL` is included in redelivery
- **Cause**: Query missing `AND handled_at IS NULL` condition
- **Hardening Action**:
  - [ ] Test: insert signals with various `handled_at` values; verify only those with NULL are redelivered
  - [ ] Mock handler to fail; verify signal is NOT marked handled; restart consumer; verify it's redelivered

**FM-7.3: Not-yet-delivered signals are redelivered**
- **Symptom**: Signal with `delivered_at IS NULL` is redelivered
- **Cause**: Query is wrong
- **Hardening Action**:
  - [ ] Test: insert signal with `delivered_at IS NULL, handled_at IS NULL`; verify it's NOT redelivered (belongs to main polling loop, not startup)

---

### Task 8: Wire Consumer into Executor Startup and Verify All Tests Pass

#### Assumptions

| Assumption | Verification | Risk |
|-----------|---|---|
| `app.py` has startup/shutdown events via `@asynccontextmanager _lifespan` | ✓ Found at `api/app.py` lines 35-36 | Low |
| Can create `asyncio.Task` inside lifespan context | ✓ Standard asyncio pattern | Low |
| Consumer cleanup on shutdown doesn't block | ⚠️ CancelledError handling unclear | **MEDIUM** |
| All existing tests pass (no new paths in Step 02) | ⚠️ Depends on Step 01 completion | **MEDIUM** |
| No signal enqueueing yet (Step 03) | ✓ Stated in scope | Low |

#### Expected Outputs

1. ✅ Consumer task created on app startup via `@app.on_event("startup")` or in `_lifespan`
2. ✅ `asyncio.create_task(consume_signals(SessionLocal))`
3. ✅ Consumer cancelled on shutdown
4. ✅ All integration tests pass: `uv run pytest tests/integration/ -q`
5. ✅ All unit tests pass: `uv run pytest tests/unit/ -q`
6. ✅ No type errors: `uv run mypy src/`

#### Blockers and Mitigation

| Blocker | Severity | Mitigation |
|---------|----------|-----------|
| Where to wire the consumer in `_lifespan`? | **MEDIUM** | After init_db, before app yields. Store task in `app.state.consumer_task`. On shutdown, cancel it. |
| Consumer task needs SessionLocal factory | **MEDIUM** | Pass `app.state.session_factory` to consumer. Consumer creates new session per poll cycle (or reuses one). |
| Consumer hangs on startup, blocking app initialization | **MEDIUM** | Consumer should NOT be awaited. Wrap in `asyncio.create_task()` so it runs in background. |
| Tests that manually insert signals expect immediate processing | **MEDIUM** | Tests must now either: (a) wait for consumer to poll and process (add `await asyncio.sleep(0.2)`), or (b) call consumer handlers directly in unit tests, not integration tests. |

#### Failure Modes and Hardening

**FM-8.1: Consumer blocks app startup**
- **Symptom**: App startup hangs indefinitely
- **Cause**: Consumer created as sync task or awaited in lifespan
- **Hardening Action**:
  - [ ] Code: `asyncio.create_task(consume_signals(session_factory))` (NOT `await consume_signals(...)`)
  - [ ] Store task: `app.state.consumer_task = asyncio.create_task(...)`
  - [ ] Test: verify app.py startup completes in < 5 seconds even with consumer

**FM-8.2: Consumer not cancelled on shutdown, subprocess orphaned**
- **Symptom**: Server stops but consumer task keeps running, preventing clean shutdown
- **Cause**: Task not cancelled or cancellation not awaited
- **Hardening Action**:
  - [ ] Shutdown handler:
    ```python
    if hasattr(app.state, "consumer_task"):
        app.state.consumer_task.cancel()
        try:
            await app.state.consumer_task
        except asyncio.CancelledError:
            pass
    ```
  - [ ] Test: stop app; verify no lingering consumer tasks in `asyncio.all_tasks()`

**FM-8.3: No integration test for consumer wiring**
- **Symptom**: Consumer is wired but nobody verifies it works end-to-end in app context
- **Cause**: Task 6/7 only test consumer in isolation; no test of app startup + consumer
- **Hardening Action**:
  - [ ] Add integration test: `test_consumer_wired_to_app()`
    - Create FastAPI test client
    - Insert signal manually into DB
    - Wait for consumer to poll
    - Verify signal is marked handled
  - [ ] **CRITICAL**: This test MUST be added to catch wiring gaps

**FM-8.4: Existing tests break due to consumer running in background**
- **Symptom**: Integration test creates run, but consumer starts processing signals before test setup completes
- **Cause**: Consumer is async and races with test logic
- **Hardening Action**:
  - [ ] Tests that use `TestClient` or create app: disable consumer for test. Add to test fixture:
    ```python
    @pytest.fixture
    async def app_no_consumer(app):
        # Stop consumer task before test
        if hasattr(app.state, "consumer_task"):
            app.state.consumer_task.cancel()
        yield app
        # Restart on cleanup
    ```
  - [ ] Or: add consumer startup/shutdown to per-test setup/teardown
  - [ ] Run all tests: `uv run pytest tests/ -x --tb=short` must pass without hangs or race conditions

**FM-8.5: DB session not properly managed by consumer**
- **Symptom**: Consumer opens session, queries pending_signals, but doesn't commit or close; subsequent tests see stale data
- **Cause**: Session lifecycle unclear
- **Hardening Action**:
  - [ ] Consumer pattern: create session per poll cycle (or per batch of signals)
    ```python
    async def consume_signals(session_factory):
        while True:
            async with session_factory() as session:
                # Query and process signals
                await session.flush()  # Persist delivered_at/handled_at updates
            await asyncio.sleep(0.1)
    ```
  - [ ] Test: verify test inserts signal; consumer processes it; test query sees `handled_at IS NOT NULL`

---

## Critical Wiring Analysis: COMPONENT INTEGRATION

### ⚠️ **MAJOR RISK: Consumer Code Isolation**

Step 02 creates consumer code that is **never called** by existing code. The consumer:
1. Is spawned in `app.py` startup as a background task
2. Polls `pending_signals` forever
3. Processes signals by calling handlers
4. Registers/unregisters workflows

But **nothing enqueues signals yet** (that's Step 03). So:

| Component | Step 02 Role | Active Code Path? | Wiring Verified? |
|-----------|---|---|---|
| Consumer polling loop | ✅ New code | ❌ NO — just polls, finds no signals | ⚠️ Not tested until Step 03 |
| RUN_START handler | ✅ New code | ❌ NO — signal type not enqueued | ⚠️ Only tested in unit tests with mocked signals |
| RESUME handler | ✅ New code | ❌ NO — signal type doesn't exist yet | ⚠️ Only tested in unit tests |
| PAUSE handler | ✅ New code | ❌ NO — no signals enqueued | ⚠️ Unit-tested only |
| CANCEL handler | ✅ New code | ❌ NO — no signals enqueued | ⚠️ Unit-tested only |
| Registry functions | ✅ Already exist, used by consumer | ✓ YES — RunWorkflow still calls them | ✓ Verified |
| App startup wiring | ✅ New code | ⚠️ PARTIALLY — task created, but does nothing | ⚠️ Tested by app startup, but no signal flow |

**Failure Mode: Wiring Bug Masqueraded as Implementation Bug**

If Task 8 wiring is wrong (e.g., consumer never started, or session_factory not passed), the code will:
- Pass all unit tests (Task 6/7 test handlers in isolation)
- Pass all integration tests (no signals enqueued, so consumer does nothing anyway)
- FAIL at Step 03 when signals are enqueued (consumer never processes them)

This creates a gap where **weeks of work could be wasted** if the wiring is subtly wrong.

**Hardening Action: Add INTEGRATION TEST for consumer in app context**

Create `tests/integration/test_consumer_wiring.py`:
```python
@pytest.mark.asyncio
async def test_consumer_processes_signal_in_app_context(client, test_run_id):
    """Verify consumer is wired and processes signals when app is running."""
    # This test requires the app to be running with consumer

    # Manually insert a RUN_START signal for a DRAFT run
    from orchestrator.db import PendingSignalModel
    async with app.state.session_factory() as session:
        signal = PendingSignalModel(
            id=uuid.uuid4(),
            run_id=test_run_id,
            signal_type="run_start",
            payload=None,
            created_at=datetime.now(timezone.utc),
            processed_at=None,  # Will change to delivered_at/handled_at
        )
        session.add(signal)
        await session.commit()

    # Wait for consumer to process
    await asyncio.sleep(0.5)

    # Verify signal was handled
    async with app.state.session_factory() as session:
        signal_row = await session.get(PendingSignalModel, signal.id)
        assert signal_row.handled_at is not None, "Consumer did not process signal"
        assert signal_row.delivered_at is not None

    # Verify run transitioned to ACTIVE
    async with app.state.session_factory() as session:
        run = await session.get(Run, test_run_id)
        assert run.status == RunStatus.ACTIVE
```

This test will **fail at Step 02 (as expected, since no signal enqueuing yet)** but will **verify the consumer wiring is correct** once Step 03 enqueues signals.

---

## Overall Risk Summary

| Risk | Likelihood | Impact | Owner |
|------|-----------|--------|-------|
| Step 01 migration incomplete | Low | CRITICAL — Task 1 can't run | Pre-Step-02 gate |
| RUN_START signal type missing | Medium | CRITICAL — Task 2 can't implement handler | Verify Step 01 |
| RunWorkflow factory interface mismatch | High | HIGH — Task 2 passes but Task 8 wiring fails | Task 2 + Task 8 coordination |
| Global registry pollution in tests | High | MEDIUM — test failures, hard to debug | Add auto-cleanup fixture (Task 6) |
| Consumer wiring not verified | High | HIGH — works in unit tests, fails in integration | Add app-context integration test (Task 8) |
| Async/await errors (missing await, not async) | Medium | MEDIUM — runtime errors at execution | Linter + type check (enforce in CI) |
| DB schema missing columns | High | CRITICAL — consumer queries fail on startup | Pre-step-02 verification of Step 01 |
| Error handling semantics undefined | Medium | MEDIUM — signals lost or redelivered infinitely | Write explicit error handling spec before Task 2 |

---

## Implementation Sequence Recommendations

### Before Task 1 Begins:

1. ✅ Verify Step 01 is complete: migration file exists, adds `delivered_at`/`handled_at` columns, adds `STOPPING` status, adds `RUN_START` signal type
2. ✅ Run migration on test DB: `alembic upgrade head` from test checkout
3. ✅ Query test DB: `SELECT delivered_at, handled_at FROM pending_signals LIMIT 1` must succeed
4. ✅ Verify `RUN_START` in `WorkflowSignal` enum: `from orchestrator.workflow.signals import WorkflowSignal; assert hasattr(WorkflowSignal, "RUN_START")`
5. ✅ Verify `STOPPING` in `RunStatus` enum: `from orchestrator.config.enums import RunStatus; assert hasattr(RunStatus, "STOPPING")`

### Before Task 2 Begins:

1. ✅ Document factory pattern: clarify `_create_run_workflow()` signature (run_id, db_session) → RunWorkflow
2. ✅ Verify state transition functions: does `engine.start_run(run_id)` exist? Or must use `run.status = ACTIVE; session.flush()`?
3. ✅ Search `RunWorkflow` for `handle_pause()` or similar method; if not found, add before Task 3

### Before Task 3 Begins:

1. ✅ Verify `STOPPING` transitions are guarded in state machine: cannot transition FROM STOPPING except to PAUSED/FAILED
2. ✅ Verify API rejects pause/cancel on STOPPING runs (return 409)
3. ✅ Document pause flow: must call `RunWorkflow.handle_pause()` or other interface?

### Before Task 6 Begins:

1. ✅ Add pytest fixture to clear global registry: `_active_run_ids.clear()`
2. ✅ Create mock RunWorkflow fixture with all required methods

### After Task 8:

1. ✅ Add `tests/integration/test_consumer_wiring.py` to verify consumer is wired and processes signals
2. ✅ Run full test suite: `uv run pytest tests/ -x --tb=short` must pass with no hangs or timeouts
3. ✅ Check for any test that times out (likely consumer-related deadlock); debug and fix before Step 03

---

## Recommended Spec Clarifications (Pre-Implementation)

Before Task 1 begins, write explicit specs for:

1. **Error Handling**: "When a signal handler raises an exception, do NOT catch it in the handler. Let it propagate to the consumer dispatch loop. The dispatch loop catches exceptions and leaves `handled_at` NULL for redelivery."

2. **Factory Pattern**: "`_create_run_workflow(run_id: str, db_session: AsyncSession) -> RunWorkflow`. No ExecutorCallbacks (Task 8 will inject a full factory with callbacks)."

3. **Inactive Workflow Handling**: "If PAUSE/CANCEL signal arrives for a run with no active workflow, the run may be PAUSED/COMPLETED/FAILED already. Check run.status in DB. If PAUSED/COMPLETED/FAILED, skip state transition (no-op). If ACTIVE but no workflow registered (orphaned), transition directly as if workflow didn't exist."

4. **Poll Interval**: "Consumer polls every 100ms. Tests can inject shorter intervals for faster test execution."

5. **Redelivery Cutoff**: "Signals with `delivered_at` older than 5 minutes and `handled_at IS NULL` are not redelivered (assumed lost/stale). Log and mark as handled with failure marker (future: add attempt_count column)."

---

## Conclusion

**Step 02 is implementable, but has HIGH RISK of latent wiring bugs** that won't manifest until Step 03 enqueues signals. The primary mitigation is:

1. ✅ Pre-step verification: confirm Step 01 migration is applied
2. ✅ Add explicit factory pattern documentation
3. ✅ Use autouse pytest fixture to clear global registry
4. ✅ Add integration test in Task 8 that verifies consumer processes signals in app context
5. ✅ Run full test suite after Task 8 with no hangs or race conditions

With these mitigations, Step 02 can proceed with confidence. Without them, bugs will likely be discovered late (Step 03 or beyond).
