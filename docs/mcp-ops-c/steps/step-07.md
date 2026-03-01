# Step 7: User-Managed MCP All-Tools + MCP Info in Prompt Response

Update the User-Managed MCP server to register all tools (removing phase-based filtering at registration), and extend the prompt response / `CallbackInstructions` to include MCP server information. External agents using the prompt endpoint will see available MCP servers they can optionally connect to. This is **Priority 3**.

## Intent Verification
**Original Intent**: User-Managed MCP server registers all tools; prompt response includes external MCP server information (see `docs/mcp-ops-c/intent.md` — "Definition of Complete" bullets 9-10).
**Functionality to Produce**:
- MCP server registers both builder and verifier tools at startup (remove phase filter)
- Runtime validation still rejects phase-inappropriate tool calls
- `CallbackInstructions` schema extended with `mcp_servers` field
- Prompt response endpoint populates `mcp_servers` from execution context
- Backward compatible when `mcp_servers` is `None`

**Final Verification Criteria**:
- Unit tests confirm all tools are registered
- Unit tests confirm runtime validation still works
- Schema tests confirm `CallbackInstructions` has `mcp_servers` field
- All existing MCP server and prompt endpoint tests pass

---

## Task 1: Register All Tools in MCP Server (Remove Phase Filter)
**Description**:
Update `_register_tools()` in `src/orchestrator/mcp/server.py` to register all orchestrator tools unconditionally, removing the phase-based filtering at registration time. Runtime validation continues to prevent phase-inappropriate calls.

**Implementation Plan (Do These Steps)**
The current implementation (lines 42-68 and 70-212) uses `self._allowed_tools` to conditionally register tools:
```python
self._allowed_tools = BUILDER_TOOLS if self.phase == "building" else VERIFIER_TOOLS
```

- [ ] Change `_register_tools()` to register ALL tools regardless of phase:
```python
# Register all tools — phase validation happens at runtime
ALL_TOOLS = BUILDER_TOOLS | VERIFIER_TOOLS
self._allowed_tools = ALL_TOOLS
```
- [ ] Alternatively, remove the conditional check in `_register_tools()` and always register every tool function
- [ ] Ensure runtime validation still checks the current phase before executing a tool call (e.g., builder calling `grade` still gets a clear error)
- [ ] Update `BUILDER_TOOLS` and `VERIFIER_TOOLS` constants to include all tools, or create an `ALL_TOOLS` union

**Dependencies**
- [ ] Step 2 complete: `ExecutionContext` carries `mcp_servers`

**References**
- Current MCP server: `src/orchestrator/mcp/server.py:19-32` (tool sets), `42-68` (init), `70-212` (_register_tools)
- Key decision: Register all tools, rely on runtime validation (simpler than per-connection scoping)
- Architecture: `docs/mcp-ops-c/architecture.md` — User-Managed row

