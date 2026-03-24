# Step 8: Restructure db/ Internals

Reorganize `db/` from a flat set of 9 files into three sub-packages — `orm/`, `access/`, and `recovery/` — that mirror the architectural layering: ORM definitions, repository access, and crash-recovery infrastructure. No behavioral changes occur; this is a pure file-movement and import-path update. External callers are migrated from sub-path imports (e.g. `from orchestrator.db.connection import init_db`) to top-level imports via `db/__init__.py` (e.g. `from orchestrator.db import init_db`).

> **Note on the step plan's "zero external changes" claim:** The original step plan states "Zero changes to any file outside `db/`". This is not achievable without shims. External callers use sub-path imports (`from orchestrator.db.connection import X`, `from orchestrator.db.repositories import X`, etc.) which break when the flat files are removed. Since shims are forbidden, external callers must be updated. All changes are purely mechanical import-path replacements — no logic changes.

> **GradeSnapshotItem stays in `state/models.py`:** The architecture doc earmarks `GradeSnapshotItem` for `db/recovery/`, citing it as "used only by recovery code." The actual codebase contradicts this: it is also used in `workflow/transitions.py`, `db/repositories.py`, and `db/repositories.py`. Moving it would require touching non-db files and risks circular imports (`state` ← `db/recovery` would invert the layer dependency). `GradeSnapshotItem` is left in `state/models.py`.

## Intent Verification

**Original Intent**: Phase 8 of the module consolidation plan — restructure `db/` internals into `orm/`, `access/`, and `recovery/` sub-packages with all public symbols accessible via `from orchestrator.db import X`, leaving the external interface unchanged in terms of symbols.

**Functionality to Produce**:
- `db/orm/` sub-package containing `base.py` and `models.py`
- `db/access/` sub-package containing `connection.py`, `repositories.py`, `event_store.py`
- `db/recovery/` sub-package containing `event_journal.py`, `journal_replay.py`, `recovery.py`, `backup.py`
- `db/__init__.py` re-exports every previously-flat-file public symbol so callers can use `from orchestrator.db import X`
- All external callers updated to `from orchestrator.db import X` top-level imports
- Old flat files (`base.py`, `models.py`, `connection.py`, `repositories.py`, `event_store.py`, `event_journal.py`, `journal_replay.py`, `recovery.py`, `backup.py`) deleted from `db/` root
- Alembic `migrations/env.py` updated to use new sub-paths

**Final Verification Criteria**:
- All backend unit and integration tests pass
- All frontend tests pass
- `ls src/orchestrator/db/*.py` shows only `__init__.py` (no flat files remain)
- `grep -r "from orchestrator\.db\." src/ tests/ scripts/ alembic/ --include="*.py"` returns only results inside `src/orchestrator/db/` itself (plus `db/migrations/env.py`)
- `uv run python -c "from orchestrator.db import RunModel, init_db, RunRepository, EventStore, replay_events; print('ok')"` succeeds
- `uv run alembic -c src/orchestrator/db/migrations/ upgrade head` succeeds (or equivalent alembic check)
- No shim or re-export files remain at old flat paths

---

## Task 1: Audit — Build Public Symbol Map

**Description**:
Before touching any file, build the definitive map of every public symbol exported from each flat file in `db/`. This map drives Tasks 5–7 (import updates). It also confirms which symbols must appear in the new `db/__init__.py`.

**Implementation Plan (Do These Steps)**

- [ ] Enumerate all external callers of `orchestrator.db.*` sub-paths by running:
```bash
grep -rn "from orchestrator\.db\." src/ tests/ scripts/ \
  --include="*.py" \
  | grep -v "src/orchestrator/db/" \
  | grep -v "__pycache__" \
  | sort -t: -k1,1
```
Record the output — it establishes the complete set of files that need import updates in Tasks 6–7.

- [ ] Enumerate every public symbol (classes, functions, constants) used from each flat file:
```bash
grep -rn "from orchestrator\.db\." src/ tests/ scripts/ \
  --include="*.py" \
  | grep -v "src/orchestrator/db/" \
  | grep -v "__pycache__" \
  | sed 's/.*from orchestrator\.db\.\([^ ]*\) import \(.*\)/\1 → \2/' \
  | sort -u
```

- [ ] Record the six migration files' internal imports:
```bash
grep -n "from orchestrator\|import orchestrator" \
  src/orchestrator/db/migrations/env.py \
  src/orchestrator/db/migrations/versions/*.py \
  | grep -v "__pycache__"
```

- [ ] Confirm `GradeSnapshotItem` has multiple consumers outside `db/`:
```bash
grep -rn "GradeSnapshotItem" src/ tests/ --include="*.py" \
  | grep -v "__pycache__"
```
Expected: lines in `state/models.py` (definition), `workflow/transitions.py`, `db/recovery.py`, `db/repositories.py`.

