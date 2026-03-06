# Step 6: Routine Schema Update

Add optional agent assignment fields to routine, step, and task config models. Implement cascading resolution and update prompt generation to use the resolved agent's system prompt.

## Intent Verification
**Original Intent**: M6 from `docs/agent-runners2/plan.md` -- add agent fields to routine schema with cascading resolution (task -> step -> routine -> system default).
**Functionality to Produce**:
- Optional `planner_agent`, `builder_agent`, `verifier_agent` fields at routine/step/task config levels
- `resolve_agent()` pure function implementing cascading resolution
- Prompt generation updated to prepend resolved agent's system prompt
- Routine validation with warnings for missing agent names
**Final Verification Criteria**:
- Cascading resolution works at all levels
- Prompt endpoint returns agent-prefixed prompts
- Existing routines without agent fields still work
- All tests pass

---

## Task 1: Add Agent Fields to Config Models

**Description**: Add optional `planner_agent`, `builder_agent`, `verifier_agent` string fields to `RoutineConfig`, `StepConfig`, and `TaskConfig` in `config/models.py`.

**Implementation Plan (Do These Steps)**
- [ ] Add to `RoutineConfig`: `planner_agent: str | None = None`, `builder_agent: str | None = None`, `verifier_agent: str | None = None`
- [ ] Add same fields to `StepConfig`
- [ ] Add same fields to `TaskConfig`
- [ ] Verify existing routine YAML files still parse without errors (new fields are optional)
- [ ] Add routine validation: log warning if referenced agent name doesn't exist in DB, but don't block

**Dependencies**
- [ ] Step 05 must be complete (Agent concept exists with CRUD API)

**References**
- `docs/agent-runners2/step-06-plan.md` -- Tasks 1, 5
- `docs/agent-runners2/architecture.md` -- routine YAML schema changes

**Constraints**
- All new fields must be optional with `None` default
- Existing routines must continue to work unchanged

**Functionality (Expected Outcomes)**
- [ ] Config models accept agent fields
- [ ] Existing routines parse without errors

**Final Verification (Proof of Completion)**
- [ ] Existing routine YAML files load successfully
- [ ] Config models have the 3 new optional fields at each level

---

## Task 2: Implement Cascading Resolution

**Description**: Create a `resolve_agent()` pure function that resolves the agent for a given phase by cascading through task -> step -> routine -> system default.

**Implementation Plan (Do These Steps)**
- [ ] Create `resolve_agent(phase, task_config, step_config, routine_config)` function
- [ ] For `phase="build"`: check `builder_agent` field at task, then step, then routine level
- [ ] For `phase="verify"`: check `verifier_agent` field at same cascade
- [ ] Fallback: return system default agent name ("Builder" for build, "Verifier" for verify)
- [ ] Handle missing agent name: if resolved name doesn't match any agent in DB, log warning and use system default
- [ ] Write unit tests for all cascade levels and fallback

**Dependencies**
- [ ] Task 1 must be complete (config models have agent fields)

**References**
- `docs/agent-runners2/step-06-plan.md` -- Tasks 2, 6
- `docs/agent-runners2/architecture.md` -- resolution order

**Constraints**
- Must be a pure function (no DB access) -- just resolves the name string
- Agent DB lookup happens in the caller, not in this function

**Functionality (Expected Outcomes)**
- [ ] Task-level override takes precedence over step and routine
- [ ] Step-level override takes precedence over routine
- [ ] Routine-level override takes precedence over system default
- [ ] System default returned when no overrides set

**Final Verification (Proof of Completion)**
- [ ] Unit tests for all 4 cascade levels pass
- [ ] Unit tests for both "build" and "verify" phases pass

---

## Task 3: Update Prompt Generation and Write Integration Tests

**Description**: Update the task prompt endpoint to prepend the resolved agent's system prompt, and write integration tests.

**Implementation Plan (Do These Steps)**
- [ ] Update `GET /api/tasks/{id}/prompt` to resolve the agent for the current phase
- [ ] Look up the resolved agent in DB to get its `system_prompt`
- [ ] Compose final prompt: `agent_system_prompt + "\n\n---\n\n" + task_prompt`
- [ ] If agent not found in DB, fall back to existing behavior (no prefix)
- [ ] Write integration tests: prompt endpoint returns agent-prefixed prompt
- [ ] Write integration test: existing routine without agent fields uses default Builder prompt
- [ ] Verify all existing tests continue to pass

**Dependencies**
- [ ] Task 2 must be complete (resolution function exists)

**References**
- `docs/agent-runners2/step-06-plan.md` -- Tasks 3, 4, 7
- Clarification Q6: Simple concatenation (agent prompt + separator + task prompt)
- Current prompt endpoint: `src/orchestrator/api/routers/tasks.py`

**Constraints**
- Don't break existing prompt behavior for routines without agent fields
- Separator is `"\n\n---\n\n"`

**Functionality (Expected Outcomes)**
- [ ] Prompt endpoint includes agent system prompt when agent is configured
- [ ] Backward compatible: no agent fields -> existing behavior
- [ ] All tests pass

**Final Verification (Proof of Completion)**
- [ ] Integration test: prompt with agent override includes agent system prompt
- [ ] Integration test: prompt without agent override works as before
- [ ] `uv run pytest` passes with no new failures
