# Step 6: Executor + Prompt Integration (M3)

Close the agent-facing loop: agents learn about the expansion API through their builder prompt, the executor correctly discovers and runs tasks added dynamically mid-step, and `expand_task` is registered as an MCP tool alongside `submit_for_verification` and `update_checklist`.

## Intent Verification
**Original Intent**: Add an "Expansion API" section to the builder prompt with budget status, modify the executor's step-task loop to refresh the task list after each completion, and register `expand_task` as an MCP tool (see `docs/orchestrated-expansion/plan.md` Step 6).
**Functionality to Produce**:
- Builder prompt gains "Expansion API (Optional)" section: REST examples for all three expansion types, budget status line, and a warning that expansion adds work
- Executor's step-task loop refreshes the pending task list after each task completes (picks up newly added peer tasks)
- `expand_task` registered as MCP tool with `ExpansionRequest` input schema; propagates 429/409/422 errors as typed MCP errors
- Unit tests for prompt additions and executor task discovery

**Final Verification Criteria**:
- `uv run pytest tests/unit/test_expansion_prompt.py -v` — all tests pass
- `uv run pytest tests/unit/ tests/integration/ -v` — no regressions
- `GET /mcp/tools` response includes `expand_task`

---

## Task 1: Add Expansion Section to Builder Prompt

**Description**: Extend `src/orchestrator/workflow/prompts.py` to inject an "Expansion API (Optional)" section into the builder prompt, including examples and a live budget status line.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/workflow/prompts.py`
- [ ] Add `expansion_limits: ExpansionLimits` parameter to `build_prompt()` (or derive from `routine_config.expansion_limits`); default to `ExpansionLimits()` if not set
- [ ] Compute budget string: `"Expansions used: {used}/{total}. Remaining: subtasks {s_used}/{s_max}, peer tasks {p_used}/{p_max}, inserted steps {i_used}/{i_max}."`
  where `used = run.total_expansions`, `total = expansion_limits.max_total_expansions`, etc.
- [ ] Add "Expansion API (Optional)" section to the prompt with:
  - Brief description of the three expansion types (`add_subtask`, `add_peer_task`, `add_next_step`) and their use cases
  - Example `POST .../expand` payloads for each type (matching architecture spec)
  - The computed budget status line
  - Warning: "IMPORTANT: Expansion adds work and does not transfer your existing task obligations."
- [ ] If `expansion_limits` is None (old routines): use `ExpansionLimits()` defaults; do not raise an error

**Dependencies**
- [ ] Step 5 complete — API endpoint and `ExpansionRequest` schema are stable

**References**
- `docs/orchestrated-expansion/step-06-plan.md` — Task 1
- `docs/orchestrated-expansion/architecture.md` — prompt template section
- `docs/orchestrated-expansion/clarifications.md` — Q5: MCP tool is required (prompt and MCP are companion changes)

**Constraints**
- Budget string must be computed at prompt-generation time (reflects current run state)
- The expansion section must be clearly demarcated (heading, not inline) so agents can find it
- Do not alter existing prompt sections; only append the new section

**Functionality (Expected Outcomes)**
- [ ] Prompt includes "Expansion API" heading when called with `expansion_limits` configured
- [ ] Budget string reflects correct used/remaining values
- [ ] Initial budget shows `0/{max}` for all counters when no expansions have occurred
- [ ] Old routines without `expansion_limits` get defaults; no error raised

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/workflow/prompts.py` — no type errors

---

## Task 2: Refresh Task List in Executor After Each Completion

**Description**: Modify `src/orchestrator/runners/executor.py` so the step-task execution loop re-queries the task list after each task completes, picking up dynamically added peer tasks and non-blocking subtasks.

**Implementation Plan (Do These Steps)**
- [ ] Open `src/orchestrator/runners/executor.py`
- [ ] Locate the step-task execution loop (around L743–L747 per plan reference; find the `pending` task list iteration)
- [ ] After each task reaches a terminal state, call `service.get_step_tasks(run_id, step_id)` (or equivalent) to refresh the task list
- [ ] Rebuild `pending` as `[t for t in refreshed_tasks if t.status == TaskStatus.PENDING]`
- [ ] Ensure already-completed tasks are NOT re-executed (filter by `PENDING` status only)
- [ ] Wrap the DB refresh in a try/except: on DB error, log a warning and use the last-known task list (do not crash the executor)

**Dependencies**
- [ ] Step 4 complete — engine can add tasks dynamically to steps; executor needs to discover them

**References**
- `docs/orchestrated-expansion/step-06-plan.md` — Task 2
- Existing executor fan-out detection: `src/orchestrator/runners/executor.py` L743-L747 (blocking subtask path already handled)

**Constraints**
- Only filter on `PENDING` status — do not re-run tasks in `BUILDING`, `VERIFYING`, or terminal states
- The refresh must happen after a task completes, not before; do not change the loop structure otherwise
- Blocking subtask (`FAN_OUT_RUNNING`) path does NOT need changes — it is already handled

**Functionality (Expected Outcomes)**
- [ ] After a task completes, newly added peer tasks (PENDING) are discovered and executed in the same step iteration
- [ ] Tasks already in terminal status are not re-executed after refresh
- [ ] DB error during refresh: logged as warning, loop continues with previous task list

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/runners/executor.py` — no type errors

---

## Task 3: Register expand_task as MCP Tool

**Description**: Register `expand_task` as an MCP tool so agents using the MCP interface can call it alongside `submit_for_verification` and `update_checklist`.

**Implementation Plan (Do These Steps)**
- [ ] Find the MCP tool registration location (search for `submit_for_verification` and `update_checklist` in `src/orchestrator/api/` to locate the file, likely `mcp.py`)
- [ ] Register `expand_task` tool with:
  - Input schema matching `ExpansionRequest` fields
  - Implementation: forward to `POST .../expand` endpoint (or call `service.expand_task()` directly via the same pattern as other MCP tools)
- [ ] Map errors to MCP error responses:
  - HTTP 429 → MCP error with code `BUDGET_EXHAUSTED` and message from response body
  - HTTP 409 → MCP error with code `PHASE_ERROR`
  - HTTP 422 → MCP error with code `VALIDATION_ERROR`
- [ ] Return `ExpansionResponse` as MCP tool result on success

**Dependencies**
- [ ] Task 1 complete (prompt updated — MCP tool is the companion registration)
- [ ] Step 5 complete — REST endpoint exists; MCP tool can delegate to it

**References**
- `docs/orchestrated-expansion/step-06-plan.md` — Task 3
- `docs/orchestrated-expansion/clarifications.md` — Q5: MCP tool registration is required
- Existing MCP tool registrations: search for `submit_for_verification` and `update_checklist` to find the registration pattern

**Constraints**
- Follow the exact registration pattern used by existing MCP tools
- The MCP tool must accept the same fields as `ExpansionRequest` (not a subset)
- Error codes (`BUDGET_EXHAUSTED`, `PHASE_ERROR`, `VALIDATION_ERROR`) must be string constants, not numbers

**Functionality (Expected Outcomes)**
- [ ] `GET /mcp/tools` response includes `expand_task` with correct input schema
- [ ] MCP `expand_task` call with valid `add_subtask` request returns `ExpansionResponse`
- [ ] MCP `expand_task` call that hits budget limit returns MCP error with `BUDGET_EXHAUSTED` code

**Final Verification (Proof of Completion)**
- [ ] `uv run pyright src/orchestrator/api/mcp.py` (or equivalent) — no type errors

---

## Task 4: Write Unit Tests for Prompt Expansion Section

**Description**: Create `tests/unit/test_expansion_prompt.py` to verify the builder prompt correctly includes the expansion API section and budget string.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_expansion_prompt.py`
- [ ] Test: builder prompt includes "Expansion API" section when `expansion_limits` provided
- [ ] Test: budget string reflects correct used/remaining values when some expansions have occurred
- [ ] Test: budget string shows `0/{max}` for all counters when no expansions have occurred
- [ ] Test: budget section not present OR gracefully uses defaults when limits not configured (old routine without `expansion_limits`)
- [ ] Run tests to confirm all pass

**Dependencies**
- [ ] Task 1 complete (prompts.py updated)

**References**
- `docs/orchestrated-expansion/step-06-plan.md` — Task 4

**Constraints**
- Tests must be self-contained (no DB or server required)
- Call `build_prompt()` directly with mock `run` and `task_state` objects

**Functionality (Expected Outcomes)**
- [ ] All prompt tests pass
- [ ] Budget string tested with at least two states: zero usage and partial usage

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_expansion_prompt.py -v` — all tests pass

---

## Task 5: Write Unit Tests for Executor Task Discovery

**Description**: Create or extend executor tests to verify that the refreshed task list picks up dynamically added tasks and does not re-run completed ones.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_expansion_executor.py` (or add to existing executor test file)
- [ ] Test: after adding a peer task via mock service, executor discovers it on the next loop iteration and executes it
- [ ] Test: tasks already in terminal status (`COMPLETED`, `FAILED`) are not re-executed after refresh
- [ ] Run tests to confirm all pass

**Dependencies**
- [ ] Task 2 complete (executor task list refresh implemented)

**References**
- `docs/orchestrated-expansion/step-06-plan.md` — Task 5
- Existing executor tests for mock service pattern

**Constraints**
- Use mocked `service.get_step_tasks()` to simulate dynamic task addition — do not require a running DB
- Tests should focus on the discovery loop, not full end-to-end task execution

**Functionality (Expected Outcomes)**
- [ ] Newly added peer task discovered and queued for execution
- [ ] Completed task not re-executed on refresh

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/unit/test_expansion_executor.py -v` (or the relevant test file) — all tests pass
- [ ] `uv run pytest tests/unit/ tests/integration/ -v` — no regressions