**Constraints**:
- No file changes in this task. Read-only audit only.

**Functionality (Expected Outcomes)**:
- [ ] A complete list of files needing import updates is established
- [ ] Every public symbol per flat file is known
- [ ] Alembic import paths are known
- [ ] GradeSnapshotItem has multiple consumers confirmed → it stays in `state/models.py`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "from orchestrator\.db\." src/ tests/ --include="*.py" | grep -v "src/orchestrator/db/" | grep -v "__pycache__" | wc -l` produces a non-zero line count (confirms callers exist)
- [ ] `grep -n "GradeSnapshotItem" src/orchestrator/workflow/transitions.py src/orchestrator/db/repositories.py src/orchestrator/db/recovery.py` all return matches (confirms multiple consumers)

---

## Task 2: Create db/orm/ Sub-Package

**Description**:
Create `db/orm/` with `base.py` and `models.py`. These are the SQLAlchemy declarative base and all ORM model class definitions. The old flat files (`db/base.py`, `db/models.py`) are NOT deleted yet; they remain so existing imports continue to work while the new sub-package is populated.

**Implementation Plan (Do These Steps)**

- [ ] Create the sub-package directory and `__init__.py`:
```bash
mkdir -p src/orchestrator/db/orm
```
```python
# src/orchestrator/db/orm/__init__.py
"""ORM base and model definitions."""
```

- [ ] Create `src/orchestrator/db/orm/base.py` by copying the content of `db/base.py` verbatim. No import changes needed (`base.py` has no `orchestrator.db` imports):
```bash
cp src/orchestrator/db/base.py src/orchestrator/db/orm/base.py
```

- [ ] Create `src/orchestrator/db/orm/models.py` by copying the content of `db/models.py` and updating its one internal import:

  Current line in `db/models.py`:
  ```python
  from orchestrator.db.base import Base
  ```
  New in `src/orchestrator/db/orm/models.py`:
  ```python
  from orchestrator.db.orm.base import Base
  ```
  All other imports in `models.py` are from `sqlalchemy` and `dataclasses` — no changes.

**Constraints**:
- Do not delete `db/base.py` or `db/models.py`.
- Do not update any external callers yet.
- `db/orm/models.py` must not import from `db/access/` or `db/recovery/` (ORM models have no upward dependency).

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/db/orm/__init__.py` exists
- [ ] `src/orchestrator/db/orm/base.py` exports `Base`
- [ ] `src/orchestrator/db/orm/models.py` exports all ORM model classes: `AttemptRecord`, `RunModel`, `StepModel`, `TaskModel`, `AttemptModel`, `EventModel`, `ClarificationRequestModel`, `RunnerProfileDefaultModel`, `ReplayCheckpointModel`, `PendingSignalModel`, `ClarificationResponseModel`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.db.orm.base import Base; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.db.orm.models import RunModel, EventModel, RunnerProfileDefaultModel; print('ok')"` succeeds
- [ ] `grep "from orchestrator\.db\.base" src/orchestrator/db/orm/models.py` returns zero results (uses `db.orm.base` instead)

---

## Task 3: Create db/recovery/ Sub-Package

**Description**:
Create `db/recovery/` with the four crash-recovery files: `event_journal.py`, `journal_replay.py`, `recovery.py`, and `backup.py`. Create this sub-package before `access/` because `access/event_store.py` will import from `db.recovery.event_journal`.

The old flat files are NOT deleted yet.

**Implementation Plan (Do These Steps)**

- [ ] Create the sub-package directory and `__init__.py`:
```bash
mkdir -p src/orchestrator/db/recovery
```
```python
# src/orchestrator/db/recovery/__init__.py
"""Crash-recovery infrastructure: event journal, replay, and backup."""
```

- [ ] Create `src/orchestrator/db/recovery/event_journal.py` by copying `db/event_journal.py` verbatim. No `orchestrator.db` imports exist in `event_journal.py` — only `aiofiles`, `sqlalchemy`, and stdlib.
```bash
cp src/orchestrator/db/event_journal.py src/orchestrator/db/recovery/event_journal.py
```

- [ ] Create `src/orchestrator/db/recovery/backup.py` by copying `db/backup.py` verbatim. `backup.py` has no `orchestrator.db` imports.
```bash
cp src/orchestrator/db/backup.py src/orchestrator/db/recovery/backup.py
```

- [ ] Create `src/orchestrator/db/recovery/recovery.py` by copying `db/recovery.py`. Update its one `orchestrator.db` import:

  Current:
  ```python
  from orchestrator.state.models import Attempt, GradeSnapshotItem, HumanApproval, Run
  ```
  This imports from `orchestrator.state`, not `orchestrator.db` — **no change needed**. `recovery.py` has no `orchestrator.db` imports. Copy verbatim:
```bash
cp src/orchestrator/db/recovery.py src/orchestrator/db/recovery/recovery.py
```

- [ ] Create `src/orchestrator/db/recovery/journal_replay.py` by copying `db/journal_replay.py` and updating its three internal `orchestrator.db.*` imports:

  Current lines in `db/journal_replay.py`:
  ```python
  from orchestrator.db.event_journal import parse_journal_timestamp, read_journal_entries
  from orchestrator.db.recovery import replay_events
  from orchestrator.db.repositories import CheckpointRepository, RunRepository
  ```
  New in `src/orchestrator/db/recovery/journal_replay.py`:
  ```python
  from orchestrator.db.recovery.event_journal import parse_journal_timestamp, read_journal_entries
  from orchestrator.db.recovery.recovery import replay_events
  from orchestrator.db.access.repositories import CheckpointRepository, RunRepository
  ```
  Note: `db/access/repositories.py` does not exist yet, but the old `db/repositories.py` is still present. The new file won't be imported until Task 7 (when old flat files are deleted and `__init__.py` is updated), so this forward reference is safe.

**Constraints**:
- Do not delete any flat files from `db/` root.
- `db/recovery/recovery.py` must not import from `db/recovery/` siblings (it already imports from `state/models`, not db — verify before copying).

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/db/recovery/__init__.py` exists
- [ ] `src/orchestrator/db/recovery/event_journal.py` exports `JsonlEventJournal`, `make_journal_entry`, `read_journal_entries`, `parse_journal_timestamp`, `resolve_default_journal_path`, `resolve_default_journal_path_from_session`
- [ ] `src/orchestrator/db/recovery/recovery.py` exports `replay_events`, `RECOVERY_MATRIX`
- [ ] `src/orchestrator/db/recovery/backup.py` exports `BackupMetadata`, `BackupError`, `create_backup`, `restore_backup`, `scan_max_sequence`
- [ ] `src/orchestrator/db/recovery/journal_replay.py` internal imports reference `db.recovery.*` and `db.access.*`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.db.recovery.event_journal import JsonlEventJournal, resolve_default_journal_path; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.db.recovery.recovery import replay_events; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.db.recovery.backup import create_backup, BackupError, scan_max_sequence; print('ok')"` succeeds
- [ ] `grep "from orchestrator\.db\.event_journal\|from orchestrator\.db\.recovery import\|from orchestrator\.db\.repositories" src/orchestrator/db/recovery/journal_replay.py` returns zero results (all updated to sub-paths)

---

## Task 4: Create db/access/ Sub-Package

**Description**:
Create `db/access/` with `connection.py`, `repositories.py`, and `event_store.py`. These files depend on `db/orm/` and `db/recovery/` sub-packages (already created), so they can import from the new locations.

The old flat files are NOT deleted yet.

**Implementation Plan (Do These Steps)**

- [ ] Create the sub-package directory and `__init__.py`:
```bash
mkdir -p src/orchestrator/db/access
```
```python
# src/orchestrator/db/access/__init__.py
"""Database connection management and repository access."""
```

- [ ] Create `src/orchestrator/db/access/connection.py` by copying `db/connection.py` and updating its one internal import:

  Current:
  ```python
  from orchestrator.db.base import Base
  ```
  New:
  ```python
  from orchestrator.db.orm.base import Base
  ```
  Also update the `_MIGRATIONS_DIR` path reference — `connection.py` uses `Path(__file__).parent / "migrations"`. After moving to `db/access/`, this path resolves to `db/access/migrations/` which does not exist. Update to:
  ```python
  _MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
  ```

- [ ] Create `src/orchestrator/db/access/repositories.py` by copying `db/repositories.py` and updating its one internal import:

  Current:
  ```python
  from orchestrator.db.models import (
      ...
  )
  ```
  New:
  ```python
  from orchestrator.db.orm.models import (
      ...
  )
  ```
  Additionally, `repositories.py` imports `GradeSnapshotItem` from `orchestrator.state.models` — no change needed there (it stays in `state/`).

- [ ] Create `src/orchestrator/db/access/event_store.py` by copying `db/event_store.py` and updating its two internal imports:

  Current:
  ```python
  from orchestrator.db.event_journal import (
      JsonlEventJournal,
      make_journal_entry,
  )
  from orchestrator.db.models import EventModel
  ```
  New:
  ```python
  from orchestrator.db.recovery.event_journal import (
      JsonlEventJournal,
      make_journal_entry,
  )
  from orchestrator.db.orm.models import EventModel
  ```

