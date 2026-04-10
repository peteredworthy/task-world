# Step 10: Explicit __all__ + Interface Narrowing

Add explicit `__all__` declarations to all 9 module `__init__.py` files and eliminate the final cross-layer violation: `runners/executor.py` importing `ConnectionManager` directly from `api/websocket.py`. This phase is purely structural — no behavior changes. Every narrowed symbol remains importable via explicit path; `__all__` only defines the recommended public API.

This is the final phase of M3 (Internal Restructuring). It depends on Phases 7–9 being complete so that all `__init__.py` re-exports reflect the final sub-package structure before `__all__` is declared.

## Intent Verification

**Original Intent**: Phase 10 of the module consolidation plan — add `__all__` to all 9 modules, introduce `BroadcastCallback` protocol to eliminate the `runners/ → api/websocket` coupling, hide internal symbols (ORM models, `RunWorkflow`, utility functions), and move `generate_id` to an internal utility file.

**Functionality to Produce**:
- `BroadcastCallback` runtime protocol defined in `runners/types.py`; `executor.py` and `execution/event_broadcaster.py` use the protocol type instead of `ConnectionManager`
- `api/deps.py` wires a `ConnectionManager`-compatible adapter so the protocol is satisfied at startup
- `generate_id` moved from `state/models.py` to `state/_utils.py`; all internal callers updated
- `RunWorkflow` excluded from `workflow/__all__` (made private or removed from public surface)
- `check_step_progression` and `check_run_completion` wrapped behind `WorkflowService` methods if any external caller exists; excluded from `workflow/__all__`
- All 9 modules (`config/`, `state/`, `db/`, `git/`, `envfiles/`, `workflow/`, `runners/`, `api/`, `cli/`) have explicit `__all__` in their `__init__.py`
- ORM models (`RunModel`, `StepModel`, etc.) excluded from `db/__all__`
- Internal utilities (`project_init.py`, `utils.py`, `security.py`, `versioning.py`, `AGENT_CONFIG_FIELDS`) excluded from respective `__all__` lists

**Final Verification Criteria**:
- All backend unit and integration tests pass
- All frontend tests pass
- `grep -l "__all__" src/orchestrator/*/__init__.py` returns exactly 9 files
- `grep -r "from orchestrator.api.websocket import ConnectionManager" src/orchestrator/runners/` returns zero results
- `grep -r "from orchestrator.db.models import" src/ tests/ --include="*.py" | grep -v "src/orchestrator/db/"` returns zero results
- `grep -r "from orchestrator.state.models import generate_id" src/ tests/ --include="*.py" | grep -v "src/orchestrator/state/"` returns zero results
- Pre-commit hooks pass

---

## Task 1: Audit Wildcard Imports and ConnectionManager Usage

**Description**:
Before making any changes, map the exact scope of work: find all `from orchestrator.X import *` usages (which `__all__` will affect directly) and all `ConnectionManager` method calls inside `runners/` (which determines the protocol surface). This task produces no file changes — only a verified understanding of what needs changing.

**Implementation Plan (Do These Steps)**

- [ ] Find all wildcard imports from orchestrator modules in the entire codebase:
```bash
grep -r "from orchestrator\." src/ tests/ scripts/ --include="*.py" | grep "import \*"
```
Record any results. If any wildcard imports exist, they must be resolved before `__all__` narrows anything.

- [ ] Find all `ConnectionManager` imports inside `runners/`:
```bash
grep -r "ConnectionManager" src/orchestrator/runners/ --include="*.py" -n
```
Record each file and line. These are the exact sites that must switch to `BroadcastCallback`.

- [ ] Find all methods called on `ConnectionManager` instances inside `runners/`:
```bash
grep -r "\.broadcast\|\.send\|\.connect\|\.disconnect\|\.manager\." src/orchestrator/runners/ --include="*.py" -n
```
This defines the minimum method surface the `BroadcastCallback` protocol must declare.

- [ ] Find all external callers of `check_step_progression` and `check_run_completion` outside `workflow/`:
```bash
grep -r "check_step_progression\|check_run_completion" src/ tests/ --include="*.py" | grep -v "src/orchestrator/workflow/"
```
If any exist, `WorkflowService` wrapper methods are required before those functions are hidden.

