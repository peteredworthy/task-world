# Step 10 Dry-Run Analysis: Explicit __all__ + Interface Narrowing

## Source Verification

### Current __init__.py Status (9 Modules)

**Already have explicit `__all__`** (4 of 9):

| Module | Status | Notes |
|--------|--------|-------|
| `config/` | ✓ Has `__all__` (26 symbols) | Exports enums + config models. Missing `NudgerConfig`, `EnvFileSpec` (from C1/C4 fixes — not yet applied to this worktree) |
| `state/` | ✓ Has `__all__` (12 symbols) | Includes `generate_id` — step plan assumes this needs to be hidden, but it's already publicly exported |
| `git/` | ✓ Has `__all__` (17 symbols) | Exports worktree, branch_ops, errors; includes `InitializedProject`/`init_project` from `project_init` which plan says to exclude |
| `workflow/` | ✓ Has `__all__` (37 symbols) | Very comprehensive; includes many symbols the plan says to hide (`evaluate_checklist_gate`, `evaluate_grades`, `VALID_TRANSITIONS`, dry-run internals) |

**Empty stubs** (5 of 9 — need full `__all__` declarations):

| Module | Current Content | Notes |
|--------|----------------|-------|
| `db/` | `"""Database layer for persistent storage."""` | No imports, no `__all__` |
| `envfiles/` | `"""Environment file management for non-git files."""` | No imports, no `__all__` |
| `runners/` | `"""Agent integrations for the orchestrator."""` | No imports, no `__all__` |
| `api/` | `"""FastAPI application for the orchestrator."""` | No imports, no `__all__` |
| `cli/` | `"""CLI package for orchestrator."""` | No imports, no `__all__` |

### Key File Locations (Step Plan Assumptions vs Reality)

| Assumption in Plan | Reality |
|-------------------|---------|
| `RunWorkflow` in `workflow/signals/runtime.py` | Actually in `workflow/runtime.py` (flat file, not sub-package) |
| `state/_utils.py` does not exist | Confirmed — does not exist yet |
| Phases 7–9 complete (sub-package restructuring done) | **NOT YET APPLIED** — workflow/ is still flat (22 files), no engine/, events/, signals/, agent/ sub-packages |

### ConnectionManager Usage in runners/

Both `executor.py` and `event_broadcaster.py` import `ConnectionManager` only under `TYPE_CHECKING`:

```python
# executor.py line 44
if TYPE_CHECKING:
    from orchestrator.api.websocket import ConnectionManager

# event_broadcaster.py line 22
if TYPE_CHECKING:
    from orchestrator.api.websocket import ConnectionManager
```

**Methods actually called** on the `ConnectionManager` instance:
- `event_broadcaster.py` line ~58: `self._connection_manager.broadcast_event(event)` (async)
- `executor.py` lines 211-221: wraps `manager.broadcast_event(event)` in an async callback lambda

The `BroadcastCallback` protocol needs to declare exactly one method: `async def broadcast_event(self, event: object) -> None`.

`broadcast_to_run`, `connect`, and `disconnect` are **not called from runners** — they are only called in `api/` (deps.py, app.py, websocket.py).

### Wildcard Imports

Eight wildcard import shims exist in `src/orchestrator/runners/`:

```
runners/openhands_common.py    → agents/openhands.common
runners/parsers/openhands_parser.py → agents/openhands.parser
runners/parsers/claude_parser.py → agents/claude_cli.parser
runners/parsers/codex_parser.py → agents/codex.parser
runners/codex_server.py        → agents/codex.agent
runners/openhands.py           → agents/openhands.agent
runners/codex_server_common.py → agents/codex.common
runners/openhands_docker.py    → agents/openhands.docker_agent
```

These are the backward-compatibility shims that Phase 1 was supposed to delete. **If Phase 1 has not been applied**, these still exist and `runners/__init__.py` `__all__` must not pull them in. The step plan's Task 1 wildcard audit must catch these.

### generate_id: Already Public

`generate_id` is already in `state/__init__.py`'s `__all__`. The plan proposes moving it to `state/_utils.py` and removing it from `__all__`. However:
- It is exported by the current `state/` module deliberately
- `workflow/service.py` and `workflow/transitions.py` import it (2 callers)
- No test file imports it directly outside `state/`

Moving it is valid but requires confirming callers don't import from `orchestrator.state` (top-level), since removing it from `__all__` with `from orchestrator.state import *` would break them — but explicit imports remain unaffected.

### RunWorkflow Consumers

`RunWorkflow` is referenced in:
- `src/orchestrator/workflow/runtime.py` (definition, line 51)
- `src/orchestrator/runners/executor.py` (TYPE_CHECKING import)
- `tests/integration/signal_helpers.py` (line 30 — direct import, active test helper)

Renaming to `_RunWorkflow` requires updating `executor.py` and `tests/integration/signal_helpers.py`. The test file is a non-trivial change.

### check_step_progression / check_run_completion External Callers

**These have external callers in `runners/` and `api/`:**

- `runners/executor.py` — local import, calls `check_step_progression` in `resolve_no_task_action`
- `api/routers/runs.py` — local import, calls these for condition evaluation

**Test files** (6 test files directly import these):
- `tests/unit/test_executor_state_machine.py`
- `tests/unit/test_task_transitions.py`
- `tests/unit/test_repeat_for_expansion.py`
- `tests/integration/test_repeat_for_edge_cases.py`
- `tests/integration/test_conditional_steps.py`

Adding `WorkflowService` wrapper methods is required before excluding these from `__all__`, and the test files need updating.

---

## Failure Modes and Hardening

### FM-1: Phase Prerequisites Not Met — workflow/ Still Flat

**Risk**: Step 10 plan states it depends on Phases 7–9 being complete. `workflow/` is still a flat 22-file directory with no `engine/`, `events/`, `signals/`, `agent/` sub-packages. The `workflow/__init__.py` imports from flat paths (`workflow.engine`, `workflow.events`, etc.) which are **single flat files**, not sub-packages. If Phases 7–9 haven't run, the `__all__` content specified in the step plan's Task 8 (`NoTaskReason`, `resolve_no_task_action` — described as moved from runners in Phase 7) may not exist in `workflow/`.

**Concrete failure**: Task 8 adds `NoTaskReason` to `workflow/__all__`, but `workflow/__init__.py` doesn't export it (it lives in `runners/`). Import verification fails.

**Hardening**: Begin Task 1 audit by checking whether `NoTaskReason` actually exists in `workflow/` after prior phases. If Phases 7–9 haven't been applied to the worktree, gate Step 10 on completing those phases first. Add explicit check:
```bash
grep -r "class NoTaskReason\|NoTaskReason" src/orchestrator/workflow/ --include="*.py"
```
If this returns zero results, Phases 7–9 are not complete and Step 10 cannot proceed.

---

### FM-2: `RunWorkflow` Location Mismatch

**Risk**: Plan's Task 5 says "likely in `workflow/signals/runtime.py`" but it's actually in `workflow/runtime.py` (flat file). After Phase 7, it may move to a sub-package, but in the current state the rename or exclusion must target the correct file.

**Concrete failure**: Agent searches `workflow/signals/runtime.py`, finds nothing, declares the rename done without actually doing it.

**Hardening**: Task 5 should start with an explicit locate step:
```bash
grep -rn "class RunWorkflow" src/orchestrator/workflow/ --include="*.py"
```
Use the actual file returned, not the path assumed in the plan. Document the actual location.

---

### FM-3: BroadcastCallback Protocol Scope Too Broad

