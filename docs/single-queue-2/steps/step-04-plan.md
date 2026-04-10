# Step 4: Registry Isolation

Restrict `register_active_run()`, `unregister_active_run()`, and `has_active_workflow()`
to the consumer module only. After S-03 rewiring, these functions are no longer called
from any non-consumer code — this step removes the stale imports and export declarations
to lock in the invariant that only the consumer manages the active-run registry.

All changes in this step are purely mechanical removals. No logic changes, no behavior
changes. The pre-commit guard (S-05) will enforce this boundary going forward.

## Intent Verification
**Original Intent**: [I-04], [I-29], [I-30] — Registry functions accessible only from consumer module; no imports outside consumer and its tests.
**Functionality to Produce**:
- `signals/__init__.py` does not export `register_active_run`, `unregister_active_run`, or `has_active_workflow`
- `workflow/__init__.py` does not export any of the three registry functions
- `consumer.py` imports registry functions via direct relative import from `.signals` (not via `__init__`)
- No non-consumer source file imports or calls any registry function
- All tests pass after removals

**Final Verification Criteria**:
- `grep -rn "register_active_run\|unregister_active_run\|has_active_workflow" src/orchestrator/workflow/signals/__init__.py` returns no output
- `grep -rn "register_active_run\|unregister_active_run\|has_active_workflow" src/orchestrator/workflow/__init__.py` returns no output
- `grep -rn "register_active_run\|unregister_active_run\|has_active_workflow" src/` only matches `signals.py` (definitions) and `consumer.py` (caller)
- Full backend test suite passes

---

## Task 1: Audit Registry Function Usage

**Description**:
Before removing anything, identify every file that currently imports or calls the three
registry functions. This audit informs Tasks 2–4 and ensures no file is missed.

**Implementation Plan (Do These Steps)**

- [ ] Run the following grep commands and record every match:

```bash
grep -rn "register_active_run\|unregister_active_run\|has_active_workflow" src/ --include="*.py"
grep -rn "register_active_run\|unregister_active_run\|has_active_workflow" tests/ --include="*.py"
```

- [ ] Categorize results into three groups:
  1. **Definitions** — `signals.py` (keep as-is; functions still live here)
  2. **Legitimate consumer imports** — `consumer.py` (keep, but update import form in Task 3)
  3. **Stale imports to remove** — all other files (addressed in Tasks 2, 4, 5)

- [ ] Confirm that after S-03 rewiring, `service.py` only contains stale/unused imports
  of `has_active_workflow` (no longer called in any live code path).

- [ ] Confirm that after S-03 rewiring, `runtime.py` only contains stale/unused imports
  of `register_active_run` and `unregister_active_run` (consumer now owns these calls).

**Functionality (Expected Outcomes)**
- [ ] Complete list of all files requiring changes in Tasks 2–5.
- [ ] Confirmation that no live business logic path calls registry functions outside consumer.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Audit output is recorded (mentally or in notes) and accounts for all grep matches.

---

## Task 2: Remove Registry Exports from `signals/__init__.py`

**Description**:
Remove the three registry functions from the import list and `__all__` in
`src/orchestrator/workflow/signals/__init__.py`. The functions remain defined in
`signals.py`; only their re-export is removed.

**Implementation Plan (Do These Steps)**

Current state of the file (lines 3–43):
```python
from orchestrator.workflow.signals.signals import (
    DbSignalTransport,
    InMemorySignalTransport,
    PendingSignal,
    SignalQueue,
    SignalTransport,
    WorkflowSignal,
    has_active_workflow,       # REMOVE
    register_active_run,       # REMOVE
    unregister_active_run,     # REMOVE
)
# ...
__all__ = [
    # ...
    "has_active_workflow",     # REMOVE
    "register_active_run",     # REMOVE
    # ...
    "unregister_active_run",   # REMOVE
]
```

- [ ] Open `src/orchestrator/workflow/signals/__init__.py`.
- [ ] Remove `has_active_workflow`, `register_active_run`, and `unregister_active_run`
  from the `from orchestrator.workflow.signals.signals import (...)` block.
- [ ] Remove `"has_active_workflow"`, `"register_active_run"`, and `"unregister_active_run"`
  from the `__all__` list.
- [ ] Ensure the remaining import block and `__all__` list are syntactically valid
  (no trailing comma issues, no orphaned parentheses).

**Constraints**
- Only `src/orchestrator/workflow/signals/__init__.py` should be modified.
- Do NOT remove the functions from `signals.py` itself — they remain defined there.

**Functionality (Expected Outcomes)**
- [ ] `from orchestrator.workflow.signals import register_active_run` raises `ImportError`.
- [ ] All other exports from `signals/__init__.py` continue to work.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "register_active_run\|unregister_active_run\|has_active_workflow" src/orchestrator/workflow/signals/__init__.py` returns no output.
- [ ] `python -c "from orchestrator.workflow.signals import SignalQueue; print('ok')"` succeeds.
- [ ] `python -c "from orchestrator.workflow.signals import register_active_run"` raises `ImportError`.

---

## Task 3: Remove Registry Exports from `workflow/__init__.py`

**Description**:
Remove the three registry functions from the import block and `__all__` in
`src/orchestrator/workflow/__init__.py`. This is a mirror of Task 2 at the
`workflow` package level.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/workflow/__init__.py`.
- [ ] Find the import block that pulls from `orchestrator.workflow.signals` and
  includes `has_active_workflow`, `register_active_run`, `unregister_active_run`.
- [ ] Remove all three from the import block (lines ~106–110 in current codebase).
- [ ] Find the `__all__` list entries for the three functions (lines ~264–268 in
  current codebase) and remove them.
