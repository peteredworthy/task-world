# Step 2: ExecutionContext Extension + Executor Wiring

Extend `ExecutionContext` to carry step-level tool and MCP information, and update the executor to populate these fields from `StepConfig`. This connects the schema layer (Step 1) to the agent layer (Steps 3–7), enabling all agents to receive step-specific configuration through the standard context object.

## Intent Verification
**Original Intent**: `ExecutionContext` carries step-level tool and MCP configuration to every agent (see `docs/mcp-ops-c/intent.md` — "Desired End State" bullet 3).
**Functionality to Produce**:
- `ExecutionContext` extended with `step_id`, `available_tools`, `mcp_servers` fields
- Executor populates these fields from `StepConfig` when creating context
- Existing routines without new fields produce `None` context values (backward compatible)

**Final Verification Criteria**:
- Unit tests confirm context is populated from step config
- Unit tests confirm context fields are `None` when step config has no tool/MCP data
- All existing tests pass

---

## Task 1: Extend ExecutionContext with Step-Level Fields
**Description**:
Add three new optional fields to `ExecutionContext` in `src/orchestrator/agents/types.py`: `step_id`, `available_tools`, and `mcp_servers`. These carry step-level configuration from the executor to all agent types.

**Implementation Plan (Do These Steps)**
- [ ] Add the import for `MCPServerConfig` at the top of `src/orchestrator/agents/types.py`:
```python
from orchestrator.config.models import MCPServerConfig
```
- [ ] Add three fields to the `ExecutionContext` class (after the existing `end_commit` field):
```python
class ExecutionContext(BaseModel):
    # ... existing fields (run_id, task_id, working_dir, prompt, requirements, api_base_url, auth_token, end_commit)
    step_id: str | None = None
    available_tools: list[str] | None = None
    mcp_servers: list[MCPServerConfig] | None = None
```

**Dependencies**
- [ ] Step 1 complete: `MCPServerConfig` model exists in `src/orchestrator/config/models.py`

**References**
- Architecture: `docs/mcp-ops-c/architecture.md` — ExecutionContext extension
- Current ExecutionContext: `src/orchestrator/agents/types.py:52`

**Constraints**
- Do not modify any existing fields on `ExecutionContext`
- All new fields must default to `None` for backward compatibility

**Functionality (Expected Outcomes)**
- [ ] `ExecutionContext(...)` with no new fields → `step_id`, `available_tools`, `mcp_servers` all `None`
- [ ] `ExecutionContext(..., step_id="step-1", available_tools=["terminal"])` → fields accessible
- [ ] `ExecutionContext(..., mcp_servers=[MCPServerConfig(name="x", url="https://x")])` → field accessible

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run python -c "from orchestrator.agents.types import ExecutionContext; c = ExecutionContext(run_id='r', task_id='t', working_dir='/tmp', prompt='p', requirements=[]); print(c.step_id, c.available_tools, c.mcp_servers)"` — prints `None None None`
- [ ] Run `uv run pytest tests/ -x --timeout=30` — all existing tests still pass

---

## Task 2: Update Executor to Populate Step-Level Context
**Description**:
Update the executor's `ExecutionContext` creation (~line 650 in `src/orchestrator/agents/executor.py`) to read step config and populate the new fields. When a step has `available_tools` or `mcp_servers`, they flow through to the context. When absent, fields remain `None`.

**Implementation Plan (Do These Steps)**
The executor creates `ExecutionContext` inside `_execute_builder_task()`. The current step config is accessible via `run.routine.steps[run.current_step_index]`.

- [ ] Locate the `ExecutionContext(...)` construction in `src/orchestrator/agents/executor.py` (~line 650)
- [ ] Read the current step config before context creation:
```python
step_config = run.routine.steps[run.current_step_index]
```
- [ ] Add the three new fields to the `ExecutionContext(...)` call:
```python
context = ExecutionContext(
    run_id=run.id,
    task_id=task_state.id,
    working_dir=working_dir,
    prompt=f"{prompt.system}\n\n{prompt.user}",
    requirements=requirements,
    api_base_url=self._api_base_url,
    step_id=step_config.id,
    available_tools=step_config.available_tools,
    mcp_servers=step_config.mcp_servers,
)
```
- [ ] Check if there is a separate verifier context creation path and apply the same changes there

**Dependencies**
- [ ] Task 1 complete: `ExecutionContext` has the new fields

**References**
- Current executor context creation: `src/orchestrator/agents/executor.py:650`
- Data flow: YAML → StepConfig → Executor → ExecutionContext → Agent

**Constraints**
- Only modify the `ExecutionContext(...)` construction — do not change executor logic
- The `step_config` variable should be read from the run's routine steps at the current index

**Functionality (Expected Outcomes)**
- [ ] When step config has `available_tools=["terminal"]`, context has `available_tools=["terminal"]`
- [ ] When step config has no tool/MCP fields, context has `available_tools=None`, `mcp_servers=None`
- [ ] `step_id` matches the current step's `id` field

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/ -x --timeout=30` — all existing tests still pass
- [ ] Run `uv run pytest tests/unit/ -k "executor" -v` — executor-specific tests pass

---

## Task 3: Write Unit Tests for ExecutionContext Extension and Executor Wiring
**Description**:
Write tests confirming that `ExecutionContext` accepts the new fields and that the executor populates them correctly from step config.

**Implementation Plan (Do These Steps)**
- [ ] Create or extend a test file for the context extension. Add tests to `tests/unit/test_mcp_server_config.py` (extending from Step 1) or create `tests/unit/test_execution_context_extension.py`:
```python
"""Tests for ExecutionContext step-level fields."""
from orchestrator.agents.types import ExecutionContext
from orchestrator.config.models import MCPServerConfig


class TestExecutionContextStepFields:
    def test_defaults_to_none(self):
        ctx = ExecutionContext(
            run_id="r1", task_id="t1", working_dir="/tmp",
            prompt="do stuff", requirements=["R1"],
        )
        assert ctx.step_id is None
        assert ctx.available_tools is None
        assert ctx.mcp_servers is None

    def test_step_id_populated(self):
        ctx = ExecutionContext(
            run_id="r1", task_id="t1", working_dir="/tmp",
            prompt="do stuff", requirements=["R1"],
            step_id="step-1",
        )
        assert ctx.step_id == "step-1"

    def test_available_tools_populated(self):
        ctx = ExecutionContext(
            run_id="r1", task_id="t1", working_dir="/tmp",
            prompt="do stuff", requirements=["R1"],
            available_tools=["terminal", "file_editor"],
        )
        assert ctx.available_tools == ["terminal", "file_editor"]

    def test_mcp_servers_populated(self):
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        ctx = ExecutionContext(
            run_id="r1", task_id="t1", working_dir="/tmp",
            prompt="do stuff", requirements=["R1"],
            mcp_servers=[mcp],
        )
        assert len(ctx.mcp_servers) == 1
        assert ctx.mcp_servers[0].name == "ctx7"
```

**Functionality (Expected Outcomes)**
- [ ] All new context tests pass
- [ ] Tests confirm backward compatibility (no new fields → None)
- [ ] Tests confirm new fields are accessible when set

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/unit/test_execution_context_extension.py -v` — all tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes
