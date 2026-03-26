# Step 04: Registry Isolation

This step restricts the active-run registry functions (`register_active_run`, `unregister_active_run`, `has_active_workflow`) to be accessible only from the consumer module. This enforces the architectural invariant that only the consumer manages RunWorkflow lifecycle and prevents scattered ownership of the registry across the codebase.

This step assumes that Step 03 has been completed, meaning all sender methods now enqueue signals unconditionally and no longer call these registry functions directly.

## Intent Verification

**Original Intent**: [I-04], [I-29], [I-30] — Registry functions restricted to consumer module; no external callers remain; public surface cleaned.

**Functionality to Produce**:
- Registry functions (`register_active_run`, `unregister_active_run`, `has_active_workflow`) moved to or owned by `consumer.py`
- `signals.py` no longer exports these functions in its public interface
- All external imports of these functions removed from the codebase
- Consumer.py and its tests are the only modules that call or import these functions
- Pre-commit hook validation (from Step 05) will pass on the updated codebase

**Final Verification Criteria**:
- `grep -r "from.*signals.*import.*(register_active_run|unregister_active_run|has_active_workflow)" src/ tests/` excludes only `consumer.py`
- `signals.py` inspection confirms functions not in `__all__` or similar export mechanism
- Full test suite (backend + frontend) passes
- Type checking and linting pass
- Manual code review confirms no stray imports in test files or elsewhere

---

## Task 1: Audit current registry function usage and location

**Description**:
Before moving the registry functions, audit where they are currently defined and imported. This establishes a baseline for what needs to change and ensures we don't miss any callsites.

**Implementation Plan (Do These Steps)**

Understand the current state of registry function definitions and usage:

- [ ] Search for the registry data structure definition in signals.py:
```bash
cd /Users/peter/code/task-world/worktrees/r53
grep -n "_active_run_ids" src/orchestrator/workflow/signals/signals.py | head -20
```
  Document the line number and context. This is the module-level set that stores active workflow IDs.

- [ ] Search for all imports of `register_active_run`:
```bash
grep -r "import.*register_active_run\|from.*signals.*import.*register_active_run" --include="*.py" src/ tests/
```
  Document each file and line number that imports this function.

- [ ] Search for all imports of `unregister_active_run`:
```bash
grep -r "import.*unregister_active_run\|from.*signals.*import.*unregister_active_run" --include="*.py" src/ tests/
```

- [ ] Search for all imports of `has_active_workflow`:
```bash
grep -r "import.*has_active_workflow\|from.*signals.*import.*has_active_workflow" --include="*.py" src/ tests/
```

- [ ] Read the function implementations in `src/orchestrator/workflow/signals/signals.py` (lines 221-236):
  - Understand that `_active_run_ids` is a module-level `set[str]` that tracks which runs have active RunWorkflows
  - Understand that `register_active_run()` adds to the set, `unregister_active_run()` removes from it, `has_active_workflow()` checks membership

- [ ] Verify that `consumer.py` exists and review its structure:
```bash
ls -la src/orchestrator/workflow/signals/consumer.py
wc -l src/orchestrator/workflow/signals/consumer.py
```

**Dependencies**:
- [ ] Step 03 must be complete (all senders now unconditionally enqueue signals)

**References**:
- `src/orchestrator/workflow/signals/signals.py` — current home of registry functions (lines 221-236)
- `src/orchestrator/workflow/signals/consumer.py` — target home of registry functions
- Plan document: `docs/single-queue/plan.md#phase-4-registry-isolation`

**Constraints**:
- Do not make code changes in this task. This is purely informational.
- Only examine Python source files, not build artifacts or caches.

**Functionality (Expected Outcomes)**:
- [ ] Complete audit report showing location of `_active_run_ids`, function definitions, and all imports
- [ ] Understanding of the current registry implementation

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] All three grep commands above complete without errors
- [ ] You can locate and read the three function definitions in `signals.py`
- [ ] You can identify all files (if any) that currently import these functions from `signals.py`
- [ ] `consumer.py` exists and is readable

---

## Task 2: Move registry functions to consumer.py and remove from signals.py

**Description**:
Move the registry data structure and the three registry functions from `signals.py` to `consumer.py`. Update the module structure so that the functions are defined and called only within consumer.py. Remove them from the public exports of signals.py.

**Implementation Plan (Do These Steps)**

Locate and copy the registry components:

- [ ] Open `src/orchestrator/workflow/signals/signals.py` and identify:
  - Line 221: `_active_run_ids: set[str] = set()` — the registry data structure
  - Lines 224-227: `register_active_run()` function definition
  - Lines 229-231: `unregister_active_run()` function definition
  - Lines 234-236: `has_active_workflow()` function definition

- [ ] Check if `signals.py` has an `__all__` export list:
```bash
grep -n "__all__" src/orchestrator/workflow/signals/signals.py
```

Move the registry to consumer.py:

- [ ] Open `src/orchestrator/workflow/signals/consumer.py` in an editor

- [ ] Add the registry data structure and three functions to `consumer.py` after the imports and before the main consumer class or function. Insert:
```python
# =====================================================================
# Active-run registry — SOLE owner of RunWorkflow lifecycle
# =====================================================================

_active_run_ids: set[str] = set()


def register_active_run(run_id: str) -> None:
    """Mark a run as having an active RunWorkflow driving it."""
    _active_run_ids.add(run_id)


def unregister_active_run(run_id: str) -> None:
    """Remove a run from the active-workflow registry."""
    _active_run_ids.discard(run_id)


def has_active_workflow(run_id: str) -> bool:
    """Return True if a RunWorkflow is currently executing for run_id."""
    return run_id in _active_run_ids
```

- [ ] Remove from `src/orchestrator/workflow/signals/signals.py`:
  - Delete lines 219-236 (the registry comment, data structure, and three functions)
  - Keep all other code in `signals.py` (signal types, transports, enqueue functions, etc.)

- [ ] **IMPORTANT:** `signals.py` itself does NOT have an `__all__` list. The registry functions
  are re-exported through two `__init__.py` files. Both must be updated:

  Check `src/orchestrator/workflow/signals/__init__.py`:
```bash
grep -n "register_active_run\|unregister_active_run\|has_active_workflow" src/orchestrator/workflow/signals/__init__.py
```
  Remove each of the three names from this file's `__all__` list (or import block).

  Check `src/orchestrator/workflow/__init__.py`:
```bash
grep -n "register_active_run\|unregister_active_run\|has_active_workflow" src/orchestrator/workflow/__init__.py
```
  Remove each of the three names from this file's `__all__` list (or import block) as well.

  After removing from both `__init__.py` files, attempting to import via the package path should fail:
```bash
uv run python -c "from orchestrator.workflow.signals import register_active_run" 2>&1 | grep -q "ImportError\|cannot import" && echo "CORRECTLY REMOVED"
```

- [ ] Verify that the consumer.py import is valid:
```bash
cd /Users/peter/code/task-world/worktrees/r53
uv run python -c "from src.orchestrator.workflow.signals.consumer import register_active_run, unregister_active_run, has_active_workflow; print('OK')"
```

- [ ] Run syntax check on both files:
```bash
uv run python -m py_compile src/orchestrator/workflow/signals/signals.py src/orchestrator/workflow/signals/consumer.py
```

- [ ] Check for import errors:
```bash
uv run pyright src/orchestrator/workflow/signals/signals.py src/orchestrator/workflow/signals/consumer.py 2>&1 | head -30
```

**Dependencies**:
- [ ] Task 1 complete (audit shows where functions are)
- [ ] Step 03 complete (all external callers have already been moved to use signals queue)

**References**:
- `src/orchestrator/workflow/signals/signals.py` — source file (lines 219-236)
- `src/orchestrator/workflow/signals/consumer.py` — target file

**Constraints**:
- Do NOT change the function signatures or behavior of the registry functions
- Do NOT remove any registry calls from within `consumer.py` itself
- Do NOT delete the `__pycache__` directory; rely on Python to rebuild it
- Only move the functions; do not refactor or optimize them in this task

**Side Effects**:
- [ ] If any other file in the codebase currently imports these functions, those imports will break (handled in Task 3)
- [ ] Type checking may briefly fail until all imports are updated (Task 3)

**Functionality (Expected Outcomes)**:
- [ ] Registry data structure `_active_run_ids` is now defined in `consumer.py`
- [ ] Registry functions are now defined in `consumer.py`
- [ ] `signals.py` no longer contains the registry structure or the three functions
- [ ] `signals.py` still exports all signal types, transports, and enqueue functions (unchanged)

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `grep "def register_active_run" src/orchestrator/workflow/signals/signals.py` returns no results
- [ ] `grep "def register_active_run" src/orchestrator/workflow/signals/consumer.py` returns exactly one result
- [ ] `grep "def unregister_active_run" src/orchestrator/workflow/signals/signals.py` returns no results
- [ ] `grep "def unregister_active_run" src/orchestrator/workflow/signals/consumer.py` returns exactly one result
- [ ] `grep "def has_active_workflow" src/orchestrator/workflow/signals/signals.py` returns no results
- [ ] `grep "def has_active_workflow" src/orchestrator/workflow/signals/consumer.py` returns exactly one result
- [ ] `grep "_active_run_ids" src/orchestrator/workflow/signals/signals.py` returns no results
- [ ] `grep "_active_run_ids" src/orchestrator/workflow/signals/consumer.py` returns exactly one result (the definition)
- [ ] `uv run python -m py_compile src/orchestrator/workflow/signals/signals.py` succeeds
- [ ] `uv run python -m py_compile src/orchestrator/workflow/signals/consumer.py` succeeds
- [ ] `uv run python -c "from src.orchestrator.workflow.signals.consumer import register_active_run, unregister_active_run, has_active_workflow; print('OK')"` prints "OK"

