# Gap Analysis: Run 92e15771 (agent-runners2)

## Summary

Run 92e15771 completed all 32 tasks across 8 steps in worktree `worktrees/r11`.
All auto_verify checks passed and all tests pass (2,262 backend, 349 frontend).
However, 8 naming gaps were found in the Agent-to-AgentRunner rename across
backend and frontend. All gaps have been remediated.

## Gaps Found (Round 1 - Backend)

All gaps in Step S-01 (Rename Agents to Agent Runners - Backend).

| # | Gap | Location | Renamed To |
|---|-----|----------|------------|
| 1 | `class AgentMonitor` | `runners/monitor.py` | `AgentRunnerMonitor` |
| 2 | `app.state.agent_executor` | `api/app.py` (3 refs) | `app.state.runner_executor` |
| 3 | `app.state.agent_monitor` | `api/app.py` (2 refs) | `app.state.runner_monitor` |
| 4 | `get_agent_executor()` | `api/deps.py` + 3 routers | `get_runner_executor()` |

## Gaps Found (Round 2 - Frontend + Router)

| # | Gap | Location | Renamed To |
|---|-----|----------|------------|
| 5 | `list_agents()` router fn | `api/routers/runners.py` | `list_agent_runners()` |
| 6 | `useAgents()` hook | `hooks/useApi.ts` + 6 components | `useAgentRunners()` |
| 7 | `listAgents()` API method | `api/client.ts` | `listAgentRunners()` |
| 8 | `AgentType` type alias | `types/enums.ts` + 2 type files | `AgentRunnerType` |

Also fixed: query key `['agents']` → `['agent-runners']` in hook and test file.

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
references in source?" -- same 3 names as auto_verify. LLM verifier matched the narrow
scope and graded as passing.

### S-02/S-07 frontend tasks

Auto_verify only checked `tsc --noEmit` and component existence. No checks for
hook/API method naming consistency with the rename.

### Recommended fix for future routines

Replace specific-name grep with pattern matches:
```bash
# Catches any Agent* class that isn't AgentRunner* or AgentConfig*
! grep -rn 'class Agent[A-Z][a-z]' src/ | grep -v 'AgentRunner\|AgentConfig'

# Catches old-style attribute/function names in API layer
! grep -rn 'agent_executor\|agent_monitor\|get_agent_executor' src/orchestrator/api/

# Catches old-style hook/method names in frontend
! grep -rn 'useAgents\b\|listAgents\b' ui/src/ | grep -v AgentRunners
! grep -rn 'AgentType\b' ui/src/types/ | grep -v AgentRunnerType
```

## Remediation Status: COMPLETE

All 8 gaps remediated in two commits:
1. `3a3e1ea` - Backend: AgentMonitor, app.state attributes, deps
2. `ecf99db` - Frontend: router fn, hook, API client, type alias

### Final Test Results

- 2,286 backend tests pass (1,458 unit + 808 integration + 20 E2E)
- 351 frontend tests pass (46 test files)
- TypeScript type-check clean
- ESLint clean (via pre-commit)
- Vite build clean
- Pyright clean (via pre-commit)
