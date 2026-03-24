# Step 6: Absorb scaffolding/ + agents/ → runners/

Move `scaffolding/` (workspace setup utilities) and `agents/` (agent persona CRUD) into `runners/` as sub-packages. Both are execution-layer concerns that belong alongside runner implementations. `agents/` is renamed `profiles/` to avoid collision with the existing `runners/agents/` directory that holds agent implementations.

This phase completes the M2 milestone: after it, the codebase has 9 top-level modules. It depends on Phase 0 (C6 coupling fix) having decoupled `UserManagedAgent` from `WorkflowService` so that `agents/` can safely move into `runners/` without creating circular imports.

The actual import site counts (from grep): scaffolding has 3 external consumers (`runners/executor.py`, `tests/integration/test_scaffolding.py`, plus internal self-imports); agents has 8 external consumers (`api/routers/agents.py`, `api/routers/tasks.py`, `api/app.py`, `tests/unit/test_agent_resolution.py`, `tests/unit/test_agent_service.py`, `tests/integration/test_api_agent_configs.py`, `tests/integration/test_e2e_agent_overrides.py`, plus internal self-imports).

## Intent Verification
**Original Intent**: Phase 6 of the module consolidation plan — absorb `scaffolding/` into `runners/scaffolding/` and `agents/` into `runners/profiles/` with zero shims, zero leftover references, and all tests passing.

**Functionality to Produce**:
- `src/orchestrator/runners/scaffolding/` sub-package with `__init__.py`, `copier.py`, `errors.py`, `models.py`
- `src/orchestrator/runners/profiles/` sub-package with `__init__.py`, `errors.py`, `models.py`, `resolution.py`, `schemas.py`, `service.py`
- `src/orchestrator/scaffolding/` directory entirely removed
- `src/orchestrator/agents/` directory entirely removed
- All `from orchestrator.scaffolding` imports updated to `from orchestrator.runners.scaffolding`
- All `from orchestrator.agents` imports updated to `from orchestrator.runners.profiles`
- `runners/__init__.py` re-exports key public symbols from both sub-packages so callers that import from `orchestrator.runners` directly still work

**Final Verification Criteria**:
- All backend unit and integration tests pass
- All frontend tests pass
- `grep -r "from orchestrator\.scaffolding" src/ tests/` returns zero results
- `grep -r "from orchestrator\.agents" src/ tests/` returns zero results
- `src/orchestrator/scaffolding/` and `src/orchestrator/agents/` do not exist
- No circular imports: `runners/profiles/` and `runners/scaffolding/` only import from `config/`, `state/`, `db/`

---

## Task 1: Create runners/scaffolding/ Sub-Package and Move Files

**Description**:
Create `runners/scaffolding/` with `__init__.py`, then copy `copier.py`, `errors.py`, and `models.py` into it, updating only the internal intra-package import paths. Do not delete the original directory yet.

**Implementation Plan (Do These Steps)**

- [ ] Create the sub-package directory:
```bash
mkdir -p src/orchestrator/runners/scaffolding
```

- [ ] Inspect the internal imports in each source file to know what to update:
```bash
grep "from orchestrator.scaffolding" src/orchestrator/scaffolding/copier.py src/orchestrator/scaffolding/errors.py src/orchestrator/scaffolding/models.py
```

- [ ] Copy `models.py` to `runners/scaffolding/models.py`. It has no intra-package imports, so no content changes are needed:
```bash
cp src/orchestrator/scaffolding/models.py src/orchestrator/runners/scaffolding/models.py
```

- [ ] Copy `errors.py` to `runners/scaffolding/errors.py`. It has no intra-package imports, so no content changes are needed:
```bash
cp src/orchestrator/scaffolding/errors.py src/orchestrator/runners/scaffolding/errors.py
```

- [ ] Copy `copier.py` to `runners/scaffolding/copier.py`. Update its two internal imports:
  ```python
  # old
  from orchestrator.scaffolding.errors import ScaffoldingCopyError
  from orchestrator.scaffolding.models import ScaffoldingResult
  ```
  →
  ```python
  # new
  from orchestrator.runners.scaffolding.errors import ScaffoldingCopyError
  from orchestrator.runners.scaffolding.models import ScaffoldingResult
  ```