- [ ] Find all external callers of `RunWorkflow` outside `runners/` and `workflow/`:
```bash
grep -r "RunWorkflow" src/ tests/ --include="*.py" | grep -v "src/orchestrator/workflow/\|src/orchestrator/runners/"
```

- [ ] Find all callers of `generate_id` outside `state/`:
```bash
grep -r "generate_id" src/ tests/ --include="*.py" | grep -v "src/orchestrator/state/"
```
Record each site — they must be updated in Task 4.

**Constraints**:
- This task makes zero file changes. If you find yourself editing a file, stop.

**Functionality (Expected Outcomes)**:
- [ ] A complete list of wildcard imports (expected: zero or near-zero)
- [ ] The exact set of files in `runners/` that import `ConnectionManager` and the methods they call
- [ ] Knowledge of whether `check_step_progression`/`check_run_completion` have external callers
- [ ] Knowledge of whether `RunWorkflow` has external callers
- [ ] A list of all `generate_id` call sites outside `state/`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Grep commands above have been run and results recorded (even if empty)
- [ ] No file has been modified

---

## Task 2: Define BroadcastCallback Protocol in runners/types.py

**Description**:
Define a `BroadcastCallback` Protocol in `runners/types.py` that covers exactly the WebSocket broadcast methods called by `executor.py` and `execution/event_broadcaster.py`. This protocol lets runners depend on an abstract callback interface rather than the concrete `ConnectionManager` from `api/`.

**Implementation Plan (Do These Steps)**

- [ ] Read `src/orchestrator/runners/types.py` to understand the current content:
```bash
# Read the file to see what's already there
```

- [ ] Read `src/orchestrator/api/websocket.py` to understand `ConnectionManager`'s method signatures for the methods identified in Task 1:
```bash
# Read the file and note the signatures of broadcast/send methods
```

- [ ] Add the `BroadcastCallback` protocol to `runners/types.py`. Based on the architecture doc, the protocol covers the broadcast method used by runners. Add it after any existing type definitions:
```python
from typing import Protocol, Any

class BroadcastCallback(Protocol):
    """Protocol for broadcasting run events to connected WebSocket clients.

    Runners depend on this protocol rather than the concrete ConnectionManager
    from api/, preserving the Execution → Interface layering boundary.
    """

    async def broadcast(self, run_id: str, message: dict[str, Any]) -> None:
        """Broadcast a message to all clients subscribed to a run."""
        ...
```
Adjust the method signature to exactly match what `ConnectionManager` provides and what runners actually call (as identified in Task 1). If runners call additional methods, add them to the protocol.

**Constraints**:
- Only edit `runners/types.py`. No other files.
- Do not import from `api/` in `runners/types.py`.
- The protocol must be structural (use `Protocol`) not a ABC/base class.
- Only declare methods that runners actually call — do not speculatively add methods.

**Functionality (Expected Outcomes)**:
- [ ] `BroadcastCallback` protocol defined in `runners/types.py`
- [ ] Protocol methods exactly match the interface runners use (from Task 1 audit)
- [ ] `runners/types.py` has no imports from `api/`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.runners.types import BroadcastCallback; print('ok')"` succeeds
- [ ] `grep "from orchestrator.api" src/orchestrator/runners/types.py` returns zero results
- [ ] `grep "class BroadcastCallback" src/orchestrator/runners/types.py` returns one result

---

## Task 3: Refactor executor.py and event_broadcaster.py to Use BroadcastCallback

**Description**:
Replace `ConnectionManager` references in `runners/executor.py` and `runners/execution/event_broadcaster.py` with `BroadcastCallback`. Wire a compatible adapter in `api/deps.py` so `ConnectionManager` satisfies the protocol at injection time (structural subtyping — no adapter class needed since `ConnectionManager` already implements the same methods).

**Implementation Plan (Do These Steps)**

- [ ] Read `src/orchestrator/runners/executor.py` to find all `ConnectionManager` references:
```bash
grep -n "ConnectionManager\|websocket" src/orchestrator/runners/executor.py
```

