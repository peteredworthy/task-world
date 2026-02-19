# Step 5: Phase-Aware MCP Tool Filtering (MCP-TOOLS-NO-PHASE-FILTERING)

This step prevents builder agents from seeing verifier-only MCP tools (e.g., `orchestrator_set_grade`)
by making the MCP server filter its tool registry at initialization time based on the agent's phase.
Currently all tools are registered unconditionally; a builder agent that discovers `orchestrator_set_grade`
wastes a tool call when it calls it and receives `InvalidTransitionError`. After this fix, builder
connections will see only builder tools and verifier connections will see only verifier tools.

## Intent Verification
**Original Intent**: `docs/bug-removal/intent.md` — "MCP-TOOLS-NO-PHASE-FILTERING: Implement phase-aware MCP tool filtering so builder agents see only builder tools and verifier agents see only verifier tools"
**Functionality to Produce**:
- MCP server accepts `phase: Literal["building", "verifying"]` at initialization
- Builder connections expose only: `orchestrator_get_requirements`, `orchestrator_update_checklist`, `orchestrator_submit`, `orchestrator_request_clarification`, `orchestrator_list_repos`, `orchestrator_list_branches`
- Verifier connections expose only: `orchestrator_get_requirements`, `orchestrator_set_grade`, `orchestrator_submit`
- `executor.py` passes the correct phase when constructing the MCP server

**Final Verification Criteria**:
- Unit test: builder tool list does not contain `orchestrator_set_grade`
- Unit test: verifier tool list does not contain `orchestrator_update_checklist`
- `ValueError` raised when an explicitly invalid phase value is passed

---

## Task 1: Add phase parameter to MCP server and filter _register_tools()
**Description**:
Add `phase: Literal["building", "verifying"]` with a safe default of `"building"` to the MCP
server's `__init__` and update `_register_tools()` to conditionally register tools based on
`self.phase`. The default ensures existing callers (not yet updated by Task 2) continue to work
with the builder tool set while the parameter is being propagated. Fail fast with `ValueError` for
any explicitly invalid phase string.

**Implementation Plan (Do These Steps)**
The MCP server in `src/orchestrator/mcp/server.py` currently registers all tools unconditionally
in `_register_tools()`. We add a phase attribute with a default and split the registration into
two sets. The default of `"building"` ensures the system stays runnable until executor.py is
updated in Task 2.

- [ ] Open `src/orchestrator/mcp/server.py`
- [ ] Update `__init__` to accept and validate the `phase` parameter with a safe default:
```python
from typing import Literal

BUILDER_TOOLS = {
    "orchestrator_get_requirements",
    "orchestrator_update_checklist",
    "orchestrator_submit",
    "orchestrator_request_clarification",
    "orchestrator_list_repos",
    "orchestrator_list_branches",
}

VERIFIER_TOOLS = {
    "orchestrator_get_requirements",
    "orchestrator_set_grade",
    "orchestrator_submit",
}

class OrchestratorMCPServer:
    def __init__(self, ..., phase: Literal["building", "verifying"] = "building"):
        if phase not in ("building", "verifying"):
            raise ValueError(f"Invalid phase: {phase!r}. Must be 'building' or 'verifying'.")
        self.phase = phase
        # ... existing init code ...
```
- [ ] Update `_register_tools()` to conditionally register based on phase:
```python
def _register_tools(self):
    allowed = BUILDER_TOOLS if self.phase == "building" else VERIFIER_TOOLS
    for tool_name, tool_fn in ALL_TOOLS.items():
        if tool_name in allowed:
            self.server.add_tool(tool_name, tool_fn)
```
- [ ] Verify existing tool registration structure to understand the correct integration point
- [ ] Run `uv run pyright src/orchestrator/mcp/server.py` and `uv run ruff check src/orchestrator/mcp/server.py`

**References**
- `docs/bug-removal/step-05-plan.md` — Task 1 description
- `docs/bug-removal/architecture.md` — "Modified Components: mcp/server.py", initialization-time phase parameter
- `docs/bugs/MCP-TOOLS-NO-PHASE-FILTERING.md` — Root Cause and Proposed Fix (Option A)

**Constraints**
- [ ] Only `server.py` should be changed in this task
- [ ] The existing `tools.py` soft-error workaround must remain as a safety net (do not remove it)

**Side Effects**
- [ ] Until Task 2 (executor.py) is applied, all MCP server instances that do not pass an explicit `phase` will default to the builder tool set (`"building"`). This is the safe behavior: verifier-only tools are filtered out for everyone, avoiding invalid tool calls during the transition window.

