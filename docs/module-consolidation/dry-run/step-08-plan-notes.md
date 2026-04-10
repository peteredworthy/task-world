# Step 08 Dry-Run Analysis: Restructure db/ Internals

## Summary

Step 08 reorganizes `db/`'s 9 flat files into three sub-packages (`orm/`, `access/`, `recovery/`) and updates all external callers to use top-level `from orchestrator.db import X` imports. The step is mechanically straightforward but has **one show-stopping naming conflict** and **several coverage gaps** that will cause failures if not addressed.

---

## Task-by-Task Walk-Through

### Task 1: Audit — Build Public Symbol Map

**Assumptions:**
- The grep commands will find all consumers. Confirmed by manual exploration: ~30 unique external files across `src/`, `tests/`, and `scripts/`.
- `GradeSnapshotItem` is confirmed to have multiple consumers outside `db/`: `state/models.py` (definition), `workflow/transitions.py`, `db/recovery.py`, `db/repositories.py`, and `api/schemas/tasks.py`. Decision to leave it in `state/models.py` is correct.

**Expected Outputs:**
- Complete list of files needing import updates.
- Confirmed `PendingExpansionRequestModel` does NOT appear in the actual ORM code (only a migration table — the Python class is absent from `db/models.py`). Must not appear in `__init__.py` exports.
- `recover_run_state` does not exist in the codebase (not defined, not used). No issue.
- `scripts/` has 3 files that import from `orchestrator.db.*`: `restore_from_journal.py`, `seed_db.py`, `worker.py`. **The audit grep includes scripts/ but Tasks 6 and 7 do not cover it — this is the primary coverage gap.**

**Blockers:** None in this task. Read-only audit.

---

### Task 2: Create db/orm/ Sub-Package

**Assumptions:**
- `db/base.py` has no internal `orchestrator.db.*` imports — confirmed correct.
- `db/models.py` imports `from orchestrator.db.base import Base` as its only internal dep — confirmed correct.
- No other files need updating during this task.

**Expected Outputs:**
- `db/orm/__init__.py`, `db/orm/base.py`, `db/orm/models.py` created.
- Old flat files untouched.

**No failure modes** specific to this task. `db/orm/` is a safe namespace — no conflict with existing flat files.

---

### Task 3: Create db/recovery/ Sub-Package

**CRITICAL FAILURE MODE: Module/Package Naming Conflict**

`src/orchestrator/db/recovery.py` (flat module → `orchestrator.db.recovery`) and `src/orchestrator/db/recovery/` (package directory → also `orchestrator.db.recovery`) **cannot coexist**. When both exist simultaneously:
- CPython's import system gives the **package (directory) precedence** over the flat module file.
- As soon as `db/recovery/__init__.py` is created, all existing imports of `from orchestrator.db.recovery import replay_events` start resolving to the package's (empty) `__init__.py` — **and fail with `ImportError`**.
- This affects: 4 integration test files (`test_parity_replay.py`, `test_event_recovery.py`, `test_db_recovery_e2e.py`, `test_agent_logs.py`), `scripts/restore_from_journal.py`, and `db/journal_replay.py` itself (the old flat file imports `from orchestrator.db.recovery import replay_events`).

**The step instructs: "Do not delete any flat files from db/ root" until Task 8.** This cannot be followed for `recovery.py`. The conflict must be resolved **atomically at the moment the directory is created**.

**Hardening Action:** Task 3 must be restructured. When creating `db/recovery/`, simultaneously:
1. Create `db/recovery/__init__.py` and populate it with full re-exports from sub-files (not an empty stub), **or**
2. Delete `db/recovery.py` immediately upon creating the directory, and update all callers that import from `orchestrator.db.recovery` before creating the directory. This means Tasks 6 and 7 for `orchestrator.db.recovery` callers must precede Task 3, reversing the stated order.

The cleanest approach is **Option 1**: populate `db/recovery/__init__.py` with re-exports at directory creation time, then remove the re-exports in Task 8. But this temporarily introduces shims. Alternative: treat `db/recovery.py`'s deletion as part of Task 3 (not Task 8), and update all `orchestrator.db.recovery.*` callers in the same commit as Task 3.

**Secondary assumption to verify:** `db/recovery.py` has no `orchestrator.db.*` imports (confirmed — it imports from `orchestrator.state.models` only). Copy is safe.

**journal_replay.py forward reference:** Task 3's new `db/recovery/journal_replay.py` references `from orchestrator.db.access.repositories import ...` before `db/access/` exists (Task 4). The step claims this is safe "because the file won't be imported until Task 8." This reasoning is correct **only if** nothing imports `orchestrator.db.recovery.journal_replay` before Task 4 completes. Since `db/recovery/__init__.py` doesn't import it, this is safe.