- [ ] Create `src/orchestrator/runners/scaffolding/__init__.py` mirroring the original `scaffolding/__init__.py`:
```python
"""Scaffolding module for copying template files to worktrees."""

from orchestrator.runners.scaffolding.copier import copy_scaffolding, ensure_gitignore
from orchestrator.runners.scaffolding.errors import ScaffoldingError
from orchestrator.runners.scaffolding.models import ScaffoldingSpec

__all__ = [
    "copy_scaffolding",
    "ensure_gitignore",
    "ScaffoldingError",
    "ScaffoldingSpec",
]
```

**Constraints**:
- Do not delete `src/orchestrator/scaffolding/` yet.
- Do not modify any file outside `runners/scaffolding/` in this task.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/runners/scaffolding/__init__.py`, `copier.py`, `errors.py`, `models.py` all exist
- [ ] `runners/scaffolding/copier.py` imports from `orchestrator.runners.scaffolding.*`, not from `orchestrator.scaffolding.*`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.runners.scaffolding import copy_scaffolding, ScaffoldingSpec; print('ok')"` succeeds
- [ ] `grep "from orchestrator.scaffolding" src/orchestrator/runners/scaffolding/copier.py` returns zero results

---

## Task 2: Create runners/profiles/ Sub-Package and Move Files

**Description**:
Create `runners/profiles/` with `__init__.py`, then copy all five files from `agents/` into it, updating only the internal intra-package import paths. Do not delete the original directory yet.

**Implementation Plan (Do These Steps)**

- [ ] Create the sub-package directory:
```bash
mkdir -p src/orchestrator/runners/profiles
```

- [ ] Inspect the internal imports in each source file to know what to update:
```bash
grep "from orchestrator.agents" src/orchestrator/agents/service.py src/orchestrator/agents/resolution.py src/orchestrator/agents/schemas.py src/orchestrator/agents/errors.py src/orchestrator/agents/models.py
```

- [ ] Copy `errors.py` to `runners/profiles/errors.py`. It likely has no intra-package imports:
```bash
cp src/orchestrator/agents/errors.py src/orchestrator/runners/profiles/errors.py
```

- [ ] Copy `models.py` to `runners/profiles/models.py`. It likely has no intra-package imports:
```bash
cp src/orchestrator/agents/models.py src/orchestrator/runners/profiles/models.py
```

- [ ] Copy `schemas.py` to `runners/profiles/schemas.py`. Update any intra-package imports from `orchestrator.agents` → `orchestrator.runners.profiles`.

- [ ] Copy `resolution.py` to `runners/profiles/resolution.py`. Update any intra-package imports:
  ```python
  # old
  from orchestrator.agents.models import AgentConfigModel
  ```
  →
  ```python
  # new
  from orchestrator.runners.profiles.models import AgentConfigModel
  ```

- [ ] Copy `service.py` to `runners/profiles/service.py`. Update the three intra-package imports:
  ```python
  # old
  from orchestrator.agents.errors import (...)
  from orchestrator.agents.models import AgentConfigModel
  from orchestrator.agents.schemas import AgentSchema, CreateAgentRequest, UpdateAgentRequest
  ```
  →
  ```python
  # new
  from orchestrator.runners.profiles.errors import (...)
  from orchestrator.runners.profiles.models import AgentConfigModel
  from orchestrator.runners.profiles.schemas import AgentSchema, CreateAgentRequest, UpdateAgentRequest
  ```

- [ ] Inspect the original `agents/__init__.py` to confirm what it exports, then create `src/orchestrator/runners/profiles/__init__.py` mirroring it with updated import paths:
```bash
cat src/orchestrator/agents/__init__.py
```
  Then write `runners/profiles/__init__.py` with all `from orchestrator.agents.*` changed to `from orchestrator.runners.profiles.*`.

