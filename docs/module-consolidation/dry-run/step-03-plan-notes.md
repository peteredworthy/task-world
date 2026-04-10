# Dry-Run Analysis: Step 3 — Absorb routines/ → config/routines/

Analyzed against the current codebase state (post-Phase-0, post-Phase-1 assumed).

---

## Overall Assessment

The step is mechanically sound and the logic is correct. The move is low-risk: `routines/` has no coupling violations to fix first, no circular-import risk after relocation, and no `__file__`-relative path resolution that would break on filesystem move. Three issues need attention:

1. **Minor import-count discrepancies** in the task descriptions (documentation only, no functional impact — the sed pattern catches all occurrences)
2. **`api/errors.py` location mislabeled** as "in api/routers/" when it lives in `api/` root
3. **`loader.py` external imports need explicit verification** to confirm no circular dependency after the move (analysis below shows it's safe, but the step doesn't call this out)

No blocking issues found.

---

## Import Site Audit (vs. Step Claims)

### Task 2 claims "9 import sites across 8 files"

Actual count from grep: **13 import lines across 8 files**:

| File | Import Lines |
|------|-------------|
| `api/errors.py` | 1 |
| `api/routers/repos.py` | 1 |
| `api/routers/routines.py` | 2 |
| `api/routers/runs.py` | 2 |
| `api/routers/tasks.py` | 2 |
| `cli/routines.py` | 3 |
| `cli/runs.py` | 1 |
| `scripts/seed_db.py` | 1 |

**File count (8) is correct; line count (9) is off.** The sed pattern `'s/from orchestrator\.routines\./from orchestrator.config.routines./g'` handles all occurrences per file in one pass, so this discrepancy has no functional impact.

### Task 2 says "5 in api/routers/"

`api/errors.py` lives in `api/` root, not `api/routers/`. There are 4 files in `api/routers/` (repos, routines, runs, tasks). The sed command correctly lists all 4 router files plus `api/errors.py` separately, so this is a documentation-only error.

### Task 3 says "~14 import sites across 17 files"

Actual count: **17 test files** (6 unit + 11 integration) — the file count is correct. The import line count is higher (e.g., `test_agent_executor.py` has 7 occurrences alone). Again, the sed command handles all occurrences per file; the verification criterion (empty grep output) is the authoritative check.

---

## Task-by-Task Analysis

### Task 1: Create config/routines/ sub-package

**Assumptions verified:**
- `errors.py`: Contains only exception class definitions with no imports. Verbatim copy is correct.
- `versioning.py`: Imports only from stdlib (`subprocess`, `pathlib`, `dataclasses`). Verbatim copy is correct.
- `loader.py`: Has one internal import to update — `from orchestrator.routines.errors import (RoutineNotFoundError, RoutineParseError, RoutineValidationError)`. The step correctly identifies this.
- `discovery.py`: Has two internal imports to update — `from orchestrator.routines.errors import RoutineError` and `from orchestrator.routines.loader import load_routine_from_path`. Both correctly identified.
- `__init__.py`: Two internal imports to update. Proposed content matches existing `routines/__init__.py` exports exactly.

**External imports in `loader.py` — circular import risk analysis:**

`loader.py` imports `RoutineConfig` and related models from `orchestrator.config.models`. After moving to `orchestrator.config.routines.loader`, this becomes a cross-module import from a sibling (`config.models` is not `config.routines`). The import chain:

```
config/__init__.py  →  config.models  →  (no imports from config.routines/)
config/routines/loader.py  →  config.models
```

`config/models.py` does not import from `config/routines/`. No circular import. Confirmed safe.

**`config/__init__.py` — no update needed:**

Verified: `config/__init__.py` imports only from `config.enums` and `config.models`. It does not import from `config.loader` (the shim) and does not need to import from `config.routines`. The step's "Do NOT modify `config/__init__.py`" instruction is correct.