- [ ] Read `src/orchestrator/runners/execution/event_broadcaster.py` to find all `ConnectionManager` references:
```bash
grep -n "ConnectionManager\|websocket" src/orchestrator/runners/execution/event_broadcaster.py
```

- [ ] In `executor.py`: replace the `from orchestrator.api.websocket import ConnectionManager` import with `from orchestrator.runners.types import BroadcastCallback`. Update the type annotation of the parameter/attribute that held `ConnectionManager` to `BroadcastCallback`.

- [ ] In `event_broadcaster.py`: same replacement — swap the import and update the type annotation.

- [ ] Read `src/orchestrator/api/deps.py` to see how `ConnectionManager` is currently injected:
```bash
grep -n "ConnectionManager\|broadcast\|manager" src/orchestrator/api/deps.py
```
Verify that `deps.py` passes a `ConnectionManager` instance to `executor.py` or `event_broadcaster.py`. Since `ConnectionManager` already implements the methods declared in `BroadcastCallback`, no adapter class is needed — structural subtyping handles it. Add a comment if helpful:
```python
# ConnectionManager satisfies BroadcastCallback protocol via structural subtyping
```

- [ ] Confirm no `ConnectionManager` imports remain in runners:
```bash
grep -r "from orchestrator.api.websocket import ConnectionManager" src/orchestrator/runners/ --include="*.py"
```
Must return zero lines.

**Constraints**:
- Only edit `executor.py`, `event_broadcaster.py`, and `deps.py` (up to 3 files).
- Do not change any behavior — only change type annotations and imports.
- Do not add an adapter class unless `ConnectionManager` genuinely doesn't satisfy the protocol.

**Side Effects**:
- If `ConnectionManager` is missing a method declared in `BroadcastCallback`, this task will expose it. In that case: either remove the method from the protocol (Task 2) or add it to `ConnectionManager`.

**Functionality (Expected Outcomes)**:
- [ ] `executor.py` imports `BroadcastCallback` from `runners.types`, not `ConnectionManager` from `api.websocket`
- [ ] `event_broadcaster.py` imports `BroadcastCallback` from `runners.types`, not `ConnectionManager`
- [ ] `api/deps.py` passes a `ConnectionManager` instance where `BroadcastCallback` is now expected (no behavior change)
- [ ] No `from orchestrator.api.websocket import ConnectionManager` remains in `runners/`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "from orchestrator.api.websocket import ConnectionManager" src/orchestrator/runners/` returns zero results
- [ ] `uv run python -c "from orchestrator.runners.executor import Executor; print('ok')"` succeeds (adjust class name to actual)
- [ ] `uv run pytest tests/unit/ -q --tb=short -x` passes (no import errors introduced)

---

## Task 4: Move generate_id to state/_utils.py

**Description**:
`generate_id` is a utility function (generates a random UUID string) that lives in `state/models.py` but is not a domain concept. Moving it to `state/_utils.py` removes it from the public interface of `state/`. All callers inside `state/` and outside will import from the new location.

**Implementation Plan (Do These Steps)**

- [ ] Read `src/orchestrator/state/models.py` to find the `generate_id` definition and identify which other functions in the same file call it:
```bash
grep -n "generate_id\|def generate_id" src/orchestrator/state/models.py
```

- [ ] Create `src/orchestrator/state/_utils.py` with the `generate_id` function extracted from `models.py`:
```python
"""Internal utilities for state module. Not part of the public API."""

import uuid


def generate_id() -> str:
    """Generate a random unique identifier."""
    return str(uuid.uuid4())
```
Adjust the implementation to match what currently exists in `models.py`.

- [ ] In `src/orchestrator/state/models.py`: remove the `generate_id` definition and add an import from `._utils`:
```python
from orchestrator.state._utils import generate_id
```
Keep this internal import in `models.py` so existing code in the state module that calls `generate_id` continues to work without changes.

- [ ] Update all callers *outside* `state/` that import `generate_id` directly from `state.models` or `state` (from the list produced in Task 1). For each:
```python
# Old:
from orchestrator.state.models import generate_id
# or:
from orchestrator.state import generate_id

