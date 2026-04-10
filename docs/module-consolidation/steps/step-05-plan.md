# Step 5: Absorb metrics/ + mcp/ → api/

Move the `metrics/` and `mcp/` modules into `api/` — `metrics/` is flattened to `api/metrics.py` and `mcp/` becomes an `api/mcp/` sub-package. Both are API-layer concerns: metrics computes cost data for API responses, and MCP exposes an alternative API interface. This phase is independent of all other phases.

There are 2 import sites for `orchestrator.metrics` (1 in `src/`, 1 in `tests/`) and 9 for `orchestrator.mcp` (2 in `app.py`, 2 internal to `mcp/`, 5 in `tests/`). All must be updated before deleting the original directories.

## Intent Verification
**Original Intent**: Phase 5 of the module consolidation plan — absorb `metrics/` and `mcp/` into `api/` with zero shims, zero leftover references, and all tests passing.

**Functionality to Produce**:
- `src/orchestrator/api/metrics.py` — content of `metrics/cost.py` (flattened from 2-file package to single file)
- `src/orchestrator/api/mcp/` sub-package with `__init__.py`, `server.py`, `tools.py`, `clarification_tools.py`
- `src/orchestrator/metrics/` and `src/orchestrator/mcp/` directories entirely removed
- All import paths updated: `orchestrator.metrics.cost` → `orchestrator.api.metrics`, `orchestrator.mcp.*` → `orchestrator.api.mcp.*`

**Final Verification Criteria**:
- All backend unit and integration tests pass
- All frontend tests pass
- `grep -r "from orchestrator.metrics" src/ tests/` returns zero results
- `grep -r "from orchestrator.mcp" src/ tests/` returns zero results (excluding `api/mcp/` self-imports)
- `src/orchestrator/metrics/` and `src/orchestrator/mcp/` directories do not exist
- No circular imports: `api/mcp/` and `api/metrics.py` must not import from `api/` routers or app-level modules

---

## Task 1: Create api/metrics.py

**Description**:
Flatten the two-file `metrics/` package (`__init__.py` + `cost.py`) into a single `api/metrics.py`. The `__init__.py` is empty, so all content is in `cost.py`.

**Implementation Plan (Do These Steps)**

- [ ] Create `src/orchestrator/api/metrics.py` by copying the content of `src/orchestrator/metrics/cost.py` verbatim. No import changes are needed — `cost.py` has no intra-package imports:
```bash
cp src/orchestrator/metrics/cost.py src/orchestrator/api/metrics.py
```

- [ ] Verify the file header is appropriate (the module docstring references "Cost estimation" which is still accurate):
```bash
head -3 src/orchestrator/api/metrics.py
```

**Constraints**:
- Do not delete `src/orchestrator/metrics/` yet.
- Do not change any import sites yet.
- `api/metrics.py` must not import from any `api/` router or app-level module.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/api/metrics.py` exists and contains `CostEstimate`, `PRICING`, and `estimate_cost`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.api.metrics import estimate_cost, CostEstimate; print('ok')"` succeeds
- [ ] `grep "from orchestrator.metrics" src/orchestrator/api/metrics.py` returns zero results (no self-referential imports)

---

## Task 2: Create api/mcp/ Sub-Package and Move Files

**Description**:
Create `api/mcp/` as a sub-package and copy the three MCP implementation files into it. Update the one internal import in `tools.py` that references `orchestrator.mcp.clarification_tools`. No other internal changes yet.

**Implementation Plan (Do These Steps)**

- [ ] Create the sub-package directory:
```bash
mkdir -p src/orchestrator/api/mcp
```

- [ ] Copy `clarification_tools.py` first (it has no intra-package imports, so no changes needed):
```bash
cp src/orchestrator/mcp/clarification_tools.py src/orchestrator/api/mcp/clarification_tools.py
```

- [ ] Copy `tools.py` and update its one internal import (line 13):

  Current:
  ```python
  from orchestrator.mcp.clarification_tools import CLARIFICATION_TOOL
  ```
  New (`src/orchestrator/api/mcp/tools.py` line 13):
  ```python
  from orchestrator.api.mcp.clarification_tools import CLARIFICATION_TOOL
  ```

- [ ] Copy `server.py` and update its one internal import (line 16):

  Current:
  ```python
  from orchestrator.mcp.tools import ORCHESTRATOR_TOOLS, ToolHandler
  ```
  New (`src/orchestrator/api/mcp/server.py` line 16):
  ```python
  from orchestrator.api.mcp.tools import ORCHESTRATOR_TOOLS, ToolHandler
  ```

- [ ] Create `src/orchestrator/api/mcp/__init__.py` mirroring the original:
```python
"""MCP server for external agent integration."""
```

