# Step 7: Restructure workflow/ Internals

Reorganize `workflow/` from 18 flat files into four well-defined sub-packages (`engine/`, `events/`, `signals/`, `agent/`), plus four stable root files (`service.py`, `locks.py`, `completion.py`, `dry_run.py`). This is a pure structural change — no behavior changes, no API changes.

**Critical constraint:** External code imports many workflow files by direct sub-module path (e.g., `from orchestrator.workflow.errors import GateBlockedError`). For sub-packages whose directory name matches the original filename (engine/, events/, signals/), Python automatically maps the old path to the new `__init__.py`. For files that move under a *differently-named* sub-package (e.g., `event_logger.py` → `events/logger.py`), a thin re-export file at the old path is required within `workflow/` to avoid breaking external callers. These re-exports are intra-module compatibility layers, not cross-module backward-compat shims.

Two cross-module moves also happen in this step: `NoTaskReason`/`resolve_no_task_action` moves from `runners/executor.py` to `workflow/signals/runtime.py`, and `DEFAULT_SUMMARIZE_MODEL` moves from `config/models.py` to `workflow/agent/summary_cache.py`.

## Intent Verification

**Original Intent**: Phase 7 of module consolidation — restructure `workflow/` flat files into engine/, events/, signals/, agent/ sub-packages. No external import path changes.

**Functionality to Produce**:
- `workflow/engine/` sub-package containing: `engine.py`, `transitions.py`, `gates.py`, `grades.py`, `condition_evaluator.py`, `errors.py`
- `workflow/events/` sub-package containing: `types.py` (content of events.py), `logger.py` (content of event_logger.py)
- `workflow/signals/` sub-package containing: `signals.py`, `handlers.py`, `runtime.py`
- `workflow/agent/` sub-package containing: `prompts.py`, `templates.py`, `context_builder.py`, `clarifications.py`, `auto_verify.py`, `summary_cache.py`
- `workflow/` root retains only: `__init__.py`, `service.py`, `locks.py`, `completion.py`, `dry_run.py`, plus thin re-export files for external paths that changed sub-package name
- `NoTaskReason` and `resolve_no_task_action` defined in `workflow/signals/runtime.py`; removed from `runners/executor.py`
- `DEFAULT_SUMMARIZE_MODEL` defined inline in `workflow/agent/summary_cache.py`; removed from `config/models.py`
- `workflow/__init__.py` updated to import from new sub-package paths

**Final Verification Criteria**:
- All backend unit and integration tests pass
- All frontend tests pass
- `grep -r "from orchestrator\.runners.*NoTaskReason" src/` returns zero results
- `grep -r "DEFAULT_SUMMARIZE_MODEL" src/orchestrator/config/` returns zero results
- `workflow/` root contains no flat `.py` files that belong in sub-packages (only service, locks, completion, dry_run, __init__, and any re-export bridges)
- `uv run python -c "from orchestrator.workflow import WorkflowEngine, WorkflowService; print('ok')"` succeeds
- Pre-commit hooks pass

---

## Task 1: Audit All External workflow/ Sub-Module Import Paths

**Description**:
Before moving any files, map every direct sub-module import from outside `workflow/`. This determines which files can be moved freely and which require a re-export bridge at the old path.

**Implementation Plan (Do These Steps)**

- [ ] Find all direct sub-module imports from external code (outside `src/orchestrator/workflow/`):
```bash
grep -rn "from orchestrator\.workflow\." src/ tests/ --include="*.py" \
  | grep -v "^src/orchestrator/workflow/" \
  | grep -oP "from orchestrator\.workflow\.\K[a-z_]+" \
  | sort -u
```
Record the output: each name is a sub-module that must remain importable at `orchestrator.workflow.<name>` after restructuring.

- [ ] For each sub-module name from the above, note whether its target sub-package has the SAME name (safe — Python resolves directory packages transparently) or a DIFFERENT name (requires a re-export bridge):
  - `engine` → sub-package named `engine/` — **SAFE** (directory name matches)
  - `events` → sub-package named `events/` — **SAFE**
  - `signals` → sub-package named `signals/` — **SAFE**
  - `errors` → moves to `engine/errors.py` — **NEEDS BRIDGE**
  - `transitions` → moves to `engine/transitions.py` — **NEEDS BRIDGE**
  - `gates` → moves to `engine/gates.py` — **NEEDS BRIDGE**
  - `grades` → moves to `engine/grades.py` — **NEEDS BRIDGE**
  - `condition_evaluator` → moves to `engine/condition_evaluator.py` — **NEEDS BRIDGE**
  - `event_logger` → moves to `events/logger.py` — **NEEDS BRIDGE**
  - `handlers` → moves to `signals/handlers.py` — check if imported externally
  - `runtime` → moves to `signals/runtime.py` — check if imported externally
  - `prompts`, `templates`, `context_builder`, `clarifications`, `auto_verify`, `summary_cache` → move to `agent/` — check each

