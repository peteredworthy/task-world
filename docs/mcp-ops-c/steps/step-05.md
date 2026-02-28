# Step 5: Codex Server Phase Filtering + Context Filtering + MCP Wiring

Fix Codex Server's phase filtering (builders currently see the `grade` tool) and add step-level tool filtering and external MCP wiring. Codex Server uses `dynamicTools` for both orchestrator callback tools and external MCP configuration, providing per-thread control. This is **Priority 2**.

## Intent Verification
**Original Intent**: Codex Server agent uses `is_verifier` for phase filtering and supports step-level tool specs via dynamicTools (see `docs/mcp-ops-c/intent.md` — "Definition of Complete" bullet 6).
**Functionality to Produce**:
- `build_dynamic_tool_specs()` accepts `is_verifier` parameter — builders don't see `grade`
- `build_dynamic_tool_specs()` accepts `context` for additive step-level tool filtering
- MCP server config included in `dynamicTools` during thread creation
- Backward compatible when `available_tools` and `mcp_servers` are `None`

**Final Verification Criteria**:
- Unit tests confirm builder threads don't get `grade` tool
- Unit tests confirm step-level tools are additive
- Unit tests confirm MCP config appears in dynamicTools
- All existing Codex Server tests pass

---

## Task 1: Add Phase Filtering to build_dynamic_tool_specs()
**Description**:
Add an `is_verifier` parameter to `build_dynamic_tool_specs()` in `src/orchestrator/agents/codex_server_common.py`. When `is_verifier=False`, exclude the `grade` tool from the returned specs. Currently all 5 tools are returned unconditionally.

**Implementation Plan (Do These Steps)**
The current function (lines 173-258 in `codex_server_common.py`) returns a hardcoded list of 5 tool specs.

- [ ] Update the function signature:
```python
def build_dynamic_tool_specs(
    is_verifier: bool = False,
    context: ExecutionContext | None = None,
) -> list[dict[str, Any]]:
```
- [ ] Add the import for `ExecutionContext` at the top of the file
- [ ] Conditionally exclude `grade` when `is_verifier=False`:
```python
specs = [
    # update_checklist spec...
    # submit spec...
    # request_clarification spec...
    # complete_recovery spec...
]
if is_verifier:
    specs.append(grade_spec)  # Only include grade for verifiers
return specs
```
- [ ] Update all callers of `build_dynamic_tool_specs()` in `codex_server.py` to pass the `is_verifier` parameter based on the current phase

**Dependencies**
- [ ] Step 2 complete: `ExecutionContext` carries `available_tools` and `mcp_servers`

**References**
- Current function: `src/orchestrator/agents/codex_server_common.py:173-258`
- Current caller: `src/orchestrator/agents/codex_server.py:435`
- Architecture: `docs/mcp-ops-c/architecture.md` — Codex Server row

**Constraints**
- Maintain backward compatibility: default `is_verifier=False` means existing callers continue to work
- Only the `grade` tool should be filtered by phase

**Functionality (Expected Outcomes)**
- [ ] `is_verifier=False` → `grade`/`set_grade` NOT in returned specs
- [ ] `is_verifier=True` → `grade`/`set_grade` IS in returned specs
- [ ] All other tools always present regardless of phase

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/ -k "codex" -v` — all Codex tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes

---

## Task 2: Add Step-Level Tool Filtering and MCP Wiring to dynamicTools
**Description**:
Extend `build_dynamic_tool_specs()` to accept `context` and add step-level tools from `available_tools`. Wire `mcp_servers` config into the `dynamicTools` payload during thread creation.

**Implementation Plan (Do These Steps)**
- [ ] In `build_dynamic_tool_specs()`, after building phase-filtered specs, add step-level tools:
```python
if context and context.available_tools:
    existing_names = {s["name"] for s in specs}
    for tool_name in context.available_tools:
        if tool_name in existing_names:
            continue
        # Log warning for unknown tools (Codex Server has no additional built-in tool registry)
        logger.warning(
            "Unknown tool '%s' in available_tools for Codex Server — skipping",
            tool_name,
        )