---

## Task 3: Update all external imports of registry functions

**Description**:
Find all files outside of `consumer.py` that import the registry functions, and update them. Based on Step 03, most production code imports should have been eliminated, but any test files that need these functions for testing purposes should import from `consumer.py` instead.

**Implementation Plan (Do These Steps)**

Locate all imports:

- [ ] Run a comprehensive grep to find all remaining imports:
```bash
cd /Users/peter/code/task-world/worktrees/r53
grep -r "from.*signals.*import.*register_active_run\|from.*signals.*import.*unregister_active_run\|from.*signals.*import.*has_active_workflow" --include="*.py" src/ tests/
```

- [ ] For each non-consumer.py file returned:
  - If the file is a **test file** (`tests/`) and legitimately needs to call these functions:
    - Change `from src.orchestrator.workflow.signals import register_active_run`
    - To: `from src.orchestrator.workflow.signals.consumer import register_active_run`
    - Apply same change to any multiline imports
  - If the file is **production code** and imports these functions:
    - This indicates Step 03 was incomplete. Verify the code path is not calling them.
    - If it is calling them, flag for review with the architecture team.
    - If it's just an unused import, remove it.
  - If only a single name is imported on a line with other imports, be careful to only change the registry functions, not other imports

- [ ] Example import update pattern:
```python
# BEFORE
from src.orchestrator.workflow.signals import register_active_run, has_active_workflow, WorkflowSignal

# AFTER
from src.orchestrator.workflow.signals import WorkflowSignal
from src.orchestrator.workflow.signals.consumer import register_active_run, has_active_workflow
```

- [ ] After updating each file, verify syntax:
```bash
uv run python -m py_compile <filepath>
```

- [ ] Run type checking on modified files:
```bash
uv run pyright <filepath>
```

- [ ] Create a summary of all files touched:
```bash
git --no-pager diff --name-only src/ tests/ | grep -E "\.py$"
```

**Dependencies**:
- [ ] Task 2 complete (functions moved to consumer.py)
- [ ] Audit from Task 1 identifying all import locations

**References**:
- Task 1 audit output
- `src/orchestrator/workflow/signals/consumer.py` — new import source

**Constraints**:
- Do NOT change function behavior or signatures
- Do NOT remove imports that are actually used (check call sites carefully)
- Only modify import statements and remove unused imports; do not refactor the calling code itself
- Preserve all other imports on the same line

**Side Effects**:
- [ ] If a file imports multiple items from `signals.py`, split the import to pull registry functions from `consumer.py`
- [ ] Test files may need updates to their import statements
- [ ] Some modules may not import these functions at all (no change needed)

**Functionality (Expected Outcomes)**:
- [ ] All imports of registry functions in production code removed or updated
- [ ] All imports in test files updated to import from `consumer.py` instead of `signals.py`
- [ ] No file outside `consumer.py` imports these functions from `signals.py`

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] Run the grep search again:
```bash
grep -r "from.*signals.*import.*register_active_run\|from.*signals.*import.*unregister_active_run\|from.*signals.*import.*has_active_workflow" --include="*.py" src/ tests/
```
  Result should be empty or only show imports from `signals/consumer.py`.

- [ ] Confirm no imports remain from signals.py (not consumer.py):
```bash
grep -r "from src.orchestrator.workflow.signals import.*register_active_run\|from src.orchestrator.workflow.signals import.*unregister_active_run\|from src.orchestrator.workflow.signals import.*has_active_workflow" --include="*.py" src/ tests/
```
  Result should be empty.

- [ ] `uv run pyright src/ tests/ 2>&1 | grep -i "register_active_run\|unregister_active_run\|has_active_workflow" | head -10` returns empty (no type errors related to these functions)

- [ ] `git --no-pager diff src/ tests/ | grep -E "^\+.*import|^-.*import" | head -20` shows only import statement changes, no other refactoring

---

## Task 4: Verify isolation and run full regression tests

**Description**:
Confirm that the registry functions are now isolated to the consumer module and that no regressions were introduced by moving the functions. Run the full test suite to ensure the codebase remains valid.

**Implementation Plan (Do These Steps)**

Verify isolation:

