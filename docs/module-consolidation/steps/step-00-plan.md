# Step 0: Resolve Couplings C1–C6

Fix all 6 anomalous cross-layer coupling violations identified in the architecture document. Each coupling is an upward import — a lower-layer module importing from a higher-layer module. This step relocates type definitions and introduces a protocol abstraction to eliminate all 6 violations, establishing clean layering before any file moves in later phases.

No files are moved between modules in this step — only type definitions are relocated within the existing module structure, and import statements are updated to match. Every change is a pure relocation with zero behavioral change.

## Intent Verification

**Original Intent**: Phase 0 from `docs/module-consolidation/plan.md` — "Resolve Couplings C1–C6 (M1 core)"

**Functionality to Produce**:
- `NudgerConfig` is defined in `config/models.py`; `runners/nudger.py` imports it from there
- `CommitInfo`, `FileStatus`, `ModifiedFile` are defined in `git/diff_models.py`; all consumers import from there
- `ActionLog` and its supporting types are defined in `state/models.py`; `runners/action_log.py` is deleted or imports nothing from `state/`
- `EnvFileSpec` is defined in `config/models.py`; `envfiles/models.py` and `state/models.py` import from there
- `RecoveryResult` dataclass is defined in `workflow/service.py`; `workflow/service.recover_run()` returns it; `api/routers/runs.py` translates it to `RecoverResponse`
- `TaskSubmitCallback` protocol is defined in `runners/types.py`; `UserManagedAgent` accepts it instead of `WorkflowService`; injection is wired in `api/deps.py`

**Final Verification Criteria**:
- All backend unit and integration tests pass
- `grep -r "from orchestrator.runners.nudger import NudgerConfig" src/` → zero results
- `grep -r "from orchestrator.review.models import" src/orchestrator/git/` → zero results
- `grep -r "from orchestrator.runners.action_log import ActionLog" src/` → zero results
- `grep -r "from orchestrator.envfiles.models import EnvFileSpec" src/orchestrator/state/` → zero results
- `grep -r "from orchestrator.api.schemas" src/orchestrator/workflow/` → zero results
- `grep -r "from orchestrator.workflow.service import WorkflowService" src/orchestrator/runners/` → zero results

---

## Task 1: C1 — Move NudgerConfig to config/models.py

**Description**: `config/global_config.py` imports `NudgerConfig` from `runners.nudger`, which is a Foundation → Execution upward import. Moving `NudgerConfig` into `config/models.py` makes it available to `global_config.py` without any upward import. `runners/nudger.py` then imports it from `config.models` instead of defining it locally.

**Implementation Plan (Do These Steps)**

- [ ] Find all files that import `NudgerConfig` from `runners.nudger`:
  ```bash
  grep -rn "from orchestrator.runners.nudger import NudgerConfig\|from orchestrator.runners import.*NudgerConfig" src/ tests/
  ```

- [ ] Read `runners/nudger.py` to locate the full `NudgerConfig` definition (class body, fields, validators, any imports it needs).

- [ ] Read `config/models.py` to find a suitable insertion point (end of file or near other config dataclasses).

- [ ] Add `NudgerConfig` to `config/models.py`. Include any imports required by the class (e.g., `timedelta` from `datetime`, `dataclass` from `dataclasses`). Do not change the class definition in any way — pure copy.

- [ ] In `runners/nudger.py`: replace the `NudgerConfig` class definition with an import from `config.models`:
  ```python
  from orchestrator.config.models import NudgerConfig
  ```
  Remove any imports that were only needed to support the `NudgerConfig` definition.

- [ ] In `config/global_config.py`: update the import of `NudgerConfig` to come from `config.models` (not `runners.nudger`):
  ```python
  from orchestrator.config.models import NudgerConfig
  ```

- [ ] Update any other files found in the grep above.

- [ ] Run `uv run python -c "from orchestrator.config.models import NudgerConfig; from orchestrator.runners.nudger import NudgerConfig"` to confirm both import paths resolve correctly (nudger re-exports from config).

**Constraints**
- Do not change `NudgerConfig`'s fields, types, or validators — pure relocation only.
- Do not touch any other class in `runners/nudger.py`.

