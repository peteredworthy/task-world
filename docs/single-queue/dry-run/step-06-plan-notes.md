# Step 06: Validation and Cleanup — Dry-Run Analysis

**Date:** 2026-03-26
**Phase:** Final verification and dead-code cleanup
**Scope:** 5 tasks across test execution, type checking, code audit, and traceability validation

---

## Executive Summary

This step is the final gate before completion of the single-queue signal model. It has no new functionality—it is pure validation. However, it **exposes integration failures** from prior steps. A test passing does not guarantee wiring is correct; all five tasks must align to confirm the implementation is complete.

**Critical risk:** Dead code removal (Task 4) and component wiring (Task 1) are tightly coupled. If Steps 01–05 created correct implementations but didn't wire them into the active code path, tests in Task 1 may still pass (testing components in isolation) while the system doesn't actually use them. Task 4 removal must be paired with Task 1 verification to confirm old code is truly unused.

---

## Task 1: Run Backend Unit and Integration Test Suite

### Assumptions

1. **Test suite is comprehensive**: Steps 01–05 included tests for every new handler, state transition, and integration point. Missing tests indicate incomplete prior steps.

2. **Alembic migration is auto-applied in test environment**: The migration `xxxx_single_queue_signals.py` (Step 01) is applied before tests run. If not, any test accessing `pending_signals` will fail with schema mismatch.

3. **Test database is compatible**: Tests use SQLite in-memory or a temporary file. The Alembic migration must work on both the test DB and production DB (Postgres). If migration uses Postgres-specific syntax (e.g., `SERIAL` instead of `AUTOINCREMENT`), tests will fail.

4. **Consumer loop is initialized in test fixtures**: Step 02 creates the consumer, but tests must instantiate it. If the consumer is a background task/asyncio task, pytest must handle it via `pytest-asyncio` or a test fixture that manages the event loop.

5. **Test baseline (~2557 tests) is accurate**: This assumes new tests added in Steps 01–05 don't exceed a reasonable count (e.g., new tests should be <50% of existing count, unless the implementation is massive).

6. **No pre-existing test failures**: The codebase starts with all tests passing. If prior commits introduced failures, they must be fixed before this step.

### Expected Outputs

- Test run completes without hanging or timeout (expected: <5 minutes for full suite)
- Summary line: `passed 2557+N` (where N = new tests from Steps 01–05, expected N < 500)
- Failure count: 0
- Skipped/warning counts: acceptable if pre-existing

### Blockers and Mitigation

#### Blocker 1: Migration File Not Found or Invalid

**Condition**: Alembic migration `xxxx_single_queue_signals.py` doesn't exist or has syntax errors.

**Evidence**: Test fails during DB initialization with error: `FileNotFoundError: migration file not found` or SQL syntax error.

**Mitigation**:
- Verify `alembic/versions/` directory contains a file with `single_queue_signals` or similar in the name
- Run `uv run alembic current` to check if migration is registered
- If missing, Step 01.1 was not completed; must be done before Task 1 can pass

#### Blocker 2: Consumer Not Running in Tests

**Condition**: Consumer loop (Step 02) is never started in test environment.

**Evidence**:
- Signals are enqueued to `pending_signals` but never processed
- Runs stay in DRAFT state indefinitely instead of transitioning to ACTIVE
- Tests timeout waiting for state change
- Log output shows no consumer poll cycles

**Mitigation**:
- Check test fixtures in `tests/conftest.py` (or similar) for consumer initialization
- Verify `executor.py` or test setup calls the consumer loop
- If consumer is an async task, ensure `pytest-asyncio` is configured and the event loop is running during tests
- Add a debug log at the start of the consumer loop and verify it appears in test output

#### Blocker 3: STOPPING State Not in Enum

**Condition**: `RunStatus.STOPPING` was not added to the enum (Step 01.2).

**Evidence**: Test fails when trying to create a run with status `STOPPING` or transition to it. Error: `ValueError: 'STOPPING' is not a valid RunStatus`.

**Mitigation**:
- Check `src/orchestrator/db/models.py` for `class RunStatus(str, Enum)` and confirm `STOPPING = "stopping"` is present
- If missing, Step 01.2 was not completed

#### Blocker 4: Registry Functions Still in Public API

**Condition**: `register_active_run` and `unregister_active_run` are still exported from `signals.py` (Step 04 not completed).

