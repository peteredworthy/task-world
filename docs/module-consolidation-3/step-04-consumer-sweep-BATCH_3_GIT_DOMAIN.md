# Step 4: Consumer Sweep – BATCH_3_GIT_DOMAIN

## Batch Summary

| Attribute | Value |
|-----------|-------|
| **batch_id** | BATCH_3_GIT_DOMAIN |
| **domain** | git |
| **symbols** | 19 public symbols: apply_prune, back_merge, BlockResolution, BranchStatus, compute_selection_preview, FileSelectionEntry, get_branch_status, get_conflict_blocks, get_conflict_files, Hunk, merge_back, parse_conflict_blocks, preview_prune, prune_hunks, prune_lines, PruneStats, resolve_conflict, RevertBackMergeResult, ensure_exists |
| **obsolete_import_prefixes** | None (already compliant in Step 3) |
| **canonical_import_path** | `from orchestrator.git import ...` |
| **status** | complete |

---

## Consumer Sweep Checklist

Complete inventory of non-source callers: tests, scripts, migrations, startup entry points, and operational tooling. This batch was already compliant in Step 3 (no sub-package imports existed); verification confirms continued compliance.

### Tests (2 files)

**Field Mapping:** `file_path` | `caller_category` | `current_import` | `canonical_import` | `status`

| file_path | caller_category | current_import | canonical_import | status | Verification Command | Note |
|-----------|-----------------|-----------------|------------------|--------|----------------------|------|
| `tests/integration/test_conflict_ops.py` | test | `from orchestrator.git import ...` (all symbols) | `from orchestrator.git import ...` | already_canonical | `uv run pytest tests/integration/test_conflict_ops.py -v` | ✓ All git conflict operations imported from canonical path |
| `tests/integration/test_prune_ops.py` | test | `from orchestrator.git import ...` (all symbols) | `from orchestrator.git import ...` | already_canonical | `uv run pytest tests/integration/test_prune_ops.py -v` | ✓ All git prune operations imported from canonical path |

**Test Assertion Logic:**
- Conflict resolution operations (`resolve_conflict`, `get_conflict_blocks`, `get_conflict_files`, `parse_conflict_blocks`) imported from canonical path
- Prune operations (`apply_prune`, `preview_prune`, `prune_hunks`, `prune_lines`) imported from canonical path
- Worktree operations (`back_merge`, `merge_back`, `ensure_exists`) imported from canonical path
- All test assertions pass using canonical import path from orchestrator.git

### Scripts & Operational Tooling (2 files)

**Field Mapping:** `file_path` | `caller_category` | `current_import` | `canonical_import` | `status`

| file_path | caller_category | current_import | canonical_import | status | Verification Command | Note |
|-----------|-----------------|-----------------|------------------|--------|----------------------|------|
| `scripts/serve.py` | startup | No direct git imports | N/A | already_canonical | `uv run python -c "import scripts.serve; assert scripts.serve.app is not None"` | ✓ No git module dependencies in server startup |
| `scripts/worker.py` | startup | No direct git imports | N/A | already_canonical | `ORCHESTRATOR_DB=/tmp/step4.db uv run python -c "import scripts.worker; print('ok')"` | ✓ No git module dependencies in worker startup |

### Source Startup Entry Points (2 files)

**Field Mapping:** `file_path` | `caller_category` | `current_import` | `canonical_import` | `status`

| file_path | caller_category | current_import | canonical_import | status | Verification Command | Note |
|-----------|-----------------|-----------------|------------------|--------|----------------------|------|
| `src/orchestrator/api/app.py` | startup | No direct git imports | N/A | already_canonical | `uv run python -c "from orchestrator.api import create_app; app = create_app(db_path=':memory:', routine_dirs=[]); assert app is not None"` | ✓ Git module used through workflow engine (indirect) |
| `src/orchestrator/cli/main.py` | startup | No direct git imports | N/A | already_canonical | `uv run python -m orchestrator.cli.main --help` | ✓ Git module used through workflow engine (indirect) |

### Migrations (0 files)

No migration files use git module imports.

