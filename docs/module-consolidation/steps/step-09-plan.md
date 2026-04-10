# Step 9: Restructure runners/ Internals

Reorganize `runners/` flat files into `detection/` and `runtime/` sub-packages. After Phase 6, all absorptions into `runners/` are complete. This phase moves the remaining flat implementation files into organized sub-packages and updates every import that references them. The existing `execution/` sub-package (`phase_handler.py`, `attempt_store.py`, `event_broadcaster.py`) is already well-structured and requires no changes.

External callers currently use sub-module import paths (e.g. `from orchestrator.runners.detector import ToolDetector`). After this phase, those callers are updated to import from the `runners` top-level (`from orchestrator.runners import ToolDetector`) using re-exports added to `runners/__init__.py`. This achieves the Phase 10 sub-package access discipline one phase early for these symbols.

## Intent Verification
**Original Intent**: Phase 9 of the module consolidation plan — reorganize `runners/` internal files into `detection/` and `runtime/` sub-packages, update all import sites, and expose public symbols through `runners/__init__.py`.

**Functionality to Produce**:
- `runners/detection/` sub-package containing `detector.py`, `profile_resolution.py`, `config_utils.py`
- `runners/runtime/` sub-package containing `monitor.py`, `nudger.py`, `quota.py`, `repetition_detector.py`
- `runners/__init__.py` re-exports all public symbols so external callers need only `from orchestrator.runners import X`
- All internal runners files (`executor.py`, `interface.py`, `agents/*`) updated to new sub-package paths
- All external callers in `api/`, `cli/`, and test files updated to `from orchestrator.runners import X`
- Original flat files at `runners/` root deleted (no re-export shims left behind)

**Final Verification Criteria**:
- All backend unit and integration tests pass
- All frontend tests pass
- `grep -rn "from orchestrator\.runners\.detector\|from orchestrator\.runners\.monitor\|from orchestrator\.runners\.nudger\|from orchestrator\.runners\.quota\|from orchestrator\.runners\.profile_resolution\|from orchestrator\.runners\.repetition_detector\|from orchestrator\.runners\.config_utils" src/ tests/` returns zero results
- `runners/detector.py`, `runners/monitor.py`, `runners/nudger.py`, `runners/quota.py`, `runners/profile_resolution.py`, `runners/repetition_detector.py`, `runners/config_utils.py` do not exist
- `runners/detection/__init__.py`, `runners/runtime/__init__.py` exist
- `runners/execution/` is unchanged (same three files, no additions or removals)

---

## Task 1: Create runners/detection/ Sub-Package

**Description**:
Create the `detection/` sub-package and move the three detection-related files into it. Update any intra-package imports within those files (none needed, as these files have no `orchestrator.runners.*` imports of their own except `detector.py` importing from `runners.types` and `runners.agents.*`, which remain in place).

**Implementation Plan (Do These Steps)**

- [ ] Create the sub-package directory and empty `__init__.py`:
```bash
mkdir -p src/orchestrator/runners/detection
touch src/orchestrator/runners/detection/__init__.py
```

- [ ] Move `detector.py` into the sub-package (no imports inside it reference moved files):
```bash
cp src/orchestrator/runners/detector.py src/orchestrator/runners/detection/detector.py
```

- [ ] Move `profile_resolution.py` into the sub-package:
```bash
cp src/orchestrator/runners/profile_resolution.py src/orchestrator/runners/detection/profile_resolution.py
```

- [ ] Move `config_utils.py` into the sub-package:
```bash
cp src/orchestrator/runners/config_utils.py src/orchestrator/runners/detection/config_utils.py
```

