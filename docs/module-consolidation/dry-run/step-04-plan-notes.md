# Step 4 Dry-Run Analysis: Absorb artifacts/ → workflow/artifacts/

## Source Verification

All file references in the step plan are confirmed correct against the actual codebase.

### Actual import sites found (9 total):

**Internal (inside `artifacts/`):**
- `src/orchestrator/artifacts/__init__.py:3` — `from orchestrator.artifacts.models import Artifact`
- `src/orchestrator/artifacts/__init__.py:4` — `from orchestrator.artifacts.registry import ArtifactRegistry`
- `src/orchestrator/artifacts/registry.py:7` — `from orchestrator.artifacts.models import Artifact`

**External src/ (3 files):**
- `src/orchestrator/workflow/context_builder.py:7` — `from orchestrator.artifacts.registry import ArtifactRegistry`
- `src/orchestrator/api/routers/tasks.py:47` — `from orchestrator.artifacts.registry import ArtifactRegistry`
- `src/orchestrator/runners/executor.py:826` — `from orchestrator.artifacts.registry import ArtifactRegistry` (lazy import inside conditional)

**External tests/ (3 files):**
- `tests/unit/test_artifact_registry.py:7` — `from orchestrator.artifacts import ArtifactRegistry`
- `tests/unit/test_context_builder.py:8` — `from orchestrator.artifacts.registry import ArtifactRegistry`
- `tests/unit/test_summary_cache.py:10` — `from orchestrator.artifacts.registry import ArtifactRegistry`

The step plan's claim of "9 import sites (3 internal, 3 src, 3 tests)" is correct.

### File content verification:

- `artifacts/models.py` — pure Pydantic model, imports only `datetime`, `typing`, `pydantic`. No intra-package imports. Step plan's claim "no content changes needed" is correct.
- `artifacts/registry.py` — has exactly one intra-package import at line 7. Step plan correctly targets this line.
- `workflow/__init__.py` — currently has `__all__` but does NOT export `Artifact` or `ArtifactRegistry`. No current consumer imports artifacts from `orchestrator.workflow`.
- `workflow/artifacts/` — does not yet exist. Step plan is correct that it must be created.
- No references in `scripts/` or `alembic/`. Audit in Task 2 will return zero for those paths.

---

## Task-by-Task Analysis

### Task 1: Create workflow/artifacts/ Sub-Package

**Assumptions:**
- `models.py` content is purely external (pydantic, datetime) — no intra-package imports to update. ✓ Verified.
- The sub-package `__init__.py` mirrors the original but with updated import paths.

**Expected outputs:**
- Three files: `workflow/artifacts/__init__.py`, `workflow/artifacts/models.py`, `workflow/artifacts/registry.py`
- `registry.py` line 7 updated from `orchestrator.artifacts.models` → `orchestrator.workflow.artifacts.models`
- Both the old `orchestrator.artifacts` and new `orchestrator.workflow.artifacts` are importable simultaneously

**Blockers:** None. This is a pure copy-with-one-edit operation.

**Mitigation:** None needed.

---

### Task 2: Update All External Import Sites

**Assumptions:**
- All 6 external import sites are exactly as listed (confirmed above).
- The lazy import in `executor.py:826` is inside a conditional block — a normal `Edit` tool call on that line will work.
- `scripts/` and `alembic/` have zero references (confirmed via grep — the audit will succeed immediately).

**Expected outputs:**
- All 6 external files use `orchestrator.workflow.artifacts` (or `orchestrator.workflow.artifacts.registry` for most)
- `test_artifact_registry.py` uses the package-level import — it imports from `orchestrator.artifacts` (not `.registry`). After change it should use `orchestrator.workflow.artifacts` (package level). ✓ Step plan handles this correctly.

**Blockers:** None. All sites are identified and the changes are mechanical.

**Mitigation:** None needed.

---

### Task 3: Delete Original artifacts/ Directory

**Assumptions:**
- After Task 2, zero external references remain to `orchestrator.artifacts`.
- The pre-delete grep check will pass cleanly.

**Expected outputs:**
- `src/orchestrator/artifacts/` does not exist.
- `src/orchestrator/workflow/artifacts/` has all three files.

**Blockers:** None if Task 2 is complete.

**Mitigation:** The step plan correctly makes the pre-delete grep check a required gate. This prevents accidental deletion before all consumers are updated.

---

### Task 4: Full Test Suite and Audit

**Assumptions:**
- No tests import from `orchestrator.artifacts` after Task 2. ✓
- No circular imports introduced (confirmed: `workflow/artifacts/registry.py` only imports from `workflow.artifacts.models`, which imports only from `pydantic`/`datetime`).

**Expected outcomes:**
- All unit and integration tests pass (16 artifact tests + 3 context builder / summary cache tests all continue to work with new paths).
- `grep -r "from orchestrator.artifacts"` returns zero results in src/tests/scripts/alembic.

---

## Failure Modes and Hardening

### F1: workflow/__init__.py re-export gap (Low Risk)

**Issue:** The Intent Verification section states "`workflow/__init__.py` re-exports `Artifact` and `ArtifactRegistry` so existing top-level consumers that import from `orchestrator.workflow` continue to work." However, no current consumer imports artifacts from `orchestrator.workflow` (all import from `orchestrator.artifacts.registry` directly). The step has no explicit task to update `workflow/__init__.py`.

