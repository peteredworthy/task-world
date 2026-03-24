# Step 3: Absorb routines/ → config/routines/

Move the `routines/` module into `config/` as a `routines/` sub-package. Routine discovery and loading are configuration concerns — they parse YAML files that define run templates. Grouping them under `config/` reflects their actual role in the architecture.

This step is independent of Phases 2, 4, and 5. It depends only on Phase 0 having established clean layering. The `routines/` files import from `config.models` and `config.enums`, which will become same-package imports after the move — no circular-import risk.

## Intent Verification
**Original Intent**: Plan Phase 3 — Absorb `routines/` → `config/routines/`; architecture doc target `config/` structure with `routines/` sub-package.

**Functionality to Produce**:
- `config/routines/` sub-package containing `errors.py`, `versioning.py`, `loader.py`, `discovery.py`, `__init__.py`
- All ~14 import sites updated from `orchestrator.routines` → `orchestrator.config.routines`
- `routines/` directory deleted entirely — no shims, no re-export files left at old location
- Dead shim `config/loader.py` (no consumers, was re-exporting from `routines.loader`) deleted

**Final Verification Criteria**:
- `grep -r "from orchestrator.routines" src/ tests/ scripts/` returns zero results
- `ls src/orchestrator/routines/` fails (directory does not exist)
- All unit and integration backend tests pass
- All frontend tests pass
- Pre-commit hooks pass

---

## Task 1: Create config/routines/ sub-package

**Description**: Create the new `config/routines/` sub-package by writing all 5 files with internal imports updated from `orchestrator.routines.*` to `orchestrator.config.routines.*`. The files `errors.py` and `versioning.py` have no internal cross-file imports and are copied verbatim. The files `loader.py`, `discovery.py`, and `__init__.py` have internal cross-file imports that must be updated.

**Implementation Plan (Do These Steps)**

The existing `routines/` files remain in place during this task — we are creating parallel copies at the new path. The old files are deleted in Task 3.

- [ ] Create directory `src/orchestrator/config/routines/`

```bash
mkdir -p src/orchestrator/config/routines
```

- [ ] Create `src/orchestrator/config/routines/errors.py` — copy verbatim from `src/orchestrator/routines/errors.py` (no import changes required):

```python
"""Custom exceptions for routine loading."""


class RoutineError(Exception):
    """Base class for routine errors."""


class RoutineNotFoundError(RoutineError):
    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Routine not found: {path}")


class RoutineParseError(RoutineError):
    def __init__(self, path: str, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"Failed to parse routine {path}: {detail}")


class RoutineValidationError(RoutineError):
    def __init__(self, path: str, errors: list[str]) -> None:
        self.path = path
        self.errors = errors
        super().__init__(f"Routine validation failed {path}: {errors}")
```

- [ ] Create `src/orchestrator/config/routines/versioning.py` — copy verbatim from `src/orchestrator/routines/versioning.py` (no import changes required; it only imports from stdlib)

- [ ] Create `src/orchestrator/config/routines/loader.py` — copy from `src/orchestrator/routines/loader.py`, updating the one internal import:

```python
# Change this line:
from orchestrator.routines.errors import (
# To:
from orchestrator.config.routines.errors import (
```

- [ ] Create `src/orchestrator/config/routines/discovery.py` — copy from `src/orchestrator/routines/discovery.py`, updating both internal imports:

```python
# Change these two lines:
from orchestrator.routines.errors import RoutineError
from orchestrator.routines.loader import load_routine_from_path
# To:
from orchestrator.config.routines.errors import RoutineError
from orchestrator.config.routines.loader import load_routine_from_path
```

- [ ] Create `src/orchestrator/config/routines/__init__.py` — copy from `src/orchestrator/routines/__init__.py`, updating both internal imports:

```python
"""Routine loading and validation."""

from orchestrator.config.routines.errors import (
    RoutineError,
    RoutineNotFoundError,
    RoutineParseError,
    RoutineValidationError,
)
from orchestrator.config.routines.loader import load_routine_from_path

__all__ = [
    "RoutineError",
    "RoutineNotFoundError",
    "RoutineParseError",
    "RoutineValidationError",
    "load_routine_from_path",
]
```

- [ ] Verify the new sub-package is importable before proceeding:

```bash
uv run python -c "from orchestrator.config.routines.loader import load_routine_from_path; print('OK')"
uv run python -c "from orchestrator.config.routines.discovery import discover_routines; print('OK')"
uv run python -c "from orchestrator.config.routines.errors import RoutineError; print('OK')"
uv run python -c "from orchestrator.config.routines.versioning import get_routine_version; print('OK')"
```

**Constraints**
- Do NOT modify `src/orchestrator/routines/` in this task — the old files stay in place until Task 3
- Do NOT modify `config/__init__.py` — no top-level re-exports are needed (no consumers use `from orchestrator.config import <routine symbol>`)

**Functionality (Expected Outcomes)**
- [ ] `src/orchestrator/config/routines/` exists with 5 Python files
- [ ] Each file has updated internal imports pointing to `orchestrator.config.routines.*`
- [ ] `from orchestrator.config.routines.loader import load_routine_from_path` works without error
- [ ] `from orchestrator.config.routines.discovery import discover_routines` works without error

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.config.routines import load_routine_from_path, RoutineError; print('OK')"` exits 0
- [ ] `uv run python -c "from orchestrator.config.routines.discovery import discover_routines, discover_routines_in_repo; print('OK')"` exits 0
- [ ] `uv run python -c "from orchestrator.config.routines.versioning import get_routine_version, find_git_root; print('OK')"` exits 0
- [ ] `grep -r "orchestrator\.routines\." src/orchestrator/config/routines/` returns zero results (no old-path imports in the new files)

---

## Task 2: Update src/ imports (api/, cli/, scripts/)

**Description**: Replace all `from orchestrator.routines` imports in production source files and scripts. There are 9 import sites across 8 files: 5 in `api/routers/`, 1 in `api/errors.py`, 2 in `cli/`, and 1 in `scripts/`. The dead shim `src/orchestrator/config/loader.py` (which re-exports from `routines.loader` and has zero consumers) is also deleted here.

**Implementation Plan (Do These Steps)**

The pattern to replace is `orchestrator.routines.` → `orchestrator.config.routines.`. Use sed for each file to make the change mechanical and auditable.

- [ ] Update `src/orchestrator/api/errors.py`:

```bash
sed -i '' 's/from orchestrator\.routines\./from orchestrator.config.routines./g' \
  src/orchestrator/api/errors.py
```

- [ ] Update the 4 api router files:

```bash
sed -i '' 's/from orchestrator\.routines\./from orchestrator.config.routines./g' \
  src/orchestrator/api/routers/runs.py \
  src/orchestrator/api/routers/routines.py \
  src/orchestrator/api/routers/repos.py \
  src/orchestrator/api/routers/tasks.py
```

- [ ] Update the 2 cli files:

```bash
sed -i '' 's/from orchestrator\.routines\./from orchestrator.config.routines./g' \
  src/orchestrator/cli/runs.py \
  src/orchestrator/cli/routines.py
```

- [ ] Update `scripts/seed_db.py`:

```bash
sed -i '' 's/from orchestrator\.routines\./from orchestrator.config.routines./g' \
  scripts/seed_db.py
```

- [ ] Delete the dead shim `src/orchestrator/config/loader.py` (it re-exports `load_routine_from_path` from `orchestrator.routines.loader` and has zero consumers — verified by grep):

```bash
rm src/orchestrator/config/loader.py
```

- [ ] Verify no `orchestrator.routines` references remain in src/ or scripts/ (excluding the old `routines/` directory itself, which is deleted in Task 3):

```bash
grep -r "from orchestrator\.routines" src/orchestrator/api/ src/orchestrator/cli/ scripts/
```

**Constraints**
- Do NOT modify files inside `src/orchestrator/routines/` — those are deleted wholesale in Task 3
- Do NOT modify test files — that is Task 3's responsibility
- `config/__init__.py` does not need updating (no callers use `from orchestrator.config import <routine symbol>`)

**Side Effects**
- After this task, both `orchestrator.routines.*` (old) and `orchestrator.config.routines.*` (new) are still importable — the old `routines/` directory has not yet been deleted

**Functionality (Expected Outcomes)**
- [ ] All api/, cli/, and scripts/ files import from `orchestrator.config.routines.*`
- [ ] `src/orchestrator/config/loader.py` no longer exists
- [ ] The old `routines/` module is still intact (not yet deleted)

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "from orchestrator\.routines" src/orchestrator/api/ src/orchestrator/cli/ scripts/` returns zero results
- [ ] `test ! -f src/orchestrator/config/loader.py && echo "shim deleted"` exits 0
- [ ] `uv run python -c "from orchestrator.api.routers import runs; print('OK')"` exits 0 (spot-check that api routers import correctly)

---

## Task 3: Update test imports and delete routines/

**Description**: Replace all `from orchestrator.routines` imports in the test suite, then delete the old `routines/` directory. There are 17 test files with imports to update. After deletion, no reference to the old path should exist anywhere in the codebase.

**Implementation Plan (Do These Steps)**

- [ ] Update all test files in a single sed pass:

```bash
find tests/ -name "*.py" -exec sed -i '' \
  's/from orchestrator\.routines\./from orchestrator.config.routines./g' {} +
```

- [ ] Verify the test updates — count should match ~14 import sites across 17 files:

```bash
grep -r "from orchestrator\.routines" tests/
```

Expected output: no results (exit 0 with empty output).

- [ ] Delete the entire old `routines/` directory:

```bash
rm -rf src/orchestrator/routines/
```

- [ ] Confirm the directory is gone:

```bash
test ! -d src/orchestrator/routines && echo "routines/ deleted"
```

- [ ] Run a final exhaustive grep to confirm zero references remain anywhere:

```bash
grep -r "from orchestrator\.routines" src/ tests/ scripts/
```

Expected: no output (exit code 0 with empty stdout, or exit code 1 from grep — both mean zero matches).

**Constraints**
- Task 2 must be complete before running this task (all src/ + scripts/ imports already updated)
- Do NOT run tests yet — that is Task 4's job

**Functionality (Expected Outcomes)**
- [ ] All test files import from `orchestrator.config.routines.*`
- [ ] `src/orchestrator/routines/` directory does not exist
- [ ] Zero occurrences of `from orchestrator.routines` anywhere in `src/`, `tests/`, `scripts/`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "from orchestrator\.routines" src/ tests/ scripts/` returns zero matches
- [ ] `ls src/orchestrator/routines/` fails with "No such file or directory"
- [ ] `ls src/orchestrator/config/routines/` succeeds and shows `__init__.py`, `errors.py`, `versioning.py`, `loader.py`, `discovery.py`

---

## Task 4: Run full verification suite

**Description**: Execute the complete verification suite to confirm the absorption is correct and no tests are broken. Fix any failures before marking this step complete.

**Implementation Plan (Do These Steps)**

All prior tasks (1–3) must be complete before running these checks.

- [ ] Run unit tests:

```bash
uv run pytest tests/unit/ -v
```

Fix any import errors or test failures before proceeding.

- [ ] Run integration tests:

```bash
uv run pytest tests/integration/ -v
```

Fix any import errors or test failures before proceeding. The two known pre-existing failures (openhands module not installed) are acceptable.

- [ ] Run frontend tests (these don't import Python, but confirm the full CI gate):

```bash
cd ui && npx vitest run
```

- [ ] Run pre-commit hooks:

```bash
uv run pre-commit run --all-files
```

Fix any lint or formatting failures.

- [ ] Final path-cleanliness verification:

```bash
grep -r "from orchestrator\.routines" src/ tests/ scripts/
```

Must return zero results. If any match appears, trace it to the file, update it, and re-run the test suite.

- [ ] Spot-check that routine YAML loading still works end-to-end:

```bash
uv run python -c "
from pathlib import Path
from orchestrator.config.routines.loader import load_routine_from_path
# Load the demo routine to confirm file-based discovery still works
p = Path('routines/demo-task.yaml')
if p.exists():
    r = load_routine_from_path(p)
    print(f'Loaded routine: {r.id}')
else:
    print('No demo-task.yaml found — skipping spot-check')
"
```

**Dependencies**
- [ ] Tasks 1, 2, 3 complete

**Functionality (Expected Outcomes)**
- [ ] All unit tests pass (same count as baseline or higher)
- [ ] All integration tests pass (same pass/fail ratio as baseline)
- [ ] Frontend tests pass
- [ ] Pre-commit hooks pass
- [ ] Routine YAML loading works correctly from the new import path

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ -q` exits 0
- [ ] `uv run pytest tests/integration/ -q` exits 0 (pre-existing openhands failures excluded)
- [ ] `cd ui && npx vitest run` exits 0
- [ ] `uv run pre-commit run --all-files` exits 0
- [ ] `grep -r "from orchestrator\.routines" src/ tests/ scripts/` returns zero results
- [ ] `test ! -d src/orchestrator/routines && echo "routines/ gone"` exits 0
- [ ] `uv run python -c "from orchestrator.config.routines import load_routine_from_path, RoutineError, RoutineNotFoundError, RoutineParseError, RoutineValidationError; print('all symbols OK')"` exits 0