- [ ] Confirm which symbols `workflow/__init__.py` currently re-exports:
```bash
grep "^from orchestrator.workflow\." src/orchestrator/workflow/__init__.py
```

**Functionality (Expected Outcomes)**:
- [ ] A complete list of sub-module names that need re-export bridges at the old path exists (no file changes made yet)

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] All audit grep commands above ran without error (exit 0)

---

## Task 2: Create workflow/engine/ Sub-Package

**Description**:
Create the `engine/` sub-package. `engine.py` becomes `engine/engine.py` with `engine/__init__.py` re-exporting its symbols. The five support files (`transitions.py`, `gates.py`, `grades.py`, `condition_evaluator.py`, `errors.py`) move into `engine/` and keep thin re-export bridges at the old paths since they are directly imported by external callers.

**Implementation Plan (Do These Steps)**

- [ ] Create the `engine/` sub-package directory:
```bash
mkdir -p src/orchestrator/workflow/engine
```

- [ ] Copy `engine.py` to `engine/engine.py`. Update any intra-module imports (e.g., `from orchestrator.workflow.errors import` → use relative imports or keep absolute). No content changes to logic.

- [ ] Copy `transitions.py` to `engine/transitions.py`. Update internal imports to use relative paths (e.g., `from orchestrator.workflow.events import` stays absolute — leave as-is since it's the same package).

- [ ] Copy `gates.py` to `engine/gates.py`. Same approach.

- [ ] Copy `grades.py` to `engine/grades.py`. Same approach.

- [ ] Copy `condition_evaluator.py` to `engine/condition_evaluator.py`. Same approach.

- [ ] Copy `errors.py` to `engine/errors.py`. This file has no imports, so copy verbatim.

- [ ] Create `src/orchestrator/workflow/engine/__init__.py` that re-exports all public symbols from the moved files:
```python
"""Workflow engine internals."""

from orchestrator.workflow.engine.engine import (
    Clock,
    DefaultClock,
    EventEmitter,
    NoOpEmitter,
    WorkflowEngine,
)
from orchestrator.workflow.engine.transitions import (
    VALID_TRANSITIONS,
    TransitionResult,
    check_step_progression,
)
from orchestrator.workflow.engine.gates import GateResult, evaluate_checklist_gate
from orchestrator.workflow.engine.grades import DEFAULT_GRADE_ORDER, GradeResult, evaluate_grades
from orchestrator.workflow.engine.condition_evaluator import (
    ConditionEvalError,
    ConditionEvaluator,
    StepOutcome,
)
from orchestrator.workflow.engine.errors import (
    GateBlockedError,
    InvalidTransitionError,
    WorkflowError,
)

__all__ = [
    "Clock",
    "ConditionEvalError",
    "ConditionEvaluator",
    "DEFAULT_GRADE_ORDER",
    "DefaultClock",
    "EventEmitter",
    "GateBlockedError",
    "GateResult",
    "GradeResult",
    "InvalidTransitionError",
    "NoOpEmitter",
    "StepOutcome",
    "TransitionResult",
    "VALID_TRANSITIONS",
    "WorkflowEngine",
    "WorkflowError",
    "check_step_progression",
    "evaluate_checklist_gate",
    "evaluate_grades",
]
```

- [ ] **Delete the original flat files** that now live in engine/:
```bash
rm src/orchestrator/workflow/engine.py
```
  The `from orchestrator.workflow.engine import X` path now maps to `engine/__init__.py` automatically — no bridge needed.

- [ ] Create thin re-export bridges for the support files (since external callers import `orchestrator.workflow.transitions`, etc. directly). Replace each original flat file with a one-line re-export:

  `src/orchestrator/workflow/errors.py`:
  ```python
  from orchestrator.workflow.engine.errors import GateBlockedError, InvalidTransitionError, WorkflowError  # noqa: F401
  ```

  `src/orchestrator/workflow/transitions.py`:
  ```python
  from orchestrator.workflow.engine.transitions import VALID_TRANSITIONS, TransitionResult, check_step_progression  # noqa: F401
  ```

  `src/orchestrator/workflow/gates.py`:
  ```python
  from orchestrator.workflow.engine.gates import GateResult, evaluate_checklist_gate  # noqa: F401
  ```

  `src/orchestrator/workflow/grades.py`:
  ```python
  from orchestrator.workflow.engine.grades import DEFAULT_GRADE_ORDER, GradeResult, evaluate_grades  # noqa: F401
  ```

  `src/orchestrator/workflow/condition_evaluator.py`:
  ```python
  from orchestrator.workflow.engine.condition_evaluator import ConditionEvalError, ConditionEvaluator, StepOutcome  # noqa: F401
  ```

- [ ] Verify the engine sub-package imports cleanly:
```bash
uv run python -c "from orchestrator.workflow.engine import WorkflowEngine, GateBlockedError; print('ok')"
uv run python -c "from orchestrator.workflow.errors import GateBlockedError; print('ok')"
uv run python -c "from orchestrator.workflow.transitions import VALID_TRANSITIONS; print('ok')"
```

**Constraints**:
- The flat files `transitions.py`, `gates.py`, `grades.py`, `condition_evaluator.py`, `errors.py` at `workflow/` root become thin re-exports (1 line each). Do not leave the old logic there alongside the new files.
- Internal imports within engine/ files should use absolute paths (`from orchestrator.workflow.engine.errors import`) — avoid relative imports that create cross-sub-package dependencies.

**Functionality (Expected Outcomes)**:
- [ ] `workflow/engine/` contains: `__init__.py`, `engine.py`, `transitions.py`, `gates.py`, `grades.py`, `condition_evaluator.py`, `errors.py`
- [ ] Old `workflow/engine.py` is deleted; `from orchestrator.workflow.engine import WorkflowEngine` resolves to `engine/__init__.py`
- [ ] `workflow/errors.py`, `transitions.py`, `gates.py`, `grades.py`, `condition_evaluator.py` exist as thin re-exports

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.workflow.engine import WorkflowEngine, Clock, GateBlockedError, VALID_TRANSITIONS; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.workflow.errors import GateBlockedError, InvalidTransitionError, WorkflowError; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.workflow.transitions import VALID_TRANSITIONS, TransitionResult; print('ok')"` succeeds
- [ ] `uv run pytest tests/unit/ -q` exits with code 0

---

## Task 3: Create workflow/events/ Sub-Package

**Description**:
Convert `events.py` into the `events/` sub-package (the directory name matches, so `orchestrator.workflow.events` resolves automatically). Move `event_logger.py` into `events/logger.py` and add a re-export bridge at the old path.

**Implementation Plan (Do These Steps)**

- [ ] Create the `events/` sub-package:
```bash
mkdir -p src/orchestrator/workflow/events
```

- [ ] Copy `events.py` to `events/types.py`. No import changes needed (the file has no intra-workflow imports beyond config/state).

- [ ] Copy `event_logger.py` to `events/logger.py`. Update any intra-package imports (e.g., `from orchestrator.workflow.events import WorkflowEvent` stays as absolute — keep as-is).

- [ ] Create `src/orchestrator/workflow/events/__init__.py` that re-exports all public event types:
```python
"""Workflow event types and persistent event logger."""

from orchestrator.workflow.events.types import (
    AgentOutputEvent,
    BufferingEmitter,
    ChecklistGateEvaluated,
    ClarificationRequested,
    ClarificationResponded,
    GradesEvaluated,
    HealthCheckEvent,
    RunStatusChanged,
    StepSkipped,
    TaskStatusChanged,
    WorkflowEvent,
)
from orchestrator.workflow.events.logger import PersistentEventEmitter

__all__ = [
    "AgentOutputEvent",
    "BufferingEmitter",
    "ChecklistGateEvaluated",
    "ClarificationRequested",
    "ClarificationResponded",
    "GradesEvaluated",
    "HealthCheckEvent",
    "PersistentEventEmitter",
    "RunStatusChanged",
    "StepSkipped",
    "TaskStatusChanged",
    "WorkflowEvent",
]
```
  Adjust the symbol list to match what `events.py` actually exports — audit with `grep "^class\|^def\|^[A-Z]" src/orchestrator/workflow/events.py` before writing the __init__.py.

- [ ] Delete `workflow/events.py` (the `events/` directory now serves this path):
```bash
rm src/orchestrator/workflow/events.py
```

- [ ] Create a thin re-export bridge for `event_logger` at the old path:

  `src/orchestrator/workflow/event_logger.py`:
  ```python
  from orchestrator.workflow.events.logger import PersistentEventEmitter  # noqa: F401
  ```
  Add any other symbols from `event_logger.py` that are imported externally.

- [ ] Delete the original `event_logger.py` after confirming all symbols are re-exported via the bridge:
```bash
rm src/orchestrator/workflow/event_logger.py
```

- [ ] Quick smoke-test:
```bash
uv run python -c "from orchestrator.workflow.events import WorkflowEvent, RunStatusChanged; print('ok')"
uv run python -c "from orchestrator.workflow.event_logger import PersistentEventEmitter; print('ok')"
```

**Constraints**:
- The old `workflow/events.py` file is deleted entirely. The new `workflow/events/` directory serves the same import path automatically.
- Export list in `events/__init__.py` must include ALL symbols currently imported by external callers — check the audit from Task 1.

**Functionality (Expected Outcomes)**:
- [ ] `workflow/events/` contains: `__init__.py`, `types.py`, `logger.py`
- [ ] `workflow/event_logger.py` is a thin re-export (1-2 lines)
- [ ] `workflow/events.py` does not exist

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.workflow.events import WorkflowEvent, RunStatusChanged, TaskStatusChanged, BufferingEmitter, StepSkipped, HealthCheckEvent, ClarificationRequested, ClarificationResponded; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.workflow.event_logger import PersistentEventEmitter; print('ok')"` succeeds
- [ ] `ls src/orchestrator/workflow/events.py` fails with "No such file or directory"
- [ ] `uv run pytest tests/unit/ -q` exits with code 0

---

## Task 4: Create workflow/signals/ Sub-Package

**Description**:
Convert `signals.py` into the `signals/` sub-package (directory name matches; import path preserved automatically). Move `handlers.py` and `runtime.py` into `signals/`. Add re-export bridges for any externally imported symbols.

**Implementation Plan (Do These Steps)**

- [ ] Create the `signals/` sub-package:
```bash
mkdir -p src/orchestrator/workflow/signals
```

- [ ] Copy `signals.py` to `signals/signals.py`. Keep internal imports as absolute paths.

- [ ] Copy `handlers.py` to `signals/handlers.py`. Update its import of `WorkflowSignal` to use the new sub-package path:
  ```python
  from orchestrator.workflow.signals.signals import WorkflowSignal
  ```

- [ ] Copy `runtime.py` to `signals/runtime.py`. Update internal imports:
  - `from orchestrator.workflow.handlers import` → `from orchestrator.workflow.signals.handlers import`
  - `from orchestrator.workflow.signals import` → `from orchestrator.workflow.signals.signals import`

- [ ] Create `src/orchestrator/workflow/signals/__init__.py`:
```python
"""Workflow signal transport and run lifecycle."""

from orchestrator.workflow.signals.signals import (
    DbSignalTransport,
    SignalTransport,
    WorkflowSignal,
)
from orchestrator.workflow.signals.handlers import build_registry, signal_handler
from orchestrator.workflow.signals.runtime import RunWorkflow

__all__ = [
    "DbSignalTransport",
    "RunWorkflow",
    "SignalTransport",
    "WorkflowSignal",
    "build_registry",
    "signal_handler",
]
```

- [ ] Delete original flat files (the `signals/` directory now serves `orchestrator.workflow.signals`):
```bash
rm src/orchestrator/workflow/signals.py
```

- [ ] Check whether `handlers` and `runtime` are imported by external code at their direct sub-module paths:
```bash
grep -rn "from orchestrator\.workflow\.handlers\|from orchestrator\.workflow\.runtime" src/ tests/ --include="*.py" | grep -v "workflow/"
```
  - If `workflow.handlers` is imported externally: create `workflow/handlers.py` re-export bridge.
  - If `workflow.runtime` is imported externally (e.g., `from orchestrator.workflow.runtime import RunWorkflow`): create `workflow/runtime.py` re-export bridge.

- [ ] Create any needed re-export bridges. Example for `runtime.py` (imported by `src/orchestrator/executor.py`):
  ```python
  from orchestrator.workflow.signals.runtime import RunWorkflow  # noqa: F401
  ```

- [ ] Delete original `handlers.py` and `runtime.py` after bridges (if any) are in place:
```bash
rm src/orchestrator/workflow/handlers.py
rm src/orchestrator/workflow/runtime.py
```

- [ ] Smoke-test:
```bash
uv run python -c "from orchestrator.workflow.signals import DbSignalTransport, SignalTransport, WorkflowSignal; print('ok')"
uv run python -c "from orchestrator.workflow.runtime import RunWorkflow; print('ok')"
```

**Functionality (Expected Outcomes)**:
- [ ] `workflow/signals/` contains: `__init__.py`, `signals.py`, `handlers.py`, `runtime.py`
- [ ] `workflow/signals.py` does not exist (replaced by `signals/` directory)
- [ ] Re-export bridges exist at `workflow/handlers.py` and `workflow/runtime.py` if those paths are imported externally

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.workflow.signals import DbSignalTransport, SignalTransport, WorkflowSignal, RunWorkflow; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.workflow.runtime import RunWorkflow; print('ok')"` succeeds (if runtime.py is externally imported)
- [ ] `ls src/orchestrator/workflow/signals.py` fails with "No such file or directory"
- [ ] `uv run pytest tests/unit/ -q` exits with code 0

---

## Task 5: Create workflow/agent/ Sub-Package

**Description**:
Create the new `agent/` sub-package and move the six agent-prompt files into it. Since `agent` is a new name (no existing `agent.py`), there's no automatic path preservation. Each file's old path (`orchestrator.workflow.prompts`, etc.) must remain importable via a thin re-export bridge.

**Implementation Plan (Do These Steps)**

- [ ] Create the `agent/` sub-package:
```bash
mkdir -p src/orchestrator/workflow/agent
```

- [ ] Copy each file into `agent/`, preserving content exactly:
```bash
cp src/orchestrator/workflow/prompts.py src/orchestrator/workflow/agent/prompts.py
cp src/orchestrator/workflow/templates.py src/orchestrator/workflow/agent/templates.py
cp src/orchestrator/workflow/context_builder.py src/orchestrator/workflow/agent/context_builder.py
cp src/orchestrator/workflow/clarifications.py src/orchestrator/workflow/agent/clarifications.py
cp src/orchestrator/workflow/auto_verify.py src/orchestrator/workflow/agent/auto_verify.py
cp src/orchestrator/workflow/summary_cache.py src/orchestrator/workflow/agent/summary_cache.py
```

- [ ] Update intra-agent imports within the copied files to use absolute paths. For example, if `context_builder.py` imports `from orchestrator.workflow.prompts import X`, it stays as-is (absolute paths work fine).

- [ ] Create `src/orchestrator/workflow/agent/__init__.py`:
```python
"""Agent prompting, context, and verification utilities."""

from orchestrator.workflow.agent.auto_verify import LocalAutoVerifyRunner
from orchestrator.workflow.agent.clarifications import ClarificationAnswer, ClarificationQuestion
from orchestrator.workflow.agent.context_builder import TaskContextBuilder
from orchestrator.workflow.agent.prompts import (
    BuilderPrompt,
    VerifierPrompt,
    generate_builder_prompt,
    generate_verifier_prompt,
    get_task_context,
)
from orchestrator.workflow.agent.summary_cache import SummaryCache
from orchestrator.workflow.agent.templates import derive_output_path, resolve_template

__all__ = [
    "BuilderPrompt",
    "ClarificationAnswer",
    "ClarificationQuestion",
    "LocalAutoVerifyRunner",
    "SummaryCache",
    "TaskContextBuilder",
    "VerifierPrompt",
    "derive_output_path",
    "generate_builder_prompt",
    "generate_verifier_prompt",
    "get_task_context",
    "resolve_template",
]
```

- [ ] Replace each original flat file with a thin re-export bridge (these paths are imported externally):

  `src/orchestrator/workflow/prompts.py` → re-export all public symbols from `agent/prompts.py`
  `src/orchestrator/workflow/templates.py` → re-export from `agent/templates.py`
  `src/orchestrator/workflow/context_builder.py` → re-export from `agent/context_builder.py`
  `src/orchestrator/workflow/clarifications.py` → re-export from `agent/clarifications.py`
  `src/orchestrator/workflow/auto_verify.py` → re-export from `agent/auto_verify.py`
  `src/orchestrator/workflow/summary_cache.py` → re-export from `agent/summary_cache.py`

  Example for `prompts.py`:
  ```python
  from orchestrator.workflow.agent.prompts import (  # noqa: F401
      BuilderPrompt,
      VerifierPrompt,
      generate_builder_prompt,
      generate_verifier_prompt,
      get_task_context,
  )
  ```

- [ ] Smoke-test each bridge:
```bash
uv run python -c "from orchestrator.workflow.prompts import generate_builder_prompt; print('ok')"
uv run python -c "from orchestrator.workflow.clarifications import ClarificationQuestion; print('ok')"
uv run python -c "from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner; print('ok')"
uv run python -c "from orchestrator.workflow.agent import TaskContextBuilder; print('ok')"
```

**Constraints**:
- Do NOT delete the original flat files — they become 1-liner re-export bridges, not empty files.
- The `agent/__init__.py` symbols must match what is actually defined in each sub-file. Audit with `grep "^class\|^def\|^[A-Z][A-Z_]*\s*=" src/orchestrator/workflow/agent/*.py` before finalizing `__all__`.

**Functionality (Expected Outcomes)**:
- [ ] `workflow/agent/` contains: `__init__.py`, `prompts.py`, `templates.py`, `context_builder.py`, `clarifications.py`, `auto_verify.py`, `summary_cache.py`
- [ ] The original flat files (prompts.py, templates.py, etc.) still exist at workflow root as 1-liner re-exports
- [ ] `from orchestrator.workflow.prompts import generate_builder_prompt` still works

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.workflow.agent import LocalAutoVerifyRunner, TaskContextBuilder, SummaryCache; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.workflow.clarifications import ClarificationQuestion, ClarificationAnswer; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.workflow.summary_cache import SummaryCache; print('ok')"` succeeds
- [ ] `uv run pytest tests/unit/ -q` exits with code 0

---

## Task 6: Move NoTaskReason from runners/ to workflow/signals/runtime.py

**Description**:
`NoTaskReason` (an enum) and `resolve_no_task_action` (a function) are defined in `runners/executor.py` but consumed by `workflow/signals/runtime.py` via a lazy import. This is a layering violation (workflow importing from runners). Move the definitions to `workflow/signals/runtime.py` and update all consumers.

**Implementation Plan (Do These Steps)**

- [ ] Identify all current consumers of `NoTaskReason` and `resolve_no_task_action`:
```bash
grep -rn "NoTaskReason\|resolve_no_task_action" src/ tests/ --include="*.py"
```
  Expected consumers: `runners/executor.py` (defines them), `workflow/signals/runtime.py` (imports lazily), `tests/integration/test_api_human_approval.py`, `tests/integration/test_executor_loop_invariant.py`.

- [ ] Add `NoTaskReason` and `resolve_no_task_action` definitions to `src/orchestrator/workflow/signals/runtime.py`. Copy the enum and function verbatim from `runners/executor.py` (lines ~53–88). Place them near the top of the file, after imports. Ensure any types they reference (`Run`, `LoopAction`) are imported in `runtime.py`.

- [ ] Update `workflow/signals/__init__.py` to re-export the new symbols:
```python
from orchestrator.workflow.signals.runtime import NoTaskReason, resolve_no_task_action
```
  Add to `__all__`.

- [ ] Remove the `NoTaskReason` and `resolve_no_task_action` definitions from `src/orchestrator/runners/executor.py`. Replace with an import from the new location:
```python
from orchestrator.workflow.signals.runtime import NoTaskReason, resolve_no_task_action
```
  This keeps `executor.py` functional while changing the canonical definition location.

- [ ] Update the lazy import in `workflow/signals/runtime.py` itself (line 372) — it previously imported from `runners.executor`. After the move, remove the lazy import and use the locally-defined `NoTaskReason` and `resolve_no_task_action` directly.

- [ ] Update test files to import from the new location:
  - `tests/integration/test_api_human_approval.py`: change `from orchestrator.runners.executor import NoTaskReason` → `from orchestrator.workflow.signals.runtime import NoTaskReason`
  - `tests/integration/test_executor_loop_invariant.py`: update `from orchestrator.runners.executor import AgentRunnerExecutor, NoTaskReason` — keep `AgentRunnerExecutor` import from runners, change `NoTaskReason` import source

- [ ] Verify:
```bash
grep -rn "from orchestrator\.runners.*NoTaskReason" src/ tests/ --include="*.py"
```
  Must return zero results.

```bash
uv run python -c "from orchestrator.workflow.signals.runtime import NoTaskReason, resolve_no_task_action; print(list(NoTaskReason))"
```

**Constraints**:
- `NoTaskReason` and `resolve_no_task_action` must be DEFINED in `workflow/signals/runtime.py`, not just re-exported.
- `runners/executor.py` imports them FROM `workflow` (not the other way). This fixes the layering violation.
- Do not change `AgentRunnerExecutor` or any other executor functionality.

**Side Effects**:
- `runners/executor.py` now depends on `orchestrator.workflow.signals.runtime` — this is the correct dependency direction (runners → workflow).

**Functionality (Expected Outcomes)**:
- [ ] `NoTaskReason` enum and `resolve_no_task_action` defined in `workflow/signals/runtime.py`
- [ ] `runners/executor.py` imports them from `orchestrator.workflow.signals.runtime`
- [ ] Test files import `NoTaskReason` from `orchestrator.workflow.signals.runtime`
- [ ] `grep -rn "from orchestrator\.runners.*NoTaskReason" src/ tests/` returns zero results

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.workflow.signals.runtime import NoTaskReason, resolve_no_task_action; print('ok')"` succeeds
- [ ] `grep -rn "from orchestrator\.runners.*NoTaskReason" src/ tests/ --include="*.py"` returns zero results
- [ ] `uv run pytest tests/integration/test_executor_loop_invariant.py -v` passes
- [ ] `uv run pytest tests/integration/test_api_human_approval.py -v` passes

---

## Task 7: Move DEFAULT_SUMMARIZE_MODEL to workflow/agent/summary_cache.py

**Description**:
`DEFAULT_SUMMARIZE_MODEL` is defined in `config/models.py` but has a single consumer: `workflow/summary_cache.py` (now `workflow/agent/summary_cache.py`). Move it to the consumer file and remove it from `config/models.py`.

**Implementation Plan (Do These Steps)**

- [ ] Confirm the single-consumer assumption:
```bash
grep -rn "DEFAULT_SUMMARIZE_MODEL" src/ tests/ --include="*.py"
```
  Expected: only in `config/models.py` (definition) and `workflow/summary_cache.py` (import). If other consumers exist, do NOT move it — stop and note this in comments.

- [ ] Add `DEFAULT_SUMMARIZE_MODEL = "claude-haiku-4-5-20251001"` directly to `src/orchestrator/workflow/agent/summary_cache.py`, near the top of the file (after imports). Remove the `from orchestrator.config.models import DEFAULT_SUMMARIZE_MODEL` import line.

- [ ] Remove `DEFAULT_SUMMARIZE_MODEL` from `src/orchestrator/config/models.py` (delete the line `DEFAULT_SUMMARIZE_MODEL = "claude-haiku-4-5-20251001"`).

- [ ] Update the re-export bridge `workflow/summary_cache.py` if it re-exports `DEFAULT_SUMMARIZE_MODEL` — remove that symbol from the bridge if present.

- [ ] Verify:
```bash
grep -rn "DEFAULT_SUMMARIZE_MODEL" src/orchestrator/config/ --include="*.py"
```
  Must return zero results.

```bash
uv run python -c "from orchestrator.workflow.agent.summary_cache import SummaryCache; print('ok')"
```

**Constraints**:
- Only move if `DEFAULT_SUMMARIZE_MODEL` has exactly one consumer. If more consumers exist, stop and escalate.
- The constant value must not change: `"claude-haiku-4-5-20251001"`.

**Functionality (Expected Outcomes)**:
- [ ] `DEFAULT_SUMMARIZE_MODEL` defined in `workflow/agent/summary_cache.py`
- [ ] `DEFAULT_SUMMARIZE_MODEL` removed from `config/models.py`
- [ ] `SummaryCache` continues to use the correct model constant

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "DEFAULT_SUMMARIZE_MODEL" src/orchestrator/config/ --include="*.py"` returns zero results
- [ ] `uv run python -c "from orchestrator.workflow.agent.summary_cache import SummaryCache; print('ok')"` succeeds
- [ ] `uv run pytest tests/unit/ -q` exits with code 0

---

## Task 8: Update workflow/__init__.py and Full Test Suite

**Description**:
Update `workflow/__init__.py` so it imports from the new sub-package paths. Run the full test suite to catch any remaining broken imports. Fix failures. This is the final gate before Phase 7 is considered complete.

**Implementation Plan (Do These Steps)**

- [ ] Update `src/orchestrator/workflow/__init__.py` — change every import to use the new sub-package paths:
  ```python
  # Old:
  from orchestrator.workflow.engine import WorkflowEngine, ...
  # New:
  from orchestrator.workflow.engine import WorkflowEngine, ...  # same path — engine/ is a package now

  # Old:
  from orchestrator.workflow.errors import GateBlockedError, ...
  # New:
  from orchestrator.workflow.engine.errors import GateBlockedError, ...

  # Old:
  from orchestrator.workflow.events import WorkflowEvent, ...
  # New (events/ is a package now):
  from orchestrator.workflow.events import WorkflowEvent, ...  # same — events/ is a package

  # Old:
  from orchestrator.workflow.prompts import generate_builder_prompt, ...
  # New:
  from orchestrator.workflow.agent.prompts import generate_builder_prompt, ...

  # Old:
  from orchestrator.workflow.condition_evaluator import ...
  # New:
  from orchestrator.workflow.engine.condition_evaluator import ...
  ```
  Update all lines that reference files that have moved. The `__all__` list does not change.

- [ ] Run backend unit tests and capture failures:
```bash
uv run pytest tests/unit/ -v 2>&1 | tail -30
```

- [ ] Run backend integration tests:
```bash
uv run pytest tests/integration/ -v 2>&1 | tail -30
```

- [ ] Fix any failures. Common causes:
  - Missing re-export bridge for a sub-module path (add 1-line re-export to the old flat file)
  - Missing symbol in a sub-package `__init__.py` (add to `__all__` and import)
  - Circular import between sub-packages (use lazy/local import to break the cycle)

- [ ] Run frontend tests (no changes expected, but confirm):
```bash
cd ui && npx vitest run
```

- [ ] Run pre-commit hooks:
```bash
uv run pre-commit run --all-files
```

- [ ] Verify directory layout is as expected:
```bash
ls src/orchestrator/workflow/
# Expected: __init__.py, agent/, artifacts/, completion.py, condition_evaluator.py, dry_run.py,
#           engine/, errors.py, event_logger.py, events/, gates.py, grades.py, handlers.py (if bridge),
#           locks.py, prompts.py, runtime.py (if bridge), service.py, signals/, summary_cache.py,
#           templates.py, transitions.py, context_builder.py, clarifications.py, auto_verify.py

ls src/orchestrator/workflow/engine/
# Expected: __init__.py, engine.py, transitions.py, gates.py, grades.py, condition_evaluator.py, errors.py

ls src/orchestrator/workflow/events/
# Expected: __init__.py, types.py, logger.py

ls src/orchestrator/workflow/signals/
# Expected: __init__.py, signals.py, handlers.py, runtime.py

ls src/orchestrator/workflow/agent/
# Expected: __init__.py, prompts.py, templates.py, context_builder.py, clarifications.py, auto_verify.py, summary_cache.py
```

- [ ] Final completeness audit — zero stale references to `runners` for `NoTaskReason`:
```bash
grep -rn "from orchestrator\.runners.*NoTaskReason" src/ tests/ --include="*.py" || echo "OK"
grep -rn "DEFAULT_SUMMARIZE_MODEL" src/orchestrator/config/ --include="*.py" || echo "OK"
```

- [ ] Commit:
```bash
git add -A src/orchestrator/workflow/ src/orchestrator/runners/executor.py src/orchestrator/config/models.py tests/
git commit -m "Restructure workflow/ into engine/, events/, signals/, agent/ sub-packages (Phase 7)"
```

**Functionality (Expected Outcomes)**:
- [ ] All backend unit and integration tests pass
- [ ] All frontend tests pass
- [ ] Pre-commit hooks pass
- [ ] `workflow/__init__.py` imports from sub-package paths; `__all__` list unchanged
- [ ] Sub-package directories exist and contain the expected files
- [ ] No stale imports to moved locations remain unresolved

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -q` exits with code 0
- [ ] `cd ui && npx vitest run` exits with code 0
- [ ] `uv run pre-commit run --all-files` exits with code 0
- [ ] `grep -rn "from orchestrator\.runners.*NoTaskReason" src/ tests/ --include="*.py"` returns zero results
- [ ] `grep -rn "DEFAULT_SUMMARIZE_MODEL" src/orchestrator/config/ --include="*.py"` returns zero results
- [ ] `uv run python -c "from orchestrator.workflow import WorkflowEngine, WorkflowService, GateBlockedError, RunStatusChanged; print('ok')"` succeeds
- [ ] `git --no-pager diff --stat HEAD` shows the expected file moves and no unintended changes