**Impact:** No test failures. The re-export is described in the intent but isn't mechanically required by any current consumer. An implementer following the task list strictly would skip this.

**Hardening:** The step plan should either (a) explicitly add a task to update `workflow/__init__.py` to re-export `Artifact` and `ArtifactRegistry` (for consistency with the architectural intent), or (b) remove the mention from Intent Verification since it's not required for correctness. Recommended: add a sub-step in Task 1 to update `workflow/__init__.py` with:
```python
from orchestrator.workflow.artifacts import Artifact, ArtifactRegistry
```
and add `"Artifact"` and `"ArtifactRegistry"` to its `__all__`. This makes the intent match the plan.

---

### F2: executor.py lazy import at line 826 (Low Risk, Correctly Identified)

**Issue:** The lazy import inside a conditional block at line 826 might be missed by a find-and-replace that only updates top-of-file imports.

**Impact:** If missed, the executor silently falls back to importing from the (now deleted) `orchestrator.artifacts`, causing a `ModuleNotFoundError` at runtime only when `task_config.context_from` is configured — not on server startup, so tests that don't exercise this code path would still pass.

**Hardening:** The step plan already correctly identifies this as a lazy import and includes it in Task 2. The grep audit in Task 2 (`grep -r "from orchestrator\.artifacts"`) will catch any missed instance. The final verification in Task 4 (`uv run pytest tests/unit/ tests/integration/ -q`) should include a test for the `context_from` path if one exists. No additional hardening needed beyond what's already specified, but verifying there's an integration test that exercises `context_from` would be ideal.

---

### F3: docs/refactor-modules.md references (Non-Issue)

**Issue:** `grep -r "from orchestrator.artifacts"` without `--include="*.py"` would also match documentation files like `docs/refactor-modules.md`. The step plan's grep commands use `--include="*.py"` which correctly excludes doc files.

**Impact:** None. The grep commands are correctly scoped to `.py` files.

**Hardening:** None needed. Already handled correctly.

---

### F4: Circular import if workflow/__init__.py re-exports artifacts (Medium Risk, Conditional)

**Issue:** If the hardening action from F1 is applied (adding artifacts re-export to `workflow/__init__.py`), there could be a circular import if `workflow/artifacts/registry.py` or `workflow/artifacts/models.py` ever imports from `orchestrator.workflow`.

**Impact:** `ImportError: cannot import name 'X' from partially initialized module 'orchestrator.workflow'` at startup.

**Hardening:** Already verified: `artifacts/models.py` imports only from `pydantic`/`datetime` and `artifacts/registry.py` imports only from `orchestrator.workflow.artifacts.models`. Neither imports from `orchestrator.workflow` directly. No circular import risk. The Task 4 verification command covers this:
```bash
grep -r "from orchestrator\.workflow\." src/orchestrator/workflow/artifacts/ --include="*.py" | grep -v "from orchestrator\.workflow\.artifacts"
```

---

### F5: Missing explicit test for executor lazy import path (Medium Risk)

**Issue:** The test suite may not exercise the `context_from` code path in executor that contains the lazy import. If no test triggers `executor.py:826`, the import update could be verified only by the grep audit, not by test execution.

**Impact:** The updated lazy import path (`orchestrator.workflow.artifacts.registry`) would not be tested at runtime. A typo in that import wouldn't be caught by `uv run pytest`.

**Hardening:** Add a verification step to Task 4:
```bash
uv run python -c "
import asyncio, sys
from orchestrator.runners.executor import *
# Trigger the lazy import by importing the module that contains it
import importlib
m = importlib.import_module('orchestrator.runners.executor')
import ast, inspect, textwrap
src = inspect.getsource(m)
assert 'from orchestrator.workflow.artifacts.registry import ArtifactRegistry' in src, 'FAIL: lazy import not updated'
print('OK: lazy import verified')
"
```
Or more practically, the Task 2 pre-check grep already validates this:
```bash
grep -r "from orchestrator\.artifacts" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "src/orchestrator/artifacts/"
```
This will catch any un-updated lazy imports since `executor.py` is in `src/`. The existing audit is sufficient.

---

### F6: Task ordering — old directory must not be deleted before all consumers updated (Low Risk, Already Mitigated)

**Issue:** If Task 3 runs before Task 2 completes, any consumer still importing from `orchestrator.artifacts` will fail at import time.

**Impact:** `ModuleNotFoundError` for the old path.

**Hardening:** The step plan already requires the pre-delete grep gate in Task 3 (zero lines before proceeding). This is the correct mitigation. No additional action needed.

---

## Summary Assessment

**This step is well-specified.** The file reference counts are correct (9 total import sites), all files are accurately identified, and the ordering (create → update → delete → verify) is sound. The lazy import in executor.py is correctly called out.

**Two gaps to address before implementation:**

1. **(F1, Low Priority)** Decide whether to update `workflow/__init__.py` to re-export `Artifact` and `ArtifactRegistry`. The intent document calls for it but no task covers it. Either add a task or remove the mention from Intent Verification to avoid confusion.

2. **(F5, Low Priority)** The executor lazy import path won't be tested by any known test that exercises `context_from` configuration. The grep audit in Task 2/4 is the primary verification. This is acceptable, but worth noting.

**No high-risk failure modes exist.** The step is mechanically straightforward, independent of other phases, and the artifacts module has no circular import risks. All verification commands are correctly specified.
