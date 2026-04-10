# D8: Plan Freshness Check

Measures how much the codebase diverges from plan instructions as execution progresses.
The worktree reflects execution through step 7.

## Methodology

For steps 01 (early), 04 (mid), and 07 (late), all concrete references were extracted from
the step instruction files: file paths, class/function/method names, import paths, line
numbers, field names, test file paths, and tool/constant names. Each reference was then
checked against the actual worktree state.

A reference is **stale** if:
- A file path does not exist at the specified location
- A class, function, or field name does not exist or has a different name
- A line number is significantly wrong (>20 lines off) such that the contextual description
  no longer matches what is at that line
- An import path is wrong
- A field placement or ordering instruction is inaccurate
- A test file was created under a different name or structure than specified

A reference is **accurate** if the entity exists and is recognizably what the plan described,
even if minor details (exact line numbers within ~20 lines, slight naming variations) differ.

---

## Step 01: MCPServerConfig Model + StepConfig Extension

**Written before any execution. All references target the pre-existing codebase.**

| # | Reference | Type | Actual State | Status |
|---|-----------|------|-------------|--------|
| 1 | `src/orchestrator/config/models.py` | file path | Exists | Accurate |
| 2 | `MCPServerConfig` class | class name | Exists at line 33 | Accurate |
| 3 | `BaseModel` from pydantic | import | Already present at line 6 | Accurate |
| 4 | `model_validator` from pydantic | import | Already present at line 6 | Accurate |
| 5 | `MCPServerConfig` placed before `StepConfig` | placement | `MCPServerConfig` at line 33, `StepConfig` at line 193 | Accurate |
| 6 | `MCPServerConfig.name: str` | field | Exists (line 41) | Accurate |
| 7 | `MCPServerConfig.url: str \| None = None` | field | Exists (line 42) | Accurate |
| 8 | `MCPServerConfig.command: str \| None = None` | field | Exists (line 43) | Accurate |
| 9 | `MCPServerConfig.args: list[str] \| None = None` | field | Exists (line 44) | Accurate |
| 10 | `MCPServerConfig.env: dict[str, str] \| None = None` | field | Exists (line 45) | Accurate |
| 11 | `MCPServerConfig.auth_token_env: str \| None = None` | field | Exists (line 46) | Accurate |
| 12 | `MCPServerConfig.timeout_seconds: int = 30` | field | Exists (line 47) | Accurate |
| 13 | `_validate_transport` model_validator | method | Exists (line 58), uses `model_validator(mode="after")` | Accurate |
| 14 | `StepConfig` class | class name | Exists at line 193 | Accurate |
| 15 | `StepConfig.available_tools: list[str] \| None = None` | field | Exists (line 204) | Accurate |
| 16 | `StepConfig.mcp_servers: list[MCPServerConfig] \| None = None` | field | Exists (line 205) | Accurate |
| 17 | Fields after `dry_run` field | placement | `dry_run` at line 203, new fields at 204-205 | Accurate |
| 18 | Existing fields: `id, title, step_context, gate, tasks, transitions, type, dry_run` | field list | All present. Plan omits `task_context` on TaskConfig but this is on StepConfig which is correct. | Accurate |
| 19 | `tests/unit/test_mcp_server_config.py` | test file path | Exists | Accurate |
| 20 | `TestMCPServerConfig` test class | class name | Exists | Accurate |
| 21 | `TestStepConfigExtension` test class | class name | Exists | Accurate |
| 22 | `from orchestrator.config.models import MCPServerConfig, StepConfig` | import path | Matches actual import in test file (line 6) | Accurate |
| 23 | Test: `test_url_transport_valid` | method | Exists | Accurate |
| 24 | Test: `test_command_transport_valid` | method | Exists | Accurate |
| 25 | Test: `test_both_transports_rejected` | method | Exists | Accurate |
| 26 | Test: `test_neither_transport_rejected` | method | Exists | Accurate |
| 27 | Test: `test_timeout_default` | method | Exists | Accurate |
| 28 | Test: `test_auth_token_env_is_string_reference` | method | Exists | Accurate |
| 29 | Test: `test_env_vars` | method | Exists | Accurate |
| 30 | Test: `test_backward_compat_no_new_fields` | method | Exists | Accurate |
| 31 | Test: `test_available_tools_parsed` | method | Exists | Accurate |
| 32 | Test: `test_mcp_servers_parsed` | method | Exists | Accurate |
| 33 | `docs/mcp-ops-c/architecture.md` | reference doc | Exists | Accurate |
| 34 | `docs/mcp-ops-c/intent.md` | reference doc | Exists | Accurate |

