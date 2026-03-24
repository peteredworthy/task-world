# Step Plan: Restructure db/ Internals

## Purpose

Reorganize `db/` internal files into sub-packages (`orm/`, `access/`, `recovery/`). This separates ORM model definitions from repository access patterns and recovery infrastructure, improving navigability of the ~1,200 LOC module.

## Prerequisites

- None — this phase is independent of other internal restructuring phases.

## Functional Contract

### Inputs

- `db/` flat files: ORM base and model definitions
- `db/` flat files: connection management, repository classes, event store
- `db/` flat files: event journal, journal replay, recovery, backup utilities
- All external imports via `from orchestrator.db import X`

### Outputs

- `db/orm/` sub-package: `base.py`, `models.py` (ORM definitions)
- `db/access/` sub-package: `connection.py`, `repositories.py`, `event_store.py`
- `db/recovery/` sub-package: `event_journal.py`, `journal_replay.py`, `recovery.py`, `backup.py`
- `db/__init__.py` re-exports all public symbols (no external import changes)
- Zero changes to any file outside `db/`

### Error Cases

- **Alembic migration imports break:** Alembic `env.py` or version files may import ORM models directly. Mitigation: check `alembic/env.py` and `alembic/versions/*.py` for `from orchestrator.db` imports; update if they reference internal paths.
- **Repository ↔ ORM circular imports:** Repositories import models; if models reference repositories, circular import occurs. Mitigation: ORM models should have no upward dependency — verify before moving.
- **`GradeSnapshotItem` relocation:** Per architecture doc, `GradeSnapshotItem` moves from `state/models.py` to `db/recovery/` (single consumer). This is a cross-module change. Mitigation: grep verification.

## Tasks

1. Audit all `from orchestrator.db import X` statements to build the public API list.
2. Create `db/orm/` sub-package. Move ORM base and model files.
3. Create `db/access/` sub-package. Move connection, repository, and event store files.
4. Create `db/recovery/` sub-package. Move journal, replay, recovery, and backup files.
   - **CRITICAL (FM21): `db/recovery.py` and `db/recovery/` cannot coexist.** The moment `db/recovery/` is created as a directory, Python will resolve `orchestrator.db.recovery` to the new empty package, shadowing the flat `db/recovery.py` file. All existing `from orchestrator.db.recovery import X` calls will fail immediately (ImportError). **Do NOT create a blank `db/recovery/__init__.py`.**
   - **Required approach:** Populate `db/recovery/__init__.py` with full re-exports at the same time the directory is created, before moving any files out of `db/recovery.py`. The sequence must be:
     1. Read `db/recovery.py` to identify all public symbols (e.g., `replay_events`, `RecoveryManager`, etc.)
     2. Create `db/recovery/` directory with `recovery.py`, `event_journal.py`, `journal_replay.py`, `backup.py` containing the moved content
     3. Write `db/recovery/__init__.py` that re-exports all public symbols from the sub-files
     4. Verify `from orchestrator.db.recovery import replay_events` still works
     5. **Only then** delete the flat `db/recovery.py` file
   - Alternatively: rename `db/recovery.py` → `db/recovery_flat.py`, create `db/recovery/__init__.py` with `from .recovery_flat import *`, then migrate content incrementally.
5. Move `GradeSnapshotItem` from `state/models.py` to `db/recovery/` (if applicable in this phase).
6. Update `db/__init__.py` to re-export all public symbols.
7. Update internal imports within db sub-packages.
   - **Known consumers in scripts/ (FM22):** The `scripts/` directory has files that import from `orchestrator.db` sub-paths directly. Audit these files explicitly:
     - `scripts/restore_from_journal.py`
     - `scripts/seed_db.py`
     - `scripts/worker.py`
     Run: `grep -n "from orchestrator.db" scripts/restore_from_journal.py scripts/seed_db.py scripts/worker.py`
   - **Conditional path for agents/models (FM23):** `src/orchestrator/db/migrations/env.py` imports `orchestrator.agents.models` for Alembic table discovery. **If Phase 6 has already run**, `agents/models.py` will be at `src/orchestrator/runners/profiles/models.py`. Update that import to `orchestrator.runners.profiles.models` in this step. If Phase 6 has not yet run, the import still points to `orchestrator.agents.models` (correct for that state). Check: `ls src/orchestrator/agents/` — if the directory no longer exists, Phase 6 has run.
8. Check and update Alembic imports (`alembic/env.py`, `alembic/versions/*.py`).
   - **FM24:** `src/orchestrator/db/migrations/env.py` imports BOTH `orchestrator.db.base` (for ORM base) AND `orchestrator.agents.models` (for Alembic table discovery of agent-profile models). Task 7 above handles the `agents.models` path. Also verify the `db.base` path: after moving `db/orm/base.py`, ensure env.py references `orchestrator.db.orm.base` (or that `orchestrator.db.base` is still a valid re-export via `db/__init__.py`). Run:
     ```
     grep -n "orchestrator" src/orchestrator/db/migrations/env.py
     ```
     Update all import lines found.
9. Run full test suite. Fix failures.
10. Verify no external import changes needed.

## Verification Approach

### Auto-Verify

- All backend tests pass (`uv run pytest tests/unit/ -v` and `uv run pytest tests/integration/ -v`)
- All frontend tests pass (`cd ui && npx vitest run`)
- No files remain at `db/` root that should be in sub-packages (only `__init__.py`)
- Alembic migrations still apply cleanly (`uv run alembic upgrade head` succeeds)
- Pre-commit hooks pass

### Manual Verification

- Confirm `from orchestrator.db import RunModel` still works (re-export intact)
- Confirm `from orchestrator.db import get_db_session` still works
- Verify Alembic `env.py` imports resolve correctly

## Context & References

- Plan: `docs/module-consolidation/plan.md` — Phase 8 specification
- Architecture: `docs/module-consolidation/architecture.md` — Target `db/` internal structure
- Independent of: Phases 7 and 9 (can run in parallel)
- Risk: ORM model import narrowing happens in Phase 10, not here