---

### Task 4: Create db/access/ Sub-Package

**Assumptions:**
- `db/connection.py` uses `_MIGRATIONS_DIR = Path(__file__).parent / "migrations"`. After moving to `db/access/connection.py`, this resolves to `db/access/migrations/` — which doesn't exist. The step correctly identifies this and prescribes `Path(__file__).parent.parent / "migrations"`.
- `db/repositories.py` imports `from orchestrator.db.models import (...)` — one import to update.
- `db/event_store.py` imports `from orchestrator.db.event_journal import (...)` and `from orchestrator.db.models import EventModel` — two imports to update.

**`alembic_cfg` path in `init_db()`:** Beyond `_MIGRATIONS_DIR`, `connection.py`'s `init_db()` also constructs an Alembic `Config` object and sets `script_location`. Verify that any `sqlalchemy.url` or other config values embedded in `connection.py` are also correctly adjusted (e.g., don't rely on `Path(__file__)` paths that may break after move).

**No naming conflicts** — `db/access/` is a new namespace with no conflict.

---

### Task 5: Update Alembic env.py and db/migrations/ Imports

**Assumptions:**
- `migrations/env.py` imports:
  - `from orchestrator.db.base import Base` → update to `from orchestrator.db.orm.base import Base`
  - `import orchestrator.db.models as _models` → update to `import orchestrator.db.orm.models as _models`
  - `import orchestrator.agents.models as _agent_models` — **this is also present and not mentioned in Task 5**

**Phase 6 Interaction (Agents Import in env.py):**
`migrations/env.py` imports `orchestrator.agents.models` to register `AgentConfigModel` in Alembic's metadata. If Phase 6 ran before Phase 8 (absorbing `agents/` into `runners/profiles/`), then `orchestrator.agents.models` no longer exists. Task 5 does not address updating `orchestrator.agents.models` → `orchestrator.runners.profiles.models` in `env.py`. If Phase 8 runs after Phase 6, Alembic will break.

**Hardening Action:** Task 5 must conditionally update `env.py`'s `agents.models` import based on execution ordering relative to Phase 6. The step should explicitly state: "If Phase 6 has already run, update `import orchestrator.agents.models` → `import orchestrator.runners.profiles.models`." (Or if Phase 8 is declared to run before Phase 6, document this constraint.)

**Migration version files:** All 23 version files confirmed to have zero `orchestrator` imports. Only `env.py` needs updating. ✓

---

### Task 6: Update All External src/ Callers

**Coverage Gap: scripts/ directory not listed.**

Task 6 covers `src/orchestrator/` files only. Three scripts also import from `orchestrator.db.*` sub-paths:
- `scripts/restore_from_journal.py` — imports `parse_journal_timestamp`, `RunRepository`, `replay_events` (deferred/lazy)
- `scripts/seed_db.py` — imports `create_engine`, `create_session_factory`, `init_db`, `EventStore`
- `scripts/worker.py` — imports `create_engine`, `create_session_factory`, `init_db`, `RunRepository`

None of these are listed in Task 6's implementation plan. Task 9's final verification grep includes `scripts/` and **will catch this** — but Task 6's per-file checklist will be declared complete while stale imports remain in scripts, causing Task 9 to fail.

**Hardening Action:** Add a "Files using `orchestrator.db.*` in scripts/" section to Task 6's implementation plan.

**`agents/models.py` Phase Dependency:**
Task 6 lists `src/orchestrator/agents/models.py` as importing `from orchestrator.db.base import Base`. If Phase 6 ran before Phase 8, this file has moved to `src/orchestrator/runners/profiles/models.py` (or similar). Task 6 would try to edit a non-existent file. The step should specify: "If Phase 6 has run, update the moved file at its new path."

**`workflow/signals.py` lazy imports:** The step mentions `PendingSignalModel` has "two occurrences, likely lazy imports inside functions." The actual file structure should be confirmed — if these are function-level `from` imports (not module-level), they must be found and updated. A targeted grep for the specific file before editing is important.

**File count accuracy:** Task 6's list of files may not be exhaustive. The actual count from the audit is ~13 src/ files. The step's list appears to cover the major ones, but lazy/deferred imports in deeply nested functions may be missed by a casual read. Post-update grep verification (`grep "from orchestrator\.db\." <file>`) per file is critical.

---

### Task 7: Update All External Test Callers

**Coverage gap: conftest files.**

The step lists `tests/e2e/conftest.py` as using `orchestrator.db.connection`. It does not explicitly list `tests/integration/conftest.py` or `tests/unit/conftest.py`. If these conftest files have `orchestrator.db.*` sub-path imports (which is likely given they set up test databases), they would be missed. The final grep in Task 9 will catch stragglers, but the per-file checklist won't track them.

**Hardening Action:** Before updating test files, run the audit grep from Task 1 (restricted to `tests/`) and diff against Task 7's listed files to identify any unlisted conftest or fixture files.

**Test file count:** Task 7 lists ~35 integration tests using `orchestrator.db.connection`. This is plausible given the test suite size (235 integration tests). However, the specific list may be incomplete for files added between when the step was written and when it is executed.

---

### Task 8: Update db/__init__.py and Delete Old Flat Files

**`PendingExpansionRequestModel` guard:** The step explicitly warns not to include `PendingExpansionRequestModel` in `__init__.py` unless confirmed to exist. Confirmed: a migration adds the table (`ca739d2b9086`) but no ORM Python class for this model exists in `db/models.py`. It must NOT be included. ✓

**`AttemptRecord` is a dataclass, not an ORM Base subclass.** This is fine — it's still a public symbol from `db/orm/models.py`. The export in `__init__.py` is correct.

**`resolve_default_journal_path_from_session`:** Listed as an export in `__init__.py`. Must be verified to exist in `event_journal.py` before including in the export list. If it doesn't exist, the import will fail immediately when `db/__init__.py` is loaded.

**`BackupMetadata` is a dataclass** in `backup.py`. Export is correct.

**Recovery package `__init__.py` state at deletion time:** When Task 8 deletes `db/recovery.py`, the package `db/recovery/` is already present. If the critical failure mode from Task 3 is resolved (by having `db/recovery/__init__.py` temporarily re-export everything), Task 8 must remove those temporary re-exports and let `db/__init__.py` become the sole re-export surface.

**Verify `db/__init__.py` currently empty:** Confirmed — current `db/__init__.py` contains only the docstring `"""Database layer for persistent storage."""`. No existing re-exports will conflict with the new ones. ✓

---

### Task 9: Full Test Suite and Reference Audit

**scripts/ audit coverage:** Task 9's verification grep includes `scripts/` — if Task 6 missed scripts, Task 9 will report failures. This is a good backstop but means work iterates back to fix scripts.

**Pre-commit hooks concern:** `uv run pre-commit run --all-files` at Task 9 will catch import issues that pytest might miss (e.g., unused import warnings, isort violations from reordering imports).

**Alembic migration check:** Task 9 includes `uv run alembic -c src/orchestrator/db/migrations/ upgrade head` (or equivalent). This verifies that Alembic's `env.py` import updates worked. If `agents/models.py` was missed in `env.py` (Phase 6 scenario), this will fail here.

---

## Failure Modes Summary

| ID | Severity | Failure Mode | Affected Tasks | Mitigation |
|----|----------|-------------|----------------|------------|
| F1 | **CRITICAL** | `db/recovery.py` and `db/recovery/` cannot coexist — package shadows flat file immediately, breaking 4 integration tests and 1 script | Task 3 | Delete `db/recovery.py` or populate `db/recovery/__init__.py` with re-exports at directory creation time; do not defer deletion to Task 8 |
| F2 | **HIGH** | `scripts/` directory callers (`restore_from_journal.py`, `seed_db.py`, `worker.py`) not listed in Task 6 — Task 9 final grep will catch them but Task 6 checklist will be incomplete | Task 6 | Add scripts/ file list to Task 6 |
| F3 | **HIGH** | If Phase 6 ran before Phase 8, `src/orchestrator/agents/models.py` no longer exists at that path — Task 6 will attempt to edit a non-existent file | Task 6 | Document Phase 6 dependency; update agents import path conditionally based on Phase 6 execution status |
| F4 | **HIGH** | `migrations/env.py` also imports `orchestrator.agents.models` (not mentioned in Task 5) — if Phase 6 ran first, Alembic migrations will fail | Task 5 | Add conditional update for `agents.models` import in `env.py` |
| F5 | **MEDIUM** | `resolve_default_journal_path_from_session` listed in `__init__.py` exports — must verify it exists in `event_journal.py` before including | Task 8 | Grep `event_journal.py` for this function name before writing `__init__.py` |
| F6 | **MEDIUM** | conftest files in `tests/integration/` and `tests/unit/` not explicitly listed in Task 7 — may be missed if they contain `orchestrator.db.*` sub-path imports | Task 7 | Run Task 1's audit grep restricted to `tests/` and diff against Task 7's list before starting updates |
| F7 | **LOW** | `PendingExpansionRequestModel` — step already warns about this; migration exists but class does not; must not be included in `__init__.py` | Task 8 | Already called out in step; verify before writing __init__.py ✓ |
| F8 | **LOW** | Lazy/deferred imports in `workflow/signals.py`, `workflow/service.py`, and `runners/executor.py` may require function-level import updates that a simple sed replacement would miss | Task 6 | Post-edit per-file grep check (`grep "from orchestrator\.db\."`) catches these |

