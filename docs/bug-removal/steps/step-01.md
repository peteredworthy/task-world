# Step 1: Fix GateBlockedError Handling (AGENT-DEATH-HUMAN-GATE — Backend)

This step fixes a critical bug where `GateBlockedError` raised by `on_submit()` falls through to the
generic `except Exception` handler in `cli.py`, causing it to be wrapped as `AgentExecutionError`
and triggering `on_agent_died`. After this fix, a gate-blocked submit causes the executor to keep
the task in `BUILDING` state and retry the agent with open-requirement feedback. This is the
prerequisite for Step 2 (human gate prompt rewrite).

## Intent Verification
**Original Intent**: `docs/bug-removal/intent.md` — "AGENT-DEATH-HUMAN-GATE: Handle `GateBlockedError` in `cli.py`"
**Functionality to Produce**:
- `GateBlockedError` imported from `workflow/errors.py` in `cli.py`
- `except GateBlockedError: raise` added before the generic `except Exception` block in `cli.py`'s `execute()`
- `executor.py:_execute_task` catches `GateBlockedError`, logs a warning, and returns without calling `on_agent_died`
- Task remains in `BUILDING` state after a gate-blocked submit
- Executor loop re-enters `_execute_task` on next iteration with open-requirement feedback

**Final Verification Criteria**:
- `pytest tests/ -k "gate_blocked"` passes
- `GateBlockedError` is explicitly re-raised in `cli.py` (not swallowed by generic handler)
- `executor.py` catches `GateBlockedError` without calling `on_agent_died`

---

## Task 1: Add GateBlockedError re-raise in cli.py
**Description**:
Import `GateBlockedError` from `workflow/errors.py` and add an explicit re-raise before the generic
`except Exception` block in `cli.py`'s `execute()` method so it propagates to `executor.py`.

**Implementation Plan (Do These Steps)**
The `execute()` method in `cli.py` currently has a generic `except Exception` block that wraps all
errors as `AgentExecutionError`. We need to intercept `GateBlockedError` before that happens.

- [ ] Open `src/orchestrator/agents/cli.py` and locate the `execute()` method (around line 438–457 based on plan)
- [ ] Add the import at the top of the file:
```python
from orchestrator.workflow.errors import GateBlockedError
```
- [ ] Inside `execute()`, add `except GateBlockedError: raise` **before** the generic `except Exception` block:
```python
# existing code
try:
    # ... existing agent execution code ...
except GateBlockedError:
    raise
except Exception as e:
    # ... existing generic handler ...
```

**References**
- `docs/bug-removal/step-01-plan.md` — Task 1 description
- `docs/bugs/AGENT-DEATH-HUMAN-GATE.md` — Issue 1 (GateBlockedError not handled)
- `docs/bug-removal/architecture.md` — "Modified Components: cli.py"

**Constraints**
- [ ] Only `cli.py` should be changed in this task; no other agent files should be altered

**Functionality (Expected Outcomes)**
- [ ] `GateBlockedError` is importable in `cli.py` from `orchestrator.workflow.errors`
- [ ] `GateBlockedError` is re-raised explicitly (not wrapped as `AgentExecutionError`) when it occurs in `execute()`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -n "GateBlockedError" src/orchestrator/agents/cli.py` shows both the import and the re-raise
- [ ] `uv run ruff check src/orchestrator/agents/cli.py` exits 0
- [ ] `uv run pyright src/orchestrator/agents/cli.py` exits 0

---

## Task 2: Catch GateBlockedError in executor.py
**Description**:
In `executor.py`'s `_execute_task`, catch `GateBlockedError` from `await agent.execute(...)`, log
a warning, and return without calling `on_agent_died` or `on_error`. This leaves the task in
`BUILDING` state so the executor loop retries automatically.

**Implementation Plan (Do These Steps)**
The `_execute_task` method currently does not distinguish `GateBlockedError` from other exceptions.
We need to add a specific catch for it before the generic exception handler.

- [ ] Open `src/orchestrator/agents/executor.py` and locate `_execute_task`
- [ ] Add the import at the top of the file:
```python
from orchestrator.workflow.errors import GateBlockedError
```
- [ ] In `_execute_task`, add the catch before the generic exception handler:
```python
try:
    await agent.execute(...)
except GateBlockedError:
    logger.warning("Agent submit blocked by gate — task remains BUILDING, will retry")
    return
except Exception as e:
    # ... existing error handling (on_agent_died, on_error) ...
```
- [ ] Verify the task is NOT transitioned or marked failed — simply return so the executor loop will re-invoke `_execute_task` on its next iteration

**References**
- `docs/bug-removal/step-01-plan.md` — Task 2 description
- `docs/bug-removal/architecture.md` — "Modified Components: executor.py"

**Constraints**
- [ ] Only `executor.py` should be changed in this task
- [ ] `on_agent_died` and `on_error` must NOT be called when `GateBlockedError` is caught

**Functionality (Expected Outcomes)**
- [ ] When `GateBlockedError` is raised during `agent.execute()`, `_execute_task` returns without calling `on_agent_died`
- [ ] Task status remains `BUILDING` after a gate-blocked submit

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `grep -n "GateBlockedError" src/orchestrator/agents/executor.py` shows the import and the catch
- [ ] `uv run ruff check src/orchestrator/agents/executor.py` exits 0
- [ ] `uv run pyright src/orchestrator/agents/executor.py` exits 0

---

## Task 3: Write unit tests for GateBlockedError handling
**Description**:
Write unit tests that verify `cli.py` re-raises `GateBlockedError` (not wrapping it) and that
`executor.py`'s `_execute_task` returns without calling `on_agent_died` when a gate-blocked error
occurs.

**Implementation Plan (Do These Steps)**
- [ ] Create or extend a test file (e.g., `tests/unit/agents/test_gate_blocked.py`)
- [ ] Test 1 — cli.py re-raise: mock `on_submit` to raise `GateBlockedError`; call `execute()`; assert `GateBlockedError` propagates (not wrapped as `AgentExecutionError`)
```python
import pytest
from unittest.mock import AsyncMock, patch
from orchestrator.workflow.errors import GateBlockedError

async def test_cli_reraises_gate_blocked_error():
    # arrange: mock the submit call to raise GateBlockedError
    # act: call agent.execute()
    # assert: GateBlockedError propagates unchanged
    ...
```
- [ ] Test 2 — executor.py no on_agent_died: mock agent that raises `GateBlockedError`; call `_execute_task`; assert `on_agent_died` was NOT called and task status is `BUILDING`
- [ ] Run `pytest tests/ -k "gate_blocked"` and confirm both tests pass

**References**
- `docs/bug-removal/step-01-plan.md` — Task 3 description
- `docs/bug-removal/architecture.md` — Testing Strategy (unit tests)

**Functionality (Expected Outcomes)**
- [ ] Unit test for `cli.py` GateBlockedError propagation exists and passes
- [ ] Unit test for `executor.py` retry-without-death behavior exists and passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `pytest tests/ -k "gate_blocked" -v` exits 0 with both tests shown as PASSED
- [ ] Test file exists at `tests/unit/agents/test_gate_blocked.py` (or equivalent path)
