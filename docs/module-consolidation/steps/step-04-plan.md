# Step 4: Absorb artifacts/ → workflow/artifacts/

Move the `artifacts/` module into `workflow/` as a `workflow/artifacts/` sub-package. The artifact registry tracks build outputs within the workflow lifecycle and belongs in the orchestration layer, not as a standalone top-level module.

There are 9 import sites (not ~3 as estimated in the step plan): 3 in `src/` consumers (`workflow/context_builder.py`, `api/routers/tasks.py`, `runners/executor.py`), 3 in test files, and the 3 internal self-imports inside `artifacts/` itself. All must be updated atomically before deleting the original directory.

## Intent Verification
**Original Intent**: Phase 4 of the module consolidation plan — absorb `artifacts/` into `workflow/artifacts/` with zero shims, zero leftover references, and all tests passing.

**Functionality to Produce**:
- `src/orchestrator/workflow/artifacts/` sub-package with `__init__.py`, `models.py`, `registry.py`
- `src/orchestrator/artifacts/` directory entirely removed
- All 9 import paths updated from `orchestrator.artifacts` → `orchestrator.workflow.artifacts`
- `workflow/__init__.py` re-exports `Artifact` and `ArtifactRegistry` so existing top-level consumers that import from `orchestrator.workflow` continue to work

**Final Verification Criteria**:
- All backend unit and integration tests pass
- All frontend tests pass
- `grep -r "from orchestrator.artifacts" src/ tests/` returns zero results
- `src/orchestrator/artifacts/` directory does not exist
- No circular import: `workflow/artifacts/` must not import from `workflow/` internals

---

## Task 1: Create workflow/artifacts/ Sub-Package and Move Files

**Description**:
Create the `workflow/artifacts/` sub-package directory and populate it with `models.py`, `registry.py`, and an `__init__.py`. This is a pure file-copy step — no import changes yet.

**Implementation Plan (Do These Steps)**

- [ ] Create the sub-package directory and `__init__.py`:
```bash
mkdir -p src/orchestrator/workflow/artifacts
```
- [ ] Copy `models.py` from `artifacts/` to `workflow/artifacts/models.py`. The file has no intra-package imports, so no content changes are needed:
```bash
cp src/orchestrator/artifacts/models.py src/orchestrator/workflow/artifacts/models.py
```
- [ ] Copy `registry.py` from `artifacts/` to `workflow/artifacts/registry.py`. Update the one internal import on line 7:

  Current content of `src/orchestrator/artifacts/registry.py` line 7:
  ```python
  from orchestrator.artifacts.models import Artifact
  ```
  New content for `src/orchestrator/workflow/artifacts/registry.py` line 7:
  ```python
  from orchestrator.workflow.artifacts.models import Artifact
  ```

- [ ] Create `src/orchestrator/workflow/artifacts/__init__.py` mirroring the original `artifacts/__init__.py`:
```python
"""Artifact tracking for generated files across steps."""

from orchestrator.workflow.artifacts.models import Artifact
from orchestrator.workflow.artifacts.registry import ArtifactRegistry

__all__ = ["Artifact", "ArtifactRegistry"]
```

**Constraints**:
- Do not delete `src/orchestrator/artifacts/` yet — it must remain importable until all consumers are updated in Task 2.
- Do not modify `workflow/__init__.py` yet.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/workflow/artifacts/__init__.py` exists and contains `__all__`
- [ ] `src/orchestrator/workflow/artifacts/models.py` exists with the `Artifact` model
- [ ] `src/orchestrator/workflow/artifacts/registry.py` exists with its import pointing to `orchestrator.workflow.artifacts.models`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.workflow.artifacts import Artifact, ArtifactRegistry; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.workflow.artifacts.registry import ArtifactRegistry; r = ArtifactRegistry(); print('ok')"` succeeds
- [ ] `grep "from orchestrator.artifacts" src/orchestrator/workflow/artifacts/registry.py` returns zero results

---

## Task 2: Update All External Import Sites

**Description**:
Update every file outside `artifacts/` that imports from `orchestrator.artifacts` to use `orchestrator.workflow.artifacts` instead. There are 6 external import sites: 3 in `src/` and 3 in `tests/`.

**Implementation Plan (Do These Steps)**

- [ ] Update `src/orchestrator/workflow/context_builder.py`:
  ```
  from orchestrator.artifacts.registry import ArtifactRegistry
  ```
  →
  ```python
  from orchestrator.workflow.artifacts.registry import ArtifactRegistry
  ```

- [ ] Update `src/orchestrator/api/routers/tasks.py`:
  ```
  from orchestrator.artifacts.registry import ArtifactRegistry
  ```
  →
  ```python
  from orchestrator.workflow.artifacts.registry import ArtifactRegistry
  ```

- [ ] Update `src/orchestrator/runners/executor.py` (lazy import inside a function body):
  ```
  from orchestrator.artifacts.registry import ArtifactRegistry
  ```
  →
  ```python
  from orchestrator.workflow.artifacts.registry import ArtifactRegistry
  ```

- [ ] Update `tests/unit/test_artifact_registry.py`:
  ```
  from orchestrator.artifacts import ArtifactRegistry
  ```
  →
  ```python
  from orchestrator.workflow.artifacts import ArtifactRegistry
  ```

- [ ] Update `tests/unit/test_summary_cache.py`:
  ```
  from orchestrator.artifacts.registry import ArtifactRegistry
  ```
  →
  ```python
  from orchestrator.workflow.artifacts.registry import ArtifactRegistry
  ```