---

## Hardening Actions

### H1 (Critical): Resolve Task 3 Package/Module Conflict

**Before creating `db/recovery/`**, either:
- (Preferred) Update all `from orchestrator.db.recovery import ...` callers in both `src/` and `tests/` and `scripts/` FIRST, then delete `db/recovery.py` in the same commit as creating `db/recovery/`, or
- Create `db/recovery/__init__.py` with explicit re-exports of `replay_events` and `RECOVERY_MATRIX` (temporary shims allowed only if deleted in Task 8)

The step's current instruction to "not delete flat files until Task 8" is **not applicable** to `db/recovery.py` due to the naming conflict.

### H2: Expand Task 6 to Cover scripts/

Add to Task 6's implementation plan:

```
**Files in scripts/ using orchestrator.db.*:**
- scripts/restore_from_journal.py: lazy imports of parse_journal_timestamp, RunRepository, replay_events
- scripts/seed_db.py: create_engine, create_session_factory, init_db, EventStore
- scripts/worker.py: create_engine, create_session_factory, init_db, RunRepository
```

### H3: Declare Phase 6 Ordering Constraint

Add to Task 5 and Task 6:

> **Phase ordering note:** If Phase 6 (agents/ → runners/ absorption) has already run, `agents/models.py` is at `runners/profiles/models.py`. Update imports in that location instead. Also update `migrations/env.py`'s `import orchestrator.agents.models` to `import orchestrator.runners.profiles.models`.

### H4: Pre-flight Check in Task 7

Before starting Task 7 updates, run:
```bash
grep -rn "from orchestrator\.db\." tests/ --include="*.py" | grep -v "__pycache__" | wc -l
```
Then diff the file list against Task 7's enumeration to catch any files added after the step was written (especially conftest files).

### H5: Verify `resolve_default_journal_path_from_session` Exists

In Task 8, before writing `__init__.py`, verify:
```bash
grep "def resolve_default_journal_path_from_session" src/orchestrator/db/event_journal.py
```
Include in `__init__.py` only if this grep returns a match.

---

## Assumptions Verified Against Actual Codebase

| Assumption in Step | Actual Status |
|-------------------|---------------|
| `db/__init__.py` is essentially empty | ✓ Confirmed (only docstring) |
| `db/base.py` has no orchestrator.db imports | ✓ Confirmed |
| `db/recovery.py` has no orchestrator.db imports | ✓ Confirmed (imports from orchestrator.state only) |
| `GradeSnapshotItem` has multiple consumers outside db/ | ✓ Confirmed (5+ consumers) |
| migration version files have no orchestrator imports | ✓ Confirmed (23 files, zero matches) |
| `PendingExpansionRequestModel` absent from models.py | ✓ Confirmed |
| `recover_run_state` function exists as alias | Not found — function does not exist in recovery.py. Not a concern for exports. |
| `workflow/runtime.py` and `workflow/signals.py` exist as flat files | ✓ Confirmed (Phase 7 has not run yet) |
| `agents/models.py` at `src/orchestrator/agents/models.py` | Depends on Phase 6 execution status |

---

## Execution Order Recommendation

Given the naming conflict, the safest execution order within Step 8 is:

1. **Task 1** (audit — read only)
2. **Task 2** (create orm/ — safe, no naming conflict)
3. **Task 4** (create access/ — safe, new namespace)
4. **Tasks 6+7+scripts combined**: Update ALL callers of `orchestrator.db.recovery.*` to `from orchestrator.db import ...`
5. **Task 3** (create recovery/ AND delete `db/recovery.py` in same operation)
6. **Task 5** (update alembic env.py)
7. **Remaining Task 6+7** items (non-recovery sub-path imports)
8. **Task 8** (update `db/__init__.py`, delete remaining 8 flat files)
9. **Task 9** (full verification)

This ordering eliminates the window where `db/recovery.py` and `db/recovery/` coexist.
