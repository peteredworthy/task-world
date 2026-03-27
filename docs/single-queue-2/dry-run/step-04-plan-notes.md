# Step 4 Dry-Run Analysis: Registry Isolation

**Date:** 2026-03-26
**Source:** `docs/single-queue-2/steps/step-04-plan.md`

---

## Executive Summary

Step 4 is a purely mechanical cleanup step — correct in principle, and the tasks are
well-structured. However, the step cannot be executed safely without S-03 being fully
complete first. As of this dry-run, the registry functions are still live call sites
in both `service.py` and `runtime.py`, not stale imports. Additionally, `consumer.py`
does not yet exist (built in Phase 2/S-02), and one file reference in the plan uses
the wrong filename (`run_workflow.py` vs `runtime.py`). All failure modes are
mitigable with targeted hardening actions.

---

## Pre-run State (Verified by Code Search)

### Registry function locations in `src/`

| File | Type | Lines |
|------|------|-------|
| `signals/signals.py` | **definitions** | ~224–236 |
| `signals/__init__.py` | re-export (import + `__all__`) | 3–43 |
| `workflow/__init__.py` | re-export (import + `__all__`) | 94–111, 252–268 |
| `signals/runtime.py` | **active call sites** | 176, 183, 195, 205, 286, 310 |
| `workflow/service.py` | **active call sites** | pause_run, cancel_run, resume_run, retry_fan_out_child |

### Registry function locations in `tests/`

**No test files reference any registry function.** (Confirmed by grep.)

### `consumer.py` status

**Does not exist.** The file `src/orchestrator/workflow/signals/consumer.py` is not
present in the current codebase. It is a Phase 2 artifact (S-02). Step 4 is only
valid after Phases 2 and 3 are complete.

---

## Task-by-Task Analysis

### Task 1: Audit Registry Function Usage

**Assumptions being made:**
- The audit grep will produce a short, manageable list.
- After S-03, `service.py` and `runtime.py` will only have stale imports.
- `consumer.py` exists and is the only live caller.

**Expected outputs (post-S-03):**
- `signals.py` — 3 definitions (keep)
- `consumer.py` — imports + calls (keep, update form in Task 4)
- `signals/__init__.py` — re-exports to remove (Task 2)
- `workflow/__init__.py` — re-exports to remove (Task 3)
- `service.py` — stale import(s) to remove (Task 5)
- `runtime.py` — stale import(s) to remove (Task 5)

**Blockers:**
- If S-03 is incomplete, `service.py` and `runtime.py` will show active call sites
  (not just stale imports). Task 1 is the correct gate: the implementor should stop
  and escalate if call sites still appear in these files.

**Mitigation:** Task 1 already asks to "Confirm that after S-03 rewiring, `service.py`
only contains stale/unused imports." This verification should be a hard stop condition,
not just a mental note.

---

### Task 2: Remove Registry Exports from `signals/__init__.py`

**Assumptions being made:**
- `workflow/__init__.py` will be updated in Task 3 before any tests are run.
- The import block in `signals/__init__.py` matches the code shown.

**Expected outputs:**
- Three names removed from the `from ... import (...)` block and `__all__`.
- File still syntactically valid.

**CRITICAL FAILURE MODE — Ordering**: `workflow/__init__.py` imports
`has_active_workflow`, `register_active_run`, `unregister_active_run` from
`orchestrator.workflow.signals` (i.e., from `signals/__init__.py`). If Task 2 is
applied and any tests run before Task 3 is complete, the entire
`orchestrator.workflow` package will fail to import with:

```
ImportError: cannot import name 'has_active_workflow' from 'orchestrator.workflow.signals'
```

This would cascade: every test that imports from `orchestrator.workflow` will fail,
even tests unrelated to registry functions.

**Mitigation:** The step must be executed atomically through Task 3 before running
any verification. The "DO NOT CHECK UNTIL IMPLEMENTATION IS COMPLETE" note applies
at the step level, not the task level, but this dependency is not stated explicitly.
Add an explicit note that Task 2 + Task 3 must be completed together before running
any import verification.

---

### Task 3: Remove Registry Exports from `workflow/__init__.py`

**Assumptions being made:**
- Lines ~106–110 contain `has_active_workflow`, `register_active_run`,
  `unregister_active_run` in the import block. **Verified: correct** (lines 106–110).
- Lines ~264–268 contain these in `__all__`. (Consistent with observed export structure.)

**Expected outputs:**
- Three names removed from the import block and `__all__`.
- File still syntactically valid.
- All other exports (WorkflowEngine, SignalQueue, etc.) continue to work.

**No additional failure modes** beyond the ordering dependency noted in Task 2.

---

### Task 4: Update `consumer.py` to Use Direct Relative Import

**CRITICAL FAILURE MODE — File does not exist**: `consumer.py` does not currently
exist in `src/orchestrator/workflow/signals/`. This task will have nothing to operate
on until Phase 2 (S-02) is complete.

Additionally, the current import form in `consumer.py` (once built) is unknown until
S-02 is implemented. The step assumes it imports from the package `__init__`
(`from orchestrator.workflow.signals import ...`), but the S-02 implementation may
already use the direct internal import (`from orchestrator.workflow.signals.signals import ...`).
If S-02 already uses the direct form, Task 4 becomes a no-op verification step rather
than a code change.

