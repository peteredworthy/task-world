# Step 06 Dry-Run Analysis: Absorb scaffolding/ + agents/ → runners/

## Overview

Phase 6 moves `scaffolding/` (workspace setup) and `agents/` (agent persona CRUD) into `runners/` as `runners/scaffolding/` and `runners/profiles/` sub-packages. This completes the M2 milestone (9 top-level modules).

Source verified against actual files in `src/orchestrator/`. The analysis below identifies gaps, failure modes, and hardening actions.

---

## Task-by-Task Analysis

### Task 1: Create runners/scaffolding/ Sub-Package

**Assumptions being made:**
- `scaffolding/` contains exactly: `__init__.py`, `copier.py`, `errors.py`, `models.py` — **verified correct**
- `copier.py` has two intra-package imports (`errors`, `models`) — **verified correct** (lines 6–7)
- `errors.py` and `models.py` have no intra-package imports — **verified correct**
- The existing `scaffolding/__init__.py` exports `copy_scaffolding`, `ensure_gitignore`, `ScaffoldingError`, `ScaffoldingSpec` — **verified correct**

**Expected outputs:** All correct per step.

**Potential blockers:**
- None significant. The step's proposed `runners/scaffolding/__init__.py` content exactly mirrors the existing `scaffolding/__init__.py`. No surprises.

**Gap noted:** `ScaffoldingNotFoundError` and `ScaffoldingCopyError` are defined in `errors.py` but not exported via `__init__.py`. The step correctly omits them (matching original behavior). No external callers import them directly.

---

### Task 2: Create runners/profiles/ Sub-Package

**Assumptions being made:**
- `agents/__init__.py` exports agents module public interface — **incorrect**: the file contains only a single docstring (`"""Agent concept: prompt templates paired with model profiles."""`). It exports nothing. No `__all__`, no re-exports.
- `agents/schemas.py` has only intra-package imports from `orchestrator.agents.*` — **incorrect**: `schemas.py` imports `from orchestrator.api.schemas.base import ApiModel` (an upward import from api/).

**Critical gap — upward import in schemas.py:**

`agents/schemas.py` line 7: `from orchestrator.api.schemas.base import ApiModel`

When moved to `runners/profiles/schemas.py`, this becomes a `runners/` → `api/` import. The step explicitly states in the Constraints: *"`runners/profiles/` must not import from ... higher layer (`workflow/`, `api/`)"* — yet the step provides no fix for this violation. Moving the file as-is violates the stated constraint.