**Functionality (Expected Outcomes)**
- [ ] `NudgerConfig` is defined exactly once, in `config/models.py`
- [ ] `runners/nudger.py` imports `NudgerConfig` from `config.models`
- [ ] `config/global_config.py` imports `NudgerConfig` from `config.models`
- [ ] No file imports `NudgerConfig` from `runners.nudger` or `runners`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "from orchestrator.runners.nudger import NudgerConfig" src/ tests/` → zero results
- [ ] `grep -rn "NudgerConfig" src/orchestrator/config/models.py` → at least one result (the definition)
- [ ] `uv run pytest tests/unit/ -x -q 2>&1 | tail -5` — passes with no errors related to NudgerConfig

---

## Task 2: C2 — Create git/diff_models.py with review type definitions

**Description**: `git/diff_ops.py` imports `CommitInfo`, `FileStatus`, and `ModifiedFile` from `review.models`, which is an Infrastructure → Domain upward import (git is infrastructure; review is domain-adjacent but above git in the coupling sense). Creating `git/diff_models.py` and moving these three types there eliminates the upward dependency while keeping the types accessible to `review/` consumers via an updated import.

**Implementation Plan (Do These Steps)**

- [ ] Find all files that import `CommitInfo`, `FileStatus`, or `ModifiedFile` from `review.models`:
  ```bash
  grep -rn "from orchestrator.review.models import\|from orchestrator.review import.*CommitInfo\|from orchestrator.review import.*FileStatus\|from orchestrator.review import.*ModifiedFile" src/ tests/
  ```

- [ ] Read `review/models.py` in full to identify the exact class bodies for `CommitInfo`, `FileStatus`, and `ModifiedFile`, including any imports they depend on.

- [ ] Create `src/orchestrator/git/diff_models.py` containing only these three type definitions:
  ```python
  # git/diff_models.py
  # Types shared between git diff operations and review consumers.
  from __future__ import annotations

  import enum
  from dataclasses import dataclass
  # ... (include whatever imports the three types need)

  class FileStatus(enum.Enum):
      # ... copy verbatim from review/models.py

  @dataclass
  class ModifiedFile:
      # ... copy verbatim

  @dataclass
  class CommitInfo:
      # ... copy verbatim
  ```

- [ ] In `review/models.py`: remove the three class definitions and add imports from `git.diff_models`:
  ```python
  from orchestrator.git.diff_models import CommitInfo, FileStatus, ModifiedFile
  ```
  Keep `DiffScope`, `DiffResult`, and any other types that belong to `review/`.

- [ ] In `git/diff_ops.py`: update the import to come from `git.diff_models`:
  ```python
  from orchestrator.git.diff_models import CommitInfo, FileStatus, ModifiedFile
  ```

- [ ] Update every other file found in the grep above to import from `orchestrator.git.diff_models`.

- [ ] Verify the import graph is acyclic: `git/diff_models.py` must not import from `review/` (it should have no orchestrator imports at all, or only from `config/` or `state/`).

**Constraints**
- Do not change the class definitions — pure relocation only.
- `review/models.py` may still re-export the types (import them from `git.diff_models`) so that callers importing `from orchestrator.review.models import FileStatus` continue to work — but only until Task 7 verification confirms all callers are updated. After that, re-exports are not required.
- Do not move `DiffScope` or `DiffResult` — those stay in `review/models.py`.

**Functionality (Expected Outcomes)**
- [ ] `CommitInfo`, `FileStatus`, `ModifiedFile` are defined in `src/orchestrator/git/diff_models.py`
- [ ] `git/diff_ops.py` imports from `git.diff_models`, not `review.models`
- [ ] `review/models.py` either re-exports or is updated; it no longer defines these three types
- [ ] All consumers discovered in the grep have their imports updated

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "from orchestrator.review.models import" src/orchestrator/git/` → zero results
- [ ] `test -f src/orchestrator/git/diff_models.py` → file exists
- [ ] `grep -n "class CommitInfo\|class FileStatus\|class ModifiedFile" src/orchestrator/git/diff_models.py` → three results
- [ ] `uv run python -c "from orchestrator.git.diff_models import CommitInfo, FileStatus, ModifiedFile"` → no error

---

## Task 3: C3 — Move ActionLog and supporting types to state/models.py

**Description**: `state/models.py` imports `ActionLog` from `runners.action_log`, which is a Domain → Execution upward import. Moving `ActionLog` and its supporting types (`ActionEntryKind`, `ActionLogEntry`, `ToolUseDetail`, `ToolResultDetail`, `TurnMetrics`) to `state/models.py` (or a new `state/action_log.py`) eliminates the upward dependency. `runners/action_log.py` then imports from `state/` or is deleted if it has no remaining content.

**Implementation Plan (Do These Steps)**

- [ ] Find all files that import from `runners.action_log`:
  ```bash
  grep -rn "from orchestrator.runners.action_log import\|from orchestrator.runners import.*ActionLog\|from orchestrator.runners import.*ActionLogEntry" src/ tests/
  ```

