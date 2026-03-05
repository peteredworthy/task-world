# D1: Gate False-Positive Audit

**Run:** `8bf41c40-9db2-49a6-b188-0145631ce134`
**Routine:** `mcp-ops-c` (MCP Operations -- Per-Step Tool & External MCP Configuration)
**Date:** 2026-03-04
**Auditor:** Opus 4.6 (automated)

## Context

This run executed routine `mcp-ops-c` against a worktree branched from commit
`c13bc41` which already contained commits labeled S-01 through S-08 from a prior
implementation pass. Nearly all foundational features (MCPServerConfig, StepConfig
extensions, ExecutionContext fields, CLI tool hints, Claude SDK filtering, Codex
Server phase filtering, OpenHands tool/MCP wiring, MCP server all-tools
registration, and CallbackInstructions mcp_servers) were already present in the
codebase at run start. The agents therefore operated in a "refinement" mode rather
than a "greenfield build" mode.

This is critical context for the audit: the gate was evaluating whether requirements
were met in the *final state*, not whether the *diff* itself constituted the work.

---

## Results Table

| # | Step | Task Title | Diff Summary | Score | Notes |
|---|------|-----------|-------------|-------|-------|
| 1 | S-01 | Define MCPServerConfig Model | +14 lines: added `auth_token_env` field_validator rejecting inline tokens; +1 test | **complete** | Model already existed. Diff adds meaningful security validation (R3 enhancement). |
| 2 | S-01 | Extend StepConfig with available_tools and mcp_servers | +22 lines: added backward compat test using RoutineConfig round-trip | **complete** | Fields already existed. Diff adds a test confirming R2 (backward compat). |
| 3 | S-01 | Write Unit Tests for MCPServerConfig and StepConfig Extension | +8/-30 lines: refactored test helper to module-level; removed the RoutineConfig test T-02 just added | **partial** | Net negative: removed the backward-compat test the prior task added. Existing tests still pass and cover core cases, but the agent undid prior work. |
| 4 | S-02 | Extend ExecutionContext with Step-Level Fields | +12 lines: added step_id/available_tools/mcp_servers to recovery context path in executor | **complete** | ExecutionContext fields already existed. Diff wires them into the `_handle_recovery` path, which was the one remaining gap. |
| 5 | S-02 | Update Executor to Populate Step-Level Context | +155/-5 lines: extracted `_get_current_step_config()`; added extensive builder+verifier context tests | **complete** | Substantial and correct. Both builder and verifier paths now populate fields from step config. New test validates the full flow. |
| 6 | S-02 | Write Unit Tests for ExecutionContext Extension | **ZERO DIFF** (start == end commit) | **insufficient** | No code changed. Test file already existed (created by a prior run). Auto-verify confirmed tests pass. Agent found nothing to do and self-reported done. |
| 7 | S-03 | Add Step-Level Tool Hints to CLI Prompt | +46/-18 lines: refactored `_build_step_sections` into separate methods; added None/empty tests | **complete** | Functionality already existed. Diff improves code structure and adds edge case tests. |
| 8 | S-03 | Add MCP Server Info to CLI Prompt and .mcp.json | +122/-17 lines: auth tokens replaced with env var refs in prompt; .mcp.json merge with existing; `_build_child_env()` helper; tests updated | **complete** | Major security improvement: auth tokens no longer inline in prompt text. New env var passing mechanism. .mcp.json merge logic added. |
| 9 | S-03 | Write Unit Tests for CLI Tool Hints and MCP Info | -134/+7 lines: **removed** .mcp.json tests, stdio tests, auth token tests, integration test | **insufficient** | Net destructive: deleted ~130 lines of valuable test coverage including .mcp.json writing, auth token env ref, stdio transport, and the execute+mcp.json integration test. Also removed the auth_token_env hint line from cli.py. |
| 10 | S-04 | Implement Additive Tool Filtering in Claude SDK Agent | +43/-7 lines: added `_STEP_TOOL_REGISTRY`; step tools now added from registry instead of always warned | **complete** | Correct additive filtering with registry lookup. Tests added for the new code path. |
| 11 | S-04 | Implement MCP Connector Beta Wiring | +8 lines: added non-HTTPS URL filter with warning; +72 lines tests for beta/standard API switching | **complete** | Filtering already existed for STDIO. Diff adds HTTPS-only enforcement and comprehensive tests for beta vs standard API path. |
| 12 | S-04 | Write Unit Tests for Claude SDK Tool Filtering and MCP Wiring | -70/+3 lines: removed most test bodies, kept only stubs | **insufficient** | Net destructive: gutted test file. Removed tests for empty list, auth token env resolution, and MCP params. Only 3 lines of new assertions added. |
| 13 | S-05 | Add Phase Filtering to build_dynamic_tool_specs() | +9/-2 lines: added `test_default_is_builder_compatible` | **complete** | Phase filtering already existed. Diff adds a default-value test. |
| 14 | S-05 | Add Step-Level Tool Filtering and MCP Wiring to dynamicTools | +45/-2 lines: added MCP servers forward test and no-MCP-key test in transport tests | **complete** | Tests exercise the actual thread/start params, confirming MCP wiring works end-to-end. |
| 15 | S-05 | Write Unit Tests for Codex Server Filtering and MCP Wiring | +81/-17 lines: added recording transport, MCP wiring integration test; adjusted assertions | **complete** | Substantial: added a real transport mock and MCP wiring test that validates the mcpServers payload format. |
| 16 | S-06 | Research OpenHands SDK MCP Support | +15 lines: research findings documented in step-06.md | **complete** | Clear documentation: SDK version (1.3.0), mcp_config parameter confirmed, transport types enumerated, fallback policy decided. |
| 17 | S-06 | Implement Step-Level Tool Filtering in OpenHands Agent | +81/-22 lines: extracted `_build_openhands_tool_names()`; made `_register_sdk_tools` additive for builtin tools | **complete** | Tool name building extracted to testable helper. Default tools always included, step tools additive, unknown tools warned. |
| 18 | S-06 | Implement MCP Config Passthrough to OpenHands Agent | +98/-20 lines: extracted `_create_openhands_agent()`; fallback tests; auth token from env | **complete** | Correct: conversion function, TypeError fallback, env var auth token resolution. Tests cover all paths. |
| 19 | S-06 | Write Unit Tests for OpenHands Tool Filtering and MCP Wiring | **ZERO DIFF** (start == end commit) | **insufficient** | No code changed. Test file already had 201 lines of coverage. Auto-verify confirmed tests pass. |
| 20 | S-07 | Register All Tools in MCP Server | +102/-58 lines: refactored tool registration; all tools registered unconditionally; tests updated | **complete** | Correct: removed phase-based filtering at registration. Runtime validation preserved. Tests updated. |
| 21 | S-07 | Extend CallbackInstructions with mcp_servers Field | **ZERO DIFF** (start == end commit) | **complete** | Field already existed at line 140 of schemas/tasks.py. Nothing to change. Verifier confirmed via existing code inspection and test references. |
| 22 | S-07 | Populate mcp_servers in Prompt Response Endpoint | +98/-2 lines: minor refactor of local vars; +94 lines of integration tests for MCP in prompt response | **complete** | Integration tests exercise the full API: create run, start, get prompt, verify mcp_servers in callback. Both present and absent cases tested. |
| 23 | S-07 | Write Unit Tests for All-Tools Registration and MCP Info | -27 lines: removed `available_tools` field tests and `test_json_serialization_none_fields` | **partial** | Net negative: removed tests for available_tools in CallbackInstructions and None serialization test. Existing coverage for mcp_servers preserved. |

