# Step 1: MCPServerConfig Model + StepConfig Extension

Add the `MCPServerConfig` Pydantic model and extend `StepConfig` with `available_tools` and `mcp_servers` fields. This is the data model foundation — all downstream steps depend on these schema changes. Existing routines must continue to parse unchanged (both new fields default to `None`).

## Intent Verification
**Original Intent**: Enable per-step tool availability and external MCP server configuration in routine YAML definitions (see `docs/mcp-ops-c/intent.md` — "Desired End State" bullet 1).
**Functionality to Produce**:
- `MCPServerConfig` Pydantic model with url/command dual transport validation
- `StepConfig` extended with `available_tools` and `mcp_servers` optional fields
- Routine YAML files with new fields parse correctly
- Existing routines without new fields parse unchanged

**Final Verification Criteria**:
- Unit tests for `MCPServerConfig` validation pass
- Unit tests for `StepConfig` backward compatibility pass
- All existing tests continue to pass

---

## Task 1: Define MCPServerConfig Model
**Description**:
Create the `MCPServerConfig` Pydantic model in the config models module. This model represents an external MCP server that can be configured per-step in routine YAML. It supports two transport types (HTTP via `url` or STDIO via `command`) and must validate that exactly one is set.

**Implementation Plan (Do These Steps)**
The model goes in `src/orchestrator/config/models.py` alongside the other config models. Place it before `StepConfig` since `StepConfig` will reference it.

- [ ] Add the `MCPServerConfig` class to `src/orchestrator/config/models.py`:
```python
class MCPServerConfig(BaseModel):
    """Configuration for an external MCP server available during a step."""
    name: str                              # Unique identifier within a step
    url: str | None = None                 # HTTP transport (e.g., "https://mcp.example.com")
    command: str | None = None             # STDIO transport (e.g., "context7-mcp")
    args: list[str] | None = None          # CLI args for STDIO transport
    env: dict[str, str] | None = None      # Environment variables for subprocess
    auth_token_env: str | None = None      # Env var name containing auth token (never inline)
    timeout_seconds: int = 30              # Connection timeout

    @model_validator(mode="after")
    def _validate_transport(self) -> "MCPServerConfig":
        has_url = self.url is not None
        has_cmd = self.command is not None
        if has_url and has_cmd:
            raise ValueError("MCPServerConfig must have exactly one of 'url' or 'command', not both")
        if not has_url and not has_cmd:
            raise ValueError("MCPServerConfig must have exactly one of 'url' or 'command'")
        return self
```
- [ ] Add `model_validator` to the pydantic imports if not already present (check the existing imports at the top of the file)

**Dependencies**
- [ ] Pydantic v2 `BaseModel` and `model_validator` (already used in this file)

**References**
- Architecture: `docs/mcp-ops-c/architecture.md` — MCPServerConfig model specification
- Security decision: `auth_token_env` stores env var *name*, never inline token values

**Constraints**
- Do not modify any existing model classes in this task
- The `MCPServerConfig` class must be placed before `StepConfig` in the file

**Functionality (Expected Outcomes)**
- [ ] `MCPServerConfig(name="ctx7", url="https://ctx7.example.com")` creates a valid instance
- [ ] `MCPServerConfig(name="local", command="context7-mcp", args=["--verbose"])` creates a valid instance
- [ ] `MCPServerConfig(name="bad", url="https://...", command="cmd")` raises `ValidationError`
- [ ] `MCPServerConfig(name="empty")` raises `ValidationError`
- [ ] `timeout_seconds` defaults to 30 when not specified
- [ ] `auth_token_env` accepts a string (env var name reference)

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run python -c "from orchestrator.config.models import MCPServerConfig; c = MCPServerConfig(name='test', url='https://x.com'); print(c.model_dump())"` — prints valid model dict
- [ ] Run `uv run python -c "from orchestrator.config.models import MCPServerConfig; MCPServerConfig(name='bad', url='x', command='y')"` — raises ValidationError
- [ ] Run `uv run pytest tests/ -x --timeout=30` — all existing tests still pass

---

## Task 2: Extend StepConfig with available_tools and mcp_servers
**Description**:
Add two optional fields to `StepConfig`: `available_tools` (list of tool name strings) and `mcp_servers` (list of `MCPServerConfig` objects). Both default to `None` for backward compatibility.

**Implementation Plan (Do These Steps)**
- [ ] Add two fields to the `StepConfig` class in `src/orchestrator/config/models.py` (after the existing `dry_run` field):
```python
class StepConfig(BaseModel):
    # ... existing fields (id, title, step_context, gate, tasks, transitions, type, dry_run)
    available_tools: list[str] | None = None
    mcp_servers: list[MCPServerConfig] | None = None