**Constraints**:
- Do not delete any flat files from `db/` root.
- Verify `_MIGRATIONS_DIR` resolves correctly after the path parent change.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/db/access/__init__.py` exists
- [ ] `db/access/connection.py` exports `create_engine`, `create_session_factory`, `init_db`
- [ ] `db/access/repositories.py` exports `RunRepository`, `CheckpointRepository`
- [ ] `db/access/event_store.py` exports `EventStore`
- [ ] `db/access/connection.py` uses `from orchestrator.db.orm.base import Base`
- [ ] `db/access/connection.py` `_MIGRATIONS_DIR` points to `db/migrations/` (two levels up from `access/`)

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.db.access.connection import create_engine, init_db; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.db.access.repositories import RunRepository, CheckpointRepository; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.db.access.event_store import EventStore; print('ok')"` succeeds
- [ ] `grep "from orchestrator\.db\.base\|from orchestrator\.db\.models\|from orchestrator\.db\.event_journal" src/orchestrator/db/access/*.py` returns zero results

---

## Task 5: Update Alembic env.py and db/migrations/ Imports

**Description**:
`db/migrations/env.py` imports directly from `orchestrator.db.base` and `orchestrator.db.models`. These flat files will be deleted in Task 7, so `env.py` must be updated to use the new `orm/` sub-package paths. The version migration files do not import from `orchestrator.db` — this is confirmed by the audit in Task 1.

**Implementation Plan (Do These Steps)**

- [ ] Confirm version migration files have no `orchestrator.db` imports:
```bash
grep -rn "from orchestrator\|import orchestrator" \
  src/orchestrator/db/migrations/versions/ \
  --include="*.py" | grep -v "__pycache__"
```
Expected: zero results.

- [ ] Update `src/orchestrator/db/migrations/env.py` — two import lines:

  Current:
  ```python
  from orchestrator.db.base import Base
  import orchestrator.db.models as _models  # noqa: F401
  ```
  New:
  ```python
  from orchestrator.db.orm.base import Base
  import orchestrator.db.orm.models as _models  # noqa: F401
  ```

**Constraints**:
- Only `migrations/env.py` is changed. No other migration file is touched.
- The comment `_models_loaded = _models` and `_agent_models_loaded = _agent_models` lines are left exactly as-is — only the import paths change.

**Side Effects**:
- `env.py` now requires the new `orm/` sub-package to exist (created in Task 2). Since Tasks 2–4 must complete before this task, that is already true.