**Constraints**:
- Do not delete `src/orchestrator/mcp/` yet.
- Do not update `app.py` or test imports yet.
- The files `tools.py` and `server.py` import from `orchestrator.workflow`, `orchestrator.repos`, etc. — those imports are unchanged because those modules still exist at the same paths.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/api/mcp/__init__.py`, `tools.py`, `server.py`, `clarification_tools.py` all exist
- [ ] No internal imports in the new `api/mcp/` files reference `orchestrator.mcp.*`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run python -c "from orchestrator.api.mcp.server import OrchestratorMCPServer; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.api.mcp.tools import ToolHandler, ORCHESTRATOR_TOOLS; print('ok')"` succeeds
- [ ] `grep "from orchestrator\.mcp\." src/orchestrator/api/mcp/tools.py src/orchestrator/api/mcp/server.py` returns zero results

---

## Task 3: Update All External Import Sites

**Description**:
Update every file outside `metrics/` and `mcp/` that imports from those old paths. There are 2 sites for metrics and 7 for mcp (2 in `app.py`, 5 in `tests/`).

**Implementation Plan (Do These Steps)**

**Metrics import sites (2 files):**

- [ ] Update `src/orchestrator/api/routers/runs.py` line 68:
  ```python
  from orchestrator.metrics.cost import estimate_cost
  ```
  →
  ```python
  from orchestrator.api.metrics import estimate_cost
  ```

- [ ] Update `tests/unit/test_cost.py` line 3:
  ```python
  from orchestrator.metrics.cost import estimate_cost
  ```
  →
  ```python
  from orchestrator.api.metrics import estimate_cost
  ```

**MCP import sites (2 in app.py, 5 in tests):**

- [ ] Update `src/orchestrator/api/app.py` line 604 (lazy import inside function):
  ```python
  from orchestrator.mcp.tools import ToolHandler
  ```
  →
  ```python
  from orchestrator.api.mcp.tools import ToolHandler
  ```

- [ ] Update `src/orchestrator/api/app.py` line 643 (lazy import inside function):
  ```python
  from orchestrator.mcp.server import OrchestratorMCPServer
  ```
  →
  ```python
  from orchestrator.api.mcp.server import OrchestratorMCPServer
  ```

- [ ] Update `tests/integration/test_mcp_server.py` line 13:
  ```python
  from orchestrator.mcp.server import OrchestratorMCPServer
  ```
  →
  ```python
  from orchestrator.api.mcp.server import OrchestratorMCPServer
  ```

- [ ] Update `tests/unit/test_cli_agent.py` line 223 (lazy import inside test):
  ```python
  from orchestrator.mcp.tools import ORCHESTRATOR_TOOLS
  ```
  →
  ```python
  from orchestrator.api.mcp.tools import ORCHESTRATOR_TOOLS
  ```

- [ ] Update `tests/integration/test_mcp_tools.py` line 19:
  ```python
  from orchestrator.mcp.tools import ToolHandler
  ```
  →
  ```python
  from orchestrator.api.mcp.tools import ToolHandler
  ```

- [ ] Update `tests/unit/mcp/test_phase_filtering.py` line 8:
  ```python
  from orchestrator.mcp.server import ALL_TOOLS, OrchestratorMCPServer
  ```
  →
  ```python
  from orchestrator.api.mcp.server import ALL_TOOLS, OrchestratorMCPServer
  ```

- [ ] Update `tests/unit/test_mcp_tool_definitions.py` line 3:
  ```python
  from orchestrator.mcp.tools import ORCHESTRATOR_TOOLS
  ```
  →
  ```python
  from orchestrator.api.mcp.tools import ORCHESTRATOR_TOOLS
  ```

- [ ] Audit for any remaining references in `scripts/` and `alembic/`:
```bash
grep -r "from orchestrator\.metrics\|from orchestrator\.mcp" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "src/orchestrator/metrics/\|src/orchestrator/mcp/\|src/orchestrator/api/metrics\|src/orchestrator/api/mcp/"
```
If any appear, update them before continuing.

**Constraints**:
- Do not delete `src/orchestrator/metrics/` or `src/orchestrator/mcp/` yet.
- Do not change the semantics of any updated file — import path changes only.

**Functionality (Expected Outcomes)**:
- [ ] All external consumers import from `orchestrator.api.metrics` or `orchestrator.api.mcp.*`
- [ ] `grep -r "from orchestrator\.metrics\|from orchestrator\.mcp" src/ tests/ scripts/ alembic/ --include="*.py"` returns only matches inside the old `src/orchestrator/metrics/` and `src/orchestrator/mcp/` directories themselves

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -r "from orchestrator\.metrics\|from orchestrator\.mcp" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "src/orchestrator/metrics/\|src/orchestrator/mcp/"` returns zero results
- [ ] `uv run python -c "from orchestrator.api.routers.runs import router; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.api.app import app; print('ok')"` succeeds

---

## Task 4: Delete Original metrics/ and mcp/ Directories

**Description**:
With all consumers updated, delete `src/orchestrator/metrics/` and `src/orchestrator/mcp/` entirely. No shim or re-export may be left behind.

**Implementation Plan (Do These Steps)**

- [ ] Confirm zero external references remain for metrics:
```bash
grep -r "from orchestrator\.metrics" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "src/orchestrator/metrics/"
```
Must return zero lines. If not, stop and fix in Task 3.

- [ ] Confirm zero external references remain for mcp:
```bash
grep -r "from orchestrator\.mcp" src/ tests/ scripts/ alembic/ --include="*.py" | grep -v "src/orchestrator/mcp/"
```
Must return zero lines. If not, stop and fix in Task 3.

- [ ] Delete both original directories:
```bash
rm -rf src/orchestrator/metrics/
rm -rf src/orchestrator/mcp/
```

- [ ] Confirm deletions:
```bash
ls src/orchestrator/metrics/ 2>&1 || echo "metrics/ deleted OK"
ls src/orchestrator/mcp/ 2>&1 || echo "mcp/ deleted OK"
```

- [ ] Confirm new locations are intact:
```bash
ls src/orchestrator/api/metrics.py
ls src/orchestrator/api/mcp/
```

**Constraints**:
- Delete the entire `metrics/` directory including `__init__.py` and `cost.py`.
- Delete the entire `mcp/` directory including `__init__.py`, `server.py`, `tools.py`, `clarification_tools.py`.
- No re-export shim may be left at either old location.

**Functionality (Expected Outcomes)**:
- [ ] `src/orchestrator/metrics/` does not exist
- [ ] `src/orchestrator/mcp/` does not exist
- [ ] `src/orchestrator/api/metrics.py` exists
- [ ] `src/orchestrator/api/mcp/` contains `__init__.py`, `server.py`, `tools.py`, `clarification_tools.py`

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `ls src/orchestrator/metrics/` fails with "No such file or directory"
- [ ] `ls src/orchestrator/mcp/` fails with "No such file or directory"
- [ ] `uv run python -c "from orchestrator.metrics import estimate_cost"` raises `ModuleNotFoundError`
- [ ] `uv run python -c "from orchestrator.mcp.server import OrchestratorMCPServer"` raises `ModuleNotFoundError`
- [ ] `uv run python -c "from orchestrator.api.metrics import estimate_cost; print('ok')"` succeeds
- [ ] `uv run python -c "from orchestrator.api.mcp.server import OrchestratorMCPServer; print('ok')"` succeeds

---

## Task 5: Full Test Suite and Final Reference Audit

**Description**:
Run the complete test suite and perform exhaustive grep verification that zero references to `orchestrator.metrics` or `orchestrator.mcp` remain anywhere in the repository. This is the gate check before Phase 5 is considered complete.

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

- [ ] If any test failures occur due to remaining old-path imports, fix those imports and re-run.

- [ ] Run the complete reference audit:
```bash
grep -r "from orchestrator\.metrics\|import orchestrator\.metrics" src/ tests/ scripts/ alembic/ --include="*.py" || echo "OK: zero metrics refs"
grep -r "from orchestrator\.mcp\|import orchestrator\.mcp" src/ tests/ scripts/ alembic/ --include="*.py" || echo "OK: zero mcp refs"
```

- [ ] Verify no circular imports — `api/mcp/` and `api/metrics.py` must not import from api routers:
```bash
grep -r "from orchestrator\.api\.routers\|from orchestrator\.api\.app\|from orchestrator\.api\.deps" src/orchestrator/api/mcp/ src/orchestrator/api/metrics.py --include="*.py" || echo "OK: no circular imports"
```

- [ ] Check for residual shim/stub markers:
```bash
grep -r "shim\|stub\|backward.compat\|backward_compat" src/orchestrator/api/mcp/ src/orchestrator/api/metrics.py --include="*.py" || echo "OK: no shim markers"
```

- [ ] Run pre-commit hooks:
```bash
uv run pre-commit run --all-files
```

**Functionality (Expected Outcomes)**:
- [ ] All backend unit and integration tests pass
- [ ] All frontend tests pass
- [ ] Every grep audit returns zero matches (or "OK:" echo)
- [ ] No circular imports in `api/mcp/` or `api/metrics.py`
- [ ] No shim markers in moved files

**Final Verification (Proof of Completion)**
DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit/ tests/integration/ -q` exits with code 0
- [ ] `cd ui && npx vitest run` exits with code 0
- [ ] `grep -r "from orchestrator\.metrics" src/ tests/ scripts/ alembic/ --include="*.py"` returns zero lines
- [ ] `grep -r "from orchestrator\.mcp" src/ tests/ scripts/ alembic/ --include="*.py"` returns zero lines
- [ ] `ls src/orchestrator/metrics/ 2>&1` exits with non-zero (directory absent)
- [ ] `ls src/orchestrator/mcp/ 2>&1` exits with non-zero (directory absent)
- [ ] `uv run python -c "from orchestrator.api.metrics import estimate_cost, CostEstimate; from orchestrator.api.mcp.server import OrchestratorMCPServer; print('ok')"` succeeds
- [ ] `git --no-pager diff --stat HEAD` shows deletions of `metrics/` and `mcp/` files and additions of `api/metrics.py` and `api/mcp/` files