- [ ] Ensure no syntax errors remain after removal.

**Constraints**
- Only `src/orchestrator/workflow/__init__.py` should be modified.

**Functionality (Expected Outcomes)**
- [ ] `from orchestrator.workflow import register_active_run` raises `ImportError`.
- [ ] All other exports from `workflow/__init__.py` continue to work.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "register_active_run\|unregister_active_run\|has_active_workflow" src/orchestrator/workflow/__init__.py` returns no output.
- [ ] `python -c "from orchestrator.workflow import WorkflowEngine; print('ok')"` succeeds.

---

## Task 4: Update `consumer.py` to Use Direct Relative Import

**Description**:
After Tasks 2 and 3 remove the public exports, `consumer.py` must import registry
functions directly from `.signals` (the internal module) rather than via the package
`__init__`. This makes the intentional bypass of the public API explicit and keeps
the import working after the export removal.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/workflow/signals/consumer.py`.
- [ ] Locate any import of `register_active_run`, `unregister_active_run`, or
  `has_active_workflow`. It may currently look like:
  ```python
  from orchestrator.workflow.signals import (
      has_active_workflow,
      register_active_run,
      unregister_active_run,
  )
  ```
  or as part of a broader import block.
- [ ] Change to a direct relative import from the internal module:
  ```python
  from orchestrator.workflow.signals.signals import (
      has_active_workflow,
      register_active_run,
      unregister_active_run,
  )
  ```
- [ ] If other symbols are imported from the package `__init__` in the same import
  block, split the import so registry functions use the direct path and other symbols
  continue using the package path.

**Constraints**
- Only `src/orchestrator/workflow/signals/consumer.py` should be modified.
- Do not change the logic of any function, only the import statement.

**Functionality (Expected Outcomes)**
- [ ] `consumer.py` module imports without error after Tasks 2 and 3 remove public exports.
- [ ] `has_active_workflow`, `register_active_run`, `unregister_active_run` are still
  accessible inside `consumer.py`.

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "from orchestrator.workflow.signals import.*register_active_run" src/orchestrator/workflow/signals/consumer.py` returns no output (import no longer uses package `__init__`).
- [ ] `grep "from orchestrator.workflow.signals.signals import.*register_active_run" src/orchestrator/workflow/signals/consumer.py` returns a match.
- [ ] `python -c "from orchestrator.workflow.signals.consumer import SignalConsumer; print('ok')"` succeeds (module imports cleanly).

---

## Task 5: Remove Stale Registry Imports from Non-Consumer Source Files

**Description**:
After S-03 rewiring, `service.py` and `runtime.py` (and any other source files
identified in Task 1) retain stale imports of registry functions that are no longer
called. Remove these dead imports.

**Implementation Plan (Do These Steps)**

For each file identified in the Task 1 audit as having stale imports:

- [ ] **`src/orchestrator/workflow/service.py`**: Locate all import statements pulling
  `has_active_workflow` from `orchestrator.workflow.signals`. Remove each import line.
  Confirm no remaining call sites reference any of the three registry functions.
  ```python
  # Remove lines like:
  from orchestrator.workflow.signals import has_active_workflow
  # or inline imports inside method bodies:
  from orchestrator.workflow.signals import has_active_workflow  # inside a method
  ```

- [ ] **`src/orchestrator/workflow/signals/runtime.py`**: Locate the import block
  pulling `register_active_run` and `unregister_active_run`. Remove those names from
  the import. If the import block becomes empty after removal, remove the entire import
  statement.
  ```python
  # Before (example):
  from orchestrator.workflow.signals.signals import (
      register_active_run,
      unregister_active_run,
  )
  # After: remove entirely if these are the only imported names
  ```
  Confirm no remaining call sites reference any of the three registry functions in
  `runtime.py`. (After S-03, `unregister_active_run` calls in `handle_pause` etc.
  should have been removed; any remaining calls indicate S-03 is incomplete.)

- [ ] For any other files flagged in the Task 1 audit: apply the same pattern —
  remove the import line, confirm no remaining call sites.

- [ ] After all removals, run a confirming grep:
  ```bash
  grep -rn "register_active_run\|unregister_active_run\|has_active_workflow" src/ --include="*.py"
  ```
  Expected: only `signals.py` (definitions) and `consumer.py` (caller) match.

**Side Effects**
- If any call site remains after removing the import, the test suite will surface an
  `AttributeError` or `NameError`. This indicates S-03 rewiring is incomplete — do NOT
  delete the call site without fixing the underlying logic gap; escalate instead.

**Constraints**
- Only remove imports, not function definitions or call sites that are still in use.
- Do not modify `signals.py` (where functions are defined) or `consumer.py` (handled
  in Task 4).
- Maximum files touched: `service.py`, `runtime.py`, and any additional files from
  the Task 1 audit (expected total ≤ 4 files).

**Functionality (Expected Outcomes)**
- [ ] No source file outside `signals.py` and `consumer.py` imports or references
  any registry function.
- [ ] All previously-working code paths continue to work (removals are dead imports only).

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "register_active_run\|unregister_active_run\|has_active_workflow" src/ --include="*.py"` only matches `signals.py` (3 definitions) and `consumer.py` (imports + calls).
- [ ] `uv run pytest tests/unit/ -x -q` passes with no errors.
- [ ] `uv run pytest tests/integration/ -x -q` passes with no errors.
- [ ] `uv run pyright src/orchestrator/workflow/service.py src/orchestrator/workflow/signals/runtime.py` reports no errors.
