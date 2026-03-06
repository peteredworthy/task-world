# Step 6: Routine Schema Update

Add optional agent assignment fields to the routine schema at routine, step, and task levels. Implement cascading resolution so task-level overrides step-level, step-level overrides routine-level, and routine-level overrides system defaults. Update prompt generation to use the resolved agent's system prompt.

## Intent Verification
**Original Intent**: Enable routines to specify which agent (prompt+profile) to use at each level, with cascading defaults (see `docs/agent-runners2/intent.md` -- "Agents" and routine schema sections).
**Functionality to Produce**:
- `RoutineConfig`, `StepConfig`, `TaskConfig` extended with `planner_agent`, `builder_agent`, `verifier_agent` optional fields
- `resolve_agent()` function implementing cascading resolution: task -> step -> routine -> system default
- Prompt generation prepends resolved agent's system prompt to task prompt
- Backward compatible: routines without agent fields use defaults

**Final Verification Criteria**:
- Unit tests for cascading resolution at all levels pass
- Prompt endpoint returns agent-prefixed prompts
- Existing routines without agent fields still work
- All existing tests pass

---

## Task 1: Extend Config Models with Agent Fields

**Description**: Add optional `planner_agent`, `builder_agent`, `verifier_agent` string fields to `RoutineConfig`, `StepConfig`, and `TaskConfig`.

**Implementation Plan (Do These Steps)**
- [ ] Add to `RoutineConfig` in `src/orchestrator/config/models.py`:
  ```python
  planner_agent: str | None = None
  builder_agent: str | None = None
  verifier_agent: str | None = None
  ```
- [ ] Add the same 3 optional fields to `StepConfig`
- [ ] Add the same 3 optional fields to `TaskConfig`
- [ ] Verify existing routine YAML files parse without error (new fields default to None)

**Dependencies**
- [ ] Step 5 must be complete (Agent concept exists with CRUD API)

**References**
- `docs/agent-runners2/architecture.md` -- routine YAML schema section
- `docs/agent-runners2/plan.md` -- M6 step 1
- Current config: `src/orchestrator/config/models.py`

**Constraints**
- All new fields must be optional with `None` default for backward compatibility
- Do not modify any existing field behavior

**Functionality (Expected Outcomes)**
- [ ] New fields are accepted in routine YAML at all three levels
- [ ] Existing routines without these fields parse unchanged
- [ ] `TaskConfig(id=..., title=..., requirements=[], builder_agent="Custom Builder")` works

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/ -x --timeout=60` -- all existing tests pass
- [ ] `uv run python -c "from orchestrator.config.models import TaskConfig; t = TaskConfig(id='t', title='t', requirements=[], builder_agent='X'); print(t.builder_agent)"` prints `X`

---

## Task 2: Implement Cascading Agent Resolution

**Description**: Create a pure function `resolve_agent()` that resolves which agent to use for a given phase by cascading through task -> step -> routine -> system default.

**Implementation Plan (Do These Steps)**
- [ ] Create resolution function (in `src/orchestrator/agents/resolution.py` or similar):
  ```python
  def resolve_agent_name(
      phase: str,  # "build" or "verify"
      task_config: TaskConfig,
      step_config: StepConfig,
      routine_config: RoutineConfig,
  ) -> str:
      """Resolve agent name via cascading: task -> step -> routine -> default."""
      field = "builder_agent" if phase == "build" else "verifier_agent"
      return (
          getattr(task_config, field)
          or getattr(step_config, field)
          or getattr(routine_config, field)
          or ("Builder" if phase == "build" else "Verifier")
      )
  ```
- [ ] Create a function to look up the agent by name from DB and return its system prompt
- [ ] Add routine validation: log a warning if referenced agent name doesn't exist (don't block)

**Dependencies**
- [ ] Task 1 must be complete (config models have agent fields)
- [ ] Step 5 Task 2 must be complete (agent service exists for DB lookup)

**References**
- `docs/agent-runners2/architecture.md` -- resolution order diagram
- `docs/agent-runners2/plan.md` -- M6 steps 2, 5

**Constraints**
- Resolution function must be pure (no DB access) -- DB lookup is a separate step
- Warn on missing agent, don't error -- fall back to system default
- Planner resolution is supported but has no engine integration

**Functionality (Expected Outcomes)**
- [ ] Task-level override takes precedence over step and routine
- [ ] Step-level override takes precedence over routine
- [ ] Missing overrides at all levels fall back to system default
- [ ] Warning logged for non-existent agent name

**Final Verification (Proof of Completion)**
- [ ] `uv run python -c "from orchestrator.agents.resolution import resolve_agent_name; print('OK')"` succeeds

---

## Task 3: Update Prompt Generation and Write Tests

**Description**: Update the prompt endpoint to prepend the resolved agent's system prompt to the task prompt, and write comprehensive tests.

**Implementation Plan (Do These Steps)**
- [ ] Update `GET /api/tasks/{id}/prompt` in `routers/tasks.py`:
  1. Determine current phase (build/verify)
  2. Resolve agent name via `resolve_agent_name()`
  3. Look up agent in DB to get `system_prompt`
  4. Concatenate: `agent_system_prompt + "\n\n---\n\n" + task_prompt`
- [ ] Write unit tests for cascading resolution:
  - Task override returns task-level agent
  - Step override returns step-level agent
  - Routine override returns routine-level agent
  - No overrides returns system default ("Builder" or "Verifier")
  - "verify" phase resolves `verifier_agent` field
- [ ] Write integration tests:
  - `GET /api/tasks/{id}/prompt` includes agent system prompt prefix
  - Existing routine without agent fields returns default Builder prompt
- [ ] Verify all existing tests still pass

**Dependencies**
- [ ] Task 2 must be complete (resolution function exists)

**References**
- `docs/agent-runners2/architecture.md` -- prompt generation section
- `docs/agent-runners2/plan.md` -- M6 steps 3-4, 6-7
- Clarification Q6: Simple concatenation (agent prompt + separator + task prompt)
- Current prompt endpoint: `src/orchestrator/api/routers/tasks.py`

**Constraints**
- Separator is `"\n\n---\n\n"` between agent prompt and task prompt
- If agent has no system_prompt (empty), just return the task prompt unchanged
- Backward compatible: prompts for runs without agent fields should be unchanged

**Functionality (Expected Outcomes)**
- [ ] Prompt includes agent system prompt when agent is resolved
- [ ] Prompt is unchanged for routines without agent fields
- [ ] All cascading resolution tests pass
- [ ] All existing tests still pass

**Final Verification (Proof of Completion)**
- [ ] `uv run pytest tests/ -x --timeout=120` -- all tests pass
- [ ] New resolution and prompt tests are in the test output