- [ ] Verify the new files have no internal `orchestrator.runners.detector`, `orchestrator.runners.profile_resolution`, or `orchestrator.runners.config_utils` imports (they don't reference each other or the moved files):
```bash
grep "orchestrator\.runners\." src/orchestrator/runners/detection/detector.py src/orchestrator/runners/detection/profile_resolution.py src/orchestrator/runners/detection/config_utils.py
```

**Constraints**:
- Do not delete the original flat files yet (`runners/detector.py` etc. — deleted in Task 3 after __init__.py re-exports are in place).
- Do not update any import sites yet.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/runners/detection/__init__.py` exists
- [ ] `src/orchestrator/runners/detection/detector.py` exists with `ToolDetector` and `AGENT_CONFIG_FIELDS`
- [ ] `src/orchestrator/runners/detection/profile_resolution.py` exists with `resolve_model_for_profile`
- [ ] `src/orchestrator/runners/detection/config_utils.py` exists with `coerce_llm_config`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.runners.detection.detector import ToolDetector; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.runners.detection.profile_resolution import resolve_model_for_profile; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.runners.detection.config_utils import coerce_llm_config; print('ok')"` succeeds

---

## Task 2: Create runners/runtime/ Sub-Package

**Description**:
Create the `runtime/` sub-package and move the four runtime-monitoring files into it. None of these files import from `orchestrator.runners.*` (except `monitor.py` and `nudger.py` importing from `config/` and `state/`, which are unaffected), so no intra-file import changes are needed.

**Implementation Plan (Do These Steps)**

- [ ] Create the sub-package directory and empty `__init__.py`:
```bash
mkdir -p src/orchestrator/runners/runtime
touch src/orchestrator/runners/runtime/__init__.py
```

- [ ] Move `monitor.py`:
```bash
cp src/orchestrator/runners/monitor.py src/orchestrator/runners/runtime/monitor.py
```

- [ ] Move `nudger.py`:
```bash
cp src/orchestrator/runners/nudger.py src/orchestrator/runners/runtime/nudger.py
```

- [ ] Move `quota.py`:
```bash
cp src/orchestrator/runners/quota.py src/orchestrator/runners/runtime/quota.py
```

- [ ] Move `repetition_detector.py`:
```bash
cp src/orchestrator/runners/repetition_detector.py src/orchestrator/runners/runtime/repetition_detector.py
```

- [ ] Confirm none of the moved files reference the other moved modules (no circular detection↔runtime dependency):
```bash
grep "orchestrator\.runners\.\(detector\|monitor\|nudger\|quota\|repetition_detector\|profile_resolution\|config_utils\)" \
  src/orchestrator/runners/runtime/monitor.py \
  src/orchestrator/runners/runtime/nudger.py \
  src/orchestrator/runners/runtime/quota.py \
  src/orchestrator/runners/runtime/repetition_detector.py \
  src/orchestrator/runners/detection/detector.py \
  src/orchestrator/runners/detection/profile_resolution.py \
  src/orchestrator/runners/detection/config_utils.py || echo "OK: no cross-references"
```

**Constraints**:
- Do not delete original flat files yet.
- Do not update any import sites yet.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/runners/runtime/__init__.py` exists
- [ ] All four runtime files exist under `runners/runtime/`
- [ ] No detection ↔ runtime circular imports

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.runners.runtime.monitor import AgentRunnerMonitor; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.runners.runtime.nudger import NudgeAction, Nudger, NudgerConfig; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.runners.runtime.quota import FakeQuotaFetcher, QuotaFetcher, HttpQuotaFetcher; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.runners.runtime.repetition_detector import RepetitionDetector, RepetitionDetectorConfig; print('ok')"` succeeds

---

## Task 3: Update runners/__init__.py + Delete Original Flat Files

**Description**:
Add re-exports for all public symbols from the two new sub-packages to `runners/__init__.py`, then delete the original flat files. After this task, `from orchestrator.runners import ToolDetector` and similar top-level imports work correctly.

**Implementation Plan (Do These Steps)**

- [ ] Read the current `src/orchestrator/runners/__init__.py` to understand existing content.

- [ ] Update `src/orchestrator/runners/__init__.py` to re-export all public symbols from the new sub-packages:
```python
"""Agent runner integrations for the orchestrator."""

# Detection
from orchestrator.runners.detection.detector import AGENT_CONFIG_FIELDS, ToolDetector
from orchestrator.runners.detection.profile_resolution import resolve_model_for_profile
from orchestrator.runners.detection.config_utils import coerce_llm_config

# Runtime monitoring
from orchestrator.runners.runtime.monitor import AgentRunnerMonitor
from orchestrator.runners.runtime.nudger import NudgeAction, Nudger, NudgerConfig, TimeProvider
from orchestrator.runners.runtime.quota import FakeQuotaFetcher, HttpQuotaFetcher, QuotaFetcher
from orchestrator.runners.runtime.repetition_detector import (
    ActionBudget,
    ActionBudgetConfig,
    ReasoningDetectorConfig,
    ReasoningRepetitionDetector,
    RepetitionAction,
    RepetitionDetector,
    RepetitionDetectorConfig,
)

__all__ = [
    # detection
    "AGENT_CONFIG_FIELDS",
    "ToolDetector",
    "resolve_model_for_profile",
    "coerce_llm_config",
    # runtime
    "AgentRunnerMonitor",
    "NudgeAction",
    "Nudger",
    "NudgerConfig",
    "TimeProvider",
    "FakeQuotaFetcher",
    "HttpQuotaFetcher",
    "QuotaFetcher",
    "ActionBudget",
    "ActionBudgetConfig",
    "ReasoningDetectorConfig",
    "ReasoningRepetitionDetector",
    "RepetitionAction",
    "RepetitionDetector",
    "RepetitionDetectorConfig",
]
```

- [ ] Verify the re-exports work before deleting old files:
```bash
uv run python -c "from orchestrator.runners import ToolDetector, AgentRunnerMonitor, NudgerConfig, QuotaFetcher, RepetitionDetector; print('ok')"
```

- [ ] Delete the original flat files:
```bash
rm src/orchestrator/runners/detector.py
rm src/orchestrator/runners/profile_resolution.py
rm src/orchestrator/runners/config_utils.py
rm src/orchestrator/runners/monitor.py
rm src/orchestrator/runners/nudger.py
rm src/orchestrator/runners/quota.py
rm src/orchestrator/runners/repetition_detector.py
```

**Constraints**:
- Preserve any existing content in `runners/__init__.py` that was already there before adding the new re-exports.
- Do not add re-exports for symbols that are purely internal to a single sub-package consumer (if any).
- No re-export shim files may remain at the old flat paths.

**Functionality (Expected Outcomes)**:
- [ ] `from orchestrator.runners import ToolDetector` works
- [ ] `from orchestrator.runners import AgentRunnerMonitor` works
- [ ] None of the seven original flat files exist at `runners/` root

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.runners import ToolDetector, AGENT_CONFIG_FIELDS, resolve_model_for_profile, coerce_llm_config, AgentRunnerMonitor, NudgeAction, Nudger, NudgerConfig, TimeProvider, FakeQuotaFetcher, HttpQuotaFetcher, QuotaFetcher, RepetitionDetector, RepetitionDetectorConfig, RepetitionAction, ActionBudget, ActionBudgetConfig, ReasoningDetectorConfig, ReasoningRepetitionDetector; print('ok')"` succeeds
- [ ] `ls src/orchestrator/runners/detector.py 2>&1` exits non-zero (file absent)
- [ ] `ls src/orchestrator/runners/nudger.py 2>&1` exits non-zero (file absent)
- [ ] `ls src/orchestrator/runners/quota.py 2>&1` exits non-zero (file absent)

---

## Task 4: Update Internal runners/ Imports

**Description**:
Update all import sites within `runners/` that reference the moved modules. Affected files: `executor.py` (imports monitor and profile_resolution), `interface.py` (imports quota), and agent implementations under `runners/agents/`.

**Implementation Plan (Do These Steps)**

- [ ] Update `src/orchestrator/runners/executor.py` — two lazy monitor imports and one lazy profile_resolution import:

  Line 43 (TYPE_CHECKING block):
  ```python
  # before
  from orchestrator.runners.monitor import AgentRunnerMonitor
  # after
  from orchestrator.runners.runtime.monitor import AgentRunnerMonitor
  ```

  Line 183 (lazy import inside method):
  ```python
  # before
  from orchestrator.runners.monitor import AgentRunnerMonitor
  # after
  from orchestrator.runners.runtime.monitor import AgentRunnerMonitor
  ```

  Line 730 (lazy import inside method):
  ```python
  # before
  from orchestrator.runners.profile_resolution import resolve_model_for_profile
  # after
  from orchestrator.runners.detection.profile_resolution import resolve_model_for_profile
  ```

- [ ] Update `src/orchestrator/runners/interface.py` line 5:
  ```python
  # before
  from orchestrator.runners.quota import QuotaFetcher
  # after
  from orchestrator.runners.runtime.quota import QuotaFetcher
  ```

- [ ] Update `src/orchestrator/runners/agents/claude_cli/agent.py` line 28 and TYPE_CHECKING block:
  ```python
  # before (line 28)
  from orchestrator.runners.nudger import NudgeAction, Nudger, NudgerConfig, TimeProvider
  # after
  from orchestrator.runners.runtime.nudger import NudgeAction, Nudger, NudgerConfig, TimeProvider
  ```
  ```python
  # before (TYPE_CHECKING block, line ~46)
  from orchestrator.runners.monitor import AgentRunnerMonitor
  # after
  from orchestrator.runners.runtime.monitor import AgentRunnerMonitor
  ```

- [ ] Update `src/orchestrator/runners/agents/claude_cli/factory.py` lines 13 and TYPE_CHECKING block:
  ```python
  # before (line 13)
  from orchestrator.runners.nudger import NudgerConfig
  # after
  from orchestrator.runners.runtime.nudger import NudgerConfig
  ```
  ```python
  # before (TYPE_CHECKING block, line ~16)
  from orchestrator.runners.monitor import AgentRunnerMonitor
  # after
  from orchestrator.runners.runtime.monitor import AgentRunnerMonitor
  ```

- [ ] Update `src/orchestrator/runners/agents/mock/agent.py` line 6:
  ```python
  # before
  from orchestrator.runners.quota import QuotaFetcher
  # after
  from orchestrator.runners.runtime.quota import QuotaFetcher
  ```

- [ ] Update `src/orchestrator/runners/agents/openhands/agent.py` lines 33 and 41:
  ```python
  # before (line 33)
  from orchestrator.runners.repetition_detector import (
  # after
  from orchestrator.runners.runtime.repetition_detector import (
  ```
  ```python
  # before (line 41)
  from orchestrator.runners.quota import HttpQuotaFetcher, QuotaFetcher
  # after
  from orchestrator.runners.runtime.quota import HttpQuotaFetcher, QuotaFetcher
  ```

- [ ] Update `src/orchestrator/runners/agents/openhands/factory.py` line 11:
  ```python
  # before
  from orchestrator.runners.config_utils import coerce_llm_config
  # after
  from orchestrator.runners.detection.config_utils import coerce_llm_config
  ```

**Constraints**:
- Only change import paths. No behavioral changes.
- Files are: `executor.py`, `interface.py`, `agents/claude_cli/agent.py`, `agents/claude_cli/factory.py`, `agents/mock/agent.py`, `agents/openhands/agent.py`, `agents/openhands/factory.py`

**Functionality (Expected Outcomes)**:
- [ ] All seven internal runners files import from sub-package paths
- [ ] No `from orchestrator.runners.detector`, `runners.monitor`, `runners.nudger`, `runners.quota`, `runners.repetition_detector`, `runners.profile_resolution`, or `runners.config_utils` remain inside `runners/`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "from orchestrator\.runners\.\(detector\|monitor\|nudger\|quota\|profile_resolution\|repetition_detector\|config_utils\)" src/orchestrator/runners/ --include="*.py"` returns zero results
- [ ] `uv run python -c "from orchestrator.runners.executor import AgentRunnerExecutor; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.runners.interface import AgentRunner; print('ok')"` succeeds

---

## Task 5: Update External src/ Callers

**Description**:
Update all files outside `runners/` (within `src/`) that import directly from the moved sub-modules. These callers are switched to `from orchestrator.runners import X` using the re-exports added in Task 3. The one exception is `config/global_config.py` which imports `NudgerConfig` — this coupling (C1) should have been resolved in Phase 0; if not, update it here too.

**Implementation Plan (Do These Steps)**

- [ ] Update `src/orchestrator/api/app.py` — two imports (lazy, inside functions):

  Line 38 (TYPE_CHECKING block):
  ```python
  # before
  from orchestrator.runners.monitor import AgentRunnerMonitor
  # after
  from orchestrator.runners import AgentRunnerMonitor
  ```

  Line 478 (lazy import inside startup function):
  ```python
  # before
  from orchestrator.runners.detector import ToolDetector
  # after
  from orchestrator.runners import ToolDetector
  ```

- [ ] Update `src/orchestrator/api/routers/runners.py` lines 16–17:
  ```python
  # before
  from orchestrator.runners.detector import ToolDetector
  from orchestrator.runners.types import AgentRunnerOption
  # after (only line 16 changes; types.py is not moved)
  from orchestrator.runners import ToolDetector
  from orchestrator.runners.types import AgentRunnerOption
  ```

- [ ] Update `src/orchestrator/api/routers/runs.py` line 329 (lazy import inside function):
  ```python
  # before
  from orchestrator.runners.detector import AGENT_CONFIG_FIELDS
  # after
  from orchestrator.runners import AGENT_CONFIG_FIELDS
  ```

- [ ] Update `src/orchestrator/cli/agents.py` line 8:
  ```python
  # before
  from orchestrator.runners.detector import ToolDetector
  # after
  from orchestrator.runners import ToolDetector
  ```

- [ ] Check `src/orchestrator/config/global_config.py` for any remaining `nudger` import (should be fixed by Phase 0 C1 fix, but verify):
```bash
grep "from orchestrator.runners.nudger" src/orchestrator/config/global_config.py
```
If present (Phase 0 not yet done), update both occurrences:
  ```python
  # before (lines 12 and 55)
  from orchestrator.runners.nudger import NudgerConfig as AgentNudgerConfig
  # after
  from orchestrator.runners import NudgerConfig as AgentNudgerConfig
  ```

- [ ] Verify no remaining direct sub-module references in src/ (outside runners/):
```bash
grep -rn "from orchestrator\.runners\.\(detector\|monitor\|nudger\|quota\|profile_resolution\|repetition_detector\|config_utils\)" \
  src/ --include="*.py" | grep -v "src/orchestrator/runners/"
```
Must return zero lines.

**Constraints**:
- Change only the import paths for moved symbols. Do not touch imports of un-moved modules (`runners.executor`, `runners.types`, `runners.errors`, `runners.interface`, `runners.agents.*`, `runners.execution.*`).

**Functionality (Expected Outcomes)**:
- [ ] All external `src/` callers use `from orchestrator.runners import X` for detection/runtime symbols

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "from orchestrator\.runners\.\(detector\|monitor\|nudger\|quota\|profile_resolution\|repetition_detector\|config_utils\)" src/ --include="*.py" | grep -v "src/orchestrator/runners/"` returns zero results
- [ ] `uv run python -c "from orchestrator.api.app import app; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.api.routers.runners import router; print('ok')"` succeeds

---

## Task 6: Update Test Imports

**Description**:
Update all test files that import directly from the moved sub-modules. All test imports switch to `from orchestrator.runners import X`.

**Implementation Plan (Do These Steps)**

- [ ] Update `tests/unit/test_tool_detector.py` line 8:
  ```python
  # before
  from orchestrator.runners.detector import ToolDetector
  # after
  from orchestrator.runners import ToolDetector
  ```

- [ ] Update `tests/unit/agents/test_detector_quota.py` line 9:
  ```python
  # before
  from orchestrator.runners.detector import ToolDetector
  # after
  from orchestrator.runners import ToolDetector
  ```

- [ ] Update `tests/unit/test_model_profiles.py` line 6:
  ```python
  # before
  from orchestrator.runners.profile_resolution import resolve_model_for_profile
  # after
  from orchestrator.runners import resolve_model_for_profile
  ```

- [ ] Update `tests/unit/test_agent_monitor.py` line 11:
  ```python
  # before
  from orchestrator.runners.monitor import AgentRunnerMonitor
  # after
  from orchestrator.runners import AgentRunnerMonitor
  ```

- [ ] Update `tests/unit/test_executor_codex_lifecycle.py` line 18:
  ```python
  # before
  from orchestrator.runners.monitor import AgentRunnerMonitor
  # after
  from orchestrator.runners import AgentRunnerMonitor
  ```

- [ ] Update `tests/unit/test_nudger.py` line 8:
  ```python
  # before
  from orchestrator.runners.nudger import NudgeAction, Nudger, NudgerConfig
  # after
  from orchestrator.runners import NudgeAction, Nudger, NudgerConfig
  ```

- [ ] Update `tests/unit/test_cli_agent.py` line 7:
  ```python
  # before
  from orchestrator.runners.nudger import NudgerConfig
  # after
  from orchestrator.runners import NudgerConfig
  ```

- [ ] Update `tests/integration/test_cli_agent.py` line 16:
  ```python
  # before
  from orchestrator.runners.nudger import NudgerConfig
  # after
  from orchestrator.runners import NudgerConfig
  ```

- [ ] Update `tests/unit/agents/test_quota_model.py` line 7:
  ```python
  # before
  from orchestrator.runners.quota import FakeQuotaFetcher
  # after
  from orchestrator.runners import FakeQuotaFetcher
  ```

- [ ] Update `tests/unit/agents/test_openhands_quota.py` lines 15–16:
  ```python
  # before
  from orchestrator.runners.quota import FakeQuotaFetcher
  from orchestrator.runners.types import AgentQuota
  # after (only line 15 changes; types.py is not moved)
  from orchestrator.runners import FakeQuotaFetcher
  from orchestrator.runners.types import AgentQuota
  ```

- [ ] Update `tests/unit/test_repetition_detector.py` line 5:
  ```python
  # before
  from orchestrator.runners.repetition_detector import (
      ActionBudget, ActionBudgetConfig, ReasoningDetectorConfig,
      ReasoningRepetitionDetector, RepetitionAction,
      RepetitionDetector, RepetitionDetectorConfig,
  )
  # after
  from orchestrator.runners import (
      ActionBudget, ActionBudgetConfig, ReasoningDetectorConfig,
      ReasoningRepetitionDetector, RepetitionAction,
      RepetitionDetector, RepetitionDetectorConfig,
  )
  ```

- [ ] Update `tests/integration/test_api_agents.py` lines 34 and 43 (both lazy imports inside test functions):
  ```python
  # before (line 34)
  from orchestrator.runners.quota import FakeQuotaFetcher
  # after
  from orchestrator.runners import FakeQuotaFetcher
  ```
  ```python
  # before (line 43)
  from orchestrator.runners.detector import ToolDetector
  # after
  from orchestrator.runners import ToolDetector
  ```

- [ ] Final audit — confirm zero remaining direct sub-module references anywhere:
```bash
grep -rn "from orchestrator\.runners\.\(detector\|monitor\|nudger\|quota\|profile_resolution\|repetition_detector\|config_utils\)" \
  src/ tests/ --include="*.py" | grep -v "src/orchestrator/runners/detection\|src/orchestrator/runners/runtime"
```
If any remain, update them before continuing.

**Constraints**:
- Change only the import path for moved symbols. Do not alter test logic.
- Do not touch imports of un-moved modules (`runners.types`, `runners.executor`, `runners.errors`, `runners.agents.*`, etc.).

**Functionality (Expected Outcomes)**:
- [ ] All 12 test files import detection/runtime symbols via `from orchestrator.runners import X`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -rn "from orchestrator\.runners\.\(detector\|monitor\|nudger\|quota\|profile_resolution\|repetition_detector\|config_utils\)" tests/ --include="*.py"` returns zero results
- [ ] `uv run pytest tests/unit/test_tool_detector.py tests/unit/test_nudger.py tests/unit/test_repetition_detector.py tests/unit/test_agent_monitor.py -v` passes

---

## Task 7: Full Test Suite and Final Reference Audit

**Description**:
Run the complete test suite (backend unit, integration, frontend) and perform exhaustive grep verification that no references to the old flat module paths remain anywhere. This is the gate check before Phase 9 is considered complete.

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

- [ ] If any failures occur due to remaining old-path imports, fix those imports and re-run.

- [ ] Final reference audit — zero old sub-module paths anywhere:
```bash
grep -rn "from orchestrator\.runners\.\(detector\|monitor\|nudger\|quota\|profile_resolution\|repetition_detector\|config_utils\)" \
  src/ tests/ scripts/ alembic/ --include="*.py" \
  | grep -v "src/orchestrator/runners/detection\|src/orchestrator/runners/runtime" \
  || echo "OK: zero stale references"
```

- [ ] Verify sub-package structure is correct:
```bash
ls src/orchestrator/runners/detection/
ls src/orchestrator/runners/runtime/
ls src/orchestrator/runners/execution/
```

- [ ] Verify original flat files are gone:
```bash
for f in detector.py profile_resolution.py config_utils.py monitor.py nudger.py quota.py repetition_detector.py; do
  ls "src/orchestrator/runners/$f" 2>&1 || echo "OK: $f deleted"
done
```

- [ ] Verify `execution/` sub-package is unchanged (no new or removed files):
```bash
ls src/orchestrator/runners/execution/
# Expected: __init__.py  attempt_store.py  event_broadcaster.py  phase_handler.py
```

- [ ] Check for accidental shim markers:
```bash
grep -r "shim\|stub\|backward.compat\|backward_compat" src/orchestrator/runners/ --include="*.py" || echo "OK: no shim markers"
```

- [ ] Run pre-commit hooks:
```bash
uv run pre-commit run --all-files
```

**Functionality (Expected Outcomes)**:
- [ ] All backend unit and integration tests pass
- [ ] All frontend tests pass
- [ ] Zero references to old flat module paths
- [ ] `runners/detection/` and `runners/runtime/` sub-packages exist with proper `__init__.py`
- [ ] `runners/execution/` unchanged
- [ ] No shim markers in runners/ source

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -q` exits with code 0
- [ ] `cd ui && npx vitest run` exits with code 0
- [ ] `grep -rn "from orchestrator\.runners\.\(detector\|monitor\|nudger\|quota\|profile_resolution\|repetition_detector\|config_utils\)" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "runners/detection\|runners/runtime"` returns zero lines
- [ ] `ls src/orchestrator/runners/detector.py 2>&1` exits non-zero
- [ ] `ls src/orchestrator/runners/monitor.py 2>&1` exits non-zero
- [ ] `uv run python -c "from orchestrator.runners import ToolDetector, AgentRunnerMonitor, NudgerConfig, QuotaFetcher, RepetitionDetector, resolve_model_for_profile; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.runners.detection.detector import ToolDetector; from orchestrator.runners.runtime.monitor import AgentRunnerMonitor; print('ok')"` succeeds (sub-package paths also work directly)
- [ ] `git --no-pager diff --stat HEAD` shows deletions of old flat files and additions of `detection/` and `runtime/` sub-package files