**Functionality (Expected Outcomes)**:
- [ ] `migrations/env.py` imports `Base` from `orchestrator.db.orm.base`
- [ ] `migrations/env.py` imports models from `orchestrator.db.orm.models`
- [ ] No migration version file imports from `orchestrator.db.*`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "from orchestrator\.db\.base\|import orchestrator\.db\.models" src/orchestrator/db/migrations/env.py` returns zero results
- [ ] `grep "from orchestrator\.db\.orm\." src/orchestrator/db/migrations/env.py` returns exactly 2 matches
- [ ] `uv run python -c "import orchestrator.db.migrations.env"` — or equivalently, the alembic migration check passes (see Task 8 for full check)

---

## Task 6: Update All External src/ Callers

**Description**:
Update every file in `src/orchestrator/` (outside `db/`) that imports from old `orchestrator.db.*` sub-paths. The changes are purely mechanical: each `from orchestrator.db.X import Y` becomes `from orchestrator.db import Y`. The old flat files still exist during this task, so the codebase remains importable throughout.

**Implementation Plan (Do These Steps)**

The complete list of src/ files outside db/ that need updating, grouped by old path used:

**Files using `orchestrator.db.base`:**
- `src/orchestrator/agents/models.py`: `from orchestrator.db.base import Base` → `from orchestrator.db import Base`

**Files using `orchestrator.db.models`:**
- `src/orchestrator/api/routers/repos.py`: `from orchestrator.db.models import RunModel` → `from orchestrator.db import RunModel`
- `src/orchestrator/api/routers/runners.py`: `from orchestrator.db.models import RunnerProfileDefaultModel` → `from orchestrator.db import RunnerProfileDefaultModel`
- `src/orchestrator/runners/execution/attempt_store.py`: `from orchestrator.db.models import RunModel` → `from orchestrator.db import RunModel`
- `src/orchestrator/runners/executor.py`: `from orchestrator.db.models import RunnerProfileDefaultModel` → `from orchestrator.db import RunnerProfileDefaultModel`
- `src/orchestrator/workflow/runtime.py`: `from orchestrator.db.models import RunModel` → `from orchestrator.db import RunModel`
- `src/orchestrator/workflow/signals.py`: `from orchestrator.db.models import PendingSignalModel` (two occurrences, likely lazy imports inside functions) → `from orchestrator.db import PendingSignalModel`
- `src/orchestrator/workflow/service.py`: `from orchestrator.db.models import ClarificationRequestModel` (lazy import) → `from orchestrator.db import ClarificationRequestModel`

**Files using `orchestrator.db.connection`:**
- `src/orchestrator/api/app.py`: `from orchestrator.db.connection import create_engine, create_session_factory, init_db` → `from orchestrator.db import create_engine, create_session_factory, init_db`
- `src/orchestrator/cli/runs.py`: `from orchestrator.db.connection import create_engine, create_session_factory, init_db` → `from orchestrator.db import create_engine, create_session_factory, init_db`

**Files using `orchestrator.db.repositories`:**
- `src/orchestrator/api/app.py`: multiple lazy imports `from orchestrator.db.repositories import RunRepository` (at least 4 occurrences) → `from orchestrator.db import RunRepository`
- `src/orchestrator/api/deps.py`: `from orchestrator.db.repositories import RunRepository` → `from orchestrator.db import RunRepository`
- `src/orchestrator/api/routers/clarifications.py`: `from orchestrator.db.repositories import RunRepository` → `from orchestrator.db import RunRepository`
- `src/orchestrator/api/routers/runs.py`: `from orchestrator.db.repositories import RunRepository` → `from orchestrator.db import RunRepository`
- `src/orchestrator/api/routers/tasks.py`: `from orchestrator.db.repositories import RunRepository` → `from orchestrator.db import RunRepository`
- `src/orchestrator/cli/runs.py`: `from orchestrator.db.repositories import CheckpointRepository, RunRepository` → `from orchestrator.db import CheckpointRepository, RunRepository`
- `src/orchestrator/runners/execution/attempt_store.py`: `from orchestrator.db.repositories import RunRepository` (multiple occurrences) → `from orchestrator.db import RunRepository`
- `src/orchestrator/runners/executor.py`: `from orchestrator.db.repositories import RunRepository` (lazy) → `from orchestrator.db import RunRepository`
- `src/orchestrator/runners/monitor.py`: `from orchestrator.db.repositories import RunRepository` (lazy, multiple) → `from orchestrator.db import RunRepository`
- `src/orchestrator/workflow/runtime.py`: `from orchestrator.db.repositories import RunRepository` (lazy) → `from orchestrator.db import RunRepository`
- `src/orchestrator/workflow/service.py`: `from orchestrator.db.repositories import RunRepository` → `from orchestrator.db import RunRepository`

**Files using `orchestrator.db.event_store`:**
- `src/orchestrator/api/app.py`: lazy imports `from orchestrator.db.event_store import EventStore` → `from orchestrator.db import EventStore`
- `src/orchestrator/api/deps.py`: `from orchestrator.db.event_store import EventStore` → `from orchestrator.db import EventStore`
- `src/orchestrator/api/routers/runs.py`: `from orchestrator.db.event_store import EventStore` (both lazy and top-level) → `from orchestrator.db import EventStore`
- `src/orchestrator/runners/execution/event_broadcaster.py`: lazy `from orchestrator.db.event_store import EventStore` → `from orchestrator.db import EventStore`
- `src/orchestrator/runners/executor.py`: lazy `from orchestrator.db.event_store import EventStore` → `from orchestrator.db import EventStore`
- `src/orchestrator/runners/monitor.py`: lazy `from orchestrator.db.event_store import EventStore` → `from orchestrator.db import EventStore`
- `src/orchestrator/workflow/event_logger.py`: `from orchestrator.db.event_store import EventStore` → `from orchestrator.db import EventStore`
- `src/orchestrator/workflow/service.py`: `from orchestrator.db.event_store import EventStore` → `from orchestrator.db import EventStore`

**Files using `orchestrator.db.event_journal`, `orchestrator.db.journal_replay`, `orchestrator.db.backup`:**
- `src/orchestrator/cli/db.py`:
  - `from orchestrator.db.backup import BackupError, create_backup, restore_backup` → `from orchestrator.db import BackupError, create_backup, restore_backup`
  - `from orchestrator.db.event_journal import resolve_default_journal_path` → `from orchestrator.db import resolve_default_journal_path`
- `src/orchestrator/cli/runs.py`:
  - `from orchestrator.db.backup import scan_max_sequence` (lazy) → `from orchestrator.db import scan_max_sequence`
  - `from orchestrator.db.event_journal import resolve_default_journal_path` → `from orchestrator.db import resolve_default_journal_path`
  - `from orchestrator.db.journal_replay import replay_journal_to_repository` → `from orchestrator.db import replay_journal_to_repository`

- [ ] Apply all changes above. For each file, open and replace sub-path imports with top-level imports. After updating each file, do a quick sanity check:
```bash
grep "from orchestrator\.db\." <file> | grep -v "^#"
```
This should return zero results when the file is fully updated.

- [ ] After updating all files, confirm no sub-path imports remain in src/ outside of db/:
```bash
grep -rn "from orchestrator\.db\." src/orchestrator/ \
  --include="*.py" \
  | grep -v "src/orchestrator/db/" \
  | grep -v "__pycache__"