`ApiModel` is a `pydantic.BaseModel` subclass that adds UTC datetime serialization for JSON encoding. Options for resolution:
1. Replace `ApiModel` with `pydantic.BaseModel` in `runners/profiles/schemas.py` (losing datetime serialization in agent schema API responses — acceptable since the API router still uses FastAPI's JSON serialization pipeline)
2. Extract `ApiModel` to a shared lower-layer module (e.g., `state/` or a new `utils/` module)
3. Inline the equivalent `model_serializer` logic in `runners/profiles/schemas.py`

The step must explicitly specify which option to take before implementation.

**Expected outputs:** `runners/profiles/__init__.py` needs to be written from scratch since the original is empty. The step says "Inspect the original `agents/__init__.py` to confirm what it exports, then create ... mirroring it" — this instruction will produce a blank file. The implementer must decide what to export.

**Proposed exports for `runners/profiles/__init__.py`:**
```python
from orchestrator.runners.profiles.errors import AgentNotFoundError, AgentNameConflictError, AgentNoDefaultPromptError
from orchestrator.runners.profiles.models import AgentConfigModel
from orchestrator.runners.profiles.schemas import AgentSchema, CreateAgentRequest, UpdateAgentRequest
from orchestrator.runners.profiles.service import AgentService, seed_default_agents
from orchestrator.runners.profiles.resolution import resolve_agent_name, get_agent_system_prompt

__all__ = [
    "AgentNotFoundError", "AgentNameConflictError", "AgentNoDefaultPromptError",
    "AgentConfigModel", "AgentSchema", "CreateAgentRequest", "UpdateAgentRequest",
    "AgentService", "seed_default_agents",
    "resolve_agent_name", "get_agent_system_prompt",
]
```

---

### Task 3: Update All External Consumers of orchestrator.scaffolding

**Assumptions being made:**
- External consumers of `orchestrator.scaffolding` in `src/` and `tests/` are: `runners/executor.py` (1 reference) and `tests/integration/test_scaffolding.py` (1 reference) — **verified correct**
- No references in `scripts/` or `alembic/` — need to verify, but likely correct

**Executor import location:** The import is a **lazy import inside a function body** at line 401:
```python
from orchestrator.scaffolding.copier import copy_scaffolding
```
This is inside a try block at `executor.py:401`. The step correctly identifies this as a lazy import.

**No hidden failures expected here.** The grep at the start of Task 3 will catch everything.

---

### Task 4: Update All External Consumers of orchestrator.agents

**CRITICAL FAILURE MODE: `db/migrations/env.py` not listed as a consumer.**

`src/orchestrator/db/migrations/env.py` line 14:
```python
import orchestrator.agents.models as _agent_models  # noqa: F401
```

This import exists so Alembic's autogenerate can detect the `AgentConfigModel` ORM table (`agent_configs`). It is NOT listed in Task 4's enumerated consumer list (which lists 3 src/ files and 4 test files = 7 total). After `agents/` is deleted in Task 5, Alembic migrations will fail to run because this import will raise `ModuleNotFoundError`.

The grep command at the start of Task 4 (`grep -r "from orchestrator\.agents\|import orchestrator\.agents" src/ tests/ ...`) WILL find this file since it's under `src/`. However, because it's not in the explicit list, an implementer following the task steps mechanically may overlook it when checking off the "confirm the complete list" step.

**Required fix:** Update `src/orchestrator/db/migrations/env.py` line 14:
```python
# old
import orchestrator.agents.models as _agent_models  # noqa: F401

# new
import orchestrator.runners.profiles.models as _agent_models  # noqa: F401
```

**Note on `agents/__init__.py` being empty:** The `agents/__init__.py` only has a docstring. The grep pattern `from orchestrator.agents` will not match it. No issue.

**Audit scope for scripts/ and alembic/:** The step checks `scripts/` and `alembic/` directories, but the migration env.py is at `src/orchestrator/db/migrations/env.py` — within `src/`, not in a top-level `alembic/` dir. The initial grep at the start of Task 4 covers `src/` so it will appear there. But the explicit consumer list must include it.

---

### Task 5: Delete Original scaffolding/ and agents/ Directories

**Assumptions being made:**
- All consumers have been updated — depends on Tasks 3 and 4 completing correctly (including the `db/migrations/env.py` fix)
- The pre-deletion grep verifications will catch any missed updates

**Potential blocker:** If the `db/migrations/env.py` consumer is not updated in Task 4, the pre-deletion grep in Task 5 will catch it (since the grep still includes `src/`). This is the safety net. But by Task 5, the fix should already be in place.

**`runners/agents/` collision risk:** The step correctly identifies this risk and uses `runners/profiles/` naming to avoid it. Verified: `src/orchestrator/runners/agents/` holds agent implementations (claude_cli, claude_sdk, codex, openhands, user_managed, mock). The top-level `src/orchestrator/agents/` is a separate directory. No collision.

---

### Task 6: Full Test Suite and Final Reference Audit

**Assumptions being made:**
- All tests pass after import path updates
- Circular import check covers `runners/profiles/` correctly

**Circular import risk from `schemas.py`:** If the `ApiModel` upward import issue (Task 2) is not resolved, the circular import check in Task 6 will catch it:
```bash
grep -r "from orchestrator\.workflow\|from orchestrator\.api" src/orchestrator/runners/profiles/
```
This grep would show `schemas.py` importing from `orchestrator.api.schemas.base`. The step correctly includes this check, so the failure will surface here if not fixed in Task 2.

**Pre-commit hook risk:** `uv run pre-commit run --all-files` may fail if any linting issues are introduced during the file moves (e.g., unused imports in moved files). All moved files should be verified clean before running pre-commit.

---

## Failure Mode Summary

| # | Severity | Failure Mode | Root Cause | Hardening Action |
|---|----------|-------------|------------|------------------|
| F1 | **CRITICAL** | Alembic migrations break after `agents/` deletion | `db/migrations/env.py` imports `orchestrator.agents.models` but is not in Task 4's consumer list | Add `src/orchestrator/db/migrations/env.py` explicitly to Task 4's update list |
| F2 | **HIGH** | Layering violation: `runners/profiles/` → `api/` | `agents/schemas.py` imports `ApiModel` from `orchestrator.api.schemas.base` | Specify a concrete fix in Task 2: replace `ApiModel` with `pydantic.BaseModel` or move `ApiModel` to a lower-layer module |
| F3 | **MEDIUM** | `runners/profiles/__init__.py` created as near-empty | `agents/__init__.py` only has a docstring; step says "mirror it" | Task 2 must specify explicit exports for `runners/profiles/__init__.py` rather than relying on mirroring the (empty) original |
| F4 | **LOW** | Intent Verification says `runners/__init__.py` re-exports new symbols; implementation doesn't do it | Discrepancy between Intent Verification and Implementation Plan | Clarify: since no callers use `from orchestrator.runners import ScaffoldingSpec`, no re-exports are needed; remove the claim from Intent Verification |

---

## Hardening Actions

### H1: Add `db/migrations/env.py` to Task 4's consumer list (fixes F1)

Add to Task 4's "Implementation Plan":
```markdown
- [ ] Update `src/orchestrator/db/migrations/env.py` (Alembic model discovery import):
  ```python
  # old
  import orchestrator.agents.models as _agent_models  # noqa: F401

  # new
  import orchestrator.runners.profiles.models as _agent_models  # noqa: F401
  ```
```

Also update the final verification grep in Task 4 to explicitly call out that `db/migrations/env.py` must not appear.

### H2: Specify ApiModel fix in Task 2 (fixes F2)

Add to Task 2's "Implementation Plan" before copying `schemas.py`:

```markdown
- [ ] In `runners/profiles/schemas.py`, replace the upward import:
  ```python
  # old — violates Execution → Interface layering rule
  from orchestrator.api.schemas.base import ApiModel
  ```
  with:
  ```python
  # new — use plain BaseModel; datetime serialization handled by API layer
  from pydantic import BaseModel as ApiModel  # alias preserves downstream compatibility
  ```
  Note: `AgentSchema` is used only in API responses where FastAPI's JSON encoder handles datetime formatting. Removing the custom `model_serializer` is safe.
```

### H3: Specify explicit exports for `runners/profiles/__init__.py` (fixes F3)

Replace the Task 2 instruction:
> "Inspect the original `agents/__init__.py` to confirm what it exports, then create `runners/profiles/__init__.py` mirroring it"

With:
> "Create `runners/profiles/__init__.py` with the following explicit exports (the original `agents/__init__.py` is empty — only a docstring):"

And provide the explicit `__init__.py` content listing all public symbols from errors, models, schemas, service, and resolution.

### H4: Remove re-export claim from Intent Verification (fixes F4)

Remove from the Intent Verification section:
> "`runners/__init__.py` re-exports key public symbols from both sub-packages so callers that import from `orchestrator.runners` directly still work"

The current `runners/__init__.py` only has a docstring. No callers import scaffolding or agents symbols from `orchestrator.runners` directly (verified by grep). No re-exports are needed.

---

## Correct Consumer Counts

The step says "~3–5 import paths each" for both modules. Actual counts:

**`orchestrator.scaffolding` external consumers (excluding `scaffolding/` internals):**
- `src/orchestrator/runners/executor.py` — 1 lazy import
- `tests/integration/test_scaffolding.py` — 1 import
- **Total: 2 files** (step says "1 external consumer in src/ and 1 in tests/" — correct)

**`orchestrator.agents` external consumers (excluding `agents/` internals):**
- `src/orchestrator/db/migrations/env.py` — 1 import (**not listed in step**)
- `src/orchestrator/api/routers/agents.py` — 3 imports
- `src/orchestrator/api/routers/tasks.py` — 1 import
- `src/orchestrator/api/app.py` — 1 lazy import
- `tests/unit/test_agent_resolution.py` — 2 imports
- `tests/unit/test_agent_service.py` — 3 imports
- `tests/integration/test_api_agent_configs.py` — 1 import
- `tests/integration/test_e2e_agent_overrides.py` — 1 import
- **Total: 8 files** (step says "3 consumers in src/ and 4 in tests/" = 7 — misses `db/migrations/env.py`)

---

## Go / No-Go Assessment

**Not ready to execute as written.** Two issues must be resolved before implementation:

1. **F1 (Critical):** Add `src/orchestrator/db/migrations/env.py` to Task 4's update list. Missing this will break Alembic after deletion.
2. **F2 (High):** Specify the `ApiModel` fix in Task 2. Moving `schemas.py` without fixing the `api/` import violates the stated layering constraint.

Once H1 and H2 are applied, the step is mechanically straightforward with low risk of missed imports or circular dependencies.