- [ ] Read `runners/action_log.py` in full to capture all class definitions and their dependencies.

- [ ] Decide placement: if `state/models.py` is already large (>300 LOC), create `src/orchestrator/state/action_log.py` and place all action log types there. If it is small, append to `state/models.py`. Either way, the types must be importable as `from orchestrator.state.models import ActionLog` for backward compatibility with `state/models.py` consumers, so if a new file is created, re-export from `state/models.py`:
  ```python
  # state/models.py
  from orchestrator.state.action_log import ActionLog, ActionLogEntry, ActionEntryKind  # noqa: F401
  ```

- [ ] Copy all types from `runners/action_log.py` into the chosen location. Include all imports those types depend on. Do not change any class definition.

- [ ] Update `state/models.py`: remove the import `from orchestrator.runners.action_log import ActionLog` and instead define (or re-export) `ActionLog` locally.

- [ ] Update `runners/action_log.py`: replace all class definitions with imports from the new location:
  ```python
  from orchestrator.state.models import ActionLog, ActionLogEntry, ActionEntryKind, ToolUseDetail, ToolResultDetail, TurnMetrics
  ```
  If `runners/action_log.py` has no remaining original content (no functions, no classes defined there), it may be deleted. Check if any file imports the module itself (not just specific names) before deleting.

- [ ] Update every other file found in the grep above to import from the new location.

**Constraints**
- Do not change any class definition — pure relocation only.
- If `runners/action_log.py` is deleted, confirm no file does `import orchestrator.runners.action_log` (module-level import, not `from ... import`).

**Side Effects**
- If a new `state/action_log.py` is created, it must be importable without importing all of `state/models.py` (to avoid circular imports). Check that `state/action_log.py` does not import from `state/models.py` for its own dependencies.

**Functionality (Expected Outcomes)**
- [ ] `ActionLog` and all supporting types are defined in `state/models.py` or `state/action_log.py`
- [ ] `state/models.py` no longer imports `ActionLog` from `runners.action_log`
- [ ] `runners/action_log.py` either does not exist or imports from `state/`
- [ ] All consumers found by grep have their imports updated

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "from orchestrator.runners.action_log import ActionLog" src/` → zero results
- [ ] `grep -n "class ActionLog" src/orchestrator/state/` → at least one result
- [ ] `uv run python -c "from orchestrator.state.models import ActionLog"` → no error
- [ ] `uv run pytest tests/unit/ -x -q 2>&1 | tail -5` — passes

---

## Task 4: C4 — Move EnvFileSpec to config/models.py

**Description**: `state/models.py` imports `EnvFileSpec` from `envfiles.models`, which is a Domain → Infrastructure upward import. Moving `EnvFileSpec` to `config/models.py` (the foundation layer) allows both `state/models.py` and `envfiles/models.py` to import it from a lower layer with no upward dependency.

**Implementation Plan (Do These Steps)**

- [ ] Find all files that import `EnvFileSpec` from `envfiles.models`:
  ```bash
  grep -rn "from orchestrator.envfiles.models import EnvFileSpec\|from orchestrator.envfiles import.*EnvFileSpec" src/ tests/
  ```

- [ ] Read the `EnvFileSpec` class definition in `envfiles/models.py` (fields, validators, imports needed).

- [ ] Add `EnvFileSpec` to `config/models.py` (copy the class definition verbatim). Add any necessary imports at the top of `config/models.py`.

- [ ] In `envfiles/models.py`: remove the `EnvFileSpec` class definition and add an import from `config.models`:
  ```python
  from orchestrator.config.models import EnvFileSpec
  ```
  Keep all other models in `envfiles/models.py` (`SnapshotPointType`, `SnapshotPoint`, `SnapshotManifest`, etc.).

- [ ] In `state/models.py`: update the import of `EnvFileSpec` to come from `config.models`:
  ```python
  from orchestrator.config.models import EnvFileSpec
  ```

- [ ] Update every other file found in the grep above.

**Constraints**
- Do not change `EnvFileSpec`'s fields or validators — pure relocation only.
- `config/models.py` must not import from `envfiles/` after this task.

**Functionality (Expected Outcomes)**
- [ ] `EnvFileSpec` is defined exactly once, in `config/models.py`
- [ ] `envfiles/models.py` imports `EnvFileSpec` from `config.models`
- [ ] `state/models.py` imports `EnvFileSpec` from `config.models`, not `envfiles.models`
- [ ] No other file imports `EnvFileSpec` from `envfiles.models`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "from orchestrator.envfiles.models import EnvFileSpec" src/` → zero results
- [ ] `grep -n "class EnvFileSpec" src/orchestrator/config/models.py` → at least one result
- [ ] `uv run python -c "from orchestrator.config.models import EnvFileSpec"` → no error
- [ ] `uv run pytest tests/unit/ -x -q 2>&1 | tail -5` — passes