```
- [ ] Add MCP server configs to the dynamicTools payload in `codex_server.py` thread creation:
```python
thread_params: dict[str, Any] = {
    "cwd": context.working_dir,
    "approvalPolicy": "never",
    "dynamicTools": build_dynamic_tool_specs(
        is_verifier=is_verifier,
        context=context,
    ),
}

# Add external MCP servers to thread params
if context.mcp_servers:
    mcp_configs = []
    for mcp in context.mcp_servers:
        mcp_entry: dict[str, Any] = {"name": mcp.name}
        if mcp.url:
            mcp_entry["url"] = mcp.url
        elif mcp.command:
            mcp_entry["command"] = mcp.command
            if mcp.args:
                mcp_entry["args"] = mcp.args
        if mcp.env:
            mcp_entry["env"] = mcp.env
        mcp_configs.append(mcp_entry)
    thread_params["mcpServers"] = mcp_configs
```

**Dependencies**
- [ ] Task 1 complete: Phase filtering in place

**References**
- Thread creation: `src/orchestrator/agents/codex_server.py:418-451`
- Key decision: dynamicTools only for MCP (no config.toml) — Clarification Q7

**Constraints**
- MCP config goes in `thread_params["mcpServers"]`, separate from `dynamicTools`
- Auth tokens: resolve from env vars at thread creation time, do not include env var names in params

**Functionality (Expected Outcomes)**
- [ ] `available_tools` with unknown tools → warning logged, tools skipped
- [ ] `mcp_servers` → MCP entries appear in thread params
- [ ] `mcp_servers=None` → no `mcpServers` key in thread params

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/ -k "codex" -v` — all Codex tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes

---

## Task 3: Write Unit Tests for Codex Server Filtering and MCP Wiring
**Description**:
Create unit tests for phase filtering, step-level tool filtering, and MCP config in dynamicTools.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_codex_server_tool_filtering.py`:
```python
"""Tests for Codex Server phase filtering, step tools, and MCP wiring."""
import logging

from orchestrator.agents.codex_server_common import build_dynamic_tool_specs
from orchestrator.agents.types import ExecutionContext
from orchestrator.config.models import MCPServerConfig


def _make_context(**overrides) -> ExecutionContext:
    defaults = dict(
        run_id="r1", task_id="t1", working_dir="/tmp",
        prompt="test", requirements=["R1"],
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)


class TestCodexPhaseFiltering:
    def test_builder_no_grade(self):
        specs = build_dynamic_tool_specs(is_verifier=False)
        names = {s["name"] for s in specs}
        assert "grade" not in names
        assert "set_grade" not in names

    def test_verifier_has_grade(self):
        specs = build_dynamic_tool_specs(is_verifier=True)
        names = {s["name"] for s in specs}
        # grade or set_grade should be present
        assert "grade" in names or "set_grade" in names

    def test_common_tools_always_present(self):
        for is_verifier in [True, False]:
            specs = build_dynamic_tool_specs(is_verifier=is_verifier)
            names = {s["name"] for s in specs}
            assert "update_checklist" in names
            assert "submit" in names


class TestCodexStepTools:
    def test_unknown_tool_warning(self, caplog):
        ctx = _make_context(available_tools=["nonexistent"])
        with caplog.at_level(logging.WARNING):
            build_dynamic_tool_specs(is_verifier=False, context=ctx)
        assert "nonexistent" in caplog.text

    def test_no_context_backward_compat(self):
        specs = build_dynamic_tool_specs(is_verifier=False)
        assert len(specs) > 0  # Returns standard tools
```

**Functionality (Expected Outcomes)**
- [ ] Phase filtering tests pass (builder vs verifier)
- [ ] Step-level tool warning tests pass
- [ ] Backward compatibility test passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/unit/test_codex_server_tool_filtering.py -v` — all tests pass
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes
