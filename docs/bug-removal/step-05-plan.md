# Step 5 Plan: Phase-Aware MCP Tool Filtering (MCP-TOOLS-NO-PHASE-FILTERING)

## Purpose

Prevent builder agents from seeing and calling verifier-only MCP tools (specifically `orchestrator_set_grade`) by making the MCP server filter its tool registry based on the agent's phase at initialization time. Currently all tools are registered unconditionally; a builder agent discovers `orchestrator_set_grade`, calls it during the BUILDING phase, receives an `InvalidTransitionError`, and wastes a tool call (a soft-error workaround exists in `tools.py` but does not prevent the wasted call). After this fix, builder connections will see only builder tools and verifier connections will see only verifier tools, eliminating the spurious call entirely.

## Prerequisites

- None (independent of all other steps)

## Functional Contract

### Inputs

- `phase: Literal["building", "verifying"]` parameter passed to the MCP server at initialization or connection time (derived from task status in `executor.py` when spawning the agent)
- Existing MCP tool registry in `src/orchestrator/mcp/server.py`

### Outputs

- `src/orchestrator/mcp/server.py` accepts `phase` at init; `_register_tools()` conditionally registers tools:
  - Builder set: `orchestrator_get_requirements`, `orchestrator_update_checklist`, `orchestrator_submit`, `orchestrator_request_clarification`, `orchestrator_list_repos`, `orchestrator_list_branches`
  - Verifier set: `orchestrator_get_requirements`, `orchestrator_set_grade`, `orchestrator_submit`
- Builder agent MCP tool list does not contain `orchestrator_set_grade`
- Verifier agent MCP tool list does not contain `orchestrator_update_checklist`
- `executor.py` passes the correct `phase` value when spawning each agent session

### Errors

- If `phase` is not provided or is an unrecognised value, the server should raise a `ValueError` at initialization (fail-fast rather than silently exposing all tools)
- If a tool is called that belongs to the other phase (e.g., via a cached or stale tool list), the existing `tools.py` soft-error workaround remains as a safety net

## Tasks

1. In `src/orchestrator/mcp/server.py`: add `phase: Literal["building", "verifying"]` parameter to the server's `__init__` (or equivalent initialization point); update `_register_tools()` to conditionally register tools based on `self.phase`
2. In `src/orchestrator/agents/executor.py`: determine the current task phase (BUILDING → `"building"`, VERIFYING → `"verifying"`) and pass it when constructing the MCP server or agent session
3. Write unit tests: connect as builder (assert `orchestrator_set_grade` absent from tool list), connect as verifier (assert `orchestrator_update_checklist` absent from tool list)

## Verification

### Auto-Verify

- [ ] `pytest tests/ -k "mcp" or "phase_filter"` passes (new unit tests)
- [ ] Builder tool list does not contain `set_grade` (unit test assertion)
- [ ] Verifier tool list does not contain `update_checklist` (unit test assertion)
- [ ] `ValueError` is raised when `phase` is omitted or invalid (unit test)

### Manual Verify

- [ ] Run a builder agent session; inspect MCP tool discovery response — `orchestrator_set_grade` must not appear
- [ ] Run a verifier agent session; inspect MCP tool discovery response — `orchestrator_update_checklist` must not appear
- [ ] Existing builder flows (update_checklist, submit) still work after the filtering change

## Context & References

- Bug report: `docs/bugs/MCP-TOOLS-NO-PHASE-FILTERING.md` — Root Cause and Proposed Fix (Option A)
- Architecture: `docs/bug-removal/architecture.md` — "Modified Components: mcp/server.py"
- Key decision: phase derived at connection/initialization time (server-side), not per-call (avoids separate endpoints)
- Source files: `src/orchestrator/mcp/server.py`, `src/orchestrator/mcp/tools.py`, `src/orchestrator/agents/executor.py`
