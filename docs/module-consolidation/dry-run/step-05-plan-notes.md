# Dry-Run Analysis: Step 5 — Absorb metrics/ + mcp/ → api/

Analyzed against the current codebase state (pre-execution, after steps 0–4 assumed complete).

---

## Overall Assessment

The step is structurally sound: line numbers are accurate, import counts are correct, and the task sequence (create → update → delete → verify) is correct. There is **one hidden ordering dependency** that contradicts the step's "independent" claim and will silently cause problems if step 5 runs out of sequence. There are also two minor gaps (unmentioned imports in tools.py, misleading reasoning in Task 2) that need hardening.

---

## Critical Finding: Step Is NOT Truly Independent of Step 2

The step file states: "This phase is independent of all other phases" and Task 2 says tools.py and server.py have imports that "are unchanged because those modules still exist at the same paths."

Both claims are **incorrect** for `orchestrator.repos`:

`src/orchestrator/mcp/tools.py` contains two imports from `orchestrator.repos`:
```python
from orchestrator.repos.discovery import get_repo, list_branches, list_repos
from orchestrator.repos.errors import RepoNotFoundError
```

Step 2 (absorbing `repos/` into `git/repos/`) explicitly updates these in `mcp/tools.py` to:
```python
from orchestrator.git.repos.discovery import get_repo, list_branches, list_repos
from orchestrator.git.repos.errors import RepoNotFoundError
```

**Scenario A — normal sequential execution (steps 0→5 in order):**
By the time step 5 runs, step 2 has already updated `src/orchestrator/mcp/tools.py`. Step 5 copies the already-updated file to `api/mcp/tools.py`, preserving the correct `orchestrator.git.repos.*` imports. **Works correctly by accident**, not by design.

**Scenario B — step 5 runs before step 2 (treating "independent" literally):**
Step 5 copies `mcp/tools.py` with the original `orchestrator.repos.*` imports. When step 2 later runs, it updates `src/orchestrator/mcp/tools.py` but has no task covering `src/orchestrator/api/mcp/tools.py` (which didn't exist at step 2 authoring time). The `api/mcp/tools.py` copy is left with broken imports that fail at runtime. Step 2's grep-based verification (`grep -r "from orchestrator\.repos" src/`) would catch this, but only if its post-deletion audit checks the new `api/mcp/` path.

**Hardening actions:**
1. Remove the "independent of all other phases" claim — step 5 must run after step 2.
2. In Task 2, replace "those imports are unchanged" with an explicit note: "By the time step 5 runs (after step 2), `mcp/tools.py` already uses `orchestrator.git.repos.*` — the copy preserves those updated paths."
3. Step 2's verification grep should include `src/orchestrator/api/` in its scope (even though `api/mcp/` didn't exist at step 2 authoring time, this makes the verification future-proof).

---

## Task-by-Task Analysis

### Task 1: Create api/metrics.py

**Assumptions:**
- `src/orchestrator/metrics/__init__.py` is empty (confirmed: single whitespace line — no content to carry forward)
- `src/orchestrator/metrics/cost.py` has no intra-package imports (confirmed: no `from orchestrator.metrics` imports in the file)
- `src/orchestrator/api/metrics.py` does not yet exist (confirmed: absent)

**Expected outputs:**
- `api/metrics.py` containing `CostEstimate`, `PRICING`, `estimate_cost` — all 71 lines copied verbatim

**Blockers / gaps:**
- None. Task 1 is clean.

**Verification commands are correct:**
- `uv run python -c "from orchestrator.api.metrics import estimate_cost, CostEstimate; print('ok')"` will succeed once the file is created.

---

### Task 2: Create api/mcp/ Sub-Package and Move Files

**Assumptions:**
- `src/orchestrator/api/mcp/` does not yet exist (confirmed: absent)
- Internal imports in `tools.py` line 13 and `server.py` line 16 need updating

**Line number verification:**
- `tools.py` line 13: `from orchestrator.mcp.clarification_tools import CLARIFICATION_TOOL` — **confirmed correct**
- `server.py` line 16: `from orchestrator.mcp.tools import ORCHESTRATOR_TOOLS, ToolHandler` — **confirmed correct**

**Unmentioned import in tools.py — `orchestrator.time_utils`:**
`src/orchestrator/mcp/tools.py` also imports:
```python
from orchestrator.time_utils import format_utc_datetime
```
The step file does not mention this. `src/orchestrator/time_utils.py` exists as a standalone utility module. It is not listed as a target of any consolidation phase, so it will remain at `orchestrator.time_utils` throughout all phases. The copy will include this import unchanged, which is correct. This is not a risk, but the step file should list it alongside the other "unchanged" imports to avoid confusion.

**Unmentioned future dependency on Step 7 (workflow restructuring):**
`tools.py` also imports:
```python
from orchestrator.workflow.clarifications import ClarificationQuestion
```
After step 7, `workflow/clarifications.py` moves to `workflow/agent/clarifications.py`. Step 7 must update `api/mcp/tools.py`. This is step 7's responsibility, not step 5's — but it's worth confirming step 7's plan covers the `api/mcp/` path.

**Expected outputs:**
- `api/mcp/__init__.py` with docstring `"""MCP server for external agent integration."""` (matches original)
- `api/mcp/clarification_tools.py` — verbatim copy (no imports to update)
- `api/mcp/tools.py` — copy with line 13 updated to `from orchestrator.api.mcp.clarification_tools import CLARIFICATION_TOOL`, plus (by the time step 5 runs) already has `orchestrator.git.repos.*` imports from step 2's update
- `api/mcp/server.py` — copy with line 16 updated to `from orchestrator.api.mcp.tools import ORCHESTRATOR_TOOLS, ToolHandler`

**Wiring check:** No wiring gap. The old `orchestrator.mcp.*` directories are deleted in Task 4, so Python will be forced to use the new `orchestrator.api.mcp.*` paths. There is no risk of the old implementation silently remaining in use.

---

### Task 3: Update All External Import Sites

**Import site count verification:**
- Step header: "2 import sites for `orchestrator.metrics`" — **confirmed**: `api/routers/runs.py` line 68 and `tests/unit/test_cost.py` line 3
- Step header: "9 for `orchestrator.mcp` (2 in `app.py`, 2 internal to `mcp/`, 5 in tests/)" — **confirmed**: 2 in `app.py` (lines 604 and 643), 2 internal (handled in Task 2), 5 in tests

**Line number verification for all 7 external sites:**

| File | Line | Import | Verified |
|------|------|--------|---------|
| `api/routers/runs.py` | 68 | `from orchestrator.metrics.cost import estimate_cost` | ✓ confirmed |
| `tests/unit/test_cost.py` | 3 | `from orchestrator.metrics.cost import estimate_cost` | ✓ confirmed |
| `api/app.py` | 604 | `from orchestrator.mcp.tools import ToolHandler` (inside `_SessionPerCallHandler.handle()`) | ✓ confirmed |
| `api/app.py` | 643 | `from orchestrator.mcp.server import OrchestratorMCPServer` (inside `_mount_mcp_sse()`) | ✓ confirmed |
| `tests/integration/test_mcp_server.py` | 13 | `from orchestrator.mcp.server import OrchestratorMCPServer` | ✓ confirmed |
| `tests/unit/test_cli_agent.py` | 223 | `from orchestrator.mcp.tools import ORCHESTRATOR_TOOLS` (inside test function) | ✓ confirmed |
| `tests/integration/test_mcp_tools.py` | 19 | `from orchestrator.mcp.tools import ToolHandler` | ✓ confirmed |
| `tests/unit/mcp/test_phase_filtering.py` | 8 | `from orchestrator.mcp.server import ALL_TOOLS, OrchestratorMCPServer` | ✓ confirmed |
| `tests/unit/test_mcp_tool_definitions.py` | 3 | `from orchestrator.mcp.tools import ORCHESTRATOR_TOOLS` | ✓ confirmed |

All line numbers and import signatures are **accurate**.

**The audit grep in Task 3 is correctly scoped** — it excludes the old module directories themselves from results, which is the right approach for verifying only external consumers are updated.