```

**Constraints**
- Only add two new fields to `StepConfig`; do not modify any existing fields
- Both fields must default to `None`

**Functionality (Expected Outcomes)**
- [ ] `StepConfig` with no `available_tools` or `mcp_servers` → fields are `None` (backward compatible)
- [ ] `StepConfig` with `available_tools=["terminal", "file_editor"]` → field accessible as list of strings
- [ ] `StepConfig` with `mcp_servers=[MCPServerConfig(name="x", url="https://x")]` → field accessible as list

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/ -x --timeout=30` — all existing tests still pass (backward compatibility confirmed)
- [ ] Run `uv run python -c "from orchestrator.config.models import StepConfig, MCPServerConfig; print(StepConfig(id='s1', title='t', tasks=[{'id':'t1','title':'t','requirements':[]}]).available_tools)"` — prints `None`

---

## Task 3: Write Unit Tests for MCPServerConfig and StepConfig Extension
**Description**:
Create a dedicated test file for the new `MCPServerConfig` model and the `StepConfig` extension. Tests must verify transport validation, field defaults, and backward compatibility.

**Implementation Plan (Do These Steps)**
- [ ] Create `tests/unit/test_mcp_server_config.py` with the following tests:
```python
"""Tests for MCPServerConfig model and StepConfig extension."""
import pytest
from pydantic import ValidationError

from orchestrator.config.models import MCPServerConfig, StepConfig


class TestMCPServerConfig:
    def test_url_transport_valid(self):
        cfg = MCPServerConfig(name="remote", url="https://mcp.example.com")
        assert cfg.url == "https://mcp.example.com"
        assert cfg.command is None

    def test_command_transport_valid(self):
        cfg = MCPServerConfig(name="local", command="context7-mcp", args=["--verbose"])
        assert cfg.command == "context7-mcp"
        assert cfg.args == ["--verbose"]
        assert cfg.url is None

    def test_both_transports_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            MCPServerConfig(name="bad", url="https://x", command="y")

    def test_neither_transport_rejected(self):
        with pytest.raises(ValidationError, match="exactly one"):
            MCPServerConfig(name="empty")

    def test_timeout_default(self):
        cfg = MCPServerConfig(name="t", url="https://x")
        assert cfg.timeout_seconds == 30

    def test_auth_token_env_is_string_reference(self):
        cfg = MCPServerConfig(name="auth", url="https://x", auth_token_env="MY_TOKEN_VAR")
        assert cfg.auth_token_env == "MY_TOKEN_VAR"

    def test_env_vars(self):
        cfg = MCPServerConfig(name="e", command="cmd", env={"KEY": "val"})
        assert cfg.env == {"KEY": "val"}


class TestStepConfigExtension:
    def test_backward_compat_no_new_fields(self):
        """Existing StepConfig usage without available_tools/mcp_servers still works."""
        step = StepConfig(
            id="s1", title="Test Step",
            tasks=[{"id": "t1", "title": "Task 1", "requirements": []}],
        )
        assert step.available_tools is None
        assert step.mcp_servers is None

    def test_available_tools_parsed(self):
        step = StepConfig(
            id="s1", title="Test Step",
            tasks=[{"id": "t1", "title": "Task 1", "requirements": []}],
            available_tools=["terminal", "file_editor"],
        )
        assert step.available_tools == ["terminal", "file_editor"]

    def test_mcp_servers_parsed(self):
        step = StepConfig(
            id="s1", title="Test Step",
            tasks=[{"id": "t1", "title": "Task 1", "requirements": []}],
            mcp_servers=[{"name": "ctx7", "url": "https://ctx7.example.com"}],
        )
        assert len(step.mcp_servers) == 1
        assert step.mcp_servers[0].name == "ctx7"
```

**Functionality (Expected Outcomes)**
- [ ] All `MCPServerConfig` validation tests pass
- [ ] `StepConfig` backward compatibility test passes
- [ ] `StepConfig` with new fields test passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] Run `uv run pytest tests/unit/test_mcp_server_config.py -v` — all tests pass (should show ~10 tests)
- [ ] Run `uv run pytest tests/ -x --timeout=30` — full test suite passes
