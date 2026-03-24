# Dry-Run Analysis: Step 0 — Resolve Couplings C1–C6

## Executive Summary

Step 0 is well-structured and mechanically correct, but has **six specific failure modes** that need hardening before implementation. Most are edge cases in the source that differ from the step's assumptions. No task has a fundamental design flaw — all couplings can be fixed as described, with targeted adjustments.

---

## Task-by-Task Analysis

---

### Task 1: C1 — Move NudgerConfig to config/models.py

#### Assumptions Being Made

- `NudgerConfig` in `runners/nudger.py` is a Pydantic model (step says "Move NudgerConfig Pydantic model").
- `config/models.py` has no existing `NudgerConfig` definition.
- Only `config/global_config.py` and `runners/nudger.py` reference the runners' `NudgerConfig`.

#### Actual Source State

**Critical deviation 1 — Wrong type descriptor:** `runners/nudger.py:NudgerConfig` is a `@dataclass`, not a Pydantic model:
```python
# runners/nudger.py
@dataclass
class NudgerConfig:
    output_timeout: timedelta = timedelta(seconds=60)
    nudge_interval: timedelta = timedelta(seconds=30)
    max_nudges: int = 3
    nudge_message: str = "Please continue or call orchestrator tools to submit."
```
Fields use `timedelta`. No validators. Moving it to `config/models.py` (a Pydantic-heavy file) requires adding `from dataclasses import dataclass` and `from datetime import timedelta` imports there.

**Critical deviation 2 — Two distinct classes named NudgerConfig:** `config/global_config.py` already defines its OWN class named `NudgerConfig` at line 42 — a completely different Pydantic BaseModel:
```python
# global_config.py
class NudgerConfig(BaseModel):
    check_interval_seconds: int = 60
    nudge_after_seconds: int = 300
    kill_after_seconds: int = 600

    def to_agent_config(self) -> AgentNudgerConfig:  # ← converts to runners' NudgerConfig
        ...
```
The coupling is `to_agent_config()` importing the runners' `NudgerConfig` (aliased as `AgentNudgerConfig`) at both the `TYPE_CHECKING` block (line 12) and inline in the method body (line 55).

**Additional consumer missed by the step's grep pattern:** `runners/agents/claude_cli/factory.py` line 13:
```python
from orchestrator.runners.nudger import NudgerConfig
```
This file is a direct consumer that must be updated.