**Constraints**:
- Do not delete `src/orchestrator/agents/` yet.
- Do not modify any file outside `runners/profiles/` in this task.
- `runners/profiles/` must not import from `runners/agents/` (agent implementations) or any higher layer (`workflow/`, `api/`).

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/runners/profiles/` contains `__init__.py`, `errors.py`, `models.py`, `resolution.py`, `schemas.py`, `service.py`
- [ ] All intra-package imports in moved files reference `orchestrator.runners.profiles.*`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.runners.profiles import AgentService; print('ok')"` succeeds (or whatever the `__init__.py` exports)
- [ ] `uv run python -c "from orchestrator.runners.profiles.resolution import resolve_agent_name; print('ok')"` succeeds
- [ ] `grep "from orchestrator.agents" src/orchestrator/runners/profiles/` returns zero results

---

## Task 3: Update All External Consumers of orchestrator.scaffolding

**Description**:
Update every file outside `scaffolding/` that imports from `orchestrator.scaffolding` to use `orchestrator.runners.scaffolding` instead. There is 1 external consumer in `src/` and 1 in `tests/`.

**Implementation Plan (Do These Steps)**

- [ ] Confirm the complete list of external consumers:
```bash
grep -r "from orchestrator\.scaffolding\|import orchestrator\.scaffolding" src/ tests/ --include="*.py" | grep -v "src/orchestrator/scaffolding/"
```

- [ ] Update `src/orchestrator/runners/executor.py` (lazy import inside a function body):
  ```python
  # old
  from orchestrator.scaffolding.copier import copy_scaffolding
  ```
  →
  ```python
  # new
  from orchestrator.runners.scaffolding.copier import copy_scaffolding
  ```

- [ ] Update `tests/integration/test_scaffolding.py`:
  ```python
  # old
  from orchestrator.scaffolding import copy_scaffolding, ensure_gitignore
  ```
  →
  ```python
  # new
  from orchestrator.runners.scaffolding import copy_scaffolding, ensure_gitignore
  ```

- [ ] Audit for any remaining references in `scripts/` and `alembic/`:
```bash
grep -r "from orchestrator\.scaffolding\|import orchestrator\.scaffolding" scripts/ alembic/ --include="*.py" 2>/dev/null || echo "OK: none"
```
Update any that appear.

**Constraints**:
- Do not delete `src/orchestrator/scaffolding/` yet.
- Only change import paths — do not alter function signatures, logic, or test assertions.