```
Expected: zero results.

**Constraints**:
- Only import line changes — no logic, variable, or function body changes.
- Old flat files (`db/base.py`, `db/models.py`, etc.) still exist, so the codebase is importable throughout.
- Do not update test files in this task (that is Task 7).

**Functionality (Expected Outcomes)**:
- [ ] All `src/orchestrator/` files outside `db/` use `from orchestrator.db import X` form
- [ ] No `from orchestrator.db.base`, `from orchestrator.db.models`, `from orchestrator.db.connection`, etc. remain in `src/orchestrator/` outside `db/`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "from orchestrator\.db\." src/orchestrator/ --include="*.py" | grep -v "src/orchestrator/db/" | grep -v "__pycache__"` returns zero results
- [ ] `uv run python -c "from orchestrator.api.app import app; print('ok')"` succeeds (app-level imports resolve)
- [ ] `uv run python -c "from orchestrator.cli.runs import cli; print('ok')"` succeeds

---

## Task 7: Update All External Test Callers

**Description**:
Update all test files that import from old `orchestrator.db.*` sub-paths, applying the same mechanical transformation as Task 6. Test files are separated here to keep each task scope manageable.

**Implementation Plan (Do These Steps)**

The test files requiring updates, grouped by import:

**`orchestrator.db.base`:**
- `tests/integration/test_parity_recovery.py`
- `tests/integration/test_parity_replay.py`
- `tests/unit/test_agent_resolution.py`
- `tests/unit/test_agent_service.py`

**`orchestrator.db.connection`:**
- `tests/e2e/conftest.py`
- `tests/integration/test_agent_executor.py`
- `tests/integration/test_full_persistence.py`
- `tests/integration/test_idempotency.py`
- `tests/integration/test_mcp_server.py`
- `tests/integration/test_mcp_sse.py`
- `tests/integration/test_mcp_tools.py`
- `tests/integration/test_merge_readiness.py`
- `tests/integration/test_mock_agent_workflow.py`
- `tests/integration/test_parity_fan_out.py`
- `tests/integration/test_parity_fan_out_replay.py`
- `tests/integration/test_parity_linear.py`
- `tests/integration/test_parity_pause_resume.py`
- `tests/integration/test_parity_recovery.py`
- `tests/integration/test_parity_replay.py`
- `tests/integration/test_parity_revision.py`
- `tests/integration/test_parity_skip.py`
- `tests/integration/test_project_routines.py`
- `tests/integration/test_prompt_agent_system_prompt.py`
- `tests/integration/test_prune_api.py`
- `tests/integration/test_repeat_for_edge_cases.py`
- `tests/integration/test_repositories.py`
- `tests/integration/test_review_api.py`
- `tests/integration/test_review_merge_readiness.py`
- `tests/integration/test_review_test_api.py`
- `tests/integration/test_review_test_runner.py`
- `tests/integration/test_scaffolding.py`
- `tests/integration/test_skip_step_api.py`
- `tests/integration/test_user_managed_agent.py`
- `tests/integration/test_verifier_model_pinning.py`
- `tests/integration/test_workflow_service.py`
- `tests/unit/test_agent_monitor.py`
- `tests/unit/test_executor_codex_lifecycle.py`
- `tests/unit/test_step_auto_verify.py`

**`orchestrator.db.repositories`:**
- `tests/integration/test_fan_out.py`
- `tests/integration/test_full_persistence.py`
- `tests/integration/test_merge_readiness.py`
- `tests/integration/test_parity_fan_out_replay.py`
- `tests/integration/test_parity_replay.py`
- `tests/integration/test_repositories.py`
- `tests/integration/test_review_merge_readiness.py`
- `tests/integration/test_scaffolding.py`
- `tests/unit/test_agent_monitor.py`
- `tests/unit/test_executor_codex_lifecycle.py`

**`orchestrator.db.event_store`:**
- `tests/integration/test_agent_executor.py`
- `tests/integration/test_full_persistence.py`
- `tests/integration/test_parity_replay.py`
- `tests/integration/test_scaffolding.py`
- `tests/integration/test_workflow_service.py`
- `tests/unit/test_agent_monitor.py`

**`orchestrator.db.recovery`:**
- `tests/integration/test_parity_replay.py`

**`orchestrator.db.event_journal`:**
- `tests/integration/test_parity_fan_out_replay.py`

**`orchestrator.db.journal_replay`:**
- `tests/integration/test_parity_fan_out_replay.py`

**`orchestrator.db.backup`:**
- `tests/unit/test_backup.py`

- [ ] For each test file listed above, replace sub-path imports with top-level `from orchestrator.db import X`. The transformation rules are the same as Task 6.

- [ ] After updating all test files, confirm no sub-path imports remain in tests/:
```bash
grep -rn "from orchestrator\.db\." tests/ \
  --include="*.py" \
  | grep -v "__pycache__"
```
Expected: zero results.

**Constraints**:
- Only import line changes — no test logic changes.
- Old flat files still exist so tests can run at any point during this task.