- [ ] Update `tests/unit/test_context_builder.py`:
  ```
  from orchestrator.artifacts.registry import ArtifactRegistry
  ```
  →
  ```python
  from orchestrator.workflow.artifacts.registry import ArtifactRegistry
  ```

- [ ] Audit for any remaining references in `scripts/` and `alembic/`:
```bash
grep -r "from orchestrator.artifacts\|import orchestrator.artifacts" src/ tests/ scripts/ alembic/ --include="*.py"
```
If any appear, update them to use `orchestrator.workflow.artifacts`.

**Constraints**:
- Do not delete `src/orchestrator/artifacts/` yet.
- Do not change the semantics of any updated file — only the import path changes.

**Functionality (Expected Outcomes)**:
- [ ] All 6 external import sites reference `orchestrator.workflow.artifacts`
- [ ] `grep -r "from orchestrator.artifacts" src/ tests/ scripts/ alembic/` returns only matches inside `src/orchestrator/artifacts/` itself

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "from orchestrator\.artifacts" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "src/orchestrator/artifacts/"` returns zero results
- [ ] `uv run python -c "from orchestrator.workflow.context_builder import ContextBuilder; print('ok')"` succeeds (or whatever the public class name is — just confirm the module imports cleanly)
- [ ] `uv run python -c "from orchestrator.api.routers.tasks import router; print('ok')"` succeeds

---

## Task 3: Delete Original artifacts/ Directory

**Description**:
With all consumers updated, delete the original `src/orchestrator/artifacts/` directory entirely. No shim or re-export should be left behind.

**Implementation Plan (Do These Steps)**

- [ ] Confirm zero external references remain before deleting:
```bash
grep -r "from orchestrator\.artifacts" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "src/orchestrator/artifacts/"
```
The above must return zero lines. If it does not, stop and fix remaining references in Task 2 before proceeding.

- [ ] Delete the original `artifacts/` directory:
```bash
rm -rf src/orchestrator/artifacts/
```

- [ ] Confirm deletion:
```bash
ls src/orchestrator/artifacts/ 2>&1 || echo "Deleted OK"
```

- [ ] Confirm `workflow/artifacts/` is intact:
```bash
ls src/orchestrator/workflow/artifacts/
```

**Constraints**:
- Delete the entire `artifacts/` directory including `__init__.py`, `models.py`, `registry.py`.
- Do not touch any other directory.
- No re-export shim may be left at the old location.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/artifacts/` does not exist
- [ ] `src/orchestrator/workflow/artifacts/` contains `__init__.py`, `models.py`, `registry.py`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `ls src/orchestrator/artifacts/` fails with "No such file or directory"
- [ ] `ls src/orchestrator/workflow/artifacts/` lists `__init__.py`, `models.py`, `registry.py`
- [ ] `uv run python -c "from orchestrator.artifacts import Artifact"` raises `ModuleNotFoundError` (old path is gone)
- [ ] `uv run python -c "from orchestrator.workflow.artifacts import Artifact, ArtifactRegistry; print('ok')"` succeeds

---

## Task 4: Full Test Suite and Final Reference Audit

**Description**:
Run the complete test suite and perform exhaustive grep verification that zero references to `orchestrator.artifacts` remain anywhere in the repository. This is the gate check before Phase 4 is considered complete.

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
- [ ] If any test failures occur due to remaining `orchestrator.artifacts` imports, fix those imports and re-run.
- [ ] Run the complete reference audit:
```bash
grep -r "from orchestrator\.artifacts\|import orchestrator\.artifacts" src/ tests/ scripts/ alembic/ --include="*.py" || echo "OK: zero refs"
```
- [ ] Verify no circular import by confirming artifacts sub-package only imports from lower layers:
```bash
grep -r "from orchestrator\.workflow\." src/orchestrator/workflow/artifacts/ --include="*.py" | grep -v "from orchestrator\.workflow\.artifacts" || echo "OK: no circular imports"
```
- [ ] Check for residual shim/stub markers in the moved files:
```bash
grep -r "shim\|stub\|backward.compat\|backward_compat" src/orchestrator/workflow/artifacts/ --include="*.py" || echo "OK: no shim markers"
```
- [ ] Confirm git status shows only deletions for `artifacts/` and new files for `workflow/artifacts/`:
```bash
git --no-pager status
```
- [ ] Run pre-commit hooks:
```bash
uv run pre-commit run --all-files
```

**Functionality (Expected Outcomes)**:
- [ ] All backend unit and integration tests pass
- [ ] All frontend tests pass
- [ ] Every grep audit command returns zero matches (or "OK:" echo)
- [ ] `workflow/artifacts/` files contain no shim markers
- [ ] No circular imports: `workflow/artifacts/` does not import from `workflow/` internals

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -q` exits with code 0
- [ ] `cd ui && npx vitest run` exits with code 0
- [ ] `grep -r "from orchestrator\.artifacts" src/ tests/ scripts/ alembic/ --include="*.py"` returns zero lines
- [ ] `ls src/orchestrator/artifacts/` fails with "No such file or directory"
- [ ] `uv run python -c "from orchestrator.workflow.artifacts import Artifact, ArtifactRegistry; print('ok')"` succeeds
- [ ] `git --no-pager diff --stat HEAD` shows deletions of `artifacts/` files and additions of `workflow/artifacts/` files