**Functionality (Expected Outcomes)**
- [ ] MCP server accepts `phase` at construction time with `"building"` as the default
- [ ] `ValueError` raised when `phase` is an explicitly invalid string (not `"building"` or `"verifying"`)
- [ ] Builder phase: `orchestrator_set_grade` is NOT registered
- [ ] Verifier phase: `orchestrator_update_checklist` is NOT registered
- [ ] Existing callers that omit `phase` continue to work (they receive builder tool set)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pyright src/orchestrator/mcp/server.py` exits 0
- [ ] `uv run ruff check src/orchestrator/mcp/server.py` exits 0

---

## Task 2: Pass phase parameter from executor.py when spawning agents
**Description**:
Update `executor.py` to determine the current task phase and pass it when constructing the MCP
server or agent session. BUILDING status maps to `"building"`, VERIFYING to `"verifying"`.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/agents/executor.py`
- [ ] Locate where the MCP server (or agent session) is constructed for each task
- [ ] Derive the phase from the task's current status:
```python
from orchestrator.models import TaskStatus

def _get_phase(task_status: TaskStatus) -> str:
    if task_status == TaskStatus.VERIFYING:
        return "verifying"
    return "building"  # BUILDING is the default for all other states

# When constructing MCP server:
phase = _get_phase(task.status)
mcp_server = OrchestratorMCPServer(..., phase=phase)
```
- [ ] Confirm the phase is passed correctly in all code paths that construct the server

**References**
- `docs/bug-removal/step-05-plan.md` — Task 2 description
- `docs/bug-removal/architecture.md` — "Interactions: MCP phase filtering"

**Constraints**
- [ ] Only `executor.py` should be changed in this task

**Functionality (Expected Outcomes)**
- [ ] Builder agents receive phase `"building"` at construction time
- [ ] Verifier agents receive phase `"verifying"` at construction time

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pyright src/orchestrator/agents/executor.py` exits 0
- [ ] `uv run ruff check src/orchestrator/agents/executor.py` exits 0

---

## Task 3: Write unit tests for phase-aware tool filtering
**Description**:
Write unit tests that verify the builder tool list excludes `orchestrator_set_grade`, the verifier
tool list excludes `orchestrator_update_checklist`, and `ValueError` is raised for an invalid phase.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/mcp/test_phase_filtering.py`
- [ ] Test 1 — builder tool list: construct the MCP server with `phase="building"`; get the registered tools; assert `orchestrator_set_grade` is NOT present
- [ ] Test 2 — verifier tool list: construct with `phase="verifying"`; assert `orchestrator_update_checklist` is NOT present
- [ ] Test 3 — invalid phase: construct with `phase="unknown"`; assert `ValueError` is raised
- [ ] Test 4 — default phase: construct with no `phase` argument; assert no exception and tool list matches builder set (i.e., `orchestrator_set_grade` is absent)
```python
import pytest
from orchestrator.mcp.server import OrchestratorMCPServer

def test_builder_cannot_see_set_grade():
    server = OrchestratorMCPServer(..., phase="building")
    tool_names = [t.name for t in server.get_tools()]
    assert "orchestrator_set_grade" not in tool_names

def test_verifier_cannot_see_update_checklist():
    server = OrchestratorMCPServer(..., phase="verifying")
    tool_names = [t.name for t in server.get_tools()]
    assert "orchestrator_update_checklist" not in tool_names

def test_invalid_phase_raises_value_error():
    with pytest.raises(ValueError, match="Invalid phase"):
        OrchestratorMCPServer(..., phase="unknown")

def test_default_phase_is_builder():
    # Omitting phase defaults to "building" — system stays runnable before executor.py is updated
    server = OrchestratorMCPServer(...)  # no phase argument
    tool_names = [t.name for t in server.get_tools()]
    assert "orchestrator_set_grade" not in tool_names
    assert "orchestrator_update_checklist" in tool_names
```
- [ ] Run `pytest tests/ -k "mcp or phase_filter" -v`

**References**
- `docs/bug-removal/step-05-plan.md` — Task 3 description
- `docs/bug-removal/architecture.md` — Testing Strategy (unit tests for MCP phase filtering)

**Functionality (Expected Outcomes)**
- [ ] Four unit tests exist in the test file, all passing
- [ ] Builder tool list explicitly tested to exclude `orchestrator_set_grade`
- [ ] Verifier tool list explicitly tested to exclude `orchestrator_update_checklist`
- [ ] Default (no `phase` arg) produces builder tool set without raising an exception

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `pytest tests/ -k "mcp or phase_filter" -v` exits 0 with all 4 tests PASSED
- [ ] Test file exists at `tests/unit/mcp/test_phase_filtering.py`