# New (for external callers — they should use the internal location):
from orchestrator.state._utils import generate_id
```
Note: since `generate_id` is an internal utility, external callers should ideally not use it at all. If they do, redirecting them to `_utils` is acceptable.

**Constraints**:
- Only create/edit `state/_utils.py`, `state/models.py`, and any external caller files identified in Task 1 (at most 4–5 files total).
- Do not change the function's behavior.
- Do not expose `_utils` in `state/__init__.py`.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/state/_utils.py` exists and contains `generate_id`
- [ ] `src/orchestrator/state/models.py` no longer defines `generate_id` (imports it from `_utils`)
- [ ] All external callers updated to import from `orchestrator.state._utils`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -n "def generate_id" src/orchestrator/state/models.py` returns zero results
- [ ] `uv run python -c "from orchestrator.state._utils import generate_id; print(generate_id())"` succeeds and prints a UUID
- [ ] `uv run python -c "from orchestrator.state.models import generate_id; print('ok')"` succeeds (re-export still works internally)
- [ ] `uv run pytest tests/unit/ -q --tb=short -x` passes

---

## Task 5: Hide RunWorkflow and Wrap check_step_progression / check_run_completion

**Description**:
`RunWorkflow` is an implementation detail of the executor loop and should not be part of the public `workflow/` API. `check_step_progression` and `check_run_completion` are internal engine functions; if any external callers exist, they get `WorkflowService` wrapper methods before being hidden.

**Implementation Plan (Do These Steps)**

- [ ] Read the current definition of `RunWorkflow` (after Phase 7 restructuring, likely in `workflow/signals/runtime.py` or similar). Rename it to `_RunWorkflow` if it is only used internally within `workflow/` and `runners/`:
```bash
grep -rn "RunWorkflow" src/orchestrator/ --include="*.py"
```
If only `executor.py` and internal `workflow/` files reference it, rename the class to `_RunWorkflow` in its definition file and update those callers. If external test files reference it, update them too.

- [ ] Review the results from Task 1 for external callers of `check_step_progression` and `check_run_completion`. For each external caller:
  - If the caller is in `api/` or `cli/`, add a `WorkflowService` method that delegates to the internal function.
  - If the caller is in `tests/`, update the test to use `WorkflowService` (preferred) or continue importing the internal function directly with a comment.

- [ ] If `WorkflowService` wrapper methods are needed, add them to `src/orchestrator/workflow/service.py`:
```python
def get_step_progression_status(self, run: RunState) -> StepProgressionResult:
    """Public API for checking whether a step should advance.

    Delegates to the internal check_step_progression engine function.
    """
    from orchestrator.workflow.engine.transitions import check_step_progression
    return check_step_progression(run)
```
Adjust types to match the actual signatures.

**Constraints**:
- Edit at most 3 files: the file containing `RunWorkflow`/`_RunWorkflow`, `workflow/service.py` (if wrappers needed), and `runners/executor.py` (if it references `RunWorkflow` by name).
- Do not change behavior.
- If `RunWorkflow` renaming would require changes to more than 4 files, keep the old name and simply exclude it from `__all__` in Task 8 instead of renaming.

**Functionality (Expected Outcomes)**:
- [ ] `RunWorkflow` is either renamed to `_RunWorkflow` or confirmed as excluded from `workflow/__all__` (Task 8)
- [ ] No external caller invokes `check_step_progression`/`check_run_completion` directly without going through `WorkflowService` (or a documented exception in tests)

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "class RunWorkflow\b" src/orchestrator/workflow/` returns zero results (renamed to `_RunWorkflow`) OR the symbol will simply not appear in `workflow/__all__` (either outcome is acceptable — document which)
- [ ] `uv run pytest tests/unit/ -q --tb=short -x` passes

---

## Task 6: Add __all__ to config/, state/, and envfiles/

**Description**:
Declare `__all__` in the `__init__.py` of the three foundation/infrastructure modules: `config/`, `state/`, and `envfiles/`. These are low-dependency modules with well-understood public surfaces.

**Implementation Plan (Do These Steps)**

- [ ] Read `src/orchestrator/config/__init__.py` to see what is currently exported:
```bash
grep -n "^from\|^import\|__all__" src/orchestrator/config/__init__.py
```