---

## Score Summary

| Score | Count | Tasks |
|-------|-------|-------|
| complete | 16 | #1, #2, #4, #5, #7, #8, #10, #11, #13, #14, #15, #16, #17, #18, #20, #21, #22 |
| partial | 2 | #3, #23 |
| insufficient | 5 | #6, #9, #12, #19 (zero diff or destructive) |

---

## False-Positive Analysis

**Gate false-positive rate: 7/23 tasks (30.4%)**

Of 23 tasks that passed the checklist gate with outcome="passed":

- **5 tasks scored "insufficient":**
  - 3 tasks (#6, #19) produced zero-diff because their work was already done by
    a preceding task. The auto-verify checks passed on pre-existing code. The gate
    correctly identified that requirements were met in the final state, but the
    task itself contributed nothing. These are **false positives by contribution**
    but not by outcome quality.
  - 2 tasks (#9, #12) were actively destructive: the agent removed substantial
    test coverage while the auto-verify/verifier only checked that a specific test
    file existed and passed. Task #9 deleted 130+ lines of tests for .mcp.json,
    auth token handling, and stdio transport. Task #12 gutted the Claude SDK test
    file. These are **genuine false positives** -- the gate passed despite the
    diff making the codebase worse.

- **2 tasks scored "partial":**
  - Task #3 undid the backward-compat test that task #2 just added (the agent
    refactored and removed it).
  - Task #23 removed `available_tools` field tests from CallbackInstructions.

### Root Causes

1. **Pre-existing implementation.** The run branched from a commit where S-01
   through S-08 were already complete. Agents found requirements already met and
   reported success with minimal or no changes. The auto-verify checks (which run
   commands like `pytest specific_file.py`) cannot distinguish "I just wrote this"
   from "this already passed."

2. **Auto-verify is existence-only.** Auto-verify items like
   `uv run pytest tests/unit/test_cli_tool_hints.py -v` check that tests pass but
   cannot detect test *removal*. A task could delete half the tests and still pass
   auto-verify as long as the remaining tests are green.

3. **Verifier rubric doesn't penalize regression.** The LLM verifier grades
   requirements as met/unmet but the rubric text says things like "A: Unit tests
   cover CLI tool hints and MCP info" -- this evaluates the *existence* of
   coverage, not whether coverage *decreased* during the attempt.

4. **No diff-quality gate.** The checklist gate has no mechanism to evaluate
   whether a diff is constructive vs destructive. It only checks that the final
   state meets requirements.

### Recommendations

1. **Add a diff-direction check.** Before marking a task as passed, compare the
   number of test assertions or test functions before vs after. Flag tasks where
   test count decreased.

2. **Record baseline metrics.** At attempt start, record `pytest --co -q | wc -l`
   (collected test count) for affected test files. At attempt end, re-measure.
   Fail if count dropped significantly.

3. **Skip-if-no-change.** When start_commit == end_commit, the task should be
   scored differently (e.g., "requirements pre-met, no action taken") rather
   than "passed."

4. **Guard against destructive refactoring.** The 2 worst false positives (#9,
   #12) were "unit test" tasks that interpreted "write tests" as "simplify the
   test file." Adding a `must_not_reduce_coverage` flag to test-writing tasks
   would prevent this.