**Functionality (Expected Outcomes)**:
- [ ] All test files use `from orchestrator.db import X` form
- [ ] No `from orchestrator.db.connection`, `from orchestrator.db.repositories`, etc. remain in any test file

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "from orchestrator\.db\." tests/ --include="*.py" | grep -v "__pycache__"` returns zero results
- [ ] `uv run pytest tests/unit/test_backup.py tests/integration/test_repositories.py -v` passes (confirms test imports work with top-level imports even before `__init__.py` is updated — old flat files still resolve)

---

## Task 8: Update db/__init__.py and Delete Old Flat Files

**Description**:
Update `db/__init__.py` to re-export every public symbol that was previously importable via sub-paths. Then delete all old flat files. After this task, `from orchestrator.db import X` is the only supported import form, and all old sub-path imports (`from orchestrator.db.connection import X`, etc.) are gone.

**Implementation Plan (Do These Steps)**

- [ ] Confirm all external callers have been updated (Tasks 6–7 complete):
```bash
grep -rn "from orchestrator\.db\." src/ tests/ scripts/ \
  --include="*.py" \
  | grep -v "src/orchestrator/db/" \
  | grep -v "__pycache__"
```
Must return zero lines. If any lines appear, stop and fix in Tasks 6 or 7.

- [ ] Rewrite `src/orchestrator/db/__init__.py` to export all public symbols:

```python
"""Database layer for persistent storage.

Public interface — all symbols importable as ``from orchestrator.db import X``.
"""

# ORM base and models
from orchestrator.db.orm.base import Base
from orchestrator.db.orm.models import (
    AttemptModel,
    AttemptRecord,
    ClarificationRequestModel,
    ClarificationResponseModel,
    EventModel,
    PendingSignalModel,
    ReplayCheckpointModel,
    RunModel,
    RunnerProfileDefaultModel,
    StepModel,
    TaskModel,
)

# Connection management
from orchestrator.db.access.connection import (
    create_engine,
    create_session_factory,
    init_db,
)

# Repositories
from orchestrator.db.access.repositories import (
    CheckpointRepository,
    RunRepository,
)

# Event store
from orchestrator.db.access.event_store import EventStore

# Event journal
from orchestrator.db.recovery.event_journal import (
    JsonlEventJournal,
    make_journal_entry,
    parse_journal_timestamp,
    read_journal_entries,
    resolve_default_journal_path,
    resolve_default_journal_path_from_session,
)

# Journal replay
from orchestrator.db.recovery.journal_replay import (
    JournalReplaySummary,
    replay_journal_to_repository,
)

# Event recovery / replay
from orchestrator.db.recovery.recovery import (
    RECOVERY_MATRIX,
    replay_events,
)

# Backup utilities
from orchestrator.db.recovery.backup import (
    BackupError,
    BackupMetadata,
    create_backup,
    restore_backup,
    scan_max_sequence,
)

__all__ = [
    # orm
    "Base",
    "AttemptModel",
    "AttemptRecord",
    "ClarificationRequestModel",
    "ClarificationResponseModel",
    "EventModel",
    "PendingSignalModel",
    "ReplayCheckpointModel",
    "RunModel",
    "RunnerProfileDefaultModel",
    "StepModel",
    "TaskModel",
    # access
    "create_engine",
    "create_session_factory",
    "init_db",
    "CheckpointRepository",
    "RunRepository",
    "EventStore",
    # recovery
    "JsonlEventJournal",
    "make_journal_entry",
    "parse_journal_timestamp",
    "read_journal_entries",
    "resolve_default_journal_path",
    "resolve_default_journal_path_from_session",
    "JournalReplaySummary",
    "replay_journal_to_repository",
    "RECOVERY_MATRIX",
    "replay_events",
    "BackupError",
    "BackupMetadata",
    "create_backup",
    "restore_backup",
    "scan_max_sequence",
]
```

- [ ] Delete the nine old flat files:
```bash
rm src/orchestrator/db/base.py \
   src/orchestrator/db/models.py \
   src/orchestrator/db/connection.py \
   src/orchestrator/db/repositories.py \
   src/orchestrator/db/event_store.py \
   src/orchestrator/db/event_journal.py \
   src/orchestrator/db/journal_replay.py \
   src/orchestrator/db/recovery.py \
   src/orchestrator/db/backup.py