- [ ] Add `__all__` to `src/orchestrator/config/__init__.py`. Include public enums, config models (including `NudgerConfig`, `EnvFileSpec` after Phase 0 moves), `GlobalConfig`, `get_global_config`. Exclude `routines/versioning` internal symbols:
```python
__all__ = [
    # Enums
    "AgentType",
    "TaskStatus",
    # ... other public enums from enums.py
    # Config models
    "NudgerConfig",
    "EnvFileSpec",
    # Global config
    "GlobalConfig",
    "get_global_config",
    # Routine loading (public entry points only)
    "load_routine",
    "discover_routines",
]
```
Adjust based on what `config/__init__.py` actually exports after Phase 0–3.

- [ ] Read `src/orchestrator/state/__init__.py` and add `__all__`. Include domain models (`RunState`, `TaskState`, `AttemptState`, etc.), factory functions, session. Exclude `_utils`:
```python
__all__ = [
    "RunState",
    "TaskState",
    "AttemptState",
    # ... other public state models
    "create_run_state",  # factory
    "StateSession",
    # errors
    "StateError",
]
```

- [ ] Read `src/orchestrator/envfiles/__init__.py` and add `__all__`. Include lifecycle, store, resolution, models. Exclude `security` (internal):
```python
__all__ = [
    "EnvFileLifecycle",
    "EnvFileStore",
    "resolve_env_files",
    # models
    "EnvFile",
    "EnvFileContent",
]
```

**Constraints**:
- Only edit the three `__init__.py` files.
- Do not add or remove re-exports from `__init__.py` — only add the `__all__` declaration for what is already exported.
- `__all__` must be a list of strings.

