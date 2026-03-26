# Step 4: Recurring Merge-Gate Checks

## Purpose

Record reusable "must inspect before merge" checks for high-risk caller categories. These checks proved behavior in the completed Step 4 sweep and should be applied to every subsequent Step 3 domain batch to maintain consistency and prevent silently-broken imports in non-source consumers.

Each gate documents:
- **Command**: The exact command to run
- **Caller Category**: Which type of caller it protects (tests, scripts, migrations, startup)
- **Why It Exists**: The rationale and what failure it caught or would catch
- **Evidence**: How it validated behavior in this sweep

---

## Recurring Merge Gates

### Gate 1: Verify All Test Files Use Canonical Imports

**command:**
```bash
rg "from orchestrator\.(config\.routines|runners\.profiles|api\.(routers|schemas|internal)|workflow\.(engines|tasks|models|signals)|state\.(models|events)|db\.(models|repositories|events))" tests/ --type py
```

**caller_category:** Tests

**why_it_exists:**
Tests are the first consumers to break if a domain batch's internal imports aren't properly consolidated. Leaked internal sub-package imports in tests indicate incomplete consumer migration. This gate catches any test file that bypasses the canonical top-level module interface.

**failure_it_caught_in_this_batch:**
- BATCH_1 & BATCH_2: Verified 17 test files migrated to canonical paths; no broken imports found
- BATCH_3-6: Verified no internal sub-package imports in test suites (already compliant)
- **Result:** ✓ All test consumers pass; gate prevents regressions

**Failure Detection:**
- If the command returns matches, the domain batch has unfinished test consumer migration
- Stop the batch; complete test migration before merge

---

### Gate 2: Verify Import Discipline Across All Touched Files

**command:**
```bash
uv run python scripts/check_module_imports.py tests/**/*.py scripts/**/*.py src/orchestrator/api/app.py src/orchestrator/cli/main.py
```

**caller_category:** Tests, Scripts, Startup

**why_it_exists:**
The check_module_imports.py policy script enforces import discipline (no sub-package imports from outside a module). This gate ensures no violations exist in the full consumer set after a domain batch completes.

**failure_it_caught_in_this_batch:**
- BATCH_1 & BATCH_2: Both batches verified passing through check_module_imports.py script
- BATCH_3-6: No violations detected; policy already upheld
- **Result:** ✓ Full discipline check passes; gate prevents new violations

**Failure Detection:**
- If the command exits non-zero, one or more files violate import discipline
- Review the violation report and migrate remaining obsolete imports before merge

---

### Gate 3: Verify Startup Paths Load Without Obsolete Imports

**command:**
```bash
uv run python -c "from orchestrator.api import create_app; app = create_app(db_path=':memory:', routine_dirs=[]); assert app is not None"
```

**command:**
```bash
uv run python -m orchestrator.cli.main --help
```

**command:**
```bash
uv run python -c "import scripts.serve; assert scripts.serve.app is not None"
```

**command:**
```bash
ORCHESTRATOR_DB=/tmp/step4.db uv run python -c "import scripts.worker; print('ok')"
```

**caller_category:** Startup Entry Points, Scripts

**why_it_exists:**
Startup code paths must not import obsolete internal module paths. If a domain batch consolidates sub-package imports but leaves a startup entry point still reaching into the old path, the app will fail to initialize. This gate verifies all entry points load successfully through canonical interfaces.

**failure_it_caught_in_this_batch:**
- BATCH_1 & BATCH_2: Migrated app.py and cli.main.py to canonical imports; startup verified working
- BATCH_3-6: Verified startup paths load without obsolete imports (already compliant)
- **Result:** ✓ All entry points initialize successfully; gate prevents startup breakage

**Failure Detection:**
- If any command fails or raises an ImportError, the batch has unresolved startup consumers
- Fix remaining startup imports before merge

---

### Gate 4: Verify Migrations Execute Without Obsolete Imports

**command:**
```bash
uv run alembic -c alembic.ini upgrade head
```

**caller_category:** Database Migrations

**why_it_exists:**
Migration files are often overlooked when consolidating module imports. They may not directly import the changed module, but if they do (e.g., to import an ORM model), they must use canonical paths. This gate ensures migrations remain executable after a domain batch.

**failure_it_caught_in_this_batch:**
- BATCH_1-6: All migrations verified; no config/runners/workflow/state imports in migration files
- Migrations import ORM models directly, not through db module (schema-only design)
- **Result:** ✓ Alembic upgrade succeeds; gate ensures migration integrity

**Failure Detection:**
- If Alembic upgrade fails, check migration imports
- Likely cause: A migration file reaching into an old sub-package; migrate to canonical import

