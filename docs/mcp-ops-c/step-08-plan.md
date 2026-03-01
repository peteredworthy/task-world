# Step Plan: Integration Tests + Example Routines

## Purpose

Validate end-to-end step-level tool and MCP configuration across the full system. Create integration tests that exercise the complete data flow (YAML → StepConfig → Executor → ExecutionContext → Agent) and provide example routines demonstrating the new features.

## Prerequisites

- **Steps 1–2** complete: Schema foundation and executor wiring.
- **Steps 3–7** complete: All agent implementations (CLI, Claude SDK, Codex Server, OpenHands, User-Managed).

## Functional Contract

### Inputs

- Test routine YAML files with per-step `available_tools` and `mcp_servers` configurations
- Existing routine YAML files (for backward compatibility testing)

### Outputs

- Integration test file `tests/integration/test_step_tool_control.py` with comprehensive test cases
- Example routine YAML files in `examples/routines/` demonstrating `available_tools` and `mcp_servers` usage
- All tests pass (new + existing)

### Error Cases

- Integration test failures indicate wiring issues between layers (schema → executor → agent)
- Backward compatibility failures indicate regressions in existing routines
- Example routines must parse without errors

## Tasks

1. Create `tests/integration/test_step_tool_control.py` with the following test cases:
   - `test_step_level_available_tools`: Different `available_tools` per step → correct context per step
   - `test_step_level_mcp_servers`: Different `mcp_servers` per step → correct MCP config per step
   - `test_backward_compat_no_tools_field`: Existing routine (no new fields) → all standard tools available
   - `test_phase_and_step_interaction`: Phase filtering works alongside step-level tools
   - `test_codex_phase_filtering`: Builder threads don't see `grade` tool
   - `test_mcp_all_tools_registration`: User-Managed MCP server exposes all tools
2. Create test fixture routines with varied per-step configurations
3. Create example routine YAML files in `examples/routines/` showing:
   - Step with `available_tools: [terminal, file_editor]` + external MCP
   - Step with different `available_tools` per step
   - Step with `mcp_servers` using both URL and command transports
4. Verify all example routines parse correctly

## Verification Approach

### Auto-Verify

- All integration tests in `test_step_tool_control.py` pass
- All existing test suites pass (no regressions):
  - `uv run pytest tests/unit/` — all unit tests pass
  - `uv run pytest tests/integration/` — all integration tests pass
- Example routine YAML files parse without errors
- Test coverage for the full data flow path

### Manual Verification

- Review integration test quality: tests are meaningful, not just smoke tests
- Review example routines for clarity and usefulness as documentation
- Confirm test fixtures cover edge cases (empty lists, None values, mixed configs)

## Context & References

- Architecture: `docs/mcp-ops-c/architecture.md` — Testing Strategy section
- Plan: `docs/mcp-ops-c/plan.md` — Milestone 4: Integration Testing & Polish
- Data flow: YAML → StepConfig → Executor → ExecutionContext → Agent
- Existing integration tests: `tests/integration/` for pattern reference
- Example routines: `examples/routines/` for format reference
