# Step Plan: Executor + Prompt Integration (M3)

## Purpose

Close the agent-facing loop: agents learn about the expansion API through their builder prompt, and the executor correctly discovers and runs tasks that were added dynamically mid-step. This step also registers `expand_task` as an MCP tool so agents using the MCP interface can call it alongside `submit_for_verification` and `update_checklist`.

## Prerequisites

- **Step 5 complete** — `POST .../expand` endpoint live; API contract stable.
- Steps 3–4 complete — engine handles all expansion types.

## Functional Contract

### Inputs

`workflow/prompts.py` — `build_prompt(task_state, run, routine_config, ...)`:
- Same existing inputs
- New: `expansion_limits: ExpansionLimits` (from `routine_config.expansion_limits`)
- New: current budget usage from `run.total_expansions`, `task_state.expansions_requested`

`runners/executor.py` — step execution loop:
- Same inputs; behavior change: task list is refreshed from DB after each task completes

MCP server registration:
- `expand_task` tool registered with JSON schema matching `ExpansionRequest`

### Outputs

Builder prompt additions:
- New "Expansion API (Optional)" section describing all three expansion types, their use cases, and the POST endpoint with example payloads
- Budget status line injected at prompt-generation time: `"Expansions used: {used}/{total}. Remaining: subtasks {s_used}/{s_max}, peer tasks {p_used}/{p_max}, inserted steps {i_used}/{i_max}."`
- Warning that expansion adds work and does not transfer existing task obligations

Executor mid-step task discovery:
- After each task in a step completes, the executor re-queries `service.get_step_tasks(run_id, step_id)` and refreshes `pending` task list
- Newly added peer tasks or non-blocking subtasks are picked up and executed in the same step

Blocking subtask (fan-out) path:
- No executor changes needed — `FAN_OUT_RUNNING` detection at L743-L747 already handles this via `_execute_fan_out`

MCP tool:
- `expand_task` registered in the MCP tools list with input schema matching `ExpansionRequest`
- Tool returns `ExpansionResponse` on success; propagates 429/409 errors as MCP error responses

### Error Cases

Prompt generation:
- If `routine_config.expansion_limits` is None (old routines without limits): use `ExpansionLimits()` defaults; no error

Executor task refresh:
- If DB query returns error during refresh: log warning, use last-known task list (do not crash executor)

MCP tool:
- HTTP 429 from endpoint → MCP error with code `BUDGET_EXHAUSTED` and message from response body
- HTTP 409 from endpoint → MCP error with code `PHASE_ERROR`
- HTTP 422 → MCP error with code `VALIDATION_ERROR`

## Tasks

1. **`src/orchestrator/workflow/prompts.py`**: Add expansion callback section to the builder prompt:
   - Include REST examples for all three expansion types (matching architecture spec exactly)
   - Inject budget string computed from `run.total_expansions`, `expansion_limits.max_total_expansions`, `task_state.expansions_requested`, etc.
   - Add "IMPORTANT: Expansion adds work..." warning line

2. **`src/orchestrator/runners/executor.py`**: Modify the step-task loop to refresh the task list after each task completes:
   ```python
   # After task completion
   tasks = await service.get_step_tasks(run_id, step_id)
   pending = [t for t in tasks if t.status == TaskStatus.PENDING]
   ```
   - Ensure this does not re-execute already-completed tasks

3. **MCP server** (identify registration location — likely `src/orchestrator/api/mcp.py` or similar):
   - Register `expand_task` as an MCP tool
   - Input schema: `ExpansionRequest` fields
   - Implementation: forward to `POST .../expand` endpoint; handle errors

4. **`tests/unit/test_expansion_prompt.py`**: Unit tests:
   - Builder prompt includes "Expansion API" section when `expansion_limits` provided
   - Budget string reflects correct used/remaining values
   - Budget string shows 0/5 subtasks when no expansions have occurred
   - Budget section not present or gracefully absent when limits not configured (use defaults)

5. **`tests/unit/test_expansion_executor.py`** (or additions to existing executor tests):
   - After adding peer task via mock, executor discovers it on next loop iteration
   - Tasks already in terminal status are not re-executed after refresh

## Verification Approach

### Auto-Verify

- `uv run pytest tests/unit/test_expansion_prompt.py -v` — all tests pass
- `uv run pytest tests/unit/ tests/integration/ -v` — no regressions

### Manual Verification (Smoke Test)

- Start a run with a debug routine; inspect the builder prompt returned by `GET /tasks/{id}/prompt`
- Confirm "Expansion API (Optional)" section is present
- Confirm budget string shows correct initial values (e.g., `"Expansions used: 0/10"`)
- Verify MCP tool `expand_task` appears in `GET /mcp/tools` response

## Context & References

- Plan: `docs/orchestrated-expansion/plan.md` — Step 6 specification
- Architecture: `docs/orchestrated-expansion/architecture.md` — prompt template, executor loop change, MCP registration
- Clarification Q5: MCP tool registration is required
- Existing MCP tools: search for `submit_for_verification` and `update_checklist` registrations to find the registration location
- Executor fan-out detection: `src/orchestrator/runners/executor.py` L743-L747