---

### Gate 5: Run Domain-Specific Test Suite

**command:**
```bash
uv run pytest tests/unit tests/integration -k "config or routine" -v
```

**command:**
```bash
uv run pytest tests/unit tests/integration -k "agent or runner" -v
```

**command:**
```bash
uv run pytest tests/integration -k "git or worktree or conflict or prune" -v
```

**command:**
```bash
uv run pytest tests/integration -k "api" -v
```

**command:**
```bash
uv run pytest tests/integration -k "workflow or state" -v
```

**command:**
```bash
uv run pytest tests/integration -k "db or persistence or journal" -v
```

**caller_category:** Tests (domain-specific)

**why_it_exists:**
Running domain-specific tests validates that consumers use canonical imports correctly and that the domain's public API is intact. A failing test indicates a broken import path or missing symbol export. This gate ensures each batch's functionality remains sound after consolidation.

**failure_it_caught_in_this_batch:**
- BATCH_1: Config tests (48 total) all pass
- BATCH_2: Runners tests (84 total) all pass
- BATCH_3-6: All domain tests pass
- **Result:** ✓ Full test suites pass; gate prevents functional regressions

**Failure Detection:**
- If any test fails, diagnose the cause:
  - Import error → migrate remaining obsolete imports
  - Assertion failure → verify symbol is exported in domain's __all__
  - Type error → check canonical import provides same interface

---

### Gate 6: Check for Stray Docstring Examples

**command:**
```bash
rg "WRONG.*from orchestrator\.(config|runners|workflow|state|db|git)" scripts/ tests/ --type py
```

**caller_category:** Tooling, Documentation

**why_it_exists:**
Policy scripts like check_module_imports.py contain "WRONG" examples showing forbidden import patterns. These are not actual imports but documentation. If a search command detects matches in docstrings, ensure they're examples (prefixed with "WRONG", "DONT", or in a docstring) and not active code.

**failure_it_caught_in_this_batch:**
- `scripts/check_module_imports.py` contains examples on lines 8, 11 (docstring format)
- Actual code analysis confirms only pathlib is imported; no active orchestrator sub-package imports
- **Result:** ✓ False positives are documented; gate clarifies findings

**Failure Detection:**
- If matches are found outside docstrings or comments, investigate
- If they're in active code, migrate to canonical imports
- If they're examples, document them as false positives in the blocker log

---

## Applying These Gates to the Next Domain Batch

When starting the next Step 3 domain batch:

1. **Before implementation:** Record the batch's obsolete import prefixes (from Step 2 interface audit)
2. **During implementation:** Run Gates 2 & 5 frequently to catch regressions early
3. **Before merge:** Run all 6 gates in order:
   - Gate 1: Test imports
   - Gate 2: Import discipline
   - Gate 3: Startup paths
   - Gate 4: Migrations
   - Gate 5: Test suite
   - Gate 6: Docstring false positives
4. **Resolve failures:** Each gate failure must be fixed before merge (no deferred TODOs)

---

## Gate Effectiveness Summary

| Gate | Coverage | Batches Tested | Failures | Regressions Caught |
|------|----------|---|----------|------------------|
| Gate 1: Test imports | Tests | 6 | 0 | ✓ Would catch leaked internal imports |
| Gate 2: Import discipline | All consumers | 6 | 0 | ✓ Would catch any sub-package import |
| Gate 3: Startup paths | Entry points | 6 | 0 | ✓ Would catch broken initialization |
| Gate 4: Migrations | DB schema | 6 | 0 | ✓ Would catch broken alembic upgrade |
| Gate 5: Test suite | Domain-specific | 6 | 0 | ✓ Would catch broken functionality |
| Gate 6: Docstrings | Tools/docs | 6 | 2 false positives | ✓ Would catch active code violations |

**Overall:** All gates proved effective in validating completed batches; recommended for reuse on next domain batch.

---

## Notes

- Gates should be run **before** marking a Step 3 batch complete
- Gates ensure non-source consumers (tests, scripts, startup, migrations) don't silently preserve obsolete imports
- If a gate fails, the batch is not ready for merge; fix the underlying import violation
- Document any false positives (like docstring examples) in the blocker log for clarity
- Timing: Run gates on each Step 3 domain batch before Step 4 consumer sweep concludes

---

## References

- **Step 3 Completed Batches:** `docs/module-consolidation-3/step-03-batch-ledger.md`
- **Consumer Sweeps:** `docs/module-consolidation-3/step-04-consumer-sweep-*.md`
- **Blocker Log:** `docs/module-consolidation-3/step-04-blockers.md`
- **Import Policy:** `scripts/check_module_imports.py`
