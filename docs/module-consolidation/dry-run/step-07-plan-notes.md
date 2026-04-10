# Step 7 Dry-Run Analysis: Restructure workflow/ Internals

## Source Verification

Current state of `src/orchestrator/workflow/` (22 flat files):

```
__init__.py, auto_verify.py, clarifications.py, completion.py,
condition_evaluator.py, context_builder.py, dry_run.py, engine.py,
errors.py, event_logger.py, events.py, gates.py, grades.py,
handlers.py, locks.py, prompts.py, runtime.py, service.py,
signals.py, summary_cache.py, templates.py, transitions.py
```

`workflow/artifacts/` does **not** exist yet — Phase 4 prerequisite has not been applied to this worktree.

`workflow/__init__.py` exports 37 symbols across 10 source files:
- From `engine`: Clock, DefaultClock, EventEmitter, NoOpEmitter, WorkflowEngine
- From `errors`: GateBlockedError, InvalidTransitionError, WorkflowError
- From `locks`: InMemoryLockManager, LockManager, LockTimeoutError, TaskLockedError
- From `events`: ChecklistGateEvaluated, GradesEvaluated, RunStatusChanged, TaskStatusChanged, WorkflowEvent
- From `gates`: GateResult, evaluate_checklist_gate
- From `grades`: DEFAULT_GRADE_ORDER, GradeResult, evaluate_grades
- From `prompts`: BuilderPrompt, VerifierPrompt, generate_builder_prompt, generate_verifier_prompt, get_task_context
- From `transitions`: VALID_TRANSITIONS, TransitionResult
- From `dry_run`: DryRunResult, build_dry_run_context, build_dry_run_prompt, execute_dry_run, get_step_by_id, parse_dry_run_response
- From `condition_evaluator`: ConditionEvalError, ConditionEvaluator, StepOutcome

`events.py` has **33+ exported symbols** (classes + BufferingEmitter), not 11 as implied by the step's template. The step's `events/__init__.py` template is severely under-specified — see Failure Mode 1.

`NoTaskReason` and `resolve_no_task_action` are in `runners/executor.py` (lines 53–97). `runtime.py` imports them via a lazy import at line 372: `from orchestrator.runners.executor import NoTaskReason, resolve_no_task_action`. `LoopAction` dataclass is also defined in `runners/executor.py` (line 63) alongside these — Task 6 does not mention it.

`src/orchestrator/executor.py` is a top-level backward-compat shim that re-exports `NoTaskReason`, `LoopAction`, `resolve_no_task_action` from `runners.executor`. Task 6 does not mention updating this file.

`DEFAULT_SUMMARIZE_MODEL` has exactly one consumer: `workflow/summary_cache.py`. Task 7 assumption confirmed.

---

## Task-by-Task Analysis

### Task 1: Audit External workflow/ Sub-Module Import Paths

**Assumptions:**
- The grep extracts sub-module names only (the `\K[a-z_]+` pattern after `workflow\.`). This misses compound paths like `workflow.events.types` or symbols imported from `workflow.signals.runtime` if they were already using sub-paths.
- The result will include: `auto_verify`, `clarifications`, `completion`, `condition_evaluator`, `context_builder`, `dry_run`, `engine`, `errors`, `event_logger`, `events`, `gates`, `grades`, `handlers`, `locks`, `prompts`, `runtime`, `service`, `signals`, `summary_cache`, `templates`, `transitions`.

**Expected outputs:**
- All 22 current sub-module names will appear in the list. The SAFE ones (where the new sub-package name matches the old filename) are: `engine`, `events`, `signals`. All others that move into a differently-named sub-package need bridges.
- Files that STAY at workflow root: `service.py`, `locks.py`, `completion.py`, `dry_run.py`. These appear in the grep results but need no bridges since they don't move.

**Blockers:** None — this is a read-only audit.

**Hardening:** The grep pattern `\K[a-z_]+` extracts only the first path segment. If any external file uses `from orchestrator.workflow.signals.runtime import RunWorkflow` (which would happen after this step is applied in a future run), the audit would show `signals` rather than `signals.runtime`. This is fine for the pre-move audit, which is its intended use.

---