**Blockers / gaps:**
- The `time_utils` import in `tools.py` is not an import site for `orchestrator.mcp` and doesn't need updating here. No gap.
- No imports found in `scripts/` or `alembic/` for either module — confirmed by the exploration. The audit command will return zero results there.

---

### Task 4: Delete Original metrics/ and mcp/ Directories

**Pre-deletion guard checks are correctly specified.** The `grep` commands exclude the old directories' own contents, which is the right approach.

**Expected outcomes:**
- Both directories deleted
- New `api/metrics.py` and `api/mcp/` confirmed present
- `uv run python -c "from orchestrator.metrics import estimate_cost"` raises `ModuleNotFoundError` — correct signal that no shim remains

**No re-export risk:** The `metrics/__init__.py` was empty, so no re-export could accidentally survive. The `mcp/__init__.py` had only a docstring. Neither can leave a functional re-export shim.

---

### Task 5: Full Test Suite and Final Reference Audit

**Circular import verification is correct:**
- `api/mcp/server.py` imports: `orchestrator.mcp.tools` → (updated to) `orchestrator.api.mcp.tools`, plus `orchestrator.workflow.service`
- `api/mcp/tools.py` imports: `orchestrator.config.enums`, `orchestrator.git.repos.*`, `orchestrator.time_utils`, `orchestrator.workflow.clarifications`, `orchestrator.workflow.service`
- Neither imports from `orchestrator.api.routers`, `orchestrator.api.app`, or `orchestrator.api.deps`
- The verification command correctly checks for these circular patterns

**Reference audit grep commands are accurate.** The double-`||`-connected greps will catch any lingering `from orchestrator.metrics` or `from orchestrator.mcp` references regardless of subdirectory depth.

**Potential test failure NOT due to this step:**
- `tests/integration/` has 2 tests that fail due to the openhands module not being installed (per MEMORY.md baseline). These are pre-existing failures unrelated to step 5 and should not be counted against this step's verification.

---

## Summary of Failure Modes and Hardening Actions

| # | Failure Mode | Severity | Hardening Action |
|---|--------------|----------|-----------------|
| 1 | Step 5 runs before step 2; `api/mcp/tools.py` gets stale `orchestrator.repos.*` imports; step 2 doesn't update the `api/mcp/` copy | **High** | Remove "independent of all other phases" claim; add explicit prerequisite: "Step 2 must be complete before step 5" |
| 2 | Step 2's post-deletion grep doesn't cover `src/orchestrator/api/mcp/` (path didn't exist at authoring time) | **Medium** | Step 2's verification grep should include `src/orchestrator/api/` in its search scope |
| 3 | Task 2's reasoning ("unchanged because those modules still exist at the same paths") is factually wrong and will confuse implementors | **Low** | Update Task 2 constraint note to accurately state: "By step 5 execution time, `mcp/tools.py` already has `orchestrator.git.repos.*` imports (updated by step 2) — the copy preserves these" |
| 4 | `from orchestrator.time_utils import format_utc_datetime` in tools.py is not listed in Task 2's unchanged-imports accounting | **Low** | Add `time_utils` to Task 2's list of external imports that are carried over verbatim |
| 5 | Step 7's workflow restructuring must update `api/mcp/tools.py` (`workflow.clarifications` → `workflow.agent.clarifications`); step 7 may not know to look in `api/mcp/` | **Low** (step 7 risk, not step 5) | Flag in step 7's plan: "Update `api/mcp/tools.py` ClarificationQuestion import path" |
| 6 | 2 pre-existing integration test failures (openhands) may cause confusion during Task 5 verification | **Low** | Add note to Task 5: "2 pre-existing integration failures (openhands not installed) are expected and not caused by this step" |

---

## What Is Correct and Does Not Need Changes

- All 9 external import site line numbers are verified accurate against source
- Import counts (2 metrics, 7 external mcp) are correct
- Task sequencing (create → copy → update external → delete → verify) is correct
- No functional circular import risk: `api/mcp/` only imports from layers below `api/`
- Deletion guard checks (grep before rm) are correctly specified
- Wiring is complete: old directories are deleted, forcing all consumers to new paths
- The `__init__.py` docstring content is correctly specified for `api/mcp/`
- `metrics/__init__.py` emptiness is correctly identified (nothing to port)