#### Expected Outputs (after correct implementation)
- `config/models.py` gains the `@dataclass NudgerConfig` (runners' version) with a new name to avoid colliding with `global_config.py`'s `NudgerConfig` — OR the naming is handled via imports with aliases.
- `runners/nudger.py` imports from `config.models`.
- `config/global_config.py` imports the runners' class with alias: `from orchestrator.config.models import NudgerConfig as AgentNudgerConfig`.
- `runners/agents/claude_cli/factory.py` imports from `config.models`.

#### Failure Modes and Hardening

**FM1 — Name collision in global_config.py:** After the move, `global_config.py` will have a local class `NudgerConfig` (Pydantic model) AND need to import a class also called `NudgerConfig` from `config.models`. The existing `AgentNudgerConfig` alias in `global_config.py`'s import handles this, but the implementer must be aware of the TWO distinct classes. The step description calling it "the NudgerConfig Pydantic model" obscures this.

**Hardening:** The notes for the implementer should explicitly state: there are two `NudgerConfig` classes — the dataclass from `runners/nudger.py` (operational parameters) and the Pydantic model in `global_config.py` (YAML config fields). Only the dataclass moves. The Pydantic model stays in `global_config.py` unchanged.

**FM2 — Missed consumer in claude_cli/factory.py:** The step's grep pattern `from orchestrator.runners.nudger import NudgerConfig` will find `factory.py` if run correctly, but the step only mentions updating `global_config.py` and `runners/nudger.py` by name. The implementer may overlook `factory.py`.

**Hardening:** Add `runners/agents/claude_cli/factory.py` explicitly to the list of files to update.

**FM3 — Wrong type descriptor ("Pydantic model"):** Step says "NudgerConfig Pydantic model" but it's a `@dataclass`. When copying to `config/models.py`, the implementer must add `from dataclasses import dataclass` and `from datetime import timedelta` — not Pydantic imports.

**Hardening:** Correct the type descriptor in the task description to "@dataclass".

**FM4 — Verification command assumes re-export exists:** The verification `uv run python -c "from orchestrator.runners.nudger import NudgerConfig"` will only pass if `runners/nudger.py` still re-exports the class. The implementation plan says to replace the class definition with an import (which is the re-export), so this should work — but the step should be explicit that `runners/nudger.py` re-exports via `from orchestrator.config.models import NudgerConfig`.

---

### Task 2: C2 — Create git/diff_models.py with review type definitions

#### Assumptions Being Made

- Only `git/diff_ops.py` and files found by the grep import `CommitInfo`, `FileStatus`, `ModifiedFile` from `review.models`.
- `review/models.py` only defines `DiffScope`, `DiffResult` (to keep) plus the three moving types.
- `review/__init__.py` doesn't re-export the moving types.

#### Actual Source State

**Deviation — review/__init__.py re-exports two of the three types:**
```python
# review/__init__.py line 3
from orchestrator.review.models import CommitInfo, DiffResult, ModifiedFile
```
`CommitInfo` and `ModifiedFile` are re-exported from `review/__init__.py` (but NOT `FileStatus`). After moving to `git/diff_models.py`, `review/__init__.py` must be updated to import from `git.diff_models` — otherwise `from orchestrator.review import CommitInfo` breaks.

**No additional complexity:** The three moving types are pure Pydantic/enum models with only stdlib imports (`datetime`, `enum`, `pydantic.BaseModel`). `git/diff_models.py` will have zero orchestrator-level imports. No circular import risk.

#### Expected Outputs (after correct implementation)

- New file `src/orchestrator/git/diff_models.py` with `FileStatus`, `ModifiedFile`, `CommitInfo`.
- `review/models.py` retains `DiffScope`, `DiffResult`; imports the three moved types from `git.diff_models`.
- `review/__init__.py` updated to import `CommitInfo` and `ModifiedFile` from `git.diff_models`.
- `git/diff_ops.py` imports from `git.diff_models`.

#### Failure Modes and Hardening

**FM5 — review/__init__.py not in scope of the grep or update list:** The step says "update every other file found in the grep above." The grep pattern targets import statements like `from orchestrator.review.models import`. But `review/__init__.py` uses exactly that pattern — so it WILL be found. However, the step's constraint note says "review/models.py may still re-export the types" — it doesn't mention `review/__init__.py`. The `__init__.py` must also be updated.

**Hardening:** Add `review/__init__.py` explicitly to the list of files to update in Task 2.

**FM6 — review/models.py re-imports could be confused with re-export shims:** The step says `review/models.py` either "re-exports or is updated." Per the overall step's zero-shim policy, `review/models.py` must import the types from `git.diff_models` (not just leave the definitions there). This is correctly stated but the "re-exports are not required after all callers are updated" language creates ambiguity about whether a shim in `review/models.py` is acceptable. It is NOT acceptable per the zero-shim policy.

**Hardening:** Clarify that `review/models.py` must import from `git.diff_models` (establishing a downward dependency), not leave the old definitions in place.

---

### Task 3: C3 — Move ActionLog and supporting types to state/models.py

#### Assumptions Being Made

- Moving all action log types to `state/models.py` or `state/action_log.py` is straightforward.
- `runners/action_log.py` either becomes a pure re-export or is deleted.
- The 300-LOC threshold for creating a new file gives guidance.

#### Actual Source State

**`state/models.py` is 218 lines** — under the threshold. Adding the ~100-line `action_log.py` contents pushes it to ~318 lines, exceeding the threshold. The step's own guidance suggests creating `state/action_log.py`.

**`db/repositories.py` is a consumer:** The grep finds `src/orchestrator/db/repositories.py:30:from orchestrator.runners.action_log import ActionLog`. This file is in `db/` — a different module layer. It imports `ActionLog` at module level (line 30). Must be updated.

**`MAX_TOOL_OUTPUT_SIZE` constant:** Defined in `runners/action_log.py`. This constant is used by parsers when truncating output. It must move with `ActionLog` to the new location. The step doesn't explicitly mention it.

**Consumer files:**
- `state/models.py` (line 9) — the direct coupling being fixed
- `runners/parsers/base.py` (line 7) — imports `ActionLog`
- `runners/execution/attempt_store.py` (line 14) — imports `ActionLog`
- `runners/agents/claude_cli/parser.py` (line 21) — imports multiple types
- `runners/agents/openhands/parser.py` (line 17) — imports multiple types
- `runners/agents/codex/parser.py` (line 21) — imports multiple types
- `db/repositories.py` (line 30) — imports `ActionLog`

All of these must be updated.

#### Failure Modes and Hardening

**FM7 — MAX_TOOL_OUTPUT_SIZE not mentioned:** The constant lives in `runners/action_log.py` and parsers depend on it. If the constant is left behind in `runners/action_log.py` while the types move, the module isn't fully cleaned up. If it moves with the types but the old file re-exports it as an empty module, that's a shim.

**Hardening:** Explicitly include `MAX_TOOL_OUTPUT_SIZE` in the list of symbols to move. Update all parser imports that use it.

**FM8 — state/action_log.py must not import state/models.py:** The step notes this under "Side Effects" — if `state/action_log.py` imports from `state/models.py` for its own dependencies, a circular import could occur. The action log types only need stdlib (`datetime`, `enum`) and `pydantic` — no `state/models.py` imports. Implementer should verify there's no temptation to add cross-imports within `state/`.

**FM9 — runners/action_log.py deletion check:** The step says "if `runners/action_log.py` has no remaining original content, it may be deleted." After moving all types, it will be content-free (only re-export imports). Per the zero-shim policy, it MUST be deleted — not left as a re-export shim. But before deletion, must verify no code does `import orchestrator.runners.action_log` (module-level import, not `from`). The grep in the step only covers `from orchestrator.runners.action_log import ActionLog` — a broader check for bare `import orchestrator.runners.action_log` is also needed.

**Hardening:** Add a grep for bare module imports: `grep -rn "import orchestrator.runners.action_log" src/ tests/` before deleting the file.

---

### Task 4: C4 — Move EnvFileSpec to config/models.py

#### Assumptions Being Made

- `EnvFileSpec` is only in `envfiles/models.py`.
- After moving, `envfiles/models.py` imports from `config.models`.
- All consumers are found by the grep on `from orchestrator.envfiles.models import EnvFileSpec`.

#### Actual Source State

**`envfiles/models.py` has `SnapshotManifest` using `EnvFileSpec`:**
```python
class SnapshotManifest(BaseModel):
    env_file_specs: list[EnvFileSpec] = Field(default_factory=lambda: list[EnvFileSpec]())
```
After moving `EnvFileSpec` to `config/models.py`, `envfiles/models.py` must import it from `config.models` for `SnapshotManifest` to compile. This is downward (envfiles → config), which is correct and safe.

**`db/repositories.py` has a local (method-internal) import:**
```python
# db/repositories.py line 221
from orchestrator.envfiles.models import EnvFileSpec
```
This is inside a method body, not at module level. The grep will find it, but it looks like a local import — the implementer must update it despite being non-obvious.

**`envfiles/resolution.py` imports `EnvFileSpec`** at line 9 — a straightforward update.

#### Failure Modes and Hardening

**FM10 — db/repositories.py local import inside method:** Easy to overlook because the grep shows it at line 221, and the file has module-level imports at the top. The implementer should not assume all imports are at module level.

**Hardening:** Explicitly note that `db/repositories.py` has an inline method import at line 221 that must be updated to `from orchestrator.config.models import EnvFileSpec`.

**FM11 — EnvFileSpec has a simple definition but must carry its Pydantic dependency:** It only uses `pydantic.BaseModel` and `Field`. `config/models.py` already imports from `pydantic`, so no new imports are needed in `config/models.py` for this class. Confirmed safe.

---

### Task 5: C5 — Define RecoveryResult in workflow, translate in API router

#### Assumptions Being Made

- `workflow/service.recover_run()` returns `RecoverResponse` directly.
- `api/routers/runs.py` returns the service result directly to FastAPI.
- `RecoverResponse` has fields: `run_id`, `status`, `pause_reason`, `current_step_index`.

#### Actual Source State

**Confirmed correct:** `workflow/service.py` line 682:
```python
return RecoverResponse(
    run_id=run.id,
    status=run.status.value,
    pause_reason=run.pause_reason,
    current_step_index=run.current_step_index,
)
```

**Router returns service result directly:**
```python
# api/routers/runs.py line 517
return await service.recover_run(...)
```
FastAPI's `response_model=RecoverResponse` serializes the return value. After the change, `service.recover_run()` returns a `RecoveryResult` dataclass — the router must construct `RecoverResponse` explicitly before returning.

**RecoverResponse fields confirmed:** `run_id: str`, `status: str`, `pause_reason: str | None = None`, `current_step_index: int | None = None`. These match `run.id`, `run.status.value` (string), `run.pause_reason` (str | None), `run.current_step_index` (int | None).

#### Failure Modes and Hardening

**FM12 — FastAPI response_model won't serialize a plain dataclass correctly:** If the router returns a `RecoveryResult` dataclass without wrapping in `RecoverResponse`, FastAPI will attempt Pydantic validation and may fail (depending on version). The step correctly requires explicit translation in the router. This is the right approach.

**FM13 — recover_run return type annotation must change:** `workflow/service.py` has `async def recover_run(...) -> RecoverResponse:`. After the fix, it must change to `-> RecoveryResult:`. The step implies this via "update recover_run() to return RecoveryResult" but doesn't call out the type annotation change explicitly.

**Hardening:** Explicitly note that the method signature return annotation must change from `-> RecoverResponse` to `-> RecoveryResult` in addition to the return statement.

**No other callers of recover_run:** Confirmed that only `api/routers/runs.py` calls `service.recover_run()`. Single call site makes this a safe, contained change.

---

### Task 6: C6 — Define TaskSubmitCallback protocol, refactor UserManagedAgent

#### Assumptions Being Made

- `UserManagedAgent` is constructed with `service: WorkflowService` passed in, wired via `api/deps.py`.
- `WorkflowService` has exactly `register_submit_event(task_id)` and `unregister_submit_event(task_id)` as the only methods used.
- Defining the protocol in `runners/types.py` is sufficient to fix the coupling.

#### Actual Source State

**Two methods confirmed:** `user_managed/agent.py` uses exactly:
- `self._service.register_submit_event(context.task_id)` → returns `asyncio.Event`
- `self._service.unregister_submit_event(context.task_id)` → returns `None`

**Method signatures confirmed on WorkflowService:**
```python
def register_submit_event(self, task_id: str) -> asyncio.Event: ...
def unregister_submit_event(self, task_id: str) -> None: ...
```

**Critical wiring gap — UserManagedAgent is NOT constructed in api/deps.py:** The step says "In `api/deps.py`: locate where `UserManagedAgent` is constructed or where `WorkflowService` is injected into it." But:

1. `api/deps.py` has no reference to `UserManagedAgent`.
2. `UserManagedAgent` is constructed in `runners/agents/user_managed/factory.py` via the factory registry pattern.
3. The executor has a special early-return for USER_MANAGED at line 435: `if run.agent_type == AgentRunnerType.USER_MANAGED: return run` — it skips agent spawning entirely.
4. The factory comment says: "The executor does not spawn UserManagedAgent via `_create_agent` — it is handled separately."

**Consequence:** Where and how `WorkflowService` is passed to `UserManagedAgent` in the ACTIVE code path is not clear from the files examined. The factory.py requires `service` in kwargs, but no call site in `executor.py` or `deps.py` appears to construct `UserManagedAgent` directly. This may mean:
- (a) `UserManagedAgent` is only constructed via `factory.py`'s `create()` in tests or via the factory registry for non-executor code paths, OR
- (b) There's a code path in `executor.py` that handles USER_MANAGED task execution that wasn't captured in the grep.

**This is the biggest wiring risk for C6:** If `UserManagedAgent` is never instantiated in the running system, the protocol change is a cosmetic improvement that doesn't fix an active coupling — but it does fix the import-time coupling (the `from orchestrator.workflow.service import WorkflowService` at line 32 of agent.py runs at import time regardless).

#### Failure Modes and Hardening

**FM14 — Wiring verification points at wrong file:** The step says to verify in `api/deps.py` that `WorkflowService` is passed when constructing `UserManagedAgent`. But `api/deps.py` doesn't construct `UserManagedAgent`. The correct verification is: find all call sites of `user_managed/factory.py:create()` or direct `UserManagedAgent(...)` construction, confirm each passes a `WorkflowService` (which structurally satisfies the protocol without change).

**Hardening:** Replace the `api/deps.py` verification step with: "Search for all `UserManagedAgent(` and `create(` calls in the `user_managed/` directory and confirm each passes `service=<WorkflowService instance>`. Since WorkflowService satisfies the protocol structurally, no runtime injection change is needed."

**FM15 — The import-time coupling IS the fix target, but this should be stated explicitly:** Even if `UserManagedAgent` were never instantiated, the `from orchestrator.workflow.service import WorkflowService` at line 32 is an import-time coupling that loads the `workflow.service` module when `runners.agents.user_managed` is imported. Eliminating this import is the concrete fix — the protocol enables type-checking without loading the module.

**FM16 — runners/agents/user_managed/factory.py has a runtime string reference to WorkflowService:** The factory docstring mentions `WorkflowService`, and the error message `"UserManagedAgent factory requires 'service' kwarg (WorkflowService)"` references it as a string — not an import. These string references don't create coupling but should not be changed to imports.

**FM17 — Protocol method signatures must match exactly:** `register_submit_event` returns `asyncio.Event`. The protocol must specify this. `asyncio` must be imported in `runners/types.py`. The current `runners/types.py` does not import `asyncio` — this import must be added.

**Hardening:** Verify `asyncio` is added to imports in `runners/types.py` when defining `TaskSubmitCallback`.

---

### Task 7: Full test suite and import path verification

#### Failure Modes and Hardening

**FM18 — Broader grep will produce false positives from TYPE_CHECKING blocks:** Task 7 includes:
```bash
grep -rn "from orchestrator.workflow" src/orchestrator/runners/
```
This will find legitimate TYPE_CHECKING imports in:
- `runners/executor.py` line 48: `from orchestrator.workflow.service import SubmitEventRegistry, WorkflowService`
- `runners/execution/phase_handler.py` line 25: `from orchestrator.workflow.service import WorkflowService`

These are inside `if TYPE_CHECKING:` blocks and are NOT runtime coupling violations. The grep will report them as matches. The implementer must distinguish TYPE_CHECKING imports (acceptable) from runtime imports (violations).

**Hardening:** Add a note that TYPE_CHECKING imports in `executor.py` and `phase_handler.py` are expected and NOT violations. The coupling check for C6 only targets `runners/agents/user_managed/agent.py`.

**FM19 — Test files in tests/ import from old locations:** The step only greps `src/` for coupling violations. Tests in `tests/` that import moved types also need updating. The step's per-task verification greps (`src/ tests/`) cover this for individual tasks, but Task 7's "broader import path check" greps only target `src/orchestrator/`. Any test importing moved types from old locations would fail at test collection, not at the coupling grep.

**Hardening:** Add `tests/` to the broader import path checks in Task 7, or verify the individual per-task greps already covered `tests/`.

---

## Cross-Cutting Issues

### Issue A: Zero-shim Policy Enforcement

Three tasks create a situation where the old file (`runners/action_log.py`, `envfiles/models.py`) must not become a shim. The step is clear on this but the constraint is sometimes contradicted by "re-exports are acceptable until all callers are updated" language. Implementation must delete shim files as part of the same task, not defer.

### Issue B: config/models.py Footprint

After C1 (NudgerConfig dataclass) and C4 (EnvFileSpec), `config/models.py` grows from 531 lines by ~15 lines (NudgerConfig dataclass is small; EnvFileSpec is 4 lines). No concern about size.

### Issue C: ActionLog Placement Decision

The step's 300-LOC threshold recommends `state/action_log.py` (state/models.py is 218 lines). The cleaner choice is `state/action_log.py` — keep `state/models.py` focused on runtime run/step/task models, and put the agent output schema in a dedicated file. The implementer should default to `state/action_log.py` and re-export from `state/models.py` if backward compatibility is needed.

---

## Summary of Hardening Actions

| # | Task | Hardening Action |
|---|------|-----------------|
| 1 | C1 | Correct "Pydantic model" → "@dataclass"; explicitly list both NudgerConfig classes |
| 2 | C1 | Add `runners/agents/claude_cli/factory.py` to explicit update list |
| 3 | C2 | Add `review/__init__.py` to explicit update list |
| 4 | C2 | Clarify `review/models.py` must import from `git.diff_models`, not keep old definitions |
| 5 | C3 | Explicitly include `MAX_TOOL_OUTPUT_SIZE` in symbols to move |
| 6 | C3 | Add grep for bare `import orchestrator.runners.action_log` before deleting file |
| 7 | C3 | Recommend `state/action_log.py` (state/models.py at 218 LOC will exceed 300 after additions) |
| 8 | C4 | Flag `db/repositories.py` line 221 as a local import inside a method body |
| 9 | C5 | Explicitly note that `recover_run` return type annotation must change to `-> RecoveryResult` |
| 10 | C6 | Replace `api/deps.py` wiring check with: find all `UserManagedAgent(` call sites in active paths |
| 11 | C6 | Add `import asyncio` to `runners/types.py` for `TaskSubmitCallback` protocol |
| 12 | Task 7 | Note that TYPE_CHECKING imports of WorkflowService in executor.py and phase_handler.py are acceptable |
| 13 | Task 7 | Add `tests/` to broader import path checks |

---

## Risk Assessment by Coupling

| Coupling | Risk | Primary Risk Factor |
|----------|------|---------------------|
| C1 NudgerConfig | Medium | Two distinct classes share the name; @dataclass vs Pydantic confusion |
| C2 Review types | Low | Clean pure-data types; only `review/__init__.py` is a gap |
| C3 ActionLog | Medium | 7 consumer files + MAX_TOOL_OUTPUT_SIZE + deletion verification |
| C4 EnvFileSpec | Low | db/repositories.py local import is the only gap |
| C5 RecoverResponse | Low | Single call site; straightforward dataclass + translation |
| C6 UserManagedAgent | Medium | Wiring verification points at wrong file; TYPE_CHECKING greps produce false positives |

All couplings are fixable as designed. No fundamental redesign needed. Hardening actions above prevent the most likely implementation errors.