### Task 2: Create workflow/engine/ Sub-Package

**Assumptions:**
- `engine.py` → `engine/engine.py`: `engine/` directory serves `orchestrator.workflow.engine` automatically. The original `engine.py` is deleted. This is correct Python behavior — a package (directory) takes precedence over a module (file) with the same name.
- `errors.py`, `transitions.py`, `gates.py`, `grades.py`, `condition_evaluator.py` stay at `workflow/` root as thin re-exports.

**Expected outputs:**
- `workflow/engine/__init__.py`, `engine/engine.py`, `engine/transitions.py`, `engine/gates.py`, `engine/grades.py`, `engine/condition_evaluator.py`, `engine/errors.py`
- Old `engine.py` deleted.
- `workflow/errors.py`, `transitions.py`, `gates.py`, `grades.py`, `condition_evaluator.py` become 1-line re-exports.

**Correctness check on engine/__init__.py symbols:**
The step's template includes `check_step_progression` from `engine/transitions.py`. This function exists in `transitions.py` and is imported by `runtime.py` and directly by external test code. Including it in `engine/__init__.py` is correct. However, `check_run_completion` (also in `transitions.py`) is NOT included in the template — external code imports it directly from `workflow.transitions`, so the bridge at `workflow/transitions.py` handles it. Consistent.

**Blockers:** None.

**Concern (low severity):** The step says "update any intra-module imports" in the copied files but does not specify which exact lines. For example, `engine.py` imports `from orchestrator.workflow.errors import` and `from orchestrator.workflow.events import`. After the copy to `engine/engine.py`, these absolute paths still resolve correctly (through bridges or packages). The implementer should not change these to relative imports — absolute paths work uniformly.

---

### Task 3: Create workflow/events/ Sub-Package

**Critical failure mode — see Failure Mode 1.**

**Assumptions:**
- `events.py` → `events/types.py`. `events/` directory serves `orchestrator.workflow.events` automatically. `events.py` is deleted.
- `events/__init__.py` re-exports all symbols currently exported by `events.py`.

**Severity of the template incompleteness:**
The step's `events/__init__.py` template lists 11 symbols. `events.py` actually defines **33 event classes + `GradeDetail` + `BufferingEmitter` = 35 symbols**. Missing from the template:

```
AutoVerifyCompleted, StepCompleted, RunStepBackward, AgentChangedEvent,
AgentDiedEvent, TaskReverted, AgentErrorEvent, ApprovalRequested,
ApprovalDecision, PruneApplied, TestRunStarted, TestRunCompleted,
ConflictResolved, BackMergeCompleted, BackMergeReverted, AgentFixStarted,
AgentFixCompleted, FanOutSpawned, ChildSpawned, ChildCompleted, ChildFailed,
FanOutCompleted, GradeDetail, BufferingEmitter
```

`ApprovalRequested` is imported by `runtime.py` (line 373, lazy import inside `_run_loop`). `BufferingEmitter` is imported in test files and potentially by `service.py`. Any symbol missing from `events/__init__.py` causes an `ImportError` for external code that imports it from `orchestrator.workflow.events`.

The step does say "Adjust the symbol list to match what events.py actually exports — audit with grep before writing." This is the correct instruction, but the template is so far from complete that it may mislead the implementer into thinking the list is nearly right when it is missing ~24 symbols.

**Hardening:** See Failure Mode 1 — require explicit audit output before writing `events/__init__.py`.

---

### Task 4: Create workflow/signals/ Sub-Package

**Assumptions:**
- `signals.py` → `signals/signals.py`. `signals/` directory serves `orchestrator.workflow.signals` automatically. `signals.py` deleted.
- `handlers.py` → `signals/handlers.py` with bridge at `workflow/handlers.py`.
- `runtime.py` → `signals/runtime.py` with bridge at `workflow/runtime.py`.

**Correctness:** `runtime.py`'s top-level imports (`from orchestrator.workflow.signals import ...`) resolve correctly after restructuring because `signals/__init__.py` re-exports those symbols. The lazy import at line 372 (`from orchestrator.runners.executor import NoTaskReason, resolve_no_task_action`) is removed in Task 6.

**Internal import update needed in signals/handlers.py:**
`handlers.py` currently imports `WorkflowSignal` from `orchestrator.workflow.signals`. After restructuring, this resolves to `signals/__init__.py` → `signals/signals.py`. This is safe as long as `signals/__init__.py` is populated before Python tries to resolve `signals/handlers.py`'s imports. Since Python populates `__init__.py` first when importing a package, and `handlers.py` is not imported at package init time (it's imported by `runtime.py`), no circular import cycle exists.

**signals/__init__.py correctness:** The template correctly re-exports `DbSignalTransport`, `SignalTransport`, `WorkflowSignal`, `build_registry`, `signal_handler`, `RunWorkflow`. However, `RunWorkflow` is in `signals/runtime.py`, not `signals/signals.py` or `signals/handlers.py`. The template correctly sources it from `signals.runtime`. Verify the template also exports `SignalQueue`, `InMemorySignalTransport`, `register_active_run`, `unregister_active_run`, `has_active_workflow` — these are all in `signals.py` and imported by runtime.py and tests. The template omits `SignalQueue` and the registry functions — see Failure Mode 2.

---

### Task 5: Create workflow/agent/ Sub-Package

**Assumptions:**
- All 6 files (`prompts.py`, `templates.py`, `context_builder.py`, `clarifications.py`, `auto_verify.py`, `summary_cache.py`) are copied to `agent/` and the originals become 1-line re-exports.
- No external callers use `from orchestrator.workflow.agent import X` today — the sub-package is entirely new. External callers continue using `from orchestrator.workflow.prompts import X` through the bridges.

**Policy concern — see Failure Mode 3.**

**agent/__init__.py symbol completeness:** The template lists reasonable symbols but should be verified against actual file contents. For example, `prompts.py` may have additional helper functions not listed in the template. The step correctly advises using grep to audit before finalizing `__all__`.

**`summary_cache.py` import update:** After Task 7, `summary_cache.py` will no longer import `DEFAULT_SUMMARIZE_MODEL` from `config.models`. The copy in `agent/summary_cache.py` should already have this update applied (Task 7 runs after Task 5 in the step order). If Task 5 copies the current file before Task 7 moves `DEFAULT_SUMMARIZE_MODEL`, the agent copy will still import from `config.models`. Task 7 then removes the constant from `config.models`, breaking the copy. **Ordering dependency:** Task 7 must update `agent/summary_cache.py` (the new location), not just the now-redundant bridge at `workflow/summary_cache.py`.

---

### Task 6: Move NoTaskReason from runners/ to workflow/signals/runtime.py

**Assumptions:**
- `NoTaskReason`, `LoopAction`, and `resolve_no_task_action` move to `workflow/signals/runtime.py`.
- `runners/executor.py` imports them from the new location.
- Test files updated.

**Critical gap — LoopAction not mentioned:**
`resolve_no_task_action` returns a `LoopAction`. `LoopAction` is defined in `runners/executor.py` alongside `NoTaskReason`. The step says to move `NoTaskReason` and `resolve_no_task_action` but is silent on `LoopAction`. After the move:
- `signals/runtime.py` defines `NoTaskReason` and `resolve_no_task_action`
- `resolve_no_task_action` references `LoopAction` — `LoopAction` must be importable from wherever `runtime.py` has access to it
- If `LoopAction` stays in `runners/executor.py`, `signals/runtime.py` would need to import from runners — which is the exact layering violation being fixed

**Resolution:** `LoopAction` must also move to `workflow/signals/runtime.py`.

**`orchestrator/executor.py` (top-level shim) not updated:**
`src/orchestrator/executor.py` re-exports `NoTaskReason`, `LoopAction`, `resolve_no_task_action` from `orchestrator.runners.executor`. After the move, `runners/executor.py` imports these from `workflow.signals.runtime` and the chain still works (shim → runners.executor → workflow.signals.runtime). But the shim's docstring and `__all__` claim these are from `runners.executor` — technically incorrect after the move. If the shim is a dead code candidate, it should be noted. The step does not mention this file.