**Step 01 deviation note:** The implementation added an extra `field_validator` for `auth_token_env` (line 49-56) that validates env var names match `^[A-Z_][A-Z0-9_]*$`. This was not specified in the plan but is an additive enhancement. Not counted as stale.

**Step 01 Staleness: 0 / 34 = 0.0%**

---

## Step 04: Claude SDK Tool Filtering + MCP Wiring

**Written before execution began but depends on Steps 1-3 being complete.**

| # | Reference | Type | Actual State | Status |
|---|-----------|------|-------------|--------|
| 1 | `src/orchestrator/agents/claude_sdk.py` | file path | Exists | Accurate |
| 2 | `_BUILDER_TOOLS` constant | name | Exists (line 173) | Accurate |
| 3 | `_VERIFIER_TOOLS` constant | name | Exists (line 228) | Accurate |
| 4 | "line ~563-584" for tool selection | line ref | Plan says current code is `tools = _VERIFIER_TOOLS if is_verifier else _BUILDER_TOOLS`. In the worktree, tools are built at line 657 via `_build_tool_list()` (i.e., already modified). The original pre-execution line range is indeterminate but the plan's characterization of the *pre-change* state is consistent. | Accurate |
| 5 | `_build_tool_list(is_verifier, available_tools)` | function | Exists at line 303 | Accurate |
| 6 | Function signature: `is_verifier: bool, available_tools: list[str] \| None = None` | signature | Matches (line 304-305) | Accurate |
| 7 | Known additional tools registry: `known_additional_tools: dict[str, dict[str, Any]]` | variable | Named `_STEP_TOOL_REGISTRY` (line 300) instead. Same concept, different name. | **Stale** |
| 8 | `context.available_tools` | field access | `ExecutionContext.available_tools` exists (types.py line 65) | Accurate |
| 9 | `_build_mcp_params(mcp_servers)` | function | Exists at line 335 | Accurate |
| 10 | Function returns `dict[str, Any]` | return type | Matches | Accurate |
| 11 | `MCPServerConfig` imported from `orchestrator.config.models` | import | Line 52: `from orchestrator.config.models import MCPServerConfig` | Accurate |
| 12 | Beta API: `client.beta.messages.create()` with `betas=["mcp-client-2025-11-20"]` | API call | Exists at lines 674-682 | Accurate |
| 13 | Standard API: `client.messages.create()` when no MCP | API call | Exists at lines 684-690 | Accurate |
| 14 | STDIO servers skipped with warning | behavior | Implemented at line 349-356 | Accurate |
| 15 | Auth token resolved from env var | behavior | Implemented at line 372 | Accurate |
| 16 | `server_config["authorization_token"]` | dict key | Present at line 374 | Accurate |
| 17 | `tests/unit/test_claude_sdk_tool_filtering.py` | test file path | Exists | Accurate |
| 18 | `from orchestrator.agents.claude_sdk import _build_tool_list, _build_mcp_params` | import path | Matches actual test file line 6 | Accurate |
| 19 | `TestClaudeSDKToolFiltering` test class | class name | Exists | Accurate |
| 20 | `TestClaudeSDKMCPParams` test class | class name | Exists | Accurate |
| 21 | Test: `test_builder_tools_when_none` | method | Exists | Accurate |
| 22 | Test: `test_verifier_tools_when_none` | method | Exists | Accurate |
| 23 | Test: `test_unknown_tool_warning` | method | Exists | Accurate |
| 24 | Test: `test_phase_tools_always_included` | method | Exists | Accurate |
| 25 | Test: `test_https_server_included` | method | Exists | Accurate |
| 26 | Test: `test_stdio_server_skipped` | method | Exists | Accurate |
| 27 | Test: `test_none_returns_empty` | method | Exists | Accurate |
| 28 | Test: `test_auth_token_from_env` | method | Exists | Accurate |
| 29 | "lines 172-292 for tool defs" | line ref | `_BUILDER_TOOLS` at 173, `_VERIFIER_TOOLS` ends at 293. Close. | Accurate |
| 30 | `docs/mcp-ops-c/architecture.md` — Claude SDK row | reference doc | Exists | Accurate |
| 31 | Step 2 complete: `ExecutionContext` carries `available_tools` | dependency | Confirmed: `available_tools` on `ExecutionContext` line 65 | Accurate |
| 32 | `context.mcp_servers` | field access | Exists on `ExecutionContext` line 66 | Accurate |