---

## Task 5: C5 — Define RecoveryResult in workflow, translate in API router

**Description**: `workflow/service.py` imports `RecoverResponse` from `api/schemas/runs`, which is an Orchestration → API upward import. The fix is to define a `RecoveryResult` dataclass in `workflow/` that carries the same data, have `recover_run()` return it, and translate it to `RecoverResponse` in the API router (the only place that should know about API schemas).

**Implementation Plan (Do These Steps)**

- [ ] Read `workflow/service.py` imports and the `recover_run()` method signature and return statement to understand what fields are included in the returned `RecoverResponse`.

- [ ] Read `api/schemas/runs.py` to find the `RecoverResponse` schema definition (fields: `run_id`, `status`, `pause_reason`, `current_step_index`).

- [ ] Read `api/routers/runs.py` to find the recover endpoint that calls `service.recover_run()`.

- [ ] Add a `RecoveryResult` dataclass to `workflow/service.py` (near the top, before the `WorkflowService` class):
  ```python
  from dataclasses import dataclass

  @dataclass
  class RecoveryResult:
      run_id: str
      status: str
      pause_reason: str | None = None
      current_step_index: int | None = None
  ```

- [ ] In `workflow/service.py`: update `recover_run()` to return `RecoveryResult` instead of `RecoverResponse`. Replace all `return RecoverResponse(...)` calls with `return RecoveryResult(...)`. Remove the `from orchestrator.api.schemas.runs import RecoverResponse` import.

- [ ] In `api/routers/runs.py`: update the recover endpoint to translate the return value:
  ```python
  result = await service.recover_run(...)
  return RecoverResponse(
      run_id=result.run_id,
      status=result.status,
      pause_reason=result.pause_reason,
      current_step_index=result.current_step_index,
  )
  ```
  The endpoint's `response_model=RecoverResponse` annotation stays unchanged.

- [ ] Verify `workflow/service.py` no longer imports from `orchestrator.api`:
  ```bash
  grep -n "from orchestrator.api" src/orchestrator/workflow/service.py
  ```

**Constraints**
- `RecoveryResult` must have exactly the same fields and types as `RecoverResponse` — no behavioral change.
- Do not modify any other method in `workflow/service.py`.
- The API endpoint's response shape (as seen by HTTP clients) must not change.