**`workflow/signals/runtime.py` self-reference:**
After Task 6, `NoTaskReason` is defined in `signals/runtime.py` (the same file that was `runtime.py`). The lazy import at line 372 (`from orchestrator.runners.executor import NoTaskReason, resolve_no_task_action`) must be removed and replaced with direct reference (they're now local). This is straightforward but the step's instruction is slightly unclear: "remove the lazy import and use the locally-defined NoTaskReason and resolve_no_task_action directly" — correct guidance.

**`signals/__init__.py` update for NoTaskReason:**
After adding `NoTaskReason`, `LoopAction`, `resolve_no_task_action` to `signals/runtime.py`, the step says to re-export them from `signals/__init__.py`. The `workflow/__init__.py` does NOT currently export `NoTaskReason` — so this export is new. If any test imports `NoTaskReason` from `orchestrator.workflow`, it would now work. But `workflow/__init__.py` should not silently gain new public exports without a corresponding update to its `__all__`.

---

### Task 7: Move DEFAULT_SUMMARIZE_MODEL to workflow/agent/summary_cache.py

**Assumptions:**
- `DEFAULT_SUMMARIZE_MODEL` has exactly one consumer: `workflow/summary_cache.py`. Confirmed correct.
- The constant value `"claude-haiku-4-5-20251001"` does not change.

**Ordering dependency:**
Task 5 copies `summary_cache.py` to `agent/summary_cache.py`. Task 7 then adds `DEFAULT_SUMMARIZE_MODEL` to `agent/summary_cache.py` and removes it from `config/models.py`. But `agent/summary_cache.py` (created in Task 5) still has `from orchestrator.config.models import DEFAULT_SUMMARIZE_MODEL`. Task 7 must update `agent/summary_cache.py` to inline the constant AND update the bridge at `workflow/summary_cache.py` (which re-exports from `agent/summary_cache`). This works correctly if the implementer applies Task 7 changes to `agent/summary_cache.py`, not just to a hypothetical standalone `summary_cache.py`.

**Verification correctness:** The step verifies `grep ... src/orchestrator/config/` returns zero results. This correctly confirms removal from config. No gap here.

---

### Task 8: Update workflow/__init__.py and Full Test Suite

**Assumptions:**
- `workflow/__init__.py` import paths can be changed to use direct sub-package paths (e.g., `from orchestrator.workflow.engine.errors import GateBlockedError`).
- Bridges at the old flat paths also work, so the `__init__.py` update is a choice, not a necessity.
- Full test suite catches any remaining broken imports.

**Expected failures before fixes:**
- Missing symbols in `events/__init__.py` (see Failure Mode 1) → ImportError in any test that imports an unlisted event type
- Missing `SignalQueue`/registry functions in `signals/__init__.py` (see Failure Mode 2) → ImportError in runtime.py or tests
- `LoopAction` missing from Task 6 scope → TypeError or ImportError in executor tests

**Commit command issue:**
The step's git commit command is `git add -A src/orchestrator/workflow/ src/orchestrator/runners/executor.py src/orchestrator/config/models.py tests/`. This would miss updating `src/orchestrator/executor.py` (the top-level shim) if it needs updating after Task 6.

---

## Failure Modes

### Failure Mode 1 (HIGH): events/__init__.py Symbol Incompleteness

**Description:** The step's `events/__init__.py` template lists 11 symbols. `events.py` defines 35 (33 event classes + `GradeDetail` + `BufferingEmitter`). Missing 24 symbols includes `ApprovalRequested` (imported by `runtime.py`), `BufferingEmitter` (imported by tests and possibly service.py), and all fan-out events. Any missing symbol causes an `ImportError` at module load time for any file that imports it from `orchestrator.workflow.events`.

**Hardening:** Before writing `events/__init__.py`, run:
```bash
grep "^class \|^[A-Z][A-Z]" src/orchestrator/workflow/events.py | sort
grep -rn "from orchestrator\.workflow\.events import" src/ tests/ --include="*.py" \
  | grep -oP "import \K.*" | tr ',' '\n' | tr -d ' ()' | sort -u
```
The second command shows every symbol imported from `workflow.events` across the codebase. The `events/__init__.py` must export ALL of them. Write `events/__init__.py` only after confirming the complete list. The safe approach: re-export everything from `events/types.py` using `from orchestrator.workflow.events.types import *` with an explicit `__all__`, plus `from orchestrator.workflow.events.logger import PersistentEventEmitter`.

---

### Failure Mode 2 (HIGH): signals/__init__.py Missing Registry Functions and SignalQueue

**Description:** `runtime.py` imports `SignalQueue`, `register_active_run`, `unregister_active_run` from `orchestrator.workflow.signals`. The step's `signals/__init__.py` template omits these. After restructuring, `from orchestrator.workflow.signals import SignalQueue` raises `ImportError`, breaking `runtime.py` initialization.

**Hardening:** Run before writing `signals/__init__.py`:
```bash
grep -rn "from orchestrator\.workflow\.signals import" src/ tests/ --include="*.py"
```
Add every imported symbol to `signals/__init__.py.__all__`. From `signals.py`: `DbSignalTransport`, `InMemorySignalTransport`, `PendingSignal`, `SignalQueue`, `SignalTransport`, `WorkflowSignal`, `register_active_run`, `unregister_active_run`, `has_active_workflow`.

---

### Failure Mode 3 (MEDIUM): Re-Export Bridges May Violate Plan Policy

**Description:** The plan's definition of complete states "Zero backward-compatibility shims, re-export stubs." The step introduces thin re-export bridges at `workflow/errors.py`, `workflow/transitions.py`, `workflow/gates.py`, `workflow/grades.py`, `workflow/condition_evaluator.py`, `workflow/event_logger.py`, `workflow/handlers.py`, `workflow/runtime.py`, and all 6 agent files. The step justifies these as "intra-module compatibility layers, not cross-module backward-compat shims."

This distinction is valid for the _intent_ of the policy (which targets cross-module absorption shims), but creates ambiguity about whether these bridges should be removed by updating all external callers instead.

**Hardening:** Decide explicitly before implementation: either (a) update all external callers to use the new sub-package paths (e.g., `from orchestrator.workflow.engine.errors import GateBlockedError`) and remove all bridges, OR (b) keep bridges and document why they are intra-module and exempt from the zero-stub policy. Option (a) is more labor-intensive (~50 import sites to update) but definitively satisfies the plan policy. Option (b) is pragmatic but leaves stubs. If Phase 10 (explicit `__all__`) will clean up internal imports anyway, option (b) is acceptable as a stepping stone.

If bridges are kept, add an explanatory comment to each:
```python
# Intra-module bridge: external callers import from this path; source of truth is engine/errors.py
```

---

### Failure Mode 4 (HIGH): LoopAction Not Moved with NoTaskReason in Task 6

**Description:** `resolve_no_task_action` returns `LoopAction`. Both are defined in `runners/executor.py` (lines 63–97). Moving `NoTaskReason` and `resolve_no_task_action` to `workflow/signals/runtime.py` without moving `LoopAction` leaves `resolve_no_task_action` unable to reference its return type without importing from `runners` — recreating the layering violation.

**Hardening:** Task 6 must explicitly include `LoopAction` in the set of symbols moved to `workflow/signals/runtime.py`. Update `signals/__init__.py` to re-export `LoopAction`. Update `runners/executor.py` to import `LoopAction` from the new location. Update `orchestrator/executor.py` shim to import `LoopAction` from `runners.executor` (which re-exports from workflow).

---

### Failure Mode 5 (MEDIUM): orchestrator/executor.py Shim Not Updated After Task 6

**Description:** `src/orchestrator/executor.py` imports `NoTaskReason`, `LoopAction`, `resolve_no_task_action` from `orchestrator.runners.executor`. After Task 6 moves these to `workflow.signals.runtime`, the chain still works (shim → runners.executor → workflow.signals.runtime), but the shim's `__all__` and comments falsely claim `runners.executor` as the canonical location.

**Hardening:** After Task 6, update `orchestrator/executor.py` to import directly from `orchestrator.workflow.signals.runtime` (or `orchestrator.workflow.signals`) for `NoTaskReason`, `LoopAction`, `resolve_no_task_action`. Or, if `orchestrator/executor.py` is itself a backward-compat shim slated for deletion in Phase 1 (or already deleted), skip this update. Verify its status before deciding.

---

### Failure Mode 6 (MEDIUM): Task Ordering Creates Stale agent/summary_cache.py

**Description:** Task 5 copies `summary_cache.py` to `agent/summary_cache.py` (with the `from config.models import DEFAULT_SUMMARIZE_MODEL` import intact). Task 7 then removes `DEFAULT_SUMMARIZE_MODEL` from `config/models.py`. If the implementer applies Task 7 only to the bridge file `workflow/summary_cache.py` and not to `agent/summary_cache.py`, the canonical source file still imports a now-deleted constant.

**Hardening:** Task 7 must explicitly target `src/orchestrator/workflow/agent/summary_cache.py` for the inline constant addition and `from config.models import DEFAULT_SUMMARIZE_MODEL` removal. The verification grep (`grep ... src/orchestrator/config/`) will pass regardless — the correct file to audit is `workflow/agent/summary_cache.py` after Task 7.

---

### Failure Mode 7 (LOW): Prerequisite Phase 4 Not Verified

**Description:** The step assumes `workflow/artifacts/` exists (created in Phase 4). If this step runs before Phase 4, the Task 8 verification command `ls src/orchestrator/workflow/` will not show `artifacts/`. This won't break tests (artifacts is independent of the restructuring), but the verification step will silently show an incomplete directory listing that may confuse the implementer.

**Hardening:** Add a prerequisite check at the start of Task 1:
```bash
test -d src/orchestrator/workflow/artifacts || echo "WARNING: Phase 4 prerequisite not met — workflow/artifacts/ missing"
```
Do not proceed with Task 8's directory verification assertion about `artifacts/` if Phase 4 hasn't run.

---

### Failure Mode 8 (LOW): check_step_progression / check_run_completion Not in engine/__init__.py

**Description:** External code imports `check_step_progression` and `check_run_completion` directly from `orchestrator.workflow.transitions` (not from `workflow` or `engine`). The bridges at `workflow/transitions.py` handle this. However, `engine/__init__.py` includes `check_step_progression` in its template but not `check_run_completion`. This asymmetry could confuse users of `from orchestrator.workflow.engine import check_run_completion` (which would fail).

**Hardening:** Either include BOTH `check_step_progression` and `check_run_completion` in `engine/__init__.py`, or include neither (since they are accessible via the `workflow/transitions.py` bridge). Consistency matters more than which choice is made.

---

## Summary Risk Table

| Task | Risk Level | Primary Concern |
|------|-----------|-----------------|
| T1: Audit imports | Low | Grep pattern is correct for its purpose |
| T2: engine/ sub-package | Low | Symbol list appears correct; copy-then-bridge approach is sound |
| T3: events/ sub-package | **High** | Template missing 24+ event symbols; will cause ImportErrors |
| T4: signals/ sub-package | **High** | Missing SignalQueue, registry functions from __init__ template |
| T5: agent/ sub-package | Medium | Bridge policy question; ordering dependency with Task 7 |
| T6: Move NoTaskReason | **High** | LoopAction not moved; executor.py shim not updated |
| T7: Move DEFAULT_SUMMARIZE_MODEL | Low | Ordering: must update agent/summary_cache.py, not workflow/summary_cache.py |
| T8: Full test suite | Medium | Will catch T3/T4/T6 failures; must fix before committing |

## Recommended Pre-Implementation Hardening Actions

1. **Before Task 3:** Run the two audit greps specified in Failure Mode 1. Write the complete `events/__init__.py` from the audit output, not the template.

2. **Before Task 4:** Run `grep -rn "from orchestrator\.workflow\.signals import" src/ tests/` and ensure `signals/__init__.py` re-exports every symbol in the result set.

3. **In Task 6:** Explicitly include `LoopAction` in the move. Update `orchestrator/executor.py` if it is still present.

4. **In Task 7:** Apply the change to `workflow/agent/summary_cache.py` (the canonical source after Task 5), not only to bridge files.

5. **Task 5 bridge policy:** Decide explicitly whether bridges are acceptable intra-module stubs or whether all ~50 external import sites must be updated to canonical sub-package paths. Document the decision.

6. **Task 8 commit:** Add `src/orchestrator/executor.py` to the git add command if it was modified in Task 6.
