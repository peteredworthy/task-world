# Step 1 Plan: Fix GateBlockedError Handling (AGENT-DEATH-HUMAN-GATE — Backend)

## Purpose

Prevent runs from entering `agent_execution_error` pause state when a CLI agent exits cleanly but the checklist gate is not satisfied. Currently, `GateBlockedError` raised by `on_submit()` falls through to the generic `except Exception` handler in `cli.py`, causing it to be wrapped as `AgentExecutionError` and triggering `on_agent_died`. This breaks autonomous operation of any routine with `human_approval` gates. After this fix, a gate-blocked submit will cause the executor to keep the task in `BUILDING` state and retry the agent with feedback about open requirements.

## Prerequisites

- None (root step with no dependencies)

## Functional Contract

### Inputs

- `GateBlockedError` raised from `on_submit()` → `service.submit_for_verification()` → `engine.submit_for_verification()` when a checklist gate requirement is not satisfied
- `agent.execute(...)` call in `executor.py:_execute_task`

### Outputs

- `cli.py`: `GateBlockedError` is imported from `workflow/errors.py` and re-raised explicitly in the `except` chain, before the generic `except Exception` block
- `executor.py`: `_execute_task` catches `GateBlockedError`, logs a warning, and returns without calling `on_agent_died` or `on_error`; the task remains in `BUILDING` state
- The executor loop re-enters `_execute_task` on the next iteration, spawning a new agent with open-requirement feedback

### Errors

- If `GateBlockedError` is not importable from `workflow/errors.py`, import path must be corrected before deployment
- If the executor retry loop does not have a back-off or max-retry guard, infinite retry loops are possible — existing `max_attempts` guard provides the ceiling

## Tasks

1. In `src/orchestrator/agents/cli.py`: import `GateBlockedError` from `src/orchestrator/workflow/errors.py`; add `except GateBlockedError: raise` before the generic `except Exception` block in `execute()`
2. In `src/orchestrator/agents/executor.py`: in `_execute_task`, catch `GateBlockedError` from `await agent.execute(...)`; log a warning and return (do not call `on_agent_died` or `on_error`); task remains in `BUILDING` state
3. Write unit test: mock agent that raises `GateBlockedError`; assert `_execute_task` returns without calling `on_agent_died` and task stays in `BUILDING`

## Verification

### Auto-Verify

- [ ] `pytest tests/ -k "gate_blocked"` passes (new unit tests for cli.py and executor.py behavior)
- [ ] `GateBlockedError` is in the explicit re-raise chain in `cli.py` (grep check)
- [ ] `executor.py` catches `GateBlockedError` without calling `on_agent_died` (grep/AST check)

### Manual Verify

- [ ] Run `idea-to-plan` routine with CLI agent through S-02 human gate; verify run does not pause with `agent_execution_error` after agent exit
- [ ] Confirm task stays in `BUILDING` state after a gate-blocked submit and the executor retries with updated feedback

## Context & References

- Bug report: `docs/bugs/AGENT-DEATH-HUMAN-GATE.md` — Issue 1 (GateBlockedError not handled)
- Source files: `src/orchestrator/agents/cli.py:438-457`, `src/orchestrator/agents/executor.py:_execute_task`
- Architecture: `docs/bug-removal/architecture.md` — "Modified Components: cli.py, executor.py"
- Dependent step: Step 2 (human gate prompt rewrite) requires Step 1 to be complete