**Evidence**: Import tests pass but integration tests that check registry isolation fail. Or, non-consumer code still calls these functions and tests don't catch it.

**Mitigation**:
- Run grep: `grep -rn "register_active_run\|unregister_active_run" src/orchestrator/workflow/ --include="*.py" | grep -v "consumer\|test"`
- Any non-test, non-consumer match indicates Step 04 was incomplete

#### Blocker 5: Async/Event Loop Misconfiguration

**Condition**: Consumer is async but pytest isn't configured to handle it.

**Evidence**: Tests hang indefinitely or fail with `RuntimeError: no running event loop`.

**Mitigation**:
- Check `pytest.ini` or `pyproject.toml` for `pytest-asyncio` plugin configuration
- Verify `asyncio_mode = "auto"` is set (if using pytest-asyncio >= 0.21)
- If consumer uses `asyncio.create_task()`, ensure test fixtures properly await or manage the task lifecycle

#### Blocker 6: Test Isolation Failure (Shared DB State)

**Condition**: Tests share database state and fail when run in parallel or out of order.

**Evidence**: Test passes when run alone but fails in full suite. `pytest -n auto` fails but `pytest` passes.

**Mitigation**:
- Ensure test fixtures truncate or roll back DB state between tests
- Use SQLite in-memory `:memory:` for each test if possible (allows full rollback)
- Verify no tests assume specific row IDs or auto-increment values

### Failure Modes (Component Wiring)

#### FM-1.1: Consumer Created But Not Wired into Startup

**Risk**: Step 02 creates `consumer.py` but Step 03 or the test setup never calls `consumer.run()` or equivalent.

**Detection**:
- Test creates a run via API: `POST /api/runs/{id}/start`
- Signal is enqueued to `pending_signals`: grep confirms INSERT happened
- Consumer never runs: run stays in DRAFT state indefinitely
- Test times out waiting for state change

**How to Verify**:
- Add temporary log statement: `logger.info("Consumer running")` at top of consumer loop
- Run a single test that starts a run; search logs for the message
- If not present, consumer isn't running
- Check `executor.py` or `app.py` for `await consumer.run()` or equivalent call

**Hardening Action**:
- Modify Step 04 requirements to explicitly state: "Executor initialization must call `consumer.start()` or equivalent; this is verified by a test that checks the consumer loop is active."

#### FM-1.2: Handler Not Implemented for New Signal Types

**Risk**: Step 02 defines `RUN_START` and `RESUME` signal types but the consumer doesn't have handlers for them.

**Detection**:
- Test enqueues `RUN_START` signal
- Consumer polls and finds signal
- Consumer encounters `KeyError` or `NotImplementedError` in dispatch (no handler for signal type)
- Test fails with exception

**How to Verify**:
- Check `src/orchestrator/workflow/signals/consumer.py` for a dispatch function (e.g., `_dispatch_signal()`)
- Verify every signal type (`RUN_START`, `RESUME`, `PAUSE`, `CANCEL`, `ACTIVITY_COMPLETED`, `ACTIVITY_VERIFIED`) has a corresponding handler
- Count signal types in `WorkflowSignal` enum and handler branches in consumer; they must match

**Hardening Action**:
- Add a unit test `test_signal_consumer_all_types_handled` that dynamically checks every signal type has a handler

#### FM-1.3: Transition Guards on STOPPING Not Enforced

**Risk**: `STOPPING` state is defined but API doesn't reject invalid operations on STOPPING runs.

**Detection**:
- Test creates a run in STOPPING state (via direct DB update or pause/cancel)
- Test calls `POST /api/tasks/{id}/submit` on a task in a STOPPING run
- Expected: 409 Conflict (run is stopping, can't submit)
- Actual: 200 OK (request succeeds, guard not enforced)

**How to Verify**:
- Check `src/orchestrator/api/routers/tasks.py` and `routers/runs.py` for guards on STOPPING state
- Search for `if run.status == RunStatus.STOPPING:` or similar
- Verify every operation that advances task state (start_task, submit, etc.) rejects STOPPING runs

**Hardening Action**:
- Add explicit test case: `test_stopping_run_rejects_submit` that asserts 409 response when calling submit on a STOPPING run

#### FM-1.4: Migration Backfill Incorrect for Existing Signals

**Risk**: Step 01.1 migration backfills existing `pending_signals` rows but assigns integer PKs incorrectly or leaves `delivered_at`/`handled_at` null when they should be set.

**Detection**:
- Migration runs on a DB with existing signals
- Consumer queries signals: `SELECT * FROM pending_signals WHERE handled_at IS NULL ORDER BY id`
- Ordering is wrong (integer PKs not sequential) or handled signals are marked as unhandled
- Consumer redelivers already-handled signals, causing duplicates or test failures

**How to Verify**:
- Review the migration file `alembic/versions/xxxx_single_queue_signals.py`
- Verify the backfill logic:
  - `id` is assigned via `ROW_NUMBER()` or similar, based on `created_at` order
  - `delivered_at` and `handled_at` are set to NULL for all existing rows (or set to `created_at` if already processed)
  - New rows use `AUTOINCREMENT` for `id`

**Hardening Action**:
- Add a migration test: `test_migration_backfill_ordering` that creates fake old-format signals, runs migration, and verifies ordering is correct

### Impact Assessment

- **If Task 1 fails**: Stop and fix all prior steps before proceeding. Task 1 is the gate.
- **If Task 1 passes but Task 4 (dead code) finds leftover old code**: The old code wasn't wired out; may be a dormant bug. Must investigate and either remove or explain why it's retained.

---

## Task 2: Run Frontend Test Suite

### Assumptions

1. **STOPPING status added to RunStatus type**: Step 01.2 adds `STOPPING` to the backend enum; the frontend must reflect this in `ui/src/lib/types.ts` or equivalent.

2. **UI components updated for STOPPING**: Components that render based on `run.status` (RunDetail, RunCard, etc.) either handle STOPPING explicitly or are indifferent to it (e.g., "Stopping..." is treated same as "Paused...").

3. **Test mocks include STOPPING**: Any test that mocks a run object must be able to set `status: "stopping"`.

4. **TypeScript is strict enough**: `--strict` mode or `noImplicitAny` is enabled, so missing switch cases on enums are caught.

5. **No breaking changes to run API response schema**: Frontend assumes `run.status` is a string enum with specific values. If backend returns unexpected shape, tests fail with type mismatch.

### Expected Outputs

- All ~221 frontend tests pass (baseline from MEMORY.md)
- Jest test summary: `Tests: XXX passed, XXX total`
- No console errors or warnings

### Blockers and Mitigation

#### Blocker 1: STOPPING Status Not in Frontend Type Definitions

**Condition**: Frontend `RunStatus` enum doesn't include `STOPPING`.

**Evidence**:
- TypeScript type check fails: `Type '"stopping"' is not assignable to type 'RunStatus'`
- Or, Jest test fails when trying to create a mock run with `status: "stopping"`

**Mitigation**:
- Check `ui/src/lib/types.ts` (or wherever RunStatus is defined)
- Add `STOPPING = "stopping"` to the enum
- Run `tsc --noEmit` to verify type check passes

#### Blocker 2: UI Component Not Handling STOPPING

**Condition**: A component has a switch statement on `run.status` without a `case "stopping"` handler.

**Evidence**:
- Component test fails with error like `Unexpected status: stopping` (if there's an error fallback)
- Or, component renders incorrectly for STOPPING (e.g., shows "Paused" instead of "Stopping")

**Mitigation**:
- Search for `switch.*status` in UI components
- Verify every switch has a case for all RunStatus values (including STOPPING)
- Use TypeScript exhaustive checking: `const _exhaustive: never = run.status` at the end of the switch to catch missing cases
- Update component snapshots if rendering has changed

#### Blocker 3: Test Mocks Outdated

**Condition**: Test fixtures that create mock runs don't include STOPPING as a valid status, causing type errors when tests try to create STOPPING runs.

**Evidence**:
- Test fails with error: `Type '"stopping"' is not assignable to type 'RunStatus'` at mock creation site

**Mitigation**:
- Update mock factories/fixtures to include `STOPPING` as a valid status
- Check `tests/unit/test_*.tsx` and `tests/__mocks__/` for run mocks
- Ensure mock types match the updated RunStatus enum

#### Blocker 4: Snapshot Tests Fail

**Condition**: Snapshot tests were generated before STOPPING was added. Component rendering for STOPPING differs from snapshot.

**Evidence**: Jest output shows snapshot mismatch for a component test.

**Mitigation**:
- Run `npm test -- -u` to update snapshots
- Manually review snapshot diffs to ensure the STOPPING rendering is intentional
- Commit updated snapshots

### Failure Modes (Component Wiring)

#### FM-2.1: STOPPING State Exists Backend But Not Wired to Frontend Type

**Risk**: Backend successfully transitions runs to STOPPING, but frontend type definitions don't reflect it. Frontend UI can't handle the status.

**Detection**:
- Backend test passes (Task 1)
- Frontend test passes (Task 2, if mocks don't include STOPPING)
- But integration test that fetches a real STOPPING run fails with type mismatch
- Or, UI crashes when displaying a STOPPING run fetched from real API

**How to Verify**:
- Run an integration test: create a run, pause it (transitions to STOPPING), fetch it via API, verify frontend can deserialize it without type error
- Check that RunResponse schema includes all possible status values

**Hardening Action**:
- Add integration test `test_frontend_handles_stopping_run_from_api` that:
  1. Creates a run and pauses it (STOPPING state)
  2. Fetches via GET `/api/runs/{id}`
  3. Deserializes response to RunResponse type (TypeScript)
  4. Renders RunDetail component with the fetched run
  5. Verifies "Stopping..." indicator appears

#### FM-2.2: Component Doesn't Handle All Status Transitions

**Risk**: Component works for old statuses but hasn't been updated for STOPPING, leading to incorrect UI behavior.

**Detection**:
- Component test renders RunCard with STOPPING run
- Test expects "Stopping..." indicator
- Actual output shows something else (e.g., empty, error, or generic message)

**How to Verify**:
- Search code for status-based conditionals: `if (run.status ===`, `status ===`, `switch.*status`
- For each conditional, verify STOPPING is handled (or explicitly documented why it's not needed)

**Hardening Action**:
- Add a component test for each UI component that displays status: `test_run_detail_shows_stopping_status` that renders with STOPPING and asserts the correct message appears

---

## Task 3: Run Type Checker and Linter

### Assumptions

1. **TypeScript strict mode is enabled**: `strict: true` in `tsconfig.json` ensures exhaustive checks on enums and union types.

2. **ESLint configuration is comprehensive**: `.eslintrc` includes rules for unused variables, imports, and type safety.

3. **Ruff is configured for the project**: `ruff.toml` or equivalent exists with appropriate rules.

4. **New code from Steps 01–05 follows project conventions**: No formatting or naming violations.

5. **No pre-existing linting issues**: Baseline is clean (or issues are documented as accepted technical debt).

### Expected Outputs

- `tsc --noEmit` exit code 0 (no output or success message)
- `eslint src/ --ext .ts,.tsx` exit code 0
- `uv run ruff check src/ scripts/ tests/` exit code 0

### Blockers and Mitigation

#### Blocker 1: TypeScript Error on STOPPING in Switch Statement

**Condition**: A TypeScript component uses exhaustive switch on `RunStatus` without a STOPPING case. TypeScript strict mode catches it.

**Evidence**: `tsc --noEmit` output shows error: `Type '"stopping"' is not handled in this switch`.

**Mitigation**:
- Locate the offending switch statement
- Add `case "stopping":` handler or mark as unreachable if intentional
- Run `tsc --noEmit` again to verify error is gone

#### Blocker 2: Circular Import Between consumer.py and signals.py

**Condition**: Consumer imports from signals.py; signals.py exports consumer. Both ruff and Python runtime detect a cycle.

**Evidence**:
- `uv run ruff check` reports circular import
- Or, tests fail with `ImportError: cannot import name X (circular import)`

**Mitigation**:
- Review import structure: Step 02 should import from signals.py into consumer.py, but signals.py should NOT import from consumer.py
- If needed, move registry functions to a separate module (e.g., `registry.py`) that both can import from
- Verify import graph: `signals → consumer` is OK; `consumer → signals` is OK; `signals → consumer → signals` is NOT OK

**Hardening Action**:
- Add a pre-submission check: `python -c "from orchestrator.workflow.signals.consumer import Consumer"` to verify no circular import at runtime

#### Blocker 3: Unused Imports After Dead Code Removal

**Condition**: Step 04 removes calls to `has_active_workflow`, but the import statement remains in service.py or run_workflow.py.

**Evidence**: ESLint or Ruff reports unused import: `Import 'has_active_workflow' is defined but never used`.

**Mitigation**:
- Task 4 should remove both the import and the code. If Ruff finds unused imports after Task 4, Task 4 was incomplete.
- Run `uv run ruff check --fix` to auto-remove unused imports
- Manually review the fixes to ensure they're correct

#### Blocker 4: Type Mismatch in New Handler Signatures

**Condition**: Step 02 consumer handlers have signatures that don't match expected types (e.g., handler returns wrong type, takes wrong args).

**Evidence**: TypeScript or Ruff type checking fails with signature mismatch.

**Mitigation**:
- Check handler definitions in `consumer.py`; verify they match the protocol/base class signature
- Use `Callable[[RunId, WorkflowSignal], Awaitable[None]]` or similar to type handlers
- Ensure handlers are consistent (all async or all sync)

### Failure Modes (Component Wiring)

#### FM-3.1: Handler Implementations Don't Match Protocol

**Risk**: Step 02 defines handlers but their signatures don't match what the dispatch loop expects.

**Detection**:
- Type checker passes (if types are loose)
- But at runtime, handler dispatch fails with TypeError (wrong argument count or type)
- Test fails with error like `handler() got an unexpected keyword argument`

**How to Verify**:
- Define a strict protocol for handlers: `Handler = Callable[[RunId, Signal, Session], Awaitable[None]]`
- Annotate consumer dispatch: `handlers: dict[SignalType, Handler]`
- Verify all handlers in the dict match the protocol

**Hardening Action**:
- Add a runtime check in consumer startup that validates all handlers against the protocol
- Or, define handlers as class methods on a single `Consumer` class, ensuring consistency

#### FM-3.2: Linter Suppression Comments Hide Real Issues

**Condition**: Code includes `# noqa`, `# type: ignore`, or `# pylint: disable` that suppress legitimate errors.

**Evidence**: Type checker passes, but linter has no warning. Checking the suppressed lines shows the underlying issue is real.

**Mitigation**:
- Audit all suppression comments: `grep -rn "noqa\|type: ignore\|disable" src/`
- For each suppression, verify it's justified (not just hiding bad code)
- Remove unjustified suppressions; fix the underlying issue instead

**Hardening Action**:
- Add a pre-commit rule that forbids new `# noqa` or `# type: ignore` comments without explanation

---

## Task 4: Audit and Remove Dead Code

### Assumptions

1. **All old routing code is truly dead**: Steps 01–05 completely replaced the old `has_active_workflow` branching. No code path uses the old patterns.

2. **Grep patterns are comprehensive**: `grep -rn "has_active_workflow"`, etc., catches all occurrences (not hidden by dynamic imports or string manipulation).

3. **Tests will still pass after removal**: Removing dead code doesn't break tests (by definition, dead code is unreachable).

4. **Comments and docstrings can reference removed code**: Documentation explaining why the old code was removed is OK; functional code must be gone.

### Expected Outputs

- Zero matches for `has_active_workflow` outside `consumer.py` and tests
- Zero matches for `spawn_run` calls in service.py (except comments/docstrings)
- Zero matches for `unregister_active_run` outside `consumer.py`
- No-op `handle_resume` log removed or method made explicit (not a no-op)
- All tests still pass (same count as Task 1)

### Blockers and Mitigation

#### Blocker 1: Grep Misses Occurrences (Dynamic Import or String)

**Condition**: Code calls `has_active_workflow` via `getattr()`, `importlib`, or as a string in config, and grep doesn't catch it.

**Evidence**:
- Grep shows zero matches
- But at runtime, tests reference `has_active_workflow` and fail with NameError
- Or, a dynamically-imported module expects the function to exist

**Mitigation**:
- Use multiple grep patterns: literal name, string literal, dynamic calls
- `grep -rn "has_active_workflow"` — literal
- `grep -rn "\"has_active_workflow\""` — in strings
- `grep -rn "getattr.*active_workflow"` — dynamic attribute access
- Manually review any file that imports from signals module

**Hardening Action**:
- Add a test: `test_no_has_active_workflow_in_service` that tries to import and use `has_active_workflow` from service.py and expects ImportError

#### Blocker 2: Dead Code Is Actually Still Used

**Condition**: A code path that appears dead is still called by tests or production code, and removing it breaks tests.

**Evidence**:
- Task 4 removes `spawn_run` from service.py
- Task 1 re-runs tests
- Tests fail with error: `AttributeError: 'WorkflowService' object has no attribute 'spawn_run'`

**Mitigation**:
- Before removing code, verify it's truly unreachable:
  - Run full test suite with the code in place (baseline)
  - Add a log statement to the code: `logger.warning("Using old spawn_run")`
  - Re-run tests; if the warning doesn't appear, code is dead
  - If warning appears, code is live; do NOT remove
- Use `pytest --cov` to see code coverage and identify untouched code paths

**Hardening Action**:
- Create a checklist for Task 4:
  1. For each dead-code candidate, add a `warnings.warn("This code path is deprecated")` statement
  2. Run full test suite; capture output to see if warnings are triggered
  3. Only remove code that generates no warnings during test run
  4. Re-run full test suite after removal; assert same pass count

#### Blocker 3: Dead Code Is Referenced in Tests

**Condition**: Test code mocks or patches `has_active_workflow`, and removing the function breaks the test.

**Evidence**:
- Test imports `from service import has_active_workflow` and patches it
- After removal, test fails at import: `ImportError: cannot import name 'has_active_workflow'`

**Mitigation**:
- Search for imports/mocks: `grep -rn "has_active_workflow" tests/`
- Any match indicates test code references the function
- Update or remove the test, or keep the function if it's tested as part of deprecation

**Hardening Action**:
- When removing code, also search for and update/remove test code that references it

#### Blocker 4: Comments or Docstrings Explain Removed Code

**Condition**: Removing a function leaves behind a comment explaining why it exists. The orphaned comment confuses future readers.

**Evidence**: Code review finds comments like `// This would call has_active_workflow but we use the queue now` with no corresponding code.

**Mitigation**:
- When removing code, also remove associated comments/docstrings
- If keeping a high-level comment (e.g., design rationale), ensure it's clear that the implementation details have changed

### Failure Modes (Component Wiring)

#### FM-4.1: Old Code Isn't Actually Dead Because New Code Isn't Wired In

**Risk**: Steps 01–05 created new implementations but didn't wire them into the active code path. The old code is called by production code, so it's live. Removing it will break the system.

**Detection**:
- Grep for `has_active_workflow` finds zero matches in service.py
- But the consumer loop from Step 02 was never wired into executor startup
- In production, start_run() still calls the old path directly because the consumer never runs
- Removing the old code breaks the system

**How to Verify**:
- Before Task 4, run Task 1 (tests) to completion and confirm the new path is actually being used
- Inspect executor.py to see if consumer loop is started
- Search for `consumer.run()` or equivalent; if not found, consumer isn't wired in
- If consumer isn't wired in, Task 4 should NOT proceed; go back and complete Step 03-04 wiring

**Hardening Action**:
- Require Task 1 to pass completely and without hang/timeout before allowing Task 4 to proceed
- Add a pre-Task 4 check: `grep -n "consumer.run\|consumer.start\|await consumer" src/orchestrator/executor.py` must have at least one match

---

## Task 5: Verify Traceability and Document Coverage

### Assumptions

1. **Intent items [I-01] through [I-36] are stable and complete**: No new items added; none removed. All 36 items are in intent.md.

2. **Plan steps S-01 through S-05 are documented**: Each step has a "Traces to" section in plan.md that lists which intent items it addresses.

3. **Mapping is many-to-many**: Multiple intent items can be addressed by one step; one intent item can span multiple steps.

4. **Out-of-scope items are explicitly marked**: [I-06], [I-18], [I-19], [I-20] are marked as NO-REQ or deferred, and this is documented.

### Expected Outputs

- Traceability document `docs/single-queue/traceability.md` created
- Table with columns: Intent ID, Description, Addressed in Step(s), Status
- All 36 intent items listed
- Each item has at least one step
- Status is ✓ (covered) or NO-REQ (out of scope, with justification)

### Blockers and Mitigation

#### Blocker 1: Intent Items Missing or Unclear

**Condition**: Intent.md doesn't list [I-01] through [I-36] clearly, or count is wrong.

**Evidence**: Traceability table has <36 items or shows `[I-XX]` items that aren't in intent.md.

**Mitigation**:
- Extract all `[I-XX]` references from intent.md: `grep -o "\[I-[0-9][0-9]\]" docs/single-queue/intent.md | sort | uniq`
- Count unique items; should be 36
- If count is wrong, intent.md is incomplete; fix it before Task 5 proceeds

#### Blocker 2: Plan Steps Don't Have "Traces to" Sections

**Condition**: plan.md describes steps but doesn't explicitly list which intent items each addresses.

**Evidence**: Trying to map intent items to steps requires reading the entire plan and inferring coverage.

**Mitigation**:
- Add explicit "Traces to: [I-XX], [I-YY], ..." sections to each step in plan.md
- Alternatively, manually read each step and extract coverage during Task 5 (more error-prone)

**Hardening Action**:
- Require plan.md to have a "Traces to" section in every step definition

#### Blocker 3: Intent Items Not Covered by Any Step

**Condition**: An intent item [I-XX] is in intent.md but no step addresses it.

**Evidence**: Traceability table shows `[I-XX] | NOT COVERED | — |` with no step listed.

**Mitigation**:
- If the item is in-scope (not explicitly NO-REQ), the implementation is incomplete; must add coverage to an existing step or create a new step
- If the item is out-of-scope, add a justification in the Status column (e.g., "NO-REQ: explicit out-of-scope in intent")

**Hardening Action**:
- Before Task 5 starts, require all in-scope items to have at least one step; out-of-scope items must be explicitly marked NO-REQ with justification

#### Blocker 4: Traceability Matrix Created But Inaccurate

**Condition**: Traceability document is created but maps are wrong (e.g., [I-01] is mapped to S-04 when it's actually S-03).

**Evidence**: Review finds mapping errors; intent item description doesn't match the step's actual work.

**Mitigation**:
- Create a detailed checklist: for each intent item, manually read its description, then find the step that implements it
- Cross-reference intent.md against plan.md and actual code (diffs/commits) to verify
- Have a second reviewer check the traceability table for accuracy

### Failure Modes (Component Wiring)

#### FM-5.1: Intent Item References New Component That Wasn't Wired

**Risk**: Traceability table shows [I-XX] mapped to a step, but the corresponding code/component from that step isn't actually used.

**Example**: [I-29] says "register_active_run() only called from consumer" but the traceability maps it to S-04 (registry isolation). Yet, if the consumer doesn't call register_active_run (FM-1.2), the intent item is not actually satisfied.

**Detection**:
- Traceability table is complete and accurate on paper
- But Task 1 (tests) or Task 4 (dead code) reveal that the implementation is incomplete
- Or, integration test fails because a promised component isn't wired

**How to Verify**:
- For each intent item, verify the corresponding step not only defines the component but also shows it's used in active code
- Example for [I-29]: The step should show `register_active_run()` is called in consumer's RUN_START handler

**Hardening Action**:
- Update traceability table to include a "Verification" column that briefly describes how the intent item is verified (e.g., "Test test_consumer_calls_register_on_start_signal"; "Grep confirms no calls in service.py")
- Require the verification column to reference tests or grep patterns, not just the description

---

## Cross-Task Failure Modes (High Risk)

### FM-CROSS-1: Consumer Wiring Incomplete

**Scenario**: Steps 01–02 create the consumer module and handlers. Step 03 enqueues signals instead of calling spawn_run. But the consumer loop is never started in production or tests.

**Impact**:
- Task 1 tests hang/timeout waiting for state transitions that never happen
- Or, if tests mock the consumer, they pass but production is broken
- Task 4 finds old code that's still used (old spawn_run path is still active)
- Traceability (Task 5) shows coverage, but actual system doesn't use new code

**Detection Chain**:
1. Task 1 times out or shows test failures waiting for state changes
2. Task 4 grep finds `spawn_run` still being called from service.py (old code isn't dead)
3. Integration test that uses API shows runs stay in DRAFT state

**Mitigation**: Verify consumer is running before Task 1 completes:
- Check for explicit `await consumer.run()` call in executor or app startup
- Add temporary log at consumer loop start; verify log appears during tests
- Require Task 1 to test consumer.run_signal() directly as a standalone unit test

### FM-CROSS-2: STOPPING State Defined But Transitions Not Enforced

**Scenario**: Step 01 adds STOPPING enum. Step 04 is supposed to add API guards. But the guards are incomplete or missing.

**Impact**:
- Task 2 (frontend) adds STOPPING to types; tests pass
- Task 3 (type checker) passes; no errors
- But production API allows invalid transitions (e.g., resume a STOPPING run)
- No test explicitly checks this because Task 1 tests don't cover all transitions

**Detection**:
- Manual testing: pause a run (STOPPING), then try to resume it
- API returns 200 (success) instead of 409 (Conflict)
- Or, integration test `test_cannot_resume_stopping_run` fails

**Mitigation**: Require Task 1 to include exhaustive state transition tests:
- For each state, test all valid and invalid transitions
- STOPPING specifically: test pause, resume, cancel, start_task, submit_for_verification all return 409

### FM-CROSS-3: Registry Isolation Not Actually Enforced

**Scenario**: Step 04 claims to isolate registry functions to consumer. Step 05 creates check_signal_routing.py guard. But the guard is never run or has bugs.

**Impact**:
- Task 4 (dead code audit) or Task 3 (linting) doesn't catch violations
- Pre-commit hook doesn't run; service.py imports has_active_workflow
- Traceability shows coverage, but invariant is violated

**Detection**:
- Grep in Task 4 finds `from signals import has_active_workflow` in service.py
- Or, pre-commit hook fails on commit but developer bypasses it

**Mitigation**:
- Task 3 must explicitly verify the pre-commit hook exists and works: `scripts/check_signal_routing.py` is executable and can be run manually
- Add a test that violates the invariant (imports registry function from non-consumer file) and verify the hook catches it
- Require the hook to fail on violation (exit code non-zero)

---

## Summary of Hardening Actions

### Before Task 1 (Test Suite)

1. **Verify consumer is wired into startup**:
   ```bash
   grep -n "consumer" src/orchestrator/executor.py
   grep -n "consumer" tests/conftest.py
   ```
   Expected: At least one match in each, showing consumer is instantiated and run

2. **Verify STOPPING is in RunStatus enum**:
   ```bash
   grep -n "STOPPING" src/orchestrator/db/models.py
   ```
   Expected: `STOPPING = "stopping"` present

3. **Verify migration file exists**:
   ```bash
   ls alembic/versions/*single_queue*
   ```
   Expected: One file with "single_queue" in name

### Before Task 2 (Frontend Tests)

1. **Verify STOPPING in frontend types**:
   ```bash
   grep -n "STOPPING" ui/src/lib/types.ts
   ```
   Expected: `STOPPING = "stopping"` present in RunStatus enum

2. **Verify component handles STOPPING**:
   ```bash
   grep -n "RunStatus.STOPPING" ui/src/
   ```
   Expected: At least one match (component case statement)

### Before Task 4 (Dead Code Removal)

1. **Verify Task 1 passed completely**: Test suite must complete without hang/timeout and show all tests passing
2. **Verify consumer is actually being used**: Add temporary log statement to consumer loop; verify it appears in test output
3. **Run grep pre-checks**:
   ```bash
   grep -rn "spawn_run" src/orchestrator/workflow/service.py | grep -v "def spawn_run\|docstring"
   grep -rn "has_active_workflow" src/orchestrator/workflow/ | grep -v test | grep -v consumer
   ```
   Expected: Zero meaningful matches

### Before Task 5 (Traceability)

1. **Count intent items**:
   ```bash
   grep -o "\[I-[0-9][0-9]\]" docs/single-queue/intent.md | sort | uniq | wc -l
   ```
   Expected: 36

2. **Verify plan has "Traces to" sections**: Every step (S-01 through S-05) must have an explicit "Traces to" section
3. **Identify out-of-scope items**: Items marked with NO-REQ in intent.md must be documented in traceability table as such

---

## Final Gate: What Must Be True for Step 06 to Pass

1. **All tests pass** (Task 1 & 2): Backend and frontend suites complete without failure or timeout
2. **Type and lint checks clean** (Task 3): `tsc`, `eslint`, `ruff` all exit with 0
3. **Dead code verified removed** (Task 4): Grep patterns for old routing show zero meaningful matches
4. **Traceability complete** (Task 5): All 36 intent items mapped to steps, with out-of-scope items explicitly noted
5. **No component wiring gaps**: Consumer is running, STOPPING state is enforced, registry is isolated, signal queue is active

If any of these fail, the step is **not complete**. Return to the failing task or prior steps and fix before resubmitting.

---

## Unknowns to Resolve Before Task 1

1. **What's the actual test count after Steps 01–05?** Need to run once to establish baseline for Task 1 verification
2. **What's the consumer polling interval in tests?** If too slow, tests may timeout; if too fast, may miss signals
3. **Does test environment use SQLite or Postgres?** Migration syntax differs; need to verify compatibility
4. **Are consumer handlers async or sync?** Affects event loop configuration and test fixtures

---

## Next Steps (After Dry-Run Analysis Completes)

1. Review this document for accuracy and completeness
2. Identify any additional failure modes or hidden assumptions not covered
3. Pre-stage Tasks 1–5 requirements in a checklist format
4. During implementation, reference this document to catch issues early