| File Path | Caller Category | Status | Note |
|-----------|-----------------|--------|------|
| `src/orchestrator/db/migrations/versions/*.py` (all) | migration | false_positive | ✓ Migration files are schema-only; no git module dependencies |

---

## Inspection Results

### Category: Tests
**Status:** ✓ Complete (Already Compliant)
**Finding:** All 2 test files already use canonical `from orchestrator.git import ...` paths
**Verification:** Direct code inspection confirms canonical pattern; git module had no sub-package imports in Step 2/3
**Command:** `rg "from orchestrator\.git\.(ops|conflict|prune|worktree)" tests/ --type py` returns no matches (all ops are in orchestrator.git or orchestrator.git.ops, but orchestrator.git.__all__ exports them publicly)
**Outcome:** No migration needed; already compliant throughout Step 3

### Category: Scripts & Operational Tooling
**Status:** ✓ Complete (No Violations)
**Finding:** Both script files have no git module imports at all; git operations used indirectly through workflow engine
**Verification:** Direct code inspection
**Command:** `rg "from orchestrator\.git\." scripts/ src/orchestrator/api/app.py src/orchestrator/cli/main.py --type py` returns no matches
**Outcome:** No migration needed; false positive (no imports to migrate)

### Category: Startup Entry Points
**Status:** ✓ Complete (Indirect Use Only)
**Finding:** Git module used indirectly through workflow engine in app initialization
  - Worktree operations invoked via `WorkflowEngine` during run execution
  - No direct imports in startup code
**Verification:** Direct code inspection
**Command:** All startup commands verified in verification section
**Outcome:** No migration needed; indirect usage maintains separation of concerns

### Category: Migrations
**Status:** ✓ Complete (No Dependencies)
**Finding:** No git module imports in migration files
**Verification:** Direct inspection of migration environment
**Command:** `rg "from orchestrator\.git" src/orchestrator/db/migrations/ --type py` returns no matches
**Outcome:** No migration needed; migrations are schema-only

---

## Verification Summary

### Import Discipline Scan
```bash
rg "from orchestrator\.git\.(ops|conflict|prune|worktree)" tests scripts src/orchestrator/db/migrations src/orchestrator/api/app.py src/orchestrator/cli/main.py -g '*.py'
```
**Result:** ✓ No matches (verified 2026-03-25) — All git operations use top-level git module path

### Test Execution
```bash
uv run pytest tests/integration/test_conflict_ops.py tests/integration/test_prune_ops.py -v
```
**Result:** ✓ PASSED (all git domain tests pass)

### Startup Verification Commands

1. **API Startup**
   ```bash
   uv run python -c "from orchestrator.api import create_app; app = create_app(db_path=':memory:', routine_dirs=[]); assert app is not None"
   ```
   **Result:** ✓ PASSED

2. **Server Script**
   ```bash
   uv run python -c "import scripts.serve; assert scripts.serve.app is not None"
   ```
   **Result:** ✓ PASSED

3. **CLI Startup**
   ```bash
   uv run python -m orchestrator.cli.main --help
   ```
   **Result:** ✓ PASSED

---

## Batch Status

| Aspect | Status | Evidence |
|--------|--------|----------|
| **All consumers identified** | ✓ Done | 2 test files + 4 startup files (no violations found) |
| **Imports categorized** | ✓ Done | All verified as canonical (no sub-package imports) |
| **Tests passing** | ✓ Done | All test files pass with canonical imports |
| **Startup paths working** | ✓ Done | All entry points load successfully |
| **No obsolete imports** | ✓ Done | Verified (no internal sub-package imports exist) |
| **No blockers** | ✓ Done | Already compliant; no migration work needed |

**Batch Status: ✓ COMPLETE** — No blockers, already fully compliant from Step 3. Batch verified as meeting canonical import standards.

---

## Notes

This batch was marked "no violations" in Step 2 analysis because all git module public symbols were already exported at the top-level `orchestrator.git` module level. No consumer migration work was required in Step 3; this sweep confirms continued compliance.

---

## Next Steps

Proceed to **BATCH_4_API_MCP_DOMAIN** consumer sweep.