**`__all__` in proposed `config/routines/__init__.py`:**

The proposed `__all__` exports `RoutineError`, `RoutineNotFoundError`, `RoutineParseError`, `RoutineValidationError`, `load_routine_from_path`. This matches the existing `routines/__init__.py` exactly. Callers that import `discover_routines`, `get_routine_from_repo`, `DiscoveredRoutine`, `RoutineVersion` etc. already import from the sub-modules directly (e.g., `from orchestrator.routines.discovery import discover_routines`) — these will be correctly updated by sed to `orchestrator.config.routines.discovery`.

**No `__file__`-relative paths:**

Both `discovery.py` and `loader.py` use standard `Path` operations with parameters. `_resolve_step_files` in `loader.py` resolves step files relative to the routine YAML's directory (passed as a parameter). Filesystem relocation of `loader.py` itself has zero effect.

**Expected output:** 5 files created with correct internal imports. Import verification commands in the step will confirm.

**Risks:** None. All assumptions verified against source.

---

### Task 2: Update src/ imports (api/, cli/, scripts/)

**`config/loader.py` deletion:**

The step calls this a "dead shim with zero consumers." Verified: `config/__init__.py` does NOT import from `config/loader.py`. No file in `src/`, `tests/`, or `scripts/` imports from `orchestrator.config.loader`. Deletion is safe.

**Sed pattern correctness:**

All discovered imports use `from orchestrator.routines.<submodule> import ...` (with a dot between `routines` and the submodule name). The pattern `'s/from orchestrator\.routines\./from orchestrator.config.routines./g'` matches all of them. There are no imports of the form `from orchestrator.routines import <symbol>` (importing from the `__init__` directly) in the src/scripts files — confirmed by grep.

**Side effect note (correctly stated):** After Task 2, both import paths are valid simultaneously (old `routines/` still exists). This is intentional and correct.

**Risks:** None.

---

### Task 3: Update test imports and delete routines/

**17 test files to update — verified breakdown:**

*Integration tests (11):* `test_agent_executor.py` (7 import lines), `test_event_recovery.py`, `test_fan_out.py`, `test_full_persistence.py`, `test_project_routines.py`, `test_repositories.py`, `test_routine_loading.py`, `test_run_creation.py`, `test_scaffolding.py`, `test_workflow_execution.py`, `test_workflow_service.py`

*Unit tests (6):* `test_error_integration_example.py`, `test_idea_to_plan_routine.py`, `test_loader_multifile.py`, `test_routine_discovery.py`, `test_routine_loader.py`, `test_routine_versioning.py`

The `find tests/ -name "*.py" -exec sed ...` command covers all `.py` files including any conftest files. This is correct and exhaustive.

**`test_routine_versioning.py`:** Imports `from orchestrator.routines.versioning import (find_git_root, get_routine_version, RoutineVersion)`. The sed command updates this correctly. The new `config/routines/versioning.py` exports all three symbols — confirmed.

**Deletion safety:** The step correctly sequences deletion after all import updates. No stubs or re-exports will remain at `src/orchestrator/routines/`.

**Risks:** None.

---

### Task 4: Full verification suite

**Assumptions:**
- Two known pre-existing integration test failures (openhands module not installed) are acknowledged.
- The `routines/demo-task.yaml` spot-check uses `Path('routines/demo-task.yaml')` — this is a relative path that resolves from the current working directory (project root). The file should exist there. The step correctly makes this conditional (`if p.exists()`).

**Missing verification:** The step does not explicitly check that `from orchestrator.config import RoutineConfig` (top-level config import) still works after the move. Since `config/__init__.py` was not modified, this is implicitly safe — but adding it as a spot-check would add confidence.

**Risks:** Low. The full test suite catches any missed import updates.

---

## Failure Modes and Hardening Actions

### FM-1: Import count mismatch causing premature "done" signal

