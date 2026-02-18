# Bug: MCP Server Exposes All Tools Regardless of Task Phase

## Summary

The MCP server exposes `orchestrator_set_grade` to builder agents (claude, codex) during the BUILDING phase. The builder agent sees this tool in the MCP tool list, calls it prematurely, and gets an `InvalidTransitionError` because grading is only allowed during VERIFYING.

**Observed error:**
```
Agent 'cli_subprocess' execution failed: Invalid transition: building -> set_grade (only allowed in VERIFYING or terminal status)
```

## Current State

A workaround has been applied in `src/orchestrator/mcp/tools.py` — the `_set_grade` handler now catches `InvalidTransitionError` and returns a friendly error dict with a hint instead of raising. This prevents the agent from crashing but doesn't prevent the wasted tool call.

## Root Cause

`src/orchestrator/mcp/server.py` registers all tools unconditionally in `_register_tools()`. There is no concept of phase-aware tool filtering. When a builder agent connects via MCP, it discovers `orchestrator_set_grade` alongside builder tools like `orchestrator_update_checklist` and `orchestrator_submit`.

The REST API has the same issue — `PUT /{run_id}/tasks/{task_id}/checklist/{req_id}/grade` is always available regardless of task status.

### Why builder agents call it

- The MCP tool list includes `orchestrator_set_grade` with description "Set a grade for a requirement (used by verifier)"
- LLM-based agents (claude, codex) see all available tools and may attempt to use them, especially if they interpret "grade" as related to marking requirements complete
- The builder prompt does NOT mention `set_grade`, but the MCP tool discovery overrides prompt instructions

## Proposed Fix

Filter MCP tools based on the current task phase. Two approaches:

### Option A: Phase-aware MCP tool registration (preferred)

Add a `phase` or `task_status` parameter to the MCP server or tool handler. When the builder connects, only expose builder tools:
- `orchestrator_get_requirements`
- `orchestrator_update_checklist`
- `orchestrator_submit`
- `orchestrator_request_clarification`
- `orchestrator_list_repos`
- `orchestrator_list_branches`

When the verifier connects, only expose verifier tools:
- `orchestrator_get_requirements`
- `orchestrator_set_grade`
- `orchestrator_submit` (for complete-verification)

This requires knowing which phase the connected agent is in. Since each agent session connects to the same MCP endpoint, this could be done by:
1. Adding a session/phase concept to the MCP server
2. Using separate MCP endpoints per phase (`/mcp/builder/sse`, `/mcp/verifier/sse`)
3. Filtering at the tool handler level based on task status lookup

### Option B: Dynamic tool filtering in handler

Keep all tools registered but check task status in each handler method, returning a descriptive error for tools that don't apply to the current phase. This is what the current workaround does for `set_grade` — extend it to all phase-sensitive tools.

## Affected Agents

- `cli_subprocess` with claude (confirmed)
- `cli_subprocess` with codex (likely, same MCP discovery behavior)
- Any MCP-connected agent

## Severity

**Medium** — The workaround prevents crashes. The agent wastes a tool call but gets a clear error message guiding it to the correct action. Full fix would eliminate the wasted call entirely.

## Related

- `AGENT-DEATH-HUMAN-GATE.md` — another agent lifecycle error in the executor
- `src/orchestrator/mcp/server.py` — MCP tool registration
- `src/orchestrator/mcp/tools.py` — tool handler (workaround applied here)
- `src/orchestrator/workflow/service.py:943-950` — the validation that correctly rejects out-of-phase grading
