# Step Plan: MCPServerConfig Model + StepConfig Extension

## Purpose

Create the data model foundation for per-step tool and MCP configuration. This step introduces the `MCPServerConfig` Pydantic model and extends `StepConfig` with `available_tools` and `mcp_servers` fields. All downstream steps depend on these schema changes.

## Prerequisites

- None — this is the first step with no dependencies.

## Functional Contract

### Inputs

- Routine YAML files containing optional `available_tools` (list of strings) and `mcp_servers` (list of MCP server config objects) within step definitions
- `MCPServerConfig` fields: `name` (required), `url` or `command` (exactly one required), `args`, `env`, `auth_token_env`, `timeout_seconds`

### Outputs

- `MCPServerConfig` Pydantic model in `src/orchestrator/config/models.py` with transport validation (exactly one of `url` or `command`)
- `StepConfig` extended with `available_tools: list[str] | None = None` and `mcp_servers: list[MCPServerConfig] | None = None`
- Both fields default to `None` for backward compatibility

### Error Cases

- `MCPServerConfig` with both `url` and `command` set → Pydantic validation error
- `MCPServerConfig` with neither `url` nor `command` set → Pydantic validation error
- Invalid YAML structure for `mcp_servers` entries → parse error at routine load time

## Tasks

1. Define `MCPServerConfig(BaseModel)` in `src/orchestrator/config/models.py` with all fields and transport validator
2. Add `available_tools` and `mcp_servers` fields to `StepConfig`
3. Write unit tests for `MCPServerConfig` validation (url-or-command constraint, defaults, all field types)
4. Write unit tests for `StepConfig` parsing with and without new fields (backward compatibility)
5. Create a test routine YAML fixture that exercises `available_tools` and `mcp_servers` in step definitions

## Verification Approach

### Auto-Verify

- Unit tests in `tests/unit/test_mcp_server_config.py`:
  - `MCPServerConfig` with `url` only → valid
  - `MCPServerConfig` with `command` only → valid
  - `MCPServerConfig` with both `url` and `command` → validation error
  - `MCPServerConfig` with neither → validation error
  - `auth_token_env` stores env var name (string), not a token value
  - `timeout_seconds` defaults to 30
- `StepConfig` tests:
  - Existing routines parse unchanged (no `available_tools` / `mcp_servers` → None)
  - New fields parse correctly from YAML with tool names and MCP configs
- All existing tests continue to pass

### Manual Verification

- Review that `MCPServerConfig` field types match the architecture doc
- Confirm `auth_token_env` is documented as env var reference, not inline token

## Context & References

- Architecture: `docs/mcp-ops-c/architecture.md` — MCPServerConfig model specification
- Current StepConfig: `src/orchestrator/config/models.py:152`
- Key decision: `auth_token_env` reference pattern for security (tokens never in YAML)
- Key decision: `url` vs `command` field presence for transport detection