**Functionality (Expected Outcomes)**:
- [ ] `config/__init__.py` has `__all__` with public config symbols
- [ ] `state/__init__.py` has `__all__` with domain model symbols
- [ ] `envfiles/__init__.py` has `__all__` with lifecycle/store symbols
- [ ] `generate_id` is NOT in `state/__all__` (it's internal)
- [ ] `security` module symbols are NOT in `envfiles/__all__`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "__all__" src/orchestrator/config/__init__.py src/orchestrator/state/__init__.py src/orchestrator/envfiles/__init__.py` returns 3 matches (one per file)
- [ ] `uv run python -c "import orchestrator.config as m; print(m.__all__)"` prints the list without error
- [ ] `uv run python -c "import orchestrator.state as m; print(m.__all__)"` prints the list without error
- [ ] `uv run pytest tests/unit/ -q --tb=short -x` passes

---

## Task 7: Add __all__ to db/ and git/

**Description**:
Declare `__all__` for `db/` and `git/` — two infrastructure modules with internal sub-packages after Phases 7–9. The key constraint for `db/` is that ORM model classes must be excluded from `__all__`; external callers must use repository methods.

**Implementation Plan (Do These Steps)**

- [ ] Read `src/orchestrator/db/__init__.py` to see current exports after Phase 8 restructuring:
```bash
grep -n "^from\|^import\|__all__" src/orchestrator/db/__init__.py
```

- [ ] Add `__all__` to `src/orchestrator/db/__init__.py`. Include session factories and repository classes. Exclude ORM model classes (`RunModel`, `StepModel`, `TaskModel`, `AttemptModel`, etc.):
```python
__all__ = [
    # Session factories
    "get_session",
    "get_async_session",
    # Repositories
    "RunRepository",
    "TaskRepository",
    "AttemptRepository",
    "EventStore",
    # Recovery
    "EventJournal",
    "recover_from_journal",
]
```
Do NOT include `RunModel`, `StepModel`, `TaskModel`, `AttemptModel`, `Base`, or other ORM internals.

- [ ] Verify that no file outside `db/` currently imports ORM models directly (these would break at runtime if `db/__all__` excludes them, but only under `import *` — explicit imports still work). Flag any external ORM importers as future cleanup:
```bash
grep -r "from orchestrator\.db.*import.*Model\b" src/ tests/ --include="*.py" | grep -v "src/orchestrator/db/"
```
If results exist, add a comment in `db/__init__.py` noting them as technical debt (do not fix them now — fixing ORM access patterns is separate work).

- [ ] Read `src/orchestrator/git/__init__.py` and add `__all__`. Include worktree operations, public diff/repos APIs. Exclude `project_init`, `utils` (internal utilities):
```python
__all__ = [
    # Worktree
    "WorktreeManager",
    "create_worktree",
    "delete_worktree",
    # Diff API (from git/diff/)
    "get_diff",
    "CommitInfo",
    "FileStatus",
    "ModifiedFile",
    # Repos API (from git/repos/)
    "discover_repos",
    "RepoInfo",
    # Testing (from git/testing/)
    "run_tests",
]
```
Adjust based on what `git/__init__.py` actually exports after Phase 2 absorption.

**Constraints**:
- Only edit `db/__init__.py` and `git/__init__.py`.
- ORM model classes must not appear in `db/__all__`.
- `project_init` and `utils` symbols must not appear in `git/__all__`.

**Functionality (Expected Outcomes)**:
- [ ] `db/__init__.py` has `__all__` with repository/session symbols only (no ORM models)
- [ ] `git/__init__.py` has `__all__` with worktree, diff, repos public symbols
- [ ] `project_init` and `utils` are not in `git/__all__`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "__all__" src/orchestrator/db/__init__.py src/orchestrator/git/__init__.py` returns 2 matches
- [ ] `uv run python -c "import orchestrator.db as m; assert 'RunModel' not in m.__all__; print('ok')"` succeeds
- [ ] `uv run python -c "import orchestrator.git as m; assert 'project_init' not in str(m.__all__); print('ok')"` succeeds
- [ ] `uv run pytest tests/unit/ -q --tb=short -x` passes

---

## Task 8: Add __all__ to workflow/ and runners/

**Description**:
Declare `__all__` for `workflow/` and `runners/` — the two largest modules. Key exclusions: `_RunWorkflow` (private after Task 5), internal engine functions `check_step_progression`/`check_run_completion`, `AGENT_CONFIG_FIELDS` (runners internal), and internal detection utilities.

**Implementation Plan (Do These Steps)**

- [ ] Read `src/orchestrator/workflow/__init__.py` to see current exports after Phase 7 restructuring:
```bash
grep -n "^from\|^import\|__all__" src/orchestrator/workflow/__init__.py
```

- [ ] Add `__all__` to `src/orchestrator/workflow/__init__.py`. Include `WorkflowService`, public engine types, event types, signal types, `NoTaskReason`/`resolve_no_task_action` (moved from runners in Phase 7). Exclude `_RunWorkflow`, `check_step_progression`, `check_run_completion`, `GradeSnapshotItem`:
```python
__all__ = [
    # Primary service
    "WorkflowService",
    # Engine types
    "WorkflowEngine",
    "GateBlockedError",
    # Events
    "WorkflowEvent",
    "RunStatusChanged",
    "TaskStatusChanged",
    # Signals
    "NoTaskReason",
    "resolve_no_task_action",
    # Locks
    "LockManager",
    "LockTimeoutError",
    # Artifacts (from workflow/artifacts/)
    "ArtifactRegistry",
    "Artifact",
]
```
Do NOT include `_RunWorkflow`, `check_step_progression`, `check_run_completion`, `GradeSnapshotItem`.

- [ ] Read `src/orchestrator/runners/__init__.py` and add `__all__`. Include `Executor`, `Agent` protocol/interface, `BroadcastCallback`, public error types. Exclude `AGENT_CONFIG_FIELDS`, internal detection/profile utilities:
```python
__all__ = [
    # Core
    "Executor",
    # Agent protocol
    "Agent",
    "AgentMetadataCallback",
    # Protocol types
    "BroadcastCallback",
    # Errors
    "AgentNotAvailableError",
    "AgentExecutionError",
    "AgentCancelledError",
    # Scaffolding (public entry points)
    "setup_workspace",
]
```
Do NOT include `AGENT_CONFIG_FIELDS`, `AgentDetector` internal config utilities, or internal profile resolution details.

**Constraints**:
- Only edit `workflow/__init__.py` and `runners/__init__.py`.
- `_RunWorkflow` (or `RunWorkflow` if not renamed) must not appear in `workflow/__all__`.
- `check_step_progression` and `check_run_completion` must not appear in `workflow/__all__`.
- `AGENT_CONFIG_FIELDS` must not appear in `runners/__all__`.

**Functionality (Expected Outcomes)**:
- [ ] `workflow/__init__.py` has `__all__` excluding internal engine functions and `_RunWorkflow`
- [ ] `runners/__init__.py` has `__all__` with public executor/agent surface, excluding `AGENT_CONFIG_FIELDS`
- [ ] `BroadcastCallback` appears in `runners/__all__`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep "__all__" src/orchestrator/workflow/__init__.py src/orchestrator/runners/__init__.py` returns 2 matches
- [ ] `uv run python -c "import orchestrator.workflow as m; assert 'check_step_progression' not in m.__all__; print('ok')"` succeeds
- [ ] `uv run python -c "import orchestrator.runners as m; assert 'AGENT_CONFIG_FIELDS' not in m.__all__; assert 'BroadcastCallback' in m.__all__; print('ok')"` succeeds
- [ ] `uv run pytest tests/unit/ -q --tb=short -x` passes

---

## Task 9: Add __all__ to api/ and cli/

**Description**:
Declare `__all__` for the two interface-layer modules: `api/` and `cli/`. These are entry points — their public surfaces are narrow (the app factory and CLI entry points). Internal routers and schemas are not part of `__all__`.

**Implementation Plan (Do These Steps)**

- [ ] Read `src/orchestrator/api/__init__.py` to see current exports:
```bash
grep -n "^from\|^import\|__all__" src/orchestrator/api/__init__.py
```

- [ ] Add `__all__` to `src/orchestrator/api/__init__.py`. The public surface of `api/` is just the app factory used by `scripts/serve.py` and the CLI:
```python
__all__ = [
    "app",
    "create_app",
]
```
Internal routers, schemas, deps, auth, errors, websocket internals are not included. If `api/__init__.py` re-exports nothing (common for FastAPI apps), `__all__` can be `[]` with a comment explaining the module is used via its `app` object at `api.app`.

- [ ] Read `src/orchestrator/cli/__init__.py` to see current exports:
```bash
grep -n "^from\|^import\|__all__" src/orchestrator/cli/__init__.py
```

- [ ] Add `__all__` to `src/orchestrator/cli/__init__.py`. Include the CLI entry point (the Typer app or click group):
```python
__all__ = [
    "cli",  # The Typer/Click app
]
```
Adjust based on what `cli/__init__.py` actually exports.

- [ ] Verify all 9 modules now have `__all__`:
```bash
grep -l "__all__" src/orchestrator/config/__init__.py \
    src/orchestrator/state/__init__.py \
    src/orchestrator/db/__init__.py \
    src/orchestrator/git/__init__.py \
    src/orchestrator/envfiles/__init__.py \
    src/orchestrator/workflow/__init__.py \
    src/orchestrator/runners/__init__.py \
    src/orchestrator/api/__init__.py \
    src/orchestrator/cli/__init__.py
```
Must return 9 file paths.

**Constraints**:
- Only edit `api/__init__.py` and `cli/__init__.py`.
- Internal router/schema modules (`api/routers/`, `api/schemas/`) must not appear in `api/__all__`.

**Functionality (Expected Outcomes)**:
- [ ] `api/__init__.py` has `__all__` exposing only the app factory / app object
- [ ] `cli/__init__.py` has `__all__` exposing only the CLI entry point
- [ ] All 9 module `__init__.py` files have `__all__`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -l "__all__" src/orchestrator/config/__init__.py src/orchestrator/state/__init__.py src/orchestrator/db/__init__.py src/orchestrator/git/__init__.py src/orchestrator/envfiles/__init__.py src/orchestrator/workflow/__init__.py src/orchestrator/runners/__init__.py src/orchestrator/api/__init__.py src/orchestrator/cli/__init__.py | wc -l` prints `9`
- [ ] `uv run python -c "import orchestrator.api as m; print(m.__all__)"` succeeds without error
- [ ] `uv run python -c "import orchestrator.cli as m; print(m.__all__)"` succeeds without error

---

## Task 10: Full Test Suite and Final Reference Audit

**Description**:
Run the complete test suite, verify all `__all__` declarations are correct, confirm the `ConnectionManager` cross-layer violation is fully resolved, and run pre-commit hooks. This is the gate check before Phase 10 is considered complete and M3 is closed.

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

- [ ] If any test failures occur due to `__all__` changes or import refactoring, fix the specific import site and re-run. Do not relax `__all__` to fix failures — fix the caller instead.

- [ ] Confirm zero `ConnectionManager` imports remain in runners:
```bash
grep -r "from orchestrator.api.websocket import ConnectionManager" src/orchestrator/runners/ --include="*.py" || echo "OK: zero violations"
```

- [ ] Confirm ORM models are not imported from outside `db/`:
```bash
grep -r "from orchestrator\.db.*import.*Model\b" src/ tests/ --include="*.py" | grep -v "src/orchestrator/db/" || echo "OK: no external ORM model imports"
```
Note: if any exist, add a comment in the db/__init__.py noting them as future cleanup. Do not block this phase on cleaning them up.

- [ ] Confirm all 9 `__init__.py` files have `__all__`:
```bash
grep -l "__all__" \
    src/orchestrator/config/__init__.py \
    src/orchestrator/state/__init__.py \
    src/orchestrator/db/__init__.py \
    src/orchestrator/git/__init__.py \
    src/orchestrator/envfiles/__init__.py \
    src/orchestrator/workflow/__init__.py \
    src/orchestrator/runners/__init__.py \
    src/orchestrator/api/__init__.py \
    src/orchestrator/cli/__init__.py
```

- [ ] Verify sub-package access discipline — no file outside a module imports from its sub-packages directly:
```bash
# Example: external code should not import from orchestrator.workflow.engine.transitions
# It should import from orchestrator.workflow
grep -r "from orchestrator\.\(config\|state\|db\|git\|envfiles\|workflow\|runners\|api\|cli\)\." src/ tests/ --include="*.py" | grep -v "src/orchestrator/" | head -20
```
Any matches represent callers that bypass the top-level module interface. Review each — if the sub-package import is unavoidable (e.g., for testing internals), add a comment. The goal is zero matches outside tests.

- [ ] Check for any residual shim/stub markers introduced during this phase:
```bash
grep -r "shim\|stub\|backward.compat\|backward_compat" src/orchestrator/ --include="*.py" || echo "OK: no shim markers"
```

- [ ] Run pre-commit hooks:
```bash
uv run pre-commit run --all-files
```

**Functionality (Expected Outcomes)**:
- [ ] All backend unit and integration tests pass
- [ ] All frontend tests pass
- [ ] Exactly 9 `__init__.py` files have `__all__`
- [ ] Zero `ConnectionManager` imports in `runners/`
- [ ] No shim markers in orchestrator source
- [ ] Pre-commit hooks pass

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -q` exits with code 0
- [ ] `cd ui && npx vitest run` exits with code 0
- [ ] `grep -l "__all__" src/orchestrator/config/__init__.py src/orchestrator/state/__init__.py src/orchestrator/db/__init__.py src/orchestrator/git/__init__.py src/orchestrator/envfiles/__init__.py src/orchestrator/workflow/__init__.py src/orchestrator/runners/__init__.py src/orchestrator/api/__init__.py src/orchestrator/cli/__init__.py | wc -l` prints `9`
- [ ] `grep -r "from orchestrator.api.websocket import ConnectionManager" src/orchestrator/runners/ --include="*.py"` returns zero lines
- [ ] `uv run python -c "from orchestrator.workflow import WorkflowService; print('ok')"` succeeds
- [ ] `uv run python -c "import orchestrator.workflow as m; assert 'check_step_progression' not in m.__all__; print('ok')"` succeeds
- [ ] `uv run python -c "import orchestrator.runners as m; assert 'BroadcastCallback' in m.__all__; print('ok')"` succeeds
- [ ] `uv run pre-commit run --all-files` exits with code 0
- [ ] `git --no-pager diff --stat HEAD` shows changes across `runners/types.py`, `runners/executor.py`, `runners/execution/event_broadcaster.py`, `state/_utils.py`, and the 9 `__init__.py` files