**Risk (low):** If an implementor manually counts import sites and stops at 9 (the stated count), they might miss 4 additional import lines in Task 2. In practice the sed command covers all occurrences regardless of count, and the grep verification is the authoritative check.

**Hardening:** Change Task 2's description from "9 import sites" to "13 import lines" and "5 in api/routers/" to "4 in api/routers/ plus api/errors.py". The verification grep is the authoritative criterion — no code change needed, just clarify the documentation.

### FM-2: `loader.py` circular import missed

**Risk (low):** An implementor might not realize `loader.py` imports from `orchestrator.config.models` and could worry about circular imports after the move.

**Hardening:** The Task 1 verification step `uv run python -c "from orchestrator.config.routines.loader import load_routine_from_path; print('OK')"` will catch any actual circular import at runtime. No additional guard needed, but adding a comment in Task 1 noting "loader.py imports from orchestrator.config.models — not circular" would preempt confusion.

### FM-3: `config/loader.py` deletion — consumer scan incomplete

**Risk (low):** The step does not show the grep command used to verify zero consumers before deleting `config/loader.py`. If a consumer was missed, deletion would cause a runtime import error that might not appear until an integration test exercises that code path.

**Hardening:** Add an explicit verification before deletion:
```bash
grep -r "from orchestrator\.config\.loader" src/ tests/ scripts/
grep -r "from orchestrator\.config import.*load_routine" src/ tests/ scripts/
```
Both should return zero results. This prevents a future refactor from accidentally adding a consumer between dry-run and execution.

### FM-4: `routines/__init__.py` self-imports not updated (stale file)

**Risk (low):** The old `src/orchestrator/routines/__init__.py` still imports `from orchestrator.routines.errors import ...`. After Task 1 creates the new sub-package (but before Task 3 deletes the old directory), the codebase has both. The old `routines/__init__.py` is not updated — it's just deleted wholesale in Task 3. This is correct.

**Hardening:** None needed. The step's approach (create new → update consumers → delete old) is the right sequence.

### FM-5: `conftest.py` files potentially missed

**Risk (very low):** If any `tests/conftest.py` or `tests/unit/conftest.py` imports from `orchestrator.routines`, the `find tests/ -name "*.py" -exec sed ...` command covers it (conftest.py ends in `.py`).

**Hardening:** The final grep in Task 3 (`grep -r "from orchestrator\.routines" src/ tests/ scripts/`) is exhaustive and catches any missed file. No additional action needed.

### FM-6: `discover_routines` top-level not re-exported from `config/routines/__init__.py`

**Risk (none):** `discover_routines`, `get_routine_from_repo`, `DiscoveredRoutine`, `ProjectRoutine`, and versioning symbols are not in the current `routines/__init__.py` `__all__` and are not proposed for `config/routines/__init__.py` either. All callers import from the sub-modules directly. After sed update, they import from `orchestrator.config.routines.discovery` etc. This is consistent and correct.

**Hardening:** None needed.

---

## Summary

| Item | Status | Action |
|------|--------|--------|
| Prerequisites (Phase 0) | Clean — no coupling dependencies for this step | None |
| File existence checks | All `routines/` files confirmed present | None |
| Internal import updates | All correctly identified in step | None |
| External import sites (src/scripts) | 8 files, 13 lines (step says 9 lines — minor doc error) | Clarify count in step description |
| Test import sites | 17 files — count matches | None |
| `config/loader.py` dead shim | Zero consumers confirmed | Add explicit grep before deletion |
| `config/__init__.py` no-change | Confirmed correct | None |
| Circular import risk | None — `config.models` does not import from `config.routines` | Add comment noting this is safe |
| `__file__`-relative paths | None found | None |
| Proposed `__init__.py` exports | Match existing exactly | None |
| Deletion sequencing | Create → update consumers → delete old | Correct |
| Full verification suite | Comprehensive (unit + integration + frontend + pre-commit) | None |