```

- [ ] Confirm only `__init__.py` remains at `db/` root (plus `migrations/`):
```bash
ls src/orchestrator/db/*.py
```
Expected: only `src/orchestrator/db/__init__.py`.

- [ ] Confirm the three sub-packages exist:
```bash
ls src/orchestrator/db/orm/
ls src/orchestrator/db/access/
ls src/orchestrator/db/recovery/
```

**Constraints**:
- Delete exactly the nine listed flat files — nothing else.
- `db/migrations/` directory and its contents are never touched by this deletion step.
- The `__init__.py` must not import `PendingExpansionRequestModel` unless confirmed it exists in `db/orm/models.py` (check during implementation).

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/db/__init__.py` exports all symbols listed in `__all__`
- [ ] Nine old flat files are deleted from `db/` root
- [ ] `from orchestrator.db import RunModel, init_db, RunRepository, EventStore, replay_events, create_backup` all succeed

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `ls src/orchestrator/db/*.py | grep -v __init__` returns empty (only `__init__.py` at root)
- [ ] `uv run python -c "from orchestrator.db import RunModel, init_db, RunRepository, EventStore, replay_events, BackupError, replay_journal_to_repository; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.db.connection import init_db"` raises `ModuleNotFoundError` (old sub-paths gone)
- [ ] `uv run python -c "from orchestrator.db.repositories import RunRepository"` raises `ModuleNotFoundError` (old sub-paths gone)
- [ ] `git --no-pager diff --stat HEAD` shows deletions of 9 flat files and additions in `orm/`, `access/`, `recovery/`, and `__init__.py`

---

## Task 9: Full Test Suite and Reference Audit

**Description**:
Run the complete test suite and perform exhaustive verification that no stale `orchestrator.db.*` sub-path imports exist anywhere in the repository, all sub-packages import correctly, and no shims remain.

**Implementation Plan (Do These Steps)**

- [ ] Run backend unit tests:
```bash
uv run pytest tests/unit/ -v
```

- [ ] Run backend integration tests:
```bash
uv run pytest tests/integration/ -v
```

- [ ] Run frontend tests:
```bash
cd ui && npx vitest run
```

- [ ] Run the complete sub-path reference audit across all code locations:
```bash
grep -rn "from orchestrator\.db\." src/ tests/ scripts/ \
  --include="*.py" \
  | grep -v "src/orchestrator/db/" \
  | grep -v "__pycache__" \
  || echo "OK: zero stale sub-path refs"
```
Expected: "OK: zero stale sub-path refs" (or zero output lines).

- [ ] Verify `db/` root contains only `__init__.py` and `migrations/`:
```bash
ls src/orchestrator/db/
```
Expected output contains: `__init__.py  access  migrations  orm  recovery`

- [ ] Verify all three sub-packages are importable and contain the expected files:
```bash
uv run python -c "
import orchestrator.db.orm.base
import orchestrator.db.orm.models
import orchestrator.db.access.connection
import orchestrator.db.access.repositories
import orchestrator.db.access.event_store
import orchestrator.db.recovery.event_journal
import orchestrator.db.recovery.journal_replay
import orchestrator.db.recovery.recovery
import orchestrator.db.recovery.backup
print('all sub-packages import OK')
"
```

- [ ] Verify the top-level interface covers all previously-public symbols:
```bash
uv run python -c "
from orchestrator.db import (
    Base, RunModel, StepModel, TaskModel, AttemptModel, EventModel,
    ClarificationRequestModel, RunnerProfileDefaultModel, ReplayCheckpointModel,
    PendingSignalModel, ClarificationResponseModel, AttemptRecord,
    create_engine, create_session_factory, init_db,
    RunRepository, CheckpointRepository,
    EventStore,
    JsonlEventJournal, make_journal_entry, parse_journal_timestamp,
    read_journal_entries, resolve_default_journal_path,
    JournalReplaySummary, replay_journal_to_repository,
    replay_events, RECOVERY_MATRIX,
    BackupError, BackupMetadata, create_backup, restore_backup, scan_max_sequence,
)
print('all symbols importable from orchestrator.db')
"
```

- [ ] Check for stale shim/stub markers:
```bash
grep -r "shim\|stub\|backward.compat\|backward_compat" \
  src/orchestrator/db/ --include="*.py" \
  || echo "OK: no shim markers"
```

- [ ] Run pre-commit hooks:
```bash
uv run pre-commit run --all-files
```

**Functionality (Expected Outcomes)**:
- [ ] All backend unit and integration tests pass
- [ ] All frontend tests pass
- [ ] Zero stale sub-path imports outside `db/`
- [ ] All sub-packages and their files are importable
- [ ] All public symbols accessible via `from orchestrator.db import X`
- [ ] No shim markers in any `db/` file

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -q` exits with code 0
- [ ] `cd ui && npx vitest run` exits with code 0
- [ ] `grep -rn "from orchestrator\.db\." src/ tests/ scripts/ --include="*.py" | grep -v "src/orchestrator/db/" | grep -v "__pycache__"` returns zero lines
- [ ] `ls src/orchestrator/db/*.py` returns only `src/orchestrator/db/__init__.py`
- [ ] `uv run python -c "from orchestrator.db import RunModel, init_db, RunRepository, EventStore, replay_events, BackupError, replay_journal_to_repository; print('ok')"` succeeds
- [ ] `uv run pre-commit run --all-files` exits with code 0
- [ ] `git --no-pager diff --stat HEAD` shows: deletions of 9 flat files in `db/`, additions in `db/orm/`, `db/access/`, `db/recovery/`, and modified `db/__init__.py` and `db/migrations/env.py`