**Constraints**
- Phase-inappropriate tool calls must still be rejected with clear error messages at runtime
- Do not remove the `BUILDER_TOOLS` and `VERIFIER_TOOLS` constants (they're useful for runtime validation)

**Functionality (Expected Outcomes)**
- [ ] MCP server exposes both builder tools (`submit`, `update_checklist`, etc.) and verifier tools (`set_grade`)
- [ ] Builder phase calling `grade` → runtime error with clear message
- [ ] Verifier phase calling `submit` → succeeds (verifiers have submit)
- [ ] All tools visible in MCP tool listing regardless of phase

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/ -k "mcp" -v` — all MCP tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes

---

## Task 2: Extend CallbackInstructions with mcp_servers Field
**Description**:
Add an optional `mcp_servers` field to `CallbackInstructions` in `src/orchestrator/api/schemas/tasks.py` to expose step-level MCP server information to external agents via the prompt endpoint.

**Implementation Plan (Do These Steps)**
- [ ] Add the import for `MCPServerConfig` at the top of `src/orchestrator/api/schemas/tasks.py`:
```python
from orchestrator.config.models import MCPServerConfig
```
- [ ] Add `mcp_servers` field to `CallbackInstructions` (lines 130-137):
```python
class CallbackInstructions(ApiModel):
    """Instructions for external agents to call back to the orchestrator."""
    run_id: str
    task_id: str
    api_base_url: str
    rest_instructions: str
    mcp_instructions: str
    mcp_servers: list[MCPServerConfig] | None = None  # External MCP servers for this step
```

**References**
- Current schema: `src/orchestrator/api/schemas/tasks.py:130-144`

**Constraints**
- Field must be optional and default to `None` for backward compatibility
- Use the `MCPServerConfig` model directly (no separate schema)

**Functionality (Expected Outcomes)**
- [ ] `CallbackInstructions` with no `mcp_servers` → field is `None`
- [ ] `CallbackInstructions` with `mcp_servers=[...]` → field contains MCP configs
- [ ] JSON serialization includes `mcp_servers` when set

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run python -c "from orchestrator.api.schemas.tasks import CallbackInstructions; print(CallbackInstructions.model_fields.keys())"` — includes `mcp_servers`
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes

---

## Task 3: Populate mcp_servers in Prompt Response Endpoint
**Description**:
Update the prompt response endpoint in `src/orchestrator/api/routers/tasks.py` to include `mcp_servers` from the execution context when building `CallbackInstructions`.

**Implementation Plan (Do These Steps)**
The current `_build_callback_instructions()` (lines 292-327) builds REST and MCP instructions. The prompt endpoint `get_task_prompt()` (lines 408-506) loads the step config.

- [ ] In `get_task_prompt()`, after loading the step config, extract `mcp_servers`:
```python
step_config = routine_config.steps[step_index]
mcp_servers = step_config.mcp_servers
```
- [ ] Pass `mcp_servers` to `_build_callback_instructions()`:
```python
callback = _build_callback_instructions(request, run_id, task_id, mcp_servers=mcp_servers)
```
- [ ] Update `_build_callback_instructions()` to accept and include `mcp_servers`:
```python
def _build_callback_instructions(
    request: Request,
    run_id: str,
    task_id: str,
    mcp_servers: list[MCPServerConfig] | None = None,
) -> CallbackInstructions:
    # ... existing REST and MCP instruction building ...
    return CallbackInstructions(
        run_id=run_id,
        task_id=task_id,
        api_base_url=str(base_url),
        rest_instructions=rest_instructions,
        mcp_instructions=mcp_instructions,
        mcp_servers=mcp_servers,
    )
```

**Dependencies**
- [ ] Task 2 complete: `CallbackInstructions` has `mcp_servers` field

**References**
- Current endpoint: `src/orchestrator/api/routers/tasks.py:408-506`
- Current builder: `src/orchestrator/api/routers/tasks.py:292-327`

**Constraints**
- Only pass `mcp_servers` from the current step's config, not from any other source
- Do not modify the prompt text itself — MCP info goes in `CallbackInstructions`

**Functionality (Expected Outcomes)**
- [ ] Step with `mcp_servers` → prompt response includes MCP server list in callback instructions
- [ ] Step without `mcp_servers` → callback instructions have `mcp_servers=None`
- [ ] Existing prompt responses work unchanged (backward compatible)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/ -k "prompt" -v` — all prompt-related tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes

---

## Task 4: Write Unit Tests for All-Tools Registration and MCP Info in Prompt
**Description**:
Create unit tests for the MCP server all-tools registration and the CallbackInstructions mcp_servers field.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_mcp_server_all_tools.py`:
```python
"""Tests for User-Managed MCP all-tools registration and prompt MCP info."""
from orchestrator.api.schemas.tasks import CallbackInstructions
from orchestrator.config.models import MCPServerConfig


class TestCallbackInstructionsMCPServers:
    def test_mcp_servers_field_optional(self):
        cb = CallbackInstructions(
            run_id="r1", task_id="t1",
            api_base_url="http://localhost:8000",
            rest_instructions="REST...", mcp_instructions="MCP...",
        )
        assert cb.mcp_servers is None

    def test_mcp_servers_field_populated(self):
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        cb = CallbackInstructions(
            run_id="r1", task_id="t1",
            api_base_url="http://localhost:8000",
            rest_instructions="REST...", mcp_instructions="MCP...",
            mcp_servers=[mcp],
        )
        assert len(cb.mcp_servers) == 1
        assert cb.mcp_servers[0].name == "ctx7"

    def test_json_serialization_includes_mcp_servers(self):
        mcp = MCPServerConfig(name="ctx7", url="https://ctx7.example.com")
        cb = CallbackInstructions(
            run_id="r1", task_id="t1",
            api_base_url="http://localhost:8000",
            rest_instructions="REST...", mcp_instructions="MCP...",
            mcp_servers=[mcp],
        )
        data = cb.model_dump()
        assert "mcp_servers" in data
        assert data["mcp_servers"][0]["name"] == "ctx7"
```

**Functionality (Expected Outcomes)**
- [ ] Optional field test passes
- [ ] Populated field test passes
- [ ] JSON serialization test passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/unit/test_mcp_server_all_tools.py -v` — all tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes
