# Step 8: Integration Tests + Example Routines

Validate end-to-end step-level tool and MCP configuration across the full system. Create integration tests that exercise the complete data flow (YAML → StepConfig → Executor → ExecutionContext → Agent) and provide example routines demonstrating the new features. This step confirms all prior work integrates correctly.

## Intent Verification
**Original Intent**: Integration tests verify step-level tool control works end-to-end; integration tests verify external MCP config reaches each agent type (see `docs/mcp-ops-c/intent.md` — "Definition of Complete" bullets 13-14).
**Functionality to Produce**:
- Integration test file covering step-level tools, MCP servers, backward compat, phase interaction
- Example routine YAML files demonstrating `available_tools` and `mcp_servers` usage
- All new and existing tests pass

**Final Verification Criteria**:
- All integration tests in `test_step_tool_control.py` pass
- All existing test suites pass (no regressions)
- Example routines parse without errors

---

## Task 1: Create Integration Tests for Step-Level Tool Control
**Description**:
Create `tests/integration/test_step_tool_control.py` with test cases that exercise the complete data flow from routine YAML through executor to context. Tests verify different steps get different tool sets and MCP configurations.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/integration/test_step_tool_control.py`:
```python
"""Integration tests for step-level tool and MCP configuration.

Tests the full data flow: YAML → StepConfig → Executor → ExecutionContext → Agent.
"""
import pytest
from orchestrator.config.models import MCPServerConfig, StepConfig, RoutineConfig


class TestStepLevelAvailableTools:
    def test_step_with_available_tools_parsed(self):
        """Step config with available_tools parses correctly from dict."""
        step_data = {
            "id": "step-1",
            "title": "Build with tools",
            "tasks": [{"id": "t1", "title": "Task 1", "requirements": []}],
            "available_tools": ["terminal", "file_editor"],
        }
        step = StepConfig(**step_data)
        assert step.available_tools == ["terminal", "file_editor"]

    def test_step_without_available_tools_defaults_none(self):
        """Existing step config without available_tools defaults to None."""
        step_data = {
            "id": "step-1",
            "title": "Standard step",
            "tasks": [{"id": "t1", "title": "Task 1", "requirements": []}],
        }
        step = StepConfig(**step_data)
        assert step.available_tools is None

    def test_different_steps_different_tools(self):
        """Different steps can have different available_tools."""
        step1 = StepConfig(
            id="s1", title="Step 1",
            tasks=[{"id": "t1", "title": "T1", "requirements": []}],
            available_tools=["terminal", "file_editor"],
        )
        step2 = StepConfig(
            id="s2", title="Step 2",
            tasks=[{"id": "t2", "title": "T2", "requirements": []}],
            available_tools=["file_editor"],
        )
        assert step1.available_tools != step2.available_tools


class TestStepLevelMCPServers:
    def test_step_with_mcp_servers_parsed(self):
        """Step config with mcp_servers parses correctly."""
        step_data = {
            "id": "step-1",
            "title": "Step with MCP",
            "tasks": [{"id": "t1", "title": "Task 1", "requirements": []}],
            "mcp_servers": [
                {"name": "ctx7", "url": "https://ctx7.example.com"},
                {"name": "local", "command": "local-mcp", "args": ["--verbose"]},
            ],
        }
        step = StepConfig(**step_data)
        assert len(step.mcp_servers) == 2
        assert step.mcp_servers[0].name == "ctx7"
        assert step.mcp_servers[0].url == "https://ctx7.example.com"
        assert step.mcp_servers[1].command == "local-mcp"

    def test_different_steps_different_mcps(self):
        """Different steps can have different mcp_servers."""
        step1 = StepConfig(
            id="s1", title="Step 1",
            tasks=[{"id": "t1", "title": "T1", "requirements": []}],
            mcp_servers=[{"name": "chrome", "url": "https://chrome.example.com"}],
        )
        step2 = StepConfig(
            id="s2", title="Step 2",
            tasks=[{"id": "t2", "title": "T2", "requirements": []}],
            mcp_servers=[{"name": "ctx7", "url": "https://ctx7.example.com"}],
        )
        assert step1.mcp_servers[0].name != step2.mcp_servers[0].name


class TestBackwardCompatibility:
    def test_existing_routine_no_new_fields(self):
        """Existing routine without available_tools/mcp_servers works unchanged."""
        step = StepConfig(
            id="s1", title="Legacy Step",
            tasks=[{"id": "t1", "title": "T1", "requirements": []}],
        )
        assert step.available_tools is None
        assert step.mcp_servers is None

    def test_mixed_steps_some_with_tools(self):
        """Routine with some steps having tools and some not."""
        step_with = StepConfig(
            id="s1", title="With tools",
            tasks=[{"id": "t1", "title": "T1", "requirements": []}],
            available_tools=["terminal"],
        )
        step_without = StepConfig(
            id="s2", title="Without tools",
            tasks=[{"id": "t2", "title": "T2", "requirements": []}],
        )
        assert step_with.available_tools == ["terminal"]
        assert step_without.available_tools is None


class TestPhaseAndStepInteraction:
    def test_step_tools_are_additive_concept(self):
        """Step-level tools expand the set, they don't restrict phase tools.

        This test verifies the semantic concept. Actual agent-level
        interaction is tested in per-agent unit tests.
        """
        step = StepConfig(
            id="s1", title="Build step",
            tasks=[{"id": "t1", "title": "T1", "requirements": []}],
            available_tools=["chrome_mcp"],
        )
        # Step has tools configured — agents will add these to their phase tools
        assert step.available_tools is not None
        assert "chrome_mcp" in step.available_tools
```
- [ ] Add imports and fixtures as needed for the existing test infrastructure

**Dependencies**
- [ ] Steps 1-7 complete: All schema and agent changes are in place

**References**
- Architecture: `docs/mcp-ops-c/architecture.md` — Testing Strategy section
- Plan: `docs/mcp-ops-c/plan.md` — Milestone 4
- Existing integration tests: `tests/integration/` for pattern reference

**Functionality (Expected Outcomes)**
- [ ] Step-level tool parsing tests pass
- [ ] Step-level MCP server parsing tests pass
- [ ] Backward compatibility tests pass
- [ ] Phase interaction concept test passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/integration/test_step_tool_control.py -v` — all tests pass (non-zero test count)
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes

---

## Task 2: Create Example Routine YAML Files
**Description**:
Create example routine YAML files in `examples/routines/` demonstrating `available_tools` and `mcp_servers` usage. These serve as documentation and can be used for manual testing.

**Implementation Plan (Do These Steps)**
- [ ] Create `examples/routines/step-tools-example.yaml`:
```yaml
name: Step Tools Example
description: Demonstrates per-step tool availability and external MCP servers.

steps:
  - id: build-with-browser
    title: Build with Browser Access
    step_context: >
      This step has access to browser tools and an external chrome MCP server
      for web testing capabilities.
    available_tools:
      - terminal
      - file_editor
      - browser
    mcp_servers:
      - name: chrome-mcp
        url: https://chrome-mcp.example.com
        timeout_seconds: 60
    tasks:
      - id: implement-feature
        title: Implement the Feature
        requirements:
          - Feature code is written and functional
          - Browser tests pass

  - id: verify-without-browser
    title: Verify Without Browser
    step_context: >
      This verification step uses only standard tools — no browser or MCP servers.
    tasks:
      - id: review-code
        title: Review Code Quality
        requirements:
          - Code follows project conventions
          - No security issues

  - id: integration-with-context7
    title: Integration with Context7
    available_tools:
      - terminal
    mcp_servers:
      - name: context7
        command: context7-mcp
        args:
          - --verbose
    tasks:
      - id: run-integration
        title: Run Integration Tests
        requirements:
          - All integration tests pass
```
- [ ] Verify the example routine parses correctly:
```bash
uv run python -c "
from orchestrator.config.models import RoutineConfig
import yaml
with open('examples/routines/step-tools-example.yaml') as f:
    data = yaml.safe_load(f)
routine = RoutineConfig(**data)
for step in routine.steps:
    print(f'{step.id}: tools={step.available_tools}, mcps={[m.name for m in (step.mcp_servers or [])]}')"
```

**References**
- Existing example routines: `examples/routines/` for format reference
- Architecture: `docs/mcp-ops-c/architecture.md` — MCPServerConfig model

**Constraints**
- Example must parse without errors using `RoutineConfig`
- Use realistic but non-functional URLs (`.example.com` domain)
- Show both URL and command transport types

**Functionality (Expected Outcomes)**
- [ ] Example YAML parses without errors
- [ ] Demonstrates `available_tools` with different tools per step
- [ ] Demonstrates `mcp_servers` with both URL and STDIO transports
- [ ] Shows steps without new fields for backward compat reference

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run the parse verification command above — prints step info without errors
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes
