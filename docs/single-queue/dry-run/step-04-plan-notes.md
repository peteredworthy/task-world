# Step 04: Registry Isolation — Dry-Run Analysis

**Date:** 2026-03-26
**Status:** Simulation — No code changes made
**Purpose:** Identify assumptions, failure modes, and gaps in Step 04 before execution

---

## Executive Summary

**Step 04 has a **CRITICAL BLOCKING DEPENDENCY**: Steps 02 and 03 are incomplete.**

This analysis simulates Step 04 execution and identifies:

1. **Cascading dependency failures** — Step 04 cannot be executed without Steps 01–03 being complete
2. **Missing prerequisite code** — `consumer.py` does not exist (Step 02 blocker)
3. **Incomplete sender rewiring** — `service.py` still calls `has_active_workflow()` (Step 03 blocker)
4. **Component wiring gap** — `runtime.py` calls registry functions but is not explicitly named or structured as the consumer
5. **Concrete hardening actions** needed to make Step 04 executable

---

## Current State Assessment

### Codebase Snapshot

**Registry functions location:**
- `src/orchestrator/workflow/signals/signals.py` lines 221–236
- Exported via `__all__` in `src/orchestrator/workflow/signals/__init__.py` and `src/orchestrator/workflow/__init__.py`

**Current callers of registry functions:**

| File | Function | Usage | Notes |
|------|----------|-------|-------|
| `src/orchestrator/workflow/signals/runtime.py` | `register_active_run()`, `unregister_active_run()` | Called in RunWorkflow lifecycle | Appropriate for current architecture; equivalent to "consumer" for single run |
| `src/orchestrator/workflow/service.py` | `has_active_workflow()` | Branches on this call in pause/resume/cancel methods | **Should not exist in Step 03+** |

**Missing components:**
- `src/orchestrator/workflow/signals/consumer.py` — **Does not exist** (Step 02 blocker)
- `RunStatus.STOPPING` — **Not in enum** (Step 01 blocker)
- `WorkflowSignal.RUN_START` — **Not in enum** (Step 01 blocker)

**Version tracking:**
- Git history shows step documents were added but no implementation commits for Steps 02–03
- Commits are about "converting step plan to structured step file" (documentation only)

---

## Task-by-Task Analysis

### Task 1: Audit Registry Function Usage and Location

**Assumptions Made by the Step:**
1. Registry functions exist in `signals.py` at lines 221–236
2. `consumer.py` exists and is ready to receive the functions
3. All external callers were removed by Step 03
4. `_active_run_ids` is a simple module-level set with no dependencies

**Expected Outputs:**
- Audit report showing:
  - Location of `_active_run_ids` definition
  - All files importing registry functions
  - Count and nature of usages

**What We Actually Found:**

✅ **Correct assumptions:**
- Registry functions ARE at lines 221–236 in `signals.py`
- `_active_run_ids` IS a simple module-level `set[str]`
- Functions ARE exported via `__init__.py` files

❌ **Broken assumptions:**
- `consumer.py` **DOES NOT EXIST** — Step 02 incomplete
- `service.py` **STILL CALLS** `has_active_workflow()` — Step 03 incomplete
- External callers were NOT removed — Step 03 was not executed

**Failure Modes:**

1. **Grep finds unexpected callers** — Step 03 was supposed to eliminate `has_active_workflow` calls in `service.py`, but they remain:
   ```bash
   src/orchestrator/workflow/service.py:        if has_active_workflow(run_id):
   ```
   **Impact:** Task 1 audit will show that external callers exist when they shouldn't.
   **Mitigation:** Before Task 1, run Task 03 to completion.

2. **Import structure is multi-level** — Registry functions are re-exported through two `__init__.py` files:
   ```
   signals/signals.py (definition)
   → signals/__init__.py (re-export)
   → workflow/__init__.py (re-export)
   ```
   **Impact:** Task 3 (import updates) must check all three levels, not just direct imports from `signals.py`.
   **Mitigation:** Grep for all variants:
   - `from orchestrator.workflow.signals import register_active_run`
   - `from orchestrator.workflow import register_active_run`
   - `from orchestrator.workflow.signals.signals import register_active_run` (direct)

3. **Audit doesn't verify consumer.py exists** — The grep commands will run but the verification step "Verify that consumer.py exists" will fail.
   **Mitigation:** Add explicit check: `test -f src/orchestrator/workflow/signals/consumer.py || { echo "ERROR: consumer.py not found"; exit 1; }`

---

### Task 2: Move Registry Functions to consumer.py

**Assumptions Made by the Step:**
1. `consumer.py` exists and is writable
2. Consumer.py has no import of `signals.py` at module level (avoid circular import)
3. The registry functions have no dependencies on `signals.py` content
4. Insertion location in consumer.py is appropriate (after imports, before main logic)

**Expected Outputs:**
- Registry functions moved to consumer.py
- Functions removed from signals.py
- Removed from `__all__` lists if present
- Syntax and import validation passes

**What Will Fail:**

❌ **CRITICAL: consumer.py does not exist**
- File not found error on any write/edit operation
- **Immediate blocker:** Cannot proceed with Task 2

**Assumptions we cannot verify:**
- Whether consumer.py imports signals.py (unknown — file doesn't exist)
- Whether insertion point is appropriate (unknown — file doesn't exist)
- Whether moved functions will have import-time dependencies (unknown — need to inspect actual consumer.py first)

**Failure Modes:**

1. **File not found** — `cp src/orchestrator/workflow/signals/signals.py src/orchestrator/workflow/signals/consumer.py` equivalent will fail because target doesn't exist.
   **Hardening action:** Step 2 should explicitly create consumer.py from template or Step 02 must be completed first.

2. **Circular import on consumer.py import** — If consumer.py needs to import signal types (e.g., `WorkflowSignal`), and signals.py imports consumer.py, this creates a cycle.
   **Hardening action:** Review Step 02 consumer.py structure to ensure signals.py is NOT imported at module level.

3. **Runtime.py is the de-facto consumer** — The codebase actually has `runtime.py` (RunWorkflow) that owns the registry lifecycle. Moving the registry to a file called `consumer.py` might cause confusion.
   **Hardening action:** Step 02 should clarify the relationship: is `consumer.py` a new module that manages the signal loop, or is it a refactor of `runtime.py`?

4. **__all__ in signals.py might not exist** — The step assumes we can check `__all__`, but if it doesn't exist, there's nothing to update. Python allows implicit exports of non-underscore names.
   **Verification:** `grep "__all__" src/orchestrator/workflow/signals/signals.py` — **Result:** No `__all__` found in signals.py itself. The exports are defined in `__init__.py` files.
   **Hardening action:** Task 2 must update `signals/__init__.py` and `workflow/__init__.py` to remove the three function names from their `__all__` lists.

---

### Task 3: Update All External Imports of Registry Functions

**Assumptions Made by the Step:**
1. All imports follow standard patterns (from X import Y)
2. Test files that need these functions can be identified and updated
3. Step 03 cleanup means production code doesn't import these
4. No "qualified imports" like `signals.register_active_run()` exist

**Expected Outputs:**
- All imports updated to import from consumer.py instead of signals.py
- No imports from signals.py remain (except consumer.py itself)
- All files compile without import errors

**What Will Fail:**

❌ **service.py still imports and calls `has_active_workflow`** (Step 03 incomplete)
```python
from orchestrator.workflow.signals import has_active_workflow
...
if has_active_workflow(run_id):
    # branch code
```

**Impact:** These imports are not supposed to exist. Task 3 assumes they've been removed, but they haven't.
**Mitigation:** Complete Step 03 first. Step 03.1 should rewrite `service.py.start_run()` to unconditionally enqueue signals.

**Failure Modes:**

1. **Import path ambiguity** — The re-export chain allows multiple valid import paths:
   ```python
   # All of these currently work:
   from orchestrator.workflow.signals import register_active_run
   from orchestrator.workflow.signals.signals import register_active_run
   from orchestrator.workflow import register_active_run
   ```
   Grep pattern might find one but not the other.
   **Hardening action:** Run THREE separate greps:
   ```bash
   grep -r "from orchestrator.workflow.signals import.*register_active_run" --include="*.py" src/
   grep -r "from orchestrator.workflow.signals.signals import.*register_active_run" --include="*.py" src/
   grep -r "from orchestrator.workflow import.*register_active_run" --include="*.py" src/
   ```

2. **Qualified calls not caught by grep** — Code might call `signals.register_active_run()` without importing the function name directly:
   ```python
   from orchestrator.workflow import signals
   signals.register_active_run(run_id)
   ```
   Grep won't find this unless we search for the call pattern.
   **Hardening action:** Add grep for call patterns: `grep -r "register_active_run()\|unregister_active_run()\|has_active_workflow()" --include="*.py" src/ | grep -v "def "`

3. **__init__.py files must be updated** — The step focuses on import statements in consumer.py and test files, but `__init__.py` files also export these functions.
   ```python
   # src/orchestrator/workflow/signals/__init__.py
   __all__ = [
       ...
       "register_active_run",
       "unregister_active_run",
       "has_active_workflow",
   ]
   ```
   Removing from `signals.py` doesn't remove from `__all__`.
   **Hardening action:** Task 3.2 (not in current plan) must update:
   - `src/orchestrator/workflow/signals/__init__.py`
   - `src/orchestrator/workflow/__init__.py`
   Remove the three function names from both `__all__` lists.

4. **Test files might need special handling** — Some tests might stub or mock the registry. Updating imports blindly could break test setup.
   **Hardening action:** Identify test files that import or mock registry functions before updating:
   ```bash
   grep -r "register_active_run\|unregister_active_run\|has_active_workflow" --include="*.py" tests/ | grep -v "__pycache__"
   ```

---

### Task 4: Verify Isolation and Run Regression Tests

**Assumptions Made by the Step:**
1. Tasks 1–3 completed successfully
2. Baseline test count is known (for comparing regression)
3. No pre-existing test failures that would mask new issues
4. Consumer module is wired into the signal dispatch loop

**Expected Outputs:**
- Grep confirms no external imports remain
- All tests pass
- Type checking and linting pass
- No regressions

**What Will Fail:**

❌ **consumer.py doesn't exist** — Can't import from it, so Task 3 can't complete, so Task 4 has nothing to verify.

❌ **service.py still has `has_active_workflow` calls** — Grep will not be clean.

**Failure Modes:**

1. **Baseline test pass rate unknown** — The step says "All tests should pass" but doesn't establish a baseline beforehand.
   - **MEMORY.md context** says: "330 unit tests pass (was 324)" and "235 integration tests pass (was 227)"
   - Total: ~565 backend tests
   - If baseline is unknown, a regression could be missed.
   **Hardening action:** Before starting Step 04, record baseline:
   ```bash
   uv run pytest tests/unit -q --tb=no 2>&1 | tail -5
   uv run pytest tests/integration -q --tb=no 2>&1 | tail -5
   ```

2. **Component wiring incomplete** — Even if the registry functions are moved to consumer.py, the code path that calls them might not exist or might be dormant.
   - Current: `runtime.py` (RunWorkflow) calls `register_active_run()` and `unregister_active_run()`
   - Future (in Step 02): `consumer.py` should own these calls
   - **Gap:** If consumer.py exists but is never called by the executor startup, the functions are orphaned.
   **Hardening action:** After Task 2, verify consumer.py is imported and started somewhere. Search:
   ```bash
   grep -r "from.*consumer import\|import.*consumer" --include="*.py" src/ | grep -v "__pycache__"
   ```

3. **Registry calls in runtime.py still occur** — If runtime.py is NOT being replaced by consumer.py (they coexist), then moving the registry functions to consumer.py means runtime.py will fail to import them.
   - Current structure: runtime.py is RunWorkflow, which IS the per-run handler
   - Step 02 should add consumer.py as the signal dispatcher
   - Runtime.py will still need registry functions because it's still a running workflow
   **Hardening action:** Clarify: after Step 04, which module owns the registry?
   - If consumer.py: then runtime.py should import from consumer.py
   - If runtime.py: then don't move the registry
   - Assumption is consumer.py owns it (per Step 04 description), but runtime.py still uses it.
   **Required change:** Task 2 should ALSO update runtime.py imports:
   ```python
   # BEFORE
   from orchestrator.workflow.signals.signals import register_active_run, unregister_active_run

   # AFTER
   from orchestrator.workflow.signals.consumer import register_active_run, unregister_active_run
   ```

4. **Type checking might fail** — If pyright/mypy are strict, moving the functions without updating stubs (if any) could cause type errors.
   **Hardening action:** After Task 2, run:
   ```bash
   uv run pyright src/orchestrator/workflow/signals/ --outputjson 2>&1 | grep -i "error\|register_active\|unregister_active\|has_active"
   ```

5. **Pre-commit hook violations** — The step says "Pre-commit hook validation (from Step 05) will pass" but Step 05's guard script doesn't exist yet. This is circular.
   **Hardening action:** Step 04 should NOT assume Step 05 has been done. After Task 4, manually verify:
   ```bash
   grep -r "register_active_run\|unregister_active_run\|has_active_workflow" --include="*.py" src/ | grep -v "consumer.py" | grep -v "__pycache__" | grep -v "def "
   ```
   Should return empty (or only runtime.py if it still uses them, which is expected).

---

## Blocker Analysis: Cascading Dependencies

### Dependency Chain

```
Step 04 (Registry Isolation)
  ↑ DEPENDS ON
Step 03 (Sender Rewiring)
  ↑ DEPENDS ON
Step 02 (Consumer)
  ↑ DEPENDS ON
Step 01 (Schema and State Machine)
```

### Status of Prerequisites

| Step | Component | Status | Blocker |
|------|-----------|--------|---------|
| **Step 01** | `RunStatus.STOPPING` enum value | ❌ Missing | Cannot add guards for STOPPING state in Step 01.1 |
| **Step 01** | `WorkflowSignal.RUN_START` signal type | ❌ Missing | Cannot enqueue RUN_START in Step 03 |
| **Step 01** | Alembic migration for `pending_signals` schema | ❌ Missing | Cannot test signal handling without new schema columns |
| **Step 02** | `consumer.py` module | ❌ Does not exist | Cannot move registry functions to non-existent module |
| **Step 02** | Consumer signal dispatch loop | ❌ Missing | Cannot test signal handlers without the consumer |
| **Step 03** | `service.py` start_run() rewritten | ❌ Not done | `start_run()` still calls executor directly, not enqueueing RUN_START |
| **Step 03** | Registry calls removed from service.py | ❌ Not done | `service.py` still calls `has_active_workflow()` |
| **Step 04** | Registry functions moved | ❌ Blocked | Depends on Step 02 creating consumer.py |
| **Step 04** | External imports updated | ❌ Blocked | Can't update imports to non-existent module |

### Consequence

**Step 04 cannot be executed as written** until Steps 01–03 are complete.

If attempted anyway:
- Task 1 audit will show unexpected external callers (service.py)
- Task 2 will fail to create consumer.py
- Task 3 will attempt to update imports to a non-existent module
- Task 4 will show import/type errors and test failures

---

## Concrete Hardening Actions

### Before Step 04 Execution

1. **Verify Step 01 is complete:**
   ```bash
   # Check for STOPPING status
   grep "STOPPING" src/orchestrator/config/enums.py
   # Expected: STOPPING = "stopping" in RunStatus enum

   # Check for RUN_START signal
   grep "RUN_START" src/orchestrator/workflow/signals/signals.py
   # Expected: RUN_START = "run_start" in WorkflowSignal enum

   # Check for Alembic migration
   ls src/orchestrator/db/migrations/versions/ | grep "pending_signals\|stopping"
   # Expected: Migration file with delivered_at/handled_at columns
   ```
   **Action:** If any missing, complete Step 01 before proceeding.

2. **Verify Step 02 is complete:**
   ```bash
   # Check consumer.py exists
   test -f src/orchestrator/workflow/signals/consumer.py || echo "FAIL: consumer.py missing"

   # Check consumer has signal handlers
   grep "def handle_run_start\|def handle_pause\|def handle_resume" src/orchestrator/workflow/signals/consumer.py
   # Expected: Signal handler functions defined

   # Check consumer is started in executor/app
   grep -r "consumer\|Consumer" src/orchestrator/executor.py src/orchestrator/app.py | grep -i "import\|start\|loop"
   # Expected: Consumer loop started on app init
   ```
   **Action:** If any missing, complete Step 02 before proceeding.

3. **Verify Step 03 is complete:**
   ```bash
   # Check service.py no longer calls has_active_workflow
   grep "has_active_workflow" src/orchestrator/workflow/service.py
   # Expected: EMPTY (no matches)

   # Check service.py enqueues RUN_START, not executor.spawn_run()
   grep "enqueue\|RUN_START" src/orchestrator/workflow/service.py | head -10
   # Expected: Calls to enqueue with WorkflowSignal.RUN_START
   ```
   **Action:** If any has_active_workflow calls remain, complete Step 03 before proceeding.

4. **Establish regression baseline:**
   ```bash
   uv run pytest tests/unit -q --tb=no 2>&1 | tail -3
   # Record: e.g., "123 passed in 4.56s"

   uv run pytest tests/integration -q --tb=no 2>&1 | tail -3
   # Record: e.g., "45 passed, 2 failed in 6.23s"
   ```
   **Action:** Save baseline before Step 04 changes to distinguish new failures from pre-existing.

### During Task 2 Execution (Move Functions)

5. **Update imports in runtime.py explicitly:**
   - Task 2 moves the functions but doesn't specify updating runtime.py imports
   - runtime.py imports: `from orchestrator.workflow.signals.signals import register_active_run, unregister_active_run`
   - Must change to: `from orchestrator.workflow.signals.consumer import register_active_run, unregister_active_run`
   - **Action:** Add as a sub-task in Task 2

6. **Update __init__.py exports:**
   - signals/__init__.py has `__all__` list that includes the three function names
   - workflow/__init__.py re-exports them
   - **Action:** Task 2 should include:
     ```python
     # Remove from src/orchestrator/workflow/signals/__init__.py
     # Remove from src/orchestrator/workflow/__init__.py
     # Remove these lines from __all__:
     "register_active_run",
     "unregister_active_run",
     "has_active_workflow",
     ```

### During Task 3 Execution (Update Imports)

7. **Check all import path variants:**
   ```bash
   # Check direct imports
   grep -r "from orchestrator.workflow.signals.signals import.*register_active_run" --include="*.py" src/ tests/

   # Check re-exported imports
   grep -r "from orchestrator.workflow.signals import.*register_active_run" --include="*.py" src/ tests/

   # Check top-level re-exports
   grep -r "from orchestrator.workflow import.*register_active_run" --include="*.py" src/ tests/

   # Check qualified calls
   grep -r "\bsignals\.register_active_run\|signals\.unregister_active_run\|signals\.has_active_workflow" --include="*.py" src/ tests/
   ```
   **Action:** Run all four grep variants. Task 3 instruction currently only covers one pattern.

8. **Verify service.py is clean:**
   ```bash
   # After Step 03, service.py should not import these functions
   grep "has_active_workflow\|register_active_run\|unregister_active_run" src/orchestrator/workflow/service.py
   # Expected: EMPTY
   ```
   **Action:** If not empty, Step 03 is incomplete. Halt Step 04.

### During Task 4 Execution (Verify & Test)

9. **Verify consumer.py actually uses the registry functions:**
   ```bash
   grep -n "register_active_run\|unregister_active_run" src/orchestrator/workflow/signals/consumer.py | grep -v "def "
   # Expected: At least 2-4 calls (registration in start handlers, unregistration in pause/cancel handlers)
   ```
   **Action:** If zero calls, the functions are orphaned. Wiring is incomplete.

10. **Verify call sites in consumer:**
    ```bash
    # Should see register calls in RUN_START and RESUME handlers
    grep -B5 -A2 "register_active_run" src/orchestrator/workflow/signals/consumer.py

    # Should see unregister calls in PAUSE and CANCEL handlers (when active)
    grep -B5 -A2 "unregister_active_run" src/orchestrator/workflow/signals/consumer.py
    ```
    **Action:** If calls are missing, consumer.py signal handlers are incomplete. Refer back to Step 02.

11. **Run full regression test:**
    ```bash
    uv run pytest tests/unit -v --tb=short 2>&1 | tail -20
    uv run pytest tests/integration -v --tb=short 2>&1 | tail -20
    ```
    **Action:** Compare to baseline from pre-Step-04. Any NEW failures must be investigated and fixed before signing off.

12. **Type check with pyright:**
    ```bash
    uv run pyright src/orchestrator/workflow/signals/ --outputjson 2>&1 | jq '.generalDiagnostics[] | select(.severity == "error")' | head -20
    ```
    **Action:** Should return zero errors. Any errors about "register_active_run not found" indicates import updates missed something.

---

## Summary Table: Task-to-Failure Mapping

| Task | Assumption | Current State | Will Fail? | Mitigation |
|------|-----------|----------------|-----------|-----------|
| 1 | Registry functions in signals.py at 221–236 | ✅ True | No | — |
| 1 | consumer.py exists | ❌ False | Yes (audit step) | Complete Step 02 first |
| 1 | No external callers of registry functions | ❌ False (service.py calls them) | Yes (audit will show them) | Complete Step 03 first |
| 2 | consumer.py is writable/creatable | ❌ False (doesn't exist) | Yes (immediate) | Complete Step 02 first |
| 2 | Registry functions have no signals.py deps | ✅ True (they don't) | No | — |
| 2 | __all__ in signals.py needs update | ❌ False (no __all__ in signals.py) | No, but __init__.py does | Update __init__.py files (not in current plan) |
| 3 | All imports follow standard patterns | ✅ Mostly true | No (but variants exist) | Use all-four-variant grep pattern |
| 3 | service.py doesn't import these functions | ❌ False (it does) | Yes (imports won't be removed) | Complete Step 03 first |
| 3 | Test files can be updated mechanically | ✅ Likely true | No | Run import validation after updates |
| 4 | All previous tasks completed | ❌ False | Yes (import errors, test failures) | Complete Tasks 1–3 (which require Steps 01–03) |
| 4 | Consumer module is wired into executor | ❌ Unknown (depends on Step 02 quality) | Possibly | Verify consumer is imported and started |
| 4 | Tests pass with baseline | ❌ Unknown | Possibly | Establish baseline before starting |

---

## Recommendations

### Immediate Actions

1. **DO NOT EXECUTE STEP 04 YET** — Execute Steps 01–03 first.
2. **Complete Step 01** — Add STOPPING status, RUN_START signal type, Alembic migration.
3. **Complete Step 02** — Create consumer.py with signal dispatch loop and handlers.
4. **Complete Step 03** — Rewrite service.py to unconditionally enqueue signals, remove has_active_workflow calls.
5. **Then execute Step 04** with the hardening actions above integrated.

### Process Improvements

- **Add pre-checks to each step plan** — Include explicit verification that all prerequisites are complete before starting
- **Create integration tests per step** — Instead of just unit tests, each step should have integration tests that verify the entire dependency chain works
- **Define explicit "hand-off" criteria** between steps — Steps 01→02, 02→03, 03→04 should have clear entry/exit verification gates

### For Step 04 Specifically

- **Add Task 2a** (before moving functions): Verify Step 02 consumer.py exists and has signal handlers
- **Add Task 3a** (before updating imports): Verify service.py no longer calls has_active_workflow
- **Add Task 3b** (before running tests): Update __init__.py files (currently missing from plan)
- **Add Task 4a** (before test suite): Verify consumer signal handlers call register/unregister_active_run
- **Add task 4b** (after test suite): Verify no dead code (orphaned registry functions) remains

---

## Risk Assessment

| Risk | Severity | Likelihood | Impact |
|------|----------|-----------|---------|
| Attempt Step 04 without Step 02 consumer.py | Critical | High | Immediate file-not-found error; no recovery path |
| Attempt Step 04 without Step 03 service.py rewrite | High | High | Import updates create dangling references; tests fail |
| Registry functions moved but not called anywhere | High | Medium | Functions exist but are dead code; no runtime error but architectural goal unmet |
| __init__.py exports not updated | Medium | High | Functions removed from signals.py but still importable from workflow/__init__.py; architectural isolation incomplete |
| Circular imports introduced (consumer.py imports signals.py that imports from consumer.py) | High | Medium | Module initialization fails; entire signal system offline |
| Test baseline not established | Medium | High | Regressions masked by unknown pre-existing failures |

---

## Conclusion

Step 04 Registry Isolation is well-designed and properly scoped, but **it has three blocking dependencies (Steps 01–03) that must be completed first**. The step plan assumes:

1. ✅ Registry functions exist in signals.py (TRUE)
2. ❌ consumer.py exists and is ready (FALSE — Step 02 not done)
3. ❌ No external callers of registry functions (FALSE — Step 03 not done)
4. ❌ STOPPING status and RUN_START signal type exist (FALSE — Step 01 not done)

Once Steps 01–03 are complete and the hardening actions above are integrated into Task 2 and Task 3, Step 04 should execute cleanly.

The following items should be added to the Step 04 plan before execution:
- Pre-flight verification that Steps 01–03 are complete
- Explicit import of registry functions in runtime.py (missed by current plan)
- Update of __init__.py files (not mentioned in current plan)
- Explicit verification that consumer.py calls the registry functions (not just that they exist)
- Regression baseline establishment before making changes