**Functionality (Expected Outcomes)**:
- [ ] `runners/executor.py` imports `copy_scaffolding` from `orchestrator.runners.scaffolding.copier`
- [ ] `tests/integration/test_scaffolding.py` imports from `orchestrator.runners.scaffolding`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "from orchestrator\.scaffolding" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "src/orchestrator/scaffolding/"` returns zero results
- [ ] `uv run python -c "from orchestrator.runners.executor import Executor; print('ok')"` succeeds (confirms executor loads cleanly)

---

## Task 4: Update All External Consumers of orchestrator.agents

**Description**:
Update every file outside `agents/` that imports from `orchestrator.agents` to use `orchestrator.runners.profiles` instead. There are 3 consumers in `src/` and 4 in `tests/`.

**Implementation Plan (Do These Steps)**

- [ ] Confirm the complete list of external consumers:
```bash
grep -r "from orchestrator\.agents\|import orchestrator\.agents" src/ tests/ --include="*.py" | grep -v "src/orchestrator/agents/"
```

- [ ] Update `src/orchestrator/api/routers/agents.py` — three imports:
  ```python
  # old
  from orchestrator.agents.errors import (...)
  from orchestrator.agents.schemas import AgentSchema, CreateAgentRequest, UpdateAgentRequest
  from orchestrator.agents.service import AgentService
  ```
  →
  ```python
  # new
  from orchestrator.runners.profiles.errors import (...)
  from orchestrator.runners.profiles.schemas import AgentSchema, CreateAgentRequest, UpdateAgentRequest
  from orchestrator.runners.profiles.service import AgentService
  ```

- [ ] Update `src/orchestrator/api/routers/tasks.py`:
  ```python
  # old
  from orchestrator.agents.resolution import get_agent_system_prompt, resolve_agent_name
  ```
  →
  ```python
  # new
  from orchestrator.runners.profiles.resolution import get_agent_system_prompt, resolve_agent_name
  ```

- [ ] Update `src/orchestrator/api/app.py` (lazy import):
  ```python
  # old
  from orchestrator.agents.service import seed_default_agents
  ```
  →
  ```python
  # new
  from orchestrator.runners.profiles.service import seed_default_agents
  ```

- [ ] Update `tests/unit/test_agent_resolution.py`:
  ```python
  # old
  from orchestrator.agents.models import AgentConfigModel
  from orchestrator.agents.resolution import get_agent_system_prompt, resolve_agent_name
  ```
  →
  ```python
  # new
  from orchestrator.runners.profiles.models import AgentConfigModel
  from orchestrator.runners.profiles.resolution import get_agent_system_prompt, resolve_agent_name
  ```

- [ ] Update `tests/unit/test_agent_service.py`:
  ```python
  # old
  from orchestrator.agents.errors import (...)
  from orchestrator.agents.schemas import CreateAgentRequest, UpdateAgentRequest
  from orchestrator.agents.service import AgentService, seed_default_agents
  ```
  →
  ```python
  # new
  from orchestrator.runners.profiles.errors import (...)
  from orchestrator.runners.profiles.schemas import CreateAgentRequest, UpdateAgentRequest
  from orchestrator.runners.profiles.service import AgentService, seed_default_agents
  ```

- [ ] Update `tests/integration/test_api_agent_configs.py`:
  ```python
  # old
  from orchestrator.agents.service import seed_default_agents
  ```
  →
  ```python
  # new
  from orchestrator.runners.profiles.service import seed_default_agents
  ```

- [ ] Update `tests/integration/test_e2e_agent_overrides.py`:
  ```python
  # old
  from orchestrator.agents.service import seed_default_agents
  ```
  →
  ```python
  # new
  from orchestrator.runners.profiles.service import seed_default_agents
  ```

- [ ] Audit for any remaining references in `scripts/` and `alembic/`:
```bash
grep -r "from orchestrator\.agents\|import orchestrator\.agents" scripts/ alembic/ --include="*.py" 2>/dev/null || echo "OK: none"
```
Update any that appear.

**Constraints**:
- Do not delete `src/orchestrator/agents/` yet.
- Only change import paths — do not alter router logic, schemas, or test assertions.
- `runners/agents/` (agent implementations) must not be confused with `runners/profiles/` — double-check that no import accidentally targets `runners.agents.*`.

**Functionality (Expected Outcomes)**:
- [ ] All 7 external consumers reference `orchestrator.runners.profiles.*`
- [ ] `grep -r "from orchestrator\.agents" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "src/orchestrator/agents/"` returns zero results

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "from orchestrator\.agents" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "src/orchestrator/agents/"` returns zero results
- [ ] `uv run python -c "from orchestrator.api.routers.agents import router; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.api.routers.tasks import router; print('ok')"` succeeds

---

## Task 5: Delete Original scaffolding/ and agents/ Directories

**Description**:
With all consumers updated, delete both original source directories entirely. No shim or re-export should be left behind.

**Implementation Plan (Do These Steps)**

- [ ] Confirm zero external references to `orchestrator.scaffolding` remain:
```bash
grep -r "from orchestrator\.scaffolding\|import orchestrator\.scaffolding" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "src/orchestrator/scaffolding/"
```
Must return zero lines. If it does not, stop and fix remaining references in Task 3.

- [ ] Confirm zero external references to `orchestrator.agents` remain:
```bash
grep -r "from orchestrator\.agents\|import orchestrator\.agents" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "src/orchestrator/agents/"
```
Must return zero lines. If it does not, stop and fix remaining references in Task 4.

- [ ] Delete both original directories:
```bash
rm -rf src/orchestrator/scaffolding/
rm -rf src/orchestrator/agents/
```

- [ ] Confirm deletions:
```bash
ls src/orchestrator/scaffolding/ 2>&1 || echo "scaffolding/ deleted OK"
ls src/orchestrator/agents/ 2>&1 || echo "agents/ deleted OK"
```

- [ ] Confirm new locations are intact:
```bash
ls src/orchestrator/runners/scaffolding/
ls src/orchestrator/runners/profiles/
```