**Step 04 deviation note:** The plan specifies an inline `known_additional_tools` dict; the implementation uses a module-level `_STEP_TOOL_REGISTRY` constant at line 300. Same purpose but different naming. The implementation also added an HTTPS-only validation (line 357-364) that rejects non-https URLs, which was not in the plan but is a reasonable enhancement.

**Step 04 Staleness: 1 / 32 = 3.1%**

---

## Step 07: User-Managed MCP All-Tools + MCP Info in Prompt Response

**Written before execution but depends on Steps 1-6 being complete. This is the latest step
executed, so cross-step drift is most likely here.**

| # | Reference | Type | Actual State | Status |
|---|-----------|------|-------------|--------|
| 1 | `src/orchestrator/mcp/server.py` | file path | Exists | Accurate |
| 2 | `_register_tools()` method | method | Exists at line 73 | Accurate |
| 3 | "lines 42-68" for init | line ref | `__init__` at line 45-71. Off by 3 lines. | Accurate |
| 4 | "lines 70-212" for `_register_tools` | line ref | `_register_tools` starts at line 73. Top of range off by 3. End not checked but plausible. | Accurate |
| 5 | `self._allowed_tools = BUILDER_TOOLS if self.phase == "building" else VERIFIER_TOOLS` | pre-change code | Current code (line 62): `self._allowed_tools = ALL_TOOLS`. The plan correctly describes the pre-change state and the change was applied. | Accurate |
| 6 | `ALL_TOOLS = BUILDER_TOOLS \| VERIFIER_TOOLS` | constant | Exists at line 35 | Accurate |
| 7 | `BUILDER_TOOLS` constant | name | Exists at line 19 | Accurate |
| 8 | `VERIFIER_TOOLS` constant | name | Exists at line 29 | Accurate |
| 9 | "lines 19-32" for tool sets | line ref | `BUILDER_TOOLS` at 19-27, `VERIFIER_TOOLS` at 29-33. Close. | Accurate |
| 10 | `src/orchestrator/api/schemas/tasks.py` | file path | Exists | Accurate |
| 11 | `CallbackInstructions` class | class name | Exists at line 131 | Accurate |
| 12 | "lines 130-137" for CallbackInstructions | line ref | Starts at line 131. Close. | Accurate |
| 13 | Plan says add `mcp_servers: list[MCPServerConfig] \| None = None` to `CallbackInstructions` | field | Exists at line 140 | Accurate |
| 14 | Plan's `CallbackInstructions` fields: `run_id, task_id, api_base_url, rest_instructions, mcp_instructions` | field list | All exist. However, actual code also has `available_tools: list[str] \| None = None` (line 139) which the plan does NOT mention. | **Stale** |
| 15 | `from orchestrator.config.models import MCPServerConfig` import in schemas/tasks.py | import | Present (confirmed MCPServerConfig used in CallbackInstructions) | Accurate |
| 16 | `src/orchestrator/api/routers/tasks.py` | file path | Exists | Accurate |
| 17 | `_build_callback_instructions()` function | function | Exists at line 292 | Accurate |
| 18 | "lines 292-327" for builder function | line ref | Starts at 292, ends around 333. Close. | Accurate |
| 19 | `get_task_prompt()` function | function | Exists at line 415 | Accurate |
| 20 | "lines 408-506" for prompt endpoint | line ref | Starts at line 415. Off by 7. | Accurate |
| 21 | Plan: `_build_callback_instructions` accepts `mcp_servers` param | parameter | Actual has both `available_tools` and `mcp_servers` params (lines 296-297). Plan only mentions `mcp_servers`. | **Stale** |
| 22 | `step_config.mcp_servers` access in prompt endpoint | code pattern | Present at line 481 | Accurate |
| 23 | `mcp_servers=mcp_servers` passed to callback builder | code pattern | Present at line 487 | Accurate |
| 24 | `tests/unit/test_mcp_server_all_tools.py` | test file path | Exists | Accurate |
| 25 | `TestCallbackInstructionsMCPServers` test class | class name | Exists | Accurate |
| 26 | `from orchestrator.api.schemas.tasks import CallbackInstructions` | import path | Matches (line 3 of test file) | Accurate |
| 27 | `from orchestrator.config.models import MCPServerConfig` | import path | Matches (line 4 of test file) | Accurate |
| 28 | Test: `test_mcp_servers_field_optional` | method | Exists | Accurate |
| 29 | Test: `test_mcp_servers_field_populated` | method | Exists | Accurate |
| 30 | Test: `test_json_serialization_includes_mcp_servers` | method | Exists | Accurate |
| 31 | Plan does NOT mention `TestMCPAllToolsRegistration` tests | test class | Exists in actual test file but not specified in plan. This is extra coverage, not a staleness issue. | N/A (additive) |
| 32 | `docs/mcp-ops-c/architecture.md` — User-Managed row | reference doc | Exists | Accurate |

### Cross-Step Staleness Analysis for Step 07

Step 07's plan was written assuming a specific state of the codebase. Several earlier steps modified files
that step 07 references:

1. **`CallbackInstructions` schema (modified by earlier execution)**: The plan at step 07 lists the
   `CallbackInstructions` fields as `run_id, task_id, api_base_url, rest_instructions, mcp_instructions`.
   But the actual implementation has an additional field `available_tools: list[str] | None = None` (line 139).
   This field was likely added during step 02 or step 03 execution (as part of wiring tool availability into
   the prompt response), but the step 07 plan was not updated to account for it. **This is cross-step drift.**

2. **`_build_callback_instructions` signature (expanded by earlier execution)**: The plan says to update
   the function to accept `mcp_servers` parameter. But the actual function already has both `available_tools`
   AND `mcp_servers` parameters. The plan does not mention `available_tools`, meaning an earlier step added it
   and step 07's plan is incomplete about the current parameter list. **This is cross-step drift.**

3. **Line numbers for `_register_tools()` and `__init__`**: The plan says lines 42-68 for init and 70-212
   for `_register_tools`. Actual init is at 45-71 and `_register_tools` starts at 73. This ~3 line shift
   is likely from the addition of `ALL_TOOLS = BUILDER_TOOLS | VERIFIER_TOOLS` at line 35 which was added
   as part of step 07 implementation itself (or possibly created pre-execution). Minor drift.

4. **Line numbers for `get_task_prompt()`**: Plan says 408-506, actual starts at 415. This 7-line shift
   could be from earlier modifications to the tasks router. Minor drift but still within tolerance.

**Step 07 Staleness: 2 / 31 = 6.5%**

---

## Summary: Staleness Rate by Step

| Step | Position | Total References | Stale References | Staleness Rate |
|------|----------|-----------------|------------------|----------------|
| 01   | Early    | 34              | 0                | **0.0%**       |
| 04   | Mid      | 32              | 1                | **3.1%**       |
| 07   | Late     | 31              | 2                | **6.5%**       |

### Trend

Staleness increases monotonically with step number, confirming the hypothesis that
plans written before execution become progressively less accurate as earlier steps
modify the codebase.

### Types of Staleness Observed

1. **Naming divergence** (Step 04, ref #7): The plan specified an inline dict named
   `known_additional_tools`. The implementation used a module-level constant named
   `_STEP_TOOL_REGISTRY`. Same concept, different name. This is a minor implementation
   decision that diverged from the plan's specificity.

2. **Cross-step field accumulation** (Step 07, ref #14): `CallbackInstructions` gained
   an `available_tools` field during earlier step execution that the step 07 plan did
   not account for. The plan's field listing became incomplete.

3. **Cross-step signature drift** (Step 07, ref #21): `_build_callback_instructions()`
   gained an `available_tools` parameter from earlier steps. Step 07 only mentions adding
   `mcp_servers`, unaware that `available_tools` was already added.

### Notable Non-Staleness Observations

- **Line number references held up well**: Despite 7 steps of modifications, line number
  references in the plans were generally within 3-7 lines of actual positions. The plans
  used "~line" hedging which proved appropriate.

- **File paths were universally accurate**: All 3 steps referenced the correct file paths.
  No files were moved or renamed during execution.

- **Test file names matched exactly**: Every specified test file was created at the planned
  path with the planned name.

- **Import paths were universally accurate**: All module import references remained valid.

- **Additive enhancements were common but not disruptive**: Implementations frequently
  added validation or features beyond what the plan specified (e.g., HTTPS-only validation,
  `auth_token_env` format validation), but these did not invalidate the plan's instructions.

### Conclusion

The overall staleness rate is low (0% to 6.5%), indicating the plan was well-structured
with stable file paths, class names, and module organization. The drift that did occur
was concentrated in **cross-step field/signature accumulation** -- where earlier steps
added fields or parameters that later step plans did not anticipate. This type of drift
is inherent to waterfall-style static plans and could be mitigated by:

1. Re-reading modified files before executing each step (runtime freshness check)
2. Using abstract references ("add to the existing parameters") rather than exhaustive
   field listings
3. Maintaining a running "modified interfaces" log between steps