**Functionality (Expected Outcomes)**
- [ ] `RecoveryResult` dataclass exists in `workflow/service.py`
- [ ] `workflow/service.recover_run()` returns `RecoveryResult`
- [ ] `api/routers/runs.py` translates `RecoveryResult` → `RecoverResponse` before returning
- [ ] `workflow/service.py` has no imports from `orchestrator.api`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "from orchestrator.api.schemas" src/orchestrator/workflow/` → zero results
- [ ] `grep -n "class RecoveryResult" src/orchestrator/workflow/service.py` → at least one result
- [ ] `uv run pytest tests/integration/ -x -q -k "recover" 2>&1 | tail -10` — passes (or no matching tests, confirm with `--collect-only`)
- [ ] `uv run pytest tests/unit/ -x -q 2>&1 | tail -5` — passes

---

## Task 6: C6 — Define TaskSubmitCallback protocol, refactor UserManagedAgent

**Description**: `runners/agents/user_managed/agent.py` imports `WorkflowService` directly, which is an Execution → Orchestration upward import. `UserManagedAgent` only uses two `WorkflowService` methods: `register_submit_event(task_id)` and `unregister_submit_event(task_id)`. Defining a `TaskSubmitCallback` protocol in `runners/types.py` with just those two methods eliminates the upward dependency. `WorkflowService` satisfies the protocol structurally (no changes to `WorkflowService` needed). Injection is wired in `api/deps.py`.

**Implementation Plan (Do These Steps)**

- [ ] Read `runners/agents/user_managed/agent.py` in full to confirm exactly which `WorkflowService` methods and attributes are used in `execute()`, `cancel()`, and any helper methods.

- [ ] Read `runners/types.py` to find a suitable location to add the protocol (after existing callback type aliases, before `ExecutionMetrics`).

- [ ] Add `TaskSubmitCallback` protocol to `runners/types.py`:
  ```python
  from typing import Protocol
  import asyncio

  class TaskSubmitCallback(Protocol):
      def register_submit_event(self, task_id: str) -> asyncio.Event: ...
      def unregister_submit_event(self, task_id: str) -> None: ...
  ```
  Adjust method signatures to exactly match what `WorkflowService` provides (check return types).

- [ ] In `runners/agents/user_managed/agent.py`:
  - Replace `from orchestrator.workflow.service import WorkflowService` with `from orchestrator.runners.types import TaskSubmitCallback`
  - Update the constructor type annotation for the `service` parameter: `service: TaskSubmitCallback`
  - No other changes needed (method calls stay the same)

- [ ] In `api/deps.py`: locate where `UserManagedAgent` is constructed or where `WorkflowService` is injected into it. Verify that `WorkflowService` is passed as the `service` argument. Since `WorkflowService` satisfies `TaskSubmitCallback` structurally, no runtime change is needed — only confirm the wiring is correct. Add a comment if helpful:
  ```python
  # WorkflowService satisfies the TaskSubmitCallback protocol structurally.
  ```

- [ ] Verify no circular import is introduced: `runners/types.py` must not import from `workflow/`. Run `uv run python -c "from orchestrator.runners.types import TaskSubmitCallback"`.

**Constraints**
- Do not change `WorkflowService` — it satisfies the protocol structurally without modification.
- Do not change `UserManagedAgent`'s behavior — only the type annotation for `service` changes.
- Do not add `TaskSubmitCallback` to `UserManagedAgent.__init__`'s runtime type check (isinstance) — protocols are for static typing only.

**Functionality (Expected Outcomes)**
- [ ] `TaskSubmitCallback` protocol is defined in `runners/types.py` with `register_submit_event` and `unregister_submit_event`
- [ ] `UserManagedAgent.__init__` accepts `service: TaskSubmitCallback`
- [ ] `runners/agents/user_managed/agent.py` has no import from `orchestrator.workflow`
- [ ] `api/deps.py` continues to pass `WorkflowService` (which satisfies the protocol) when constructing `UserManagedAgent`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "from orchestrator.workflow.service import WorkflowService" src/orchestrator/runners/` → zero results
- [ ] `grep -n "class TaskSubmitCallback" src/orchestrator/runners/types.py` → at least one result
- [ ] `uv run python -c "from orchestrator.runners.types import TaskSubmitCallback"` → no error
- [ ] `uv run python -c "from orchestrator.runners.agents.user_managed.agent import UserManagedAgent"` → no error
- [ ] `uv run pytest tests/unit/ -x -q 2>&1 | tail -5` — passes

---

## Task 7: Full test suite and import path verification

**Description**: Run the complete test suite and perform exhaustive `grep -r` checks to confirm that all 6 coupling violations are fully eliminated and no stale import paths remain. Fix any failures before marking the step complete.

**Implementation Plan (Do These Steps)**

- [ ] Run full backend unit tests:
  ```bash
  uv run pytest tests/unit/ -v 2>&1 | tail -20
  ```

- [ ] Run full backend integration tests:
  ```bash
  uv run pytest tests/integration/ -v 2>&1 | tail -20
  ```

- [ ] Run all 6 coupling verification greps:
  ```bash
  grep -rn "from orchestrator.runners.nudger import NudgerConfig" src/
  grep -rn "from orchestrator.review.models import" src/orchestrator/git/
  grep -rn "from orchestrator.runners.action_log import ActionLog" src/
  grep -rn "from orchestrator.envfiles.models import EnvFileSpec" src/orchestrator/state/
  grep -rn "from orchestrator.api.schemas" src/orchestrator/workflow/
  grep -rn "from orchestrator.workflow.service import WorkflowService" src/orchestrator/runners/
  ```
  Each must return zero results.

- [ ] Run broader import path check for any residual upward imports:
  ```bash
  grep -rn "from orchestrator.runners" src/orchestrator/config/
  grep -rn "from orchestrator.runners" src/orchestrator/state/
  grep -rn "from orchestrator.runners" src/orchestrator/git/
  grep -rn "from orchestrator.api" src/orchestrator/workflow/
  grep -rn "from orchestrator.workflow" src/orchestrator/runners/
  ```

- [ ] Fix any test failures or residual import violations found above before proceeding.

- [ ] Run pre-commit hooks:
  ```bash
  uv run pre-commit run --all-files 2>&1 | tail -20
  ```

**Functionality (Expected Outcomes)**
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] All 6 coupling grep checks return zero results
- [ ] Broader upward-import grep returns zero results (or only legitimate exceptions documented inline)
- [ ] Pre-commit hooks pass

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -q 2>&1 | tail -5` shows no failures
- [ ] All 6 coupling greps from the Auto-Verify section in the original step plan return zero results
- [ ] `uv run pre-commit run --all-files` exits with code 0