**Mitigation:** Before executing Task 4, verify that `consumer.py` exists (S-02
prerequisite) and grep its current import form. If already using the direct import,
skip the edit and just verify.

---

### Task 5: Remove Stale Registry Imports from Non-Consumer Source Files

**Assumptions being made:**
- After S-03, `service.py` has only stale imports (no call sites).
- After S-03, `runtime.py` has only stale imports (no call sites).
- No other source files outside `signals.py`, `consumer.py`, `service.py`, `runtime.py`
  import registry functions.

**CRITICAL FAILURE MODE — Call sites not yet removed**: Currently, `runtime.py`
has active call sites (not just imports):

| Line | Call |
|------|------|
| 176 | `register_active_run(run_id)` |
| 183 | `unregister_active_run(run_id)` (CancelledError handler) |
| 195 | `unregister_active_run(run_id)` (Exception handler) |
| 205 | `unregister_active_run(run_id)` (finally block) |
| 286 | `unregister_active_run(self.run_id)` (handle_pause signal handler) |
| 310 | `unregister_active_run(self.run_id)` (handle_cancel signal handler) |

Similarly, `service.py` has active call sites in `cancel_run()`, `pause_run()`,
`resume_run()`, and `retry_fan_out_child()` — not just stale imports.

If Task 5 is executed when any call site remains, removing the import will cause
a `NameError` at runtime, breaking the affected code path. The test suite WILL catch
this if integration tests cover those paths (which they do), but the failure mode
is silent during development if only unit tests are run first.

The step itself contains the correct safety: "If any call site remains after removing
the import, the test suite will surface an AttributeError or NameError. This indicates
S-03 rewiring is incomplete — do NOT delete the call site without fixing the underlying
logic gap; escalate instead." This guidance is correct, but should be treated as a
**hard stop**, not a recovery option.

**Mitigation:** Before any Task 5 edits, verify zero call sites (not just import lines)
with a targeted grep:
```bash
grep -n "register_active_run\|unregister_active_run\|has_active_workflow" \
  src/orchestrator/workflow/service.py \
  src/orchestrator/workflow/signals/runtime.py
```
Any line that is NOT a bare `import` statement indicates S-03 is incomplete.

**File reference error — `run_workflow.py` vs `runtime.py`**: The step plan file
(bottom Tasks section) mentions `run_workflow.py` as a potential file to audit or update.
The actual file is `src/orchestrator/workflow/signals/runtime.py`. There is no
`run_workflow.py` in the codebase. An implementor must know to look at `runtime.py`.
The step file itself (Task 5 main body) correctly references `runtime.py`, so this
inconsistency is between the step plan and the step file — low risk but worth noting.

**Grep scope note**: The final confirming grep in Task 5 only covers `src/`. Since no
test files currently reference registry functions, this is adequate. But if Phase 2
creates `tests/unit/test_signal_consumer.py` with direct imports of registry functions,
the `src/`-only grep would give a false "clean" result. The step's final verification
criteria grep also only covers `src/`, which creates the same gap.

**Mitigation:** Change the confirming grep to cover both `src/` and `tests/` — or
note explicitly that `tests/` is clean (confirmed) and `consumer.py` tests are allowed
to import directly from `signals.py`.

---

## Summary of Failure Modes and Hardening Actions

| # | Failure Mode | Severity | Hardening Action |
|---|-------------|----------|-----------------|
| F-1 | `consumer.py` does not exist — Task 4 has no target | **Blocker** | Add explicit S-02 prerequisite check: verify `consumer.py` exists before starting |
| F-2 | S-03 incomplete: `service.py`/`runtime.py` have live call sites, not stale imports | **Blocker** | Task 1 grep must treat any non-import match in these files as a hard stop; do not proceed |
| F-3 | Task 2 + Task 3 ordering: removing from `signals/__init__.py` before `workflow/__init__.py` breaks all module imports | **High** | Document that Tasks 2 and 3 must be applied atomically; do not run tests between them |
| F-4 | `run_workflow.py` filename in step plan — file doesn't exist (actual is `runtime.py`) | **Medium** | Harmless if implementor uses the step file (which is correct), but the plan file is misleading |
| F-5 | Final verification grep only covers `src/` — misses test files that may import registry functions after Phase 2 | **Low** | Extend grep to `tests/` in both confirming grep and final verification criteria |
| F-6 | `consumer.py` may already use direct import form (S-02 could implement it correctly) — Task 4 becomes unnecessary | **Low** | Verify import form before editing; skip edit if already correct |
| F-7 | `runtime.py` has 6 active call sites — removing the import without removing calls produces silent runtime failures on code paths covered only by integration tests | **Medium** | Pre-Task-5 grep that flags any non-import match as a blocker |

---

## Verdict

Step 4 is **safe to execute IF S-02 and S-03 are fully complete**. The mechanical
nature of the changes (export removal + import cleanup) means the risk of introducing
new bugs is low. The primary risk is executing prematurely when prerequisites are not
met, in which case the test suite would catch the breakage.

**Recommended hardening before execution:**
1. Add a gate at the start of Task 1: grep for non-import call sites in `service.py`
   and `runtime.py`; stop and escalate if any are found.
2. Note explicitly that Tasks 2 and 3 must be applied in a single atomic edit session
   before running any Python import verification.
3. Verify `consumer.py` exists before starting Task 4.
4. Extend final verification greps to include `tests/` directory.
