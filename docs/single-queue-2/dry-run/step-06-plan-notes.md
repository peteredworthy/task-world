# Step 6 Dry-Run Analysis: Validation and Cleanup

**Step file:** `docs/single-queue-2/steps/step-06-plan.md`
**Analysis date:** 2026-03-26

---

## Overall Assessment

Step 6 is a verification-and-cleanup step with no new functionality. Its success
depends entirely on S-01 through S-05 having been executed correctly. Most failure
modes here are actually undetected gaps from prior steps surfacing at final
validation. Several concrete risks are identified below.

---

## Task-by-Task Analysis

### Task 1: Run Full Backend Test Suite

**Assumptions**
- All 2557 baseline backend tests (from MEMORY.md) still exist after S-01–S-05.
- No test file was deleted or permanently disabled during prior phases.
- Integration tests that previously asserted synchronous state changes after API
  calls (e.g., run is ACTIVE immediately after start) have been updated in S-03 to
  accommodate the 202/async model.

**Expected Output**
- `pytest tests/unit/ tests/integration/` exits 0.

**Blockers and Mitigations**

1. **Async-state-assertion mismatch** (HIGH RISK): Integration tests in
   `test_api_full_lifecycle.py` previously called `service.start_run()` and
   immediately read `run.status == "active"`. After S-03 rewiring, `start_run()`
   only enqueues a signal — the DRAFT→ACTIVE transition happens in the consumer
   loop. Any test that does not poll/wait for the consumer to process will fail with
   `status == "draft"` instead of `"active"`.

   **Mitigation**: Step 3.1 of the plan states "update expectations" in
   `test_api_full_lifecycle.py`. If S-03 does not add poll-until-active helpers to
   tests, these failures will appear here. At analysis time the test helpers do not
   exist yet. Step 6 should explicitly verify or create a `wait_for_status()` test
   utility.

2. **Registry isolation test breakage** (MEDIUM RISK): After S-04 removes
   `register_active_run` / `unregister_active_run` / `has_active_workflow` from the
   `workflow` and `signals` public `__all__`, any test that imports these directly
   from `orchestrator.workflow` will get `ImportError`. Current known call sites:
   - `src/orchestrator/workflow/signals/runtime.py` lines 286 and 310 call
     `unregister_active_run()` — S-03 [I-13] must remove these before S-04.
   - Any unit test that calls `has_active_workflow()` to assert registry state will
     need a consumer-aware helper (mentioned in plan.md §Resolved Design Decisions
     item 8, but no concrete helper is specified).

   **Mitigation**: Grep for `has_active_workflow\|register_active_run\|
   unregister_active_run` in `tests/` before running the suite. If hits appear
   outside consumer test files, they are breaking tests.

3. **Consumer loop in tests** (MEDIUM RISK): Integration tests that test the full
   run lifecycle now require the consumer loop to be running (or stubbed). If the
   test harness uses `WorkflowService` directly without starting the consumer, the
   signals queue up but nothing processes them. Tests hang or assert wrong state.

   **Mitigation**: S-02 §2.1 mentions "inject mock RunWorkflow creation" — a
   factory interface. If S-02 implements a synchronous/test-mode consumer (e.g.,
   `DrainOnceConsumer`), tests should use it. Step 6 should verify that the
   integration test fixture starts (or mocks) the consumer.

---

### Task 2: Run Full Frontend Test Suite

**Assumptions**
- Frontend `RunStatus` type includes `"stopping"` after S-01.
- Frontend API client was updated to handle 202 responses for start/pause/resume/cancel.
- The exact file path for the frontend `RunStatus` type is known.

**Expected Output**
- `cd ui && npm test -- --run` exits 0.

**Blockers and Mitigations**

1. **Missing `"stopping"` in frontend RunStatus type** (HIGH RISK if S-01 missed it):
   The step mentions this as a "common cause" but doesn't specify which TypeScript
   file to edit. The `RunStatus` type likely lives in `ui/src/types/runs.ts`. If
   S-01 added `STOPPING` to the Python enum but didn't update the TypeScript type,
   tsc will also fail in Task 3.

   **Hardening**: Add explicit file reference to step: `ui/src/types/runs.ts` (or
   wherever `RunStatus` is defined). Step 2 should fail-fast on `tsc --noEmit`
   before running the full npm test suite.

2. **HTTP 200 → 202 assertions in frontend tests** (MEDIUM RISK): If any frontend
   test mocks the API and asserts `status: 200` for lifecycle endpoints, it will
   fail. Step 2 correctly lists this as a common cause but doesn't specify which
   test files to check.

   **Mitigation**: `grep -rn "status: 200\|statusCode: 200" ui/src/` scoped to
   tests that exercise start/pause/resume/cancel endpoints.

---

### Task 3: Run Type Checker and Linter

**Assumptions**
- `consumer.py` was created in S-02 and is type-correct.
- All imports removed in S-04 (registry functions from `__init__.py`) have been
  removed from every importing file, not just `__init__.py` itself.
- No circular imports were introduced when consumer.py imports from signals.py.

**Expected Output**
- `pyright src/` exits 0, `ruff check src/` exits 0, `tsc --noEmit` exits 0.

**Blockers and Mitigations**

1. **Stale imports after registry isolation** (HIGH RISK): After S-04 removes
   `has_active_workflow` from `workflow/__init__.py __all__`, any file that does
   `from orchestrator.workflow import has_active_workflow` will get an `ImportError`
   at runtime and a `pyright` error at type-check time. This must be clean before
   Step 6.

   **Mitigation**: Before Step 6, run:
   ```bash
   grep -rn "from orchestrator.workflow import.*has_active_workflow\|
   from orchestrator.workflow.signals import.*has_active_workflow" src/ tests/
   ```
   All hits must be consumer.py or its test file.

2. **Ruff unused-import warnings** (LOW RISK): Removing registry function calls from
   `service.py` may leave orphaned `from ... import has_active_workflow` lines that
   ruff will flag as `F401 unused import`. These are trivial to fix but easy to miss.

3. **Consumer.py type errors** (MEDIUM RISK): If `consumer.py` uses `asyncio.Task`
   type annotations, pyright requires careful handling of `asyncio.Task[None]` vs
   bare `Task`. The `RunWorkflow` factory interface (plan.md §8) must be typed
   consistently with how `RunWorkflow` is instantiated.

---

### Task 4: Remove Dead Code from Old Dual-Path Routing

**Assumptions**
- After S-03, `service.py` contains no `has_active_workflow` calls.
- After S-03 [I-13], `runtime.py` (RunWorkflow) does not call `unregister_active_run`.
- The no-op `handle_resume` in `runtime.py` (lines 291–299 at analysis time) has
  been replaced by a real implementation or removed entirely.

**Expected Output**
- `grep -rn "has_active_workflow" src/orchestrator/workflow/service.py` returns nothing.
- `grep -rn "has_active_workflow" src/orchestrator/api/` returns nothing.
- `grep -n "handle_resume" src/orchestrator/workflow/run_workflow.py` returns nothing
  (or only a real implementation).

**Blockers and Mitigations**

1. **handle_resume ambiguity — dead code vs. real implementation** (HIGH RISK):
   The step says "remove no-op handle_resume log." But per [I-09] and [I-36], RESUME
   must become functional. The question is: where does RESUME handling live after
   S-02 and S-03?

   In the target architecture, `RESUME` is handled by the consumer (creates a new
   `RunWorkflow` for a PAUSED run). The existing `RunWorkflow.handle_resume()` at
   analysis time is a no-op because RESUME was sent to a running workflow — after
   the refactor, RESUME never reaches a live `RunWorkflow` (it creates a new one).
   So `handle_resume()` in `RunWorkflow` is genuinely dead after S-02/S-03.

   **Risk**: If S-02/S-03 does not remove `handle_resume` from `RunWorkflow`,
   the pre-commit guard in S-05 may or may not catch it (it guards registry calls,
   not no-ops). Step 6 Task 4 must explicitly confirm: does `RunWorkflow` still have
   a `handle_resume()` method? If yes, is it called? If not called, remove it.

   **Hardening**: The step's grep pattern `grep -n "handle_resume"
   src/orchestrator/workflow/run_workflow.py` must check `runtime.py` as well
   (the actual file at analysis time is `signals/runtime.py`, not `run_workflow.py`).
   The step file references `run_workflow.py` which may be an alias or the wrong path.

2. **Wrong file path in grep commands** (MEDIUM RISK): The step file references
   `src/orchestrator/workflow/run_workflow.py` but the actual file explored is
   `src/orchestrator/workflow/signals/runtime.py`. If these are different files,
   the grep will return no output (vacuously "clean") while the dead code remains in
   `runtime.py`.

   **Hardening**: Before Step 6 execution, verify actual file paths:
   ```bash
   find src/orchestrator/workflow -name "*.py" | sort
   ```
   Update grep commands to target the correct paths.

3. **retry_fan_out_child dead code** (LOW RISK): `retry_fan_out_child()` at analysis
   time has `has_active_workflow` checks at lines 1100 and 1112. S-03 step 3.3
   removes this. If it was not cleaned up, Step 6 Task 4 will catch it — but the
   grep command in Task 4 does not include `retry_fan_out_child` scope. Add to the
   grep search.

---

### Task 5: Verify [I-XX] Traceability Coverage

**Assumptions**
- `docs/single-queue-2/intent.md` contains all 36 [I-XX] items.
- Each item already has or needs a `→ S-NN` or `→ NO-REQ` annotation.

**Expected Output**
- `grep "\[I-[0-9]" docs/single-queue-2/intent.md | grep -v "→"` returns nothing.

**Blockers and Mitigations**

1. **Annotation format inconsistency** (LOW RISK): The verification grep uses
   `grep -v "→"`. If any annotation uses `->` (ASCII arrow) instead of `→`
   (Unicode), the grep will report false failures. Also, if [I-XX] items appear as
   back-references (e.g., in comments), they may not have `→` annotations and will
   generate false hits.

   **Hardening**: Use a more precise pattern:
   ```bash
   grep -n "\[I-[0-9][0-9]*\]" docs/single-queue-2/intent.md | grep -v "→\|->"
   ```

2. **Item count check** (LOW RISK): The intent document has items [I-01] through
   [I-27+]. If items were added after the plan was written without being assigned
   to steps, they appear unannotated. Step 5 correctly catches this — no additional
   hardening needed beyond running the grep.

---

### Task 6: Final Full Suite Pass

**Assumptions**
- All of Tasks 1–5 have been completed successfully.
- `scripts/check_signal_routing.py` exists (created in S-05).
- The pre-commit guard correctly identifies consumer.py as the allowed module.

**Expected Output**
- All checks exit 0.

**Blockers and Mitigations**

1. **check_signal_routing.py allow-list path** (MEDIUM RISK): The guard must be
   configured with the correct path for the consumer module. If the allow-list uses
   `consumer.py` (basename) but the script walks absolute paths, the comparison may
   fail. Conversely, if consumer.py imports registry functions from signals.py (which
   it must), signals.py must NOT be in the deny list for those functions.

   **Hardening**: Step 5 (S-05) should specify the exact allow-list path as
   `src/orchestrator/workflow/signals/consumer.py`. Step 6 should verify the guard
   doesn't accidentally flag consumer.py itself.

2. **Guard false positives in test files** (LOW RISK): Test files for the consumer
   (`tests/unit/test_signal_consumer.py`, `tests/unit/test_signal_redelivery.py`)
   likely call or import registry functions. The guard must include these test files
   in the allow-list or support `# noqa: signal-routing` suppression (mentioned in
   plan S-05).

   **Hardening**: Confirm that the guard's allow-list includes the consumer test
   files, or confirm that those tests use consumer-mediated calls (not direct
   registry calls).

---

## Cross-Cutting Failure Modes

### FM-1: Consumer Wiring Not Verified by Tests

The most critical wiring check for this architecture is: **does the consumer
actually process signals, or do signals accumulate in `pending_signals` forever?**

After S-03, `start_run()` enqueues a `RUN_START` signal and returns 202. If the
consumer is not started (e.g., `executor.py` was not updated in S-03 step 3.4), all
integration tests that wait for `run.status == "active"` will time out. This is the
most common "it compiled but doesn't work" failure mode for async architectures.

**Verification step missing from Step 6**: Add explicit verification that
`pending_signals` table is empty after a successful run lifecycle in integration
tests. A non-empty `pending_signals` at test end indicates the consumer is not
processing.

**Hardening**: Add to Task 1:
```bash
# After running integration tests, check for stuck signals:
uv run python -c "
from orchestrator.db import get_session
from orchestrator.db.models import PendingSignal
with get_session() as s:
    count = s.query(PendingSignal).filter(PendingSignal.handled_at.is_(None)).count()
    print(f'Unhandled signals: {count}')
"
```

### FM-2: `unregister_active_run` Calls Remain in runtime.py

At analysis time, `runtime.py` lines 286 and 310 call `unregister_active_run()`. Per
[I-13], S-03 must remove these. After S-04 removes registry function exports, if
these calls remain, they become `AttributeError` at runtime (and `ImportError` at
module load if the import is also removed). This would cause ALL tests using
RunWorkflow to fail.

**Hardening**: Task 4 should explicitly grep for `unregister_active_run` in
`src/orchestrator/workflow/signals/runtime.py`:
```bash
grep -n "unregister_active_run\|register_active_run" \
  src/orchestrator/workflow/signals/runtime.py
```
Expected: no output (should have been removed in S-03).

### FM-3: STOPPING State Not in Frontend Types

If S-01 added `STOPPING` to the Python enum but did not update `ui/src/types/runs.ts`,
TypeScript will reject the value when the backend returns it in API responses. This
manifests as tsc errors in Task 3. Task 2's frontend tests might pass (if tests don't
exercise STOPPING responses) while Task 3 fails.

**Hardening**: Make tsc the FIRST check in Task 3, before running the full npm test
suite. TypeScript errors are faster to catch and fix than runtime test failures.

### FM-4: Integration Test Fixture Does Not Start Consumer

The plan.md §Resolved Design Decisions item 8 states: "Consumer tests need a way to
inject mock RunWorkflow creation. Define a factory interface the consumer uses."

If the integration test fixture (likely in `tests/conftest.py` or
`tests/integration/conftest.py`) does not start the consumer alongside the
`WorkflowService`, then all integration tests that exercise the full lifecycle
through the API will observe signals in the queue but no state transitions.

**Verification**: Before Task 1, check:
```bash
grep -n "consumer\|SignalConsumer\|start_consumer" \
  tests/integration/conftest.py tests/conftest.py 2>/dev/null
```
If no hits, the consumer is not started in tests — this is a critical gap.

---

## Summary of Hardening Actions

| # | Risk | Severity | Hardening Action |
|---|------|----------|-----------------|
| H1 | Async state assertion mismatch in integration tests | HIGH | Add `wait_for_status()` test helper; verify consumer is started in test fixtures |
| H2 | `handle_resume` in wrong file (`runtime.py` not `run_workflow.py`) | HIGH | Update grep in Task 4 to target `runtime.py` |
| H3 | Consumer not wired into executor (signals enqueue but never process) | HIGH | Add `pending_signals` empty-check after integration tests |
| H4 | `unregister_active_run` calls remain in `runtime.py` after S-03 | HIGH | Add explicit grep for registry calls in `runtime.py` to Task 4 |
| H5 | Integration tests don't start consumer | HIGH | Check conftest.py for consumer startup; add if missing |
| H6 | `"stopping"` missing from frontend `RunStatus` type | MEDIUM | Run `tsc --noEmit` first in Task 3; specify `ui/src/types/runs.ts` as target |
| H7 | check_signal_routing.py allow-list path mismatch | MEDIUM | Verify guard allows both `consumer.py` and its test files |
| H8 | Stale imports of registry functions in non-consumer files | MEDIUM | Pre-Task-1 grep for registry function imports outside consumer |
| H9 | `retry_fan_out_child` dead code not covered by Task 4 grep | LOW | Extend Task 4 grep to include that method |
| H10 | Intent annotation format inconsistency (ASCII vs Unicode arrow) | LOW | Use both `→` and `->` in verification grep |

---

## Pre-Conditions Checklist for Step 6

Before beginning Step 6, confirm:

- [ ] `src/orchestrator/workflow/signals/consumer.py` exists (S-02 output)
- [ ] `scripts/check_signal_routing.py` exists (S-05 output)
- [ ] `src/orchestrator/db/models.py` has `STOPPING = "stopping"` in `RunStatus`
- [ ] Alembic migration exists with `delivered_at` column and `handled_at` rename
- [ ] `service.py` has no `has_active_workflow` calls (S-03 output)
- [ ] `runtime.py` has no `unregister_active_run` calls (S-03 [I-13] output)
- [ ] `workflow/__init__.py` does not export registry functions in `__all__` (S-04 output)
- [ ] Integration test fixture starts the consumer loop
- [ ] Frontend `RunStatus` type includes `"stopping"`
- [ ] API lifecycle endpoints return 202 (not 200)

If any of these are not true, the corresponding prior step is incomplete and Step 6
will surface failures that cannot be "fixed inline."
