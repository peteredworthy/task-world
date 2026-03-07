# Gap Analysis: Run 92e15771 (agent-runners2)

## Summary

Run 92e15771 completed all 32 tasks across 8 steps in worktree `worktrees/r11`.
All auto_verify checks passed and all tests pass (2,262 backend, 349 frontend).
However, 4 cosmetic naming gaps remain in the Agent-to-AgentRunner rename.

## Gaps Found

All gaps are in Step S-01 (Rename Agents to Agent Runners - Backend).

| # | Gap | Location | Should Be |
|---|-----|----------|-----------|
| 1 | `class AgentMonitor` | `src/orchestrator/runners/monitor.py:67` | `AgentRunnerMonitor` |
| 2 | `app.state.agent_executor` | `src/orchestrator/api/app.py` (3 refs) | `app.state.runner_executor` |
| 3 | `app.state.agent_monitor` | `src/orchestrator/api/app.py` (2 refs) | `app.state.runner_monitor` |
| 4 | `get_agent_executor()` | `src/orchestrator/api/deps.py:138` + 3 router imports | `get_runner_executor()` |

## Root Cause: Narrow Verification in Routine

The routine's **requirement text was broad** ("All Agent* Python classes renamed to
AgentRunner* equivalents", "No orphaned AgentType/AgentExecutor/AgentInfo references")
but the **auto_verify checks and verifier rubric were too narrow**, only checking 3
specific class names.

### T-01 auto_verify (Rename Python Classes)

Checked only:
- `from orchestrator.agents.interface import AgentRunner` (import works)
- `from orchestrator.config.enums import AgentRunnerType` (import works)
- `! grep 'class AgentType\b' src/` (no old class)

Missing: No check for `class AgentMonitor` or any `Agent[A-Z]` pattern.

### T-05 auto_verify (Update Config, Engine, Non-Python)

Checked only:
- `! grep 'AgentType\b\|AgentExecutor\b\|AgentInfo\b' src/`

Missing: `AgentMonitor` not in the grep pattern. `agent_executor`, `agent_monitor`
attribute names and `get_agent_executor` function name not checked.

### T-05 verifier rubric

Asked: "Does the implementation satisfy: No orphaned AgentType/AgentExecutor/AgentInfo
references in source?" — same 3 names as auto_verify. LLM verifier matched the narrow
scope and graded as passing.

### Recommended fix for routine

Replace specific-name grep with a pattern match:
```bash
# Catches any Agent* class that isn't AgentRunner* or AgentConfig*
! grep -rn 'class Agent[A-Z][a-z]' src/ | grep -v 'AgentRunner\|AgentConfig'

# Catches old-style attribute/function names
! grep -rn 'agent_executor\|agent_monitor\|get_agent_executor\|get_agent_monitor' src/orchestrator/api/
```

## Remediation Plan

1. Rename `AgentMonitor` to `AgentRunnerMonitor` in monitor.py and all references
2. Rename `app.state.agent_executor` to `app.state.runner_executor` in app.py and deps.py
3. Rename `app.state.agent_monitor` to `app.state.runner_monitor` in app.py
4. Rename `get_agent_executor()` to `get_runner_executor()` in deps.py and all router imports
5. Run full test suite to confirm no regressions