**Risk**: Plan suggests the protocol may need multiple methods. The audit shows runners only call `broadcast_event` — not `broadcast_to_run`, `connect`, or `disconnect`. If the protocol is over-specified (adds methods runners don't call), it adds unnecessary coupling and may not be satisfied by a minimal mock in tests.

**Concrete failure**: Tests that mock `BroadcastCallback` must implement all methods in the protocol. Over-specified protocols create test-writing burden and can mask genuine narrowing.

**Hardening**: Task 2 must explicitly document after the audit: "runners only call `broadcast_event`. Protocol declares exactly one method." Resist the temptation to add other `ConnectionManager` methods "for completeness."

---

### FM-4: TYPE_CHECKING Import — Cross-Layer Violation Is Softer Than Stated

**Risk**: Both `executor.py` and `event_broadcaster.py` import `ConnectionManager` ONLY under `TYPE_CHECKING`. This means there is **no runtime import** of `ConnectionManager` in runners — only a type annotation reference. The plan frames this as a hard "cross-layer violation" requiring a protocol fix. However:
- Runtime behavior is already decoupled (dependency injection handles it)
- The violation is annotation-level only — mypy/pyright would still flag it as a circular/layering issue

**Concrete failure**: Agent changes runtime code paths thinking the injection is broken, when actually only the annotation needs to change. Alternatively, agent skips the task reasoning "it's just TYPE_CHECKING, no runtime impact."

**Hardening**: The task should still be done (the annotation violation is real), but framing matters. Task 3 should note: "These are annotation-only imports under TYPE_CHECKING. Replacing them with `BroadcastCallback` cleans up the layering annotation without behavior change. No adapter class needed since `ConnectionManager.broadcast_event` already matches the protocol signature."

---

### FM-5: `state/__all__` Already Contains `generate_id` — Move Creates Inconsistency

**Risk**: Currently `state/__init__.py`'s `__all__` exports `generate_id`. Task 4 moves `generate_id` to `state/_utils.py` and Task 6 is supposed to define `state/__all__` without `generate_id`. But:
- Task 6 adds `__all__` to `state/__init__.py`
- `state/__init__.py` already has `__all__` (including `generate_id`)

If Task 4 moves `generate_id` to `_utils.py` but keeps the re-import in `models.py`, and the `__all__` in `state/__init__.py` still lists `generate_id`, the current export still works. The plan's intent is to remove `generate_id` from `__all__`. But the `__init__.py` currently **already imports and exports it**.

**Concrete failure**: Task 6 "adds `__all__` to `state/__init__.py`" but `__all__` already exists — the agent should be **removing `generate_id` from the existing `__all__`**, not creating a new one. If the agent creates a second `__all__` or appends to the wrong place, you get a duplicate definition or a confused export.

**Hardening**: Task 4 and Task 6 must be coordinated:
1. Task 4: move `generate_id` to `_utils.py`, keep internal `from ._utils import generate_id` in `models.py`
2. Task 6 (actually updating an existing `__all__`): remove `generate_id` from `state/__init__.py.__all__`. Since `__all__` already exists, the task is an edit, not a creation.

Verify step says: `grep "generate_id" src/orchestrator/state/__init__.py` should return zero results after Task 6.

---

### FM-6: `workflow/__all__` Already Exists — Task 8 Is an Edit, Not a Creation

**Risk**: `workflow/__init__.py` already has an explicit `__all__` with 37 symbols. Task 8 "adds `__all__` to `workflow/__init__.py`" but what it really needs to do is:
1. Remove excluded symbols (`evaluate_checklist_gate`, `evaluate_grades`, `VALID_TRANSITIONS`, internal dry-run helpers, etc.)
2. Add new symbols brought in by Phase 7 (sub-package re-exports for `NoTaskReason`, etc.)
3. Keep all genuinely public symbols

If an agent interprets "add `__all__`" as "create a new `__all__`" and overwrites the existing one with the plan's template, it will drop 37 currently-exported symbols and break all callers.

**Hardening**: Task 8 must explicitly state: "The existing `__all__` in `workflow/__init__.py` must be updated, not replaced. Read the current `__all__`, decide what to keep vs remove, and produce a diff, not a rewrite." The plan's template `__all__` is a starting point, not a verbatim replacement.

Similarly for `config/__init__.py` and `state/__init__.py` and `git/__init__.py` (all already have `__all__`).

---

### FM-7: `git/__init__.py` Exports `project_init` — Plan Wants It Excluded

**Risk**: `git/__init__.py.__all__` currently includes `InitializedProject` and `init_project` from `project_init.py`. The plan's architecture doc says `project_init` and `utils` should be excluded from `git/__all__`. Removing these from `__all__` does not break explicit imports, but if any code uses `from orchestrator.git import *`, it would stop seeing these.

More critically: callers such as `api/` or `cli/` that do `from orchestrator.git import init_project` (explicit, not wildcard) are unaffected by `__all__` changes — they continue to work. But the removal from `__all__` signals "this is internal." If the plan also intends to stop exporting these from `__init__.py`, that's a different (breaking) change.

**Hardening**: Task 7 must clarify: does removing from `__all__` mean (a) removing from `__all__` only (explicit imports still work), or (b) also removing the `from orchestrator.git.project_init import ...` line in `__init__.py`? If (b), all callers of `from orchestrator.git import init_project` break. Stick with (a) for now — narrowing `__all__` without removing the re-export.

---

### FM-8: Empty __init__.py Modules Need Full Import Setup Before __all__

**Risk**: `db/`, `envfiles/`, `runners/`, `api/`, `cli/` all have empty `__init__.py` files (no imports, no re-exports). Before adding `__all__`, the agent must first add the appropriate `from .submodule import Symbol` lines. If the agent just adds `__all__ = [...]` without importing the symbols, Python will raise `AttributeError: module has no attribute 'RunRepository'` when `from orchestrator.db import RunRepository` is called.

**Concrete failure**: `__all__` is a list of names. If those names don't exist in the module's namespace, `from module import *` raises `AttributeError`. More commonly, the module just silently doesn't export them and explicit imports like `from orchestrator.db import RunRepository` also fail.

**Hardening**: For each empty module, the task must:
1. First audit all symbols that should be public (grep for what's actually imported across the codebase)
2. Add `from .submodule import Symbol` lines to establish the namespace
3. Then add `__all__` as the list of those symbols

This is 2× the work implied by "just add `__all__`."

---

### FM-9: `runners/` Has Backward-Compat Wildcard Shims — Must Audit Before Adding __all__

**Risk**: `runners/` contains 8 wildcard-import shims (e.g., `runners/openhands.py`, `runners/parsers/`). These were supposed to be deleted in Phase 1. If they still exist when `runners/__init__.py` is written, the task must explicitly not include their re-exported symbols in `runners/__all__`. If Phase 1 hasn't run, these files exist and some code may still depend on them.

**Concrete failure**: Agent adds `__all__` to `runners/__init__.py` that includes `OpenHandsAgent` via the shim. Then Phase 1 runs and deletes the shim, breaking the `__all__` declaration and all callers who relied on `from orchestrator.runners import *`.

**Hardening**: Task 1 audit must explicitly check whether these shims still exist. If they do, mark Phase 1 as a prerequisite and document this as a blocker. The `runners/__all__` must be written assuming shims are deleted. If shims survive into Step 10, they must be deleted first (or documented as out-of-scope debt).

---

### FM-10: check_step_progression / check_run_completion Have 6 External Test Callers

**Risk**: Task 5 says "if external callers exist" — they do. Six test files import these functions directly. The task plan says to add `WorkflowService` wrapper methods and update callers. But updating 6 test files plus `runners/executor.py` and `api/routers/runs.py` is significantly more work than implied.

**Concrete failure**: Agent adds `WorkflowService` wrappers but doesn't update the 6 test files. Tests continue using the old import path, which still works (explicit imports aren't blocked by `__all__`), so tests pass — but the intended narrowing is incomplete. Future `__all__` enforcement via linting would fail.

**Hardening**: Task 5 must enumerate the exact files that need updating:
- `runners/executor.py` → use `WorkflowService.check_step_progression()` wrapper
- `api/routers/runs.py` → use `WorkflowService` wrapper
- All 6 test files → either use `WorkflowService` or keep direct import with explicit comment

The verification criterion should include:
```bash
grep -r "from orchestrator.workflow.transitions import check_step_progression\|from orchestrator.workflow import check_step_progression" src/ tests/ --include="*.py"
```

---

### FM-11: Wiring Verification — BroadcastCallback Not Exercised by Existing Tests

**Risk**: After Task 3, `executor.py` and `event_broadcaster.py` use `BroadcastCallback` type annotation instead of `ConnectionManager`. But since the original imports were `TYPE_CHECKING`-only, no runtime behavior changes — tests that don't check type annotations will still pass even if the annotation is wrong or incomplete. The protocol's correctness is not verified by the test suite.

**Concrete failure**: Agent changes annotations but the `broadcast_event` signature on the protocol doesn't match `ConnectionManager.broadcast_event` (e.g., wrong parameter name or return type). Tests pass (runtime behavior unchanged), but mypy would fail. Pre-commit's type checking would catch this only if mypy is in the hook chain.

**Hardening**: Task 10's verification should add a `mypy` check specifically on the protocol boundary:
```bash
uv run mypy src/orchestrator/runners/types.py src/orchestrator/api/websocket.py --strict
```
Or at minimum verify that `ConnectionManager` is structurally compatible with `BroadcastCallback` via a runtime check:
```python
from orchestrator.runners.types import BroadcastCallback
from orchestrator.api.websocket import ConnectionManager
import inspect
# Verify ConnectionManager has all methods declared in BroadcastCallback
```

---

### FM-12: `db/__init__.py` — What to Export When It Currently Exports Nothing?

**Risk**: `db/__init__.py` is empty. The plan proposes adding `__all__` with `RunRepository`, `TaskRepository`, `get_session`, etc. But these are not currently importable as `from orchestrator.db import RunRepository` — callers currently use the full sub-path:
```python
from orchestrator.db.repositories import RunRepository
from orchestrator.db.connection import get_session
```

If Task 7 adds `__all__` to `db/__init__.py` without first adding the `from .repositories import RunRepository` re-exports, the `__all__` declaration is dangling (symbols listed in `__all__` don't exist in the module namespace).

**Hardening**: Verify that adding re-exports to `db/__init__.py` doesn't create circular imports. The ORM models (`db/models.py`) are imported by nearly everything; if `db/__init__.py` starts importing from `db/models.py`, any module that also imports from `db/` and transitively from `db/models.py` could create import cycles. Do a circular import audit before writing any re-exports.

---

## Summary: Structural Gaps in the Step Plan

| Gap | Severity | Impact |
|-----|----------|--------|
| Plan assumes Phases 7–9 complete; they may not be in this worktree | HIGH | NoTaskReason, sub-package paths don't exist yet |
| `RunWorkflow` location wrong (not in signals/runtime.py) | HIGH | Agent searches wrong file, rename silently skipped |
| 4 of 9 modules already have `__all__` — tasks frame these as creation, not update | HIGH | Agent overwrites existing `__all__`, breaking callers |
| `generate_id` already in `state/__all__` — Task 6 must edit, not create | MEDIUM | Duplicate `__all__` definition or missed removal |
| BroadcastCallback only needs `broadcast_event` (not all ConnectionManager methods) | MEDIUM | Over-specified protocol, test mocking burden |
| Empty __init__.py modules need imports added before __all__ can be declared | MEDIUM | `__all__` with non-existent symbols raises AttributeError |
| 6 test files import `check_step_progression` directly | MEDIUM | "Fixed" without updating tests; narrowing incomplete |
| Backward-compat wildcard shims in runners/ may still exist | MEDIUM | __all__ built on top of stale shims |
| BroadcastCallback correctness not exercised by test suite | LOW | Type annotation error survives test suite |
| `git/__init__.py` includes `project_init` symbols — plan wants them excluded | LOW | Behavior-vs-annotation ambiguity; callers unaffected |

## Hardened Action List

1. **Before any changes**: Run `grep -rn "class NoTaskReason" src/orchestrator/workflow/` — if zero results, Phases 7–9 are not complete. Gate Step 10 on their completion.

2. **Task 1 audit additions**:
   - Locate `RunWorkflow` with `grep -rn "class RunWorkflow" src/orchestrator/workflow/`
   - Check whether backward-compat shims in `runners/` still exist — if yes, flag Phase 1 incomplete
   - Explicitly check which of the 9 modules already have `__all__` and note them

3. **Task 2 (BroadcastCallback)**: Protocol declares exactly one method — `async def broadcast_event(self, event: object) -> None`. Document this explicitly. Do not speculatively add `broadcast_to_run`, `connect`, or `disconnect`.

4. **Task 3 clarification**: Since existing imports are `TYPE_CHECKING`-only, this is an annotation-level change only. Add note that no runtime behavior changes. Add mypy check to Task 10 verification.

5. **Task 4 + Task 6 coordination**: State explicitly that `state/__init__.py` already has `__all__` containing `generate_id`. Task 4 must remove `generate_id` from the existing `__all__` (edit, not recreate). Task 6 verifies the edit is already done and no duplicate `__all__` exists.

6. **Task 5 (RunWorkflow / check_step_progression)**: List the exact files needing updates:
   - `runners/executor.py`, `api/routers/runs.py` (production code)
   - 6 test files (unit + integration)
   Decide upfront: update all callers to use `WorkflowService` wrappers, OR keep direct imports in test files with `# noqa` and an explicit comment.

7. **Task 6/7/8/9 for all modules with existing `__all__`**: Frame these as EDIT operations. Read the existing `__all__`, produce a diff showing what's added and what's removed, don't overwrite.

8. **Empty __init__.py modules (db, envfiles, runners, api, cli)**: For each, before declaring `__all__`:
   - Grep for all callers of `from orchestrator.{module} import ...` across codebase
   - Add matching re-exports to `__init__.py`
   - Then declare `__all__`
   - Verify no circular imports introduced

9. **Task 10 verification additions**:
   ```bash
   # Verify no duplicate __all__ definitions
   grep -c "__all__" src/orchestrator/state/__init__.py  # must be 1
   grep -c "__all__" src/orchestrator/workflow/__init__.py  # must be 1

   # Verify BroadcastCallback has exactly the methods runners call
   uv run python -c "
   from orchestrator.runners.types import BroadcastCallback
   import inspect
   methods = [m for m in dir(BroadcastCallback) if not m.startswith('_')]
   print('Protocol methods:', methods)
   "
   ```