- [ ] Run a final grep to confirm complete isolation:
```bash
cd /Users/peter/code/task-world/worktrees/r53
grep -r "from src.orchestrator.workflow.signals import.*register_active_run\|from src.orchestrator.workflow.signals import.*unregister_active_run\|from src.orchestrator.workflow.signals import.*has_active_workflow" --include="*.py" src/ tests/
```
  This should return nothing.

- [ ] Verify signals.py no longer exports registry functions:
```bash
grep "__all__" src/orchestrator/workflow/signals/signals.py
```
  If `__all__` is defined, it should not contain "register_active_run", "unregister_active_run", or "has_active_workflow".

- [ ] Optional: Verify that consumer.py is the only file calling these functions (besides tests):
```bash
grep -r "register_active_run\|unregister_active_run\|has_active_workflow" --include="*.py" src/ | grep -v "def register_active_run\|def unregister_active_run\|def has_active_workflow" | grep -v "consumer.py" | head -20
```
  This should show only test files or comments, not actual calls in production code.

Run backend tests:

- [ ] Run the backend unit tests:
```bash
uv run pytest tests/unit -v --tb=short 2>&1 | tail -50
```
  All tests should pass. If any fail, examine the error and check if it's related to signal routing or registry imports.

- [ ] Run the backend integration tests:
```bash
uv run pytest tests/integration -v --tb=short 2>&1 | tail -50
```
  All tests should pass (except known skips related to openhands not being installed).

Run type and lint checks:

- [ ] Run type checking:
```bash
uv run pyright src/orchestrator/workflow/signals/ --outputjson 2>&1 | head -50
```
  No new type errors should appear related to registry functions.

- [ ] Run linting:
```bash
uv run ruff check src/orchestrator/workflow/signals/
```
  No new linting errors should appear related to registry functions.

- [ ] Full linting pass (optional, but recommended):
```bash
uv run ruff check src/ tests/ 2>&1 | tail -20
```

Final verification:

- [ ] Confirm the git diff shows only the expected changes:
```bash
git --no-pager diff src/orchestrator/workflow/signals/signals.py | head -50
```
  Should show removal of the registry data structure and three function definitions.

- [ ] Confirm consumer.py shows the new registry code:
```bash
git --no-pager diff src/orchestrator/workflow/signals/consumer.py | head -50
```
  Should show addition of the registry data structure and three function definitions.

**Dependencies**:
- [ ] Task 3 complete (all imports updated)

**References**:
- `docs/single-queue/intent.md` — original intent
- `docs/single-queue/plan.md` — overall plan (Phase 4)

**Constraints**:
- Do NOT modify any function logic to make tests pass. If tests fail, debug the root cause.
- Do NOT skip test failures. Each failure must be understood and fixed.

**Side Effects**:
- None expected if Tasks 1-3 were completed correctly.

**Functionality (Expected Outcomes)**:
- [ ] Registry functions are isolated to `consumer.py`
- [ ] No external imports of registry functions from `signals.py` remain anywhere in the codebase
- [ ] All tests pass
- [ ] Type checking and linting pass
- [ ] Consumer module is the sole owner of the active-run registry

**Final Verification (Proof of Completion)**:
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE

- [ ] `grep -r "from src.orchestrator.workflow.signals import.*register_active_run\|from src.orchestrator.workflow.signals import.*unregister_active_run\|from src.orchestrator.workflow.signals import.*has_active_workflow" --include="*.py" src/ tests/` returns empty (no imports from signals.py, only from consumer.py)

- [ ] `grep "register_active_run\|unregister_active_run\|has_active_workflow" src/orchestrator/workflow/signals/signals.py` returns empty (no function definitions or registry in signals.py)

- [ ] `grep "_active_run_ids" src/orchestrator/workflow/signals/signals.py` returns empty

- [ ] `uv run pytest tests/unit -x -q` passes with zero failures

- [ ] `uv run pytest tests/integration -x -q --ignore=tests/integration/test_api_agent_errors.py` passes (openhands failures ignored)

- [ ] `uv run pyright src/orchestrator/workflow/signals/ --outputjson 2>&1 | grep -c "error"` returns 0 (no errors)

- [ ] `uv run ruff check src/orchestrator/workflow/signals/` shows no errors (warnings OK if pre-existing)

- [ ] Manual code review: search confirms no stray registry function calls outside `consumer.py`:
```bash
grep -r "register_active_run()\|unregister_active_run()\|has_active_workflow()" --include="*.py" src/ | grep -v consumer.py
```
  Returns empty.

- [ ] Confirm `__init__.py` re-exports are removed from both package init files:
```bash
grep "register_active_run\|unregister_active_run\|has_active_workflow" src/orchestrator/workflow/signals/__init__.py src/orchestrator/workflow/__init__.py
```
  Returns empty.

- [ ] Architecture invariant confirmed: only `consumer.py` and its tests can import/call registry functions