**Constraints**:
- Delete `scaffolding/` and `agents/` entirely — `__init__.py` and all `.py` files.
- Do not touch `runners/agents/` (agent implementations) — only the top-level `agents/` directory is deleted.
- No re-export shim may be left at the old locations.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/scaffolding/` does not exist
- [ ] `src/orchestrator/agents/` does not exist
- [ ] `src/orchestrator/runners/scaffolding/` contains `__init__.py`, `copier.py`, `errors.py`, `models.py`
- [ ] `src/orchestrator/runners/profiles/` contains `__init__.py`, `errors.py`, `models.py`, `resolution.py`, `schemas.py`, `service.py`
- [ ] `src/orchestrator/runners/agents/` is unchanged (agent implementations untouched)

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `ls src/orchestrator/scaffolding/` fails with "No such file or directory"
- [ ] `ls src/orchestrator/agents/` fails with "No such file or directory"
- [ ] `uv run python -c "from orchestrator.scaffolding import copy_scaffolding"` raises `ModuleNotFoundError`
- [ ] `uv run python -c "from orchestrator.agents import AgentService"` raises `ModuleNotFoundError`
- [ ] `uv run python -c "from orchestrator.runners.scaffolding import copy_scaffolding, ScaffoldingSpec; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.runners.profiles.service import AgentService; print('ok')"` succeeds

---

## Task 6: Full Test Suite and Final Reference Audit

**Description**:
Run the complete test suite and perform exhaustive grep verification that zero references to the old `orchestrator.scaffolding` and `orchestrator.agents` paths remain anywhere in the repository. This is the gate check before Phase 6 is considered complete.

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
- [ ] If any test failures occur due to remaining stale imports, fix those imports and re-run.
- [ ] Run the scaffolding reference audit:
```bash
grep -r "from orchestrator\.scaffolding\|import orchestrator\.scaffolding" src/ tests/ scripts/ alembic/ --include="*.py" || echo "OK: zero refs"
```
- [ ] Run the agents reference audit:
```bash
grep -r "from orchestrator\.agents\|import orchestrator\.agents" src/ tests/ scripts/ alembic/ --include="*.py" || echo "OK: zero refs"
```
- [ ] Verify no circular imports — `runners/profiles/` must not import from `runners/` internals or higher layers:
```bash
grep -r "from orchestrator\.runners\." src/orchestrator/runners/profiles/ --include="*.py" | grep -v "from orchestrator\.runners\.profiles" || echo "OK: no circular imports"
grep -r "from orchestrator\.workflow\|from orchestrator\.api" src/orchestrator/runners/profiles/ --include="*.py" || echo "OK: no upward imports"
```
- [ ] Verify `runners/agents/` (implementations) is distinct and untouched:
```bash
ls src/orchestrator/runners/agents/
```
- [ ] Check for residual shim/stub markers in the moved files:
```bash
grep -r "shim\|stub\|backward.compat\|backward_compat" src/orchestrator/runners/scaffolding/ src/orchestrator/runners/profiles/ --include="*.py" || echo "OK: no shim markers"
```
- [ ] Confirm git status shows deletions of old directories and new files in runners/:
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
- [ ] Every grep audit returns zero matches (or "OK:" echo)
- [ ] No circular imports in `runners/profiles/` or `runners/scaffolding/`
- [ ] `runners/agents/` (implementations) is untouched
- [ ] No shim markers in moved files

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -q` exits with code 0
- [ ] `cd ui && npx vitest run` exits with code 0
- [ ] `grep -r "from orchestrator\.scaffolding" src/ tests/ scripts/ alembic/ --include="*.py"` returns zero lines
- [ ] `grep -r "from orchestrator\.agents" src/ tests/ scripts/ alembic/ --include="*.py"` returns zero lines
- [ ] `ls src/orchestrator/scaffolding/` fails with "No such file or directory"
- [ ] `ls src/orchestrator/agents/` fails with "No such file or directory"
- [ ] `uv run python -c "from orchestrator.runners.scaffolding import copy_scaffolding, ScaffoldingSpec; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.runners.profiles.service import AgentService, seed_default_agents; print('ok')"` succeeds
- [ ] `git --no-pager diff --stat HEAD` shows deletions of `scaffolding/` and `agents/` files and additions of `runners/scaffolding/` and `runners/profiles/` files
