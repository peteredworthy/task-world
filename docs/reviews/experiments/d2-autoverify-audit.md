# D2: Auto-Verify Command Audit (Static Analysis)

**Routine:** `mcp-ops-c` (MCP Operations -- Per-Step Tool & External MCP Configuration)
**Date:** 2026-03-04
**Scope:** All auto_verify items across 9 steps, 26 tasks

---

## 1. Inventory of Auto-Verify Items

| Step | Task | Item ID | Command (abbreviated) | must |
|------|------|---------|-----------------------|------|
| S-01 | T-01 | `model_importable` | `python -c "from ...models import MCPServerConfig; c = MCPServerConfig(name='test', url='https://x.com'); print(c.model_dump())"` | true |
| S-01 | T-01 | `dual_transport_rejected` | `python -c "...MCPServerConfig(name='bad', url='x', command='y')" 2>/dev/null && exit 1 \|\| exit 0` | true |
| S-01 | T-02 | `backward_compat` | `pytest tests/ -x --timeout=30 -q` | true |
| S-01 | T-03 | `tests_pass` | `pytest tests/unit/test_mcp_server_config.py -v` | true |
| S-02 | T-01 | `context_fields` | `python -c "from ...types import ExecutionContext; c = ExecutionContext(...); print(c.step_id, c.available_tools, c.mcp_servers)"` | true |
| S-02 | T-02 | `tests_pass` | `pytest tests/ -x --timeout=30 -q` | true |
| S-02 | T-03 | `tests_pass` | `pytest tests/unit/test_execution_context_extension.py -v` | true |
| S-03 | T-03 | `tests_pass` | `pytest tests/unit/test_cli_tool_hints.py -v` | true |
| S-04 | T-03 | `tests_pass` | `pytest tests/unit/test_claude_sdk_tool_filtering.py -v` | true |
| S-05 | T-03 | `tests_pass` | `pytest tests/unit/test_codex_server_tool_filtering.py -v` | true |
| S-06 | T-04 | `tests_pass` | `pytest tests/unit/test_openhands_tool_filtering.py -v` | true |
| S-07 | T-04 | `tests_pass` | `pytest tests/unit/test_mcp_server_all_tools.py -v` | true |
| S-08 | T-01 | `integration_tests_pass` | `pytest tests/integration/test_step_tool_control.py -v` | true |
| S-08 | T-01 | `full_suite_pass` | `pytest tests/ -x --timeout=30 -q` | true |
| S-09 | T-01 | `backend_tests` | `pytest tests/ --timeout=60 -q` | true |
| S-09 | T-02 | `precommit_pass` | `pre-commit run --all-files` | true |

**Total: 16 auto_verify items across 26 tasks (10 tasks have no auto_verify)**

---

## 2. Per-Command Analysis

### S-01/T-01: `model_importable`

```
uv run python -c "from orchestrator.config.models import MCPServerConfig; c = MCPServerConfig(name='test', url='https://x.com'); print(c.model_dump())"
```

**(a) Exit code reliability:** Reliable for what it tests. Python will exit non-zero if the import fails or if the constructor raises a ValidationError.

**(b) False-pass scenario:** The model could exist with all the right field names but have no `model_validator` -- this check would still pass because it only tests the happy path (url-only). A model with wrong field types (e.g., `timeout_seconds: str` instead of `int`) would also pass since no timeout value is explicitly tested. The `auth_token_env` field is not checked at all.

**(c) Behavior vs existence:** Primarily tests existence and importability. It verifies one valid construction path but does not test validation behavior, default values, or rejected inputs.

**(d) Shell patterns masking exit codes:** None. Single Python command with direct exit code propagation.

**(e) Rating: MODERATE.** Catches import errors and total construction failures, but misses validation logic, field type correctness, and most of R3 (auth_token_env).

---

### S-01/T-01: `dual_transport_rejected`

```
uv run python -c "from orchestrator.config.models import MCPServerConfig; MCPServerConfig(name='bad', url='x', command='y')" 2>/dev/null && exit 1 || exit 0
```

**(a) Exit code reliability:** The `&& exit 1 || exit 0` pattern inverts the exit code, so this passes when the Python command fails (raises ValidationError). This is correct for a negative test.

**(b) False-pass scenario:** If the Python command fails for ANY reason (import error, syntax error, unrelated exception), this check still passes. The `2>/dev/null` suppresses stderr so the actual error is invisible. A completely broken module would cause this check to pass. Also, this only tests the "both set" case -- the "neither set" case (`MCPServerConfig(name='bad')`) is not tested.

**(c) Behavior vs existence:** Tests one specific validation behavior (both transports rejected). Does not test the complementary "neither set" case.

**(d) Shell patterns masking exit codes:** YES. The `2>/dev/null && exit 1 || exit 0` chain masks all errors. Any failure (not just ValidationError) maps to success. This is a significant weakness.

**(e) Rating: WEAK.** The error suppression and inverted exit code pattern means any failure is treated as success. A broken import, a typo in the command, or an unrelated crash all register as "dual transport correctly rejected."

---

### S-01/T-02: `backward_compat`

```
uv run pytest tests/ -x --timeout=30 -q
```

**(a) Exit code reliability:** Reliable. pytest exits non-zero if any test fails.

**(b) False-pass scenario:** This runs the ENTIRE existing test suite, not targeted tests for the new fields. It verifies no regressions but does not verify the new fields exist or have correct types. An agent that makes no changes at all would pass this check. An agent that adds the fields but with wrong types (e.g., `available_tools: str` instead of `list[str]`) would also pass if no existing test exercises the new fields.

**(c) Behavior vs existence:** Tests behavior of existing code. Does not test the new functionality at all -- only that existing functionality is unbroken.

**(d) Shell patterns masking exit codes:** None. Direct pytest invocation.

**(e) Rating: MODERATE.** Strong regression guard but provides zero positive verification that the required fields were actually added. This is a necessary-but-not-sufficient check.

---

### S-01/T-03: `tests_pass`

```
uv run pytest tests/unit/test_mcp_server_config.py -v
```

**(a) Exit code reliability:** Reliable. pytest exits non-zero on any failure.

**(b) False-pass scenario:** This check depends on the AGENT writing the test file. If the agent writes trivially passing tests (e.g., `assert True`) or tests that don't actually exercise the validation logic, this check passes. The auto_verify does not inspect test quality -- it only checks that the file exists and all tests in it pass.

**(c) Behavior vs existence:** Delegates behavior testing to the test file itself. The auto_verify only checks that tests pass, not what they test.

**(d) Shell patterns masking exit codes:** None. Direct pytest invocation.

**(e) Rating: MODERATE.** The quality of this check is entirely dependent on the quality of the tests the agent writes. A circular dependency: the task asks the agent to write tests, and the auto_verify checks that the agent's tests pass. However, the task_context specifies 10 exact test scenarios, which provides good guidance. If the agent follows instructions, this is strong; if it writes weak tests, the check provides a false sense of security.

---

### S-02/T-01: `context_fields`

```
uv run python -c "from orchestrator.agents.types import ExecutionContext; c = ExecutionContext(run_id='r', task_id='t', working_dir='/tmp', prompt='p', requirements=[]); print(c.step_id, c.available_tools, c.mcp_servers)"
```

**(a) Exit code reliability:** Reliable for import and construction. Python exits non-zero if import fails or fields don't exist.

**(b) False-pass scenario:** This constructs an ExecutionContext WITHOUT the new fields and prints them. It verifies the fields default to something printable (likely None). However, it does not verify the fields can be SET to non-None values. An implementation that adds `step_id` as a computed property always returning None would pass. Field type annotations are not validated (e.g., `step_id: int = None` would pass).

**(c) Behavior vs existence:** Tests existence and default values only. Does not test that the fields accept correct types or that MCPServerConfig import is wired up.

**(d) Shell patterns masking exit codes:** None.

**(e) Rating: MODERATE.** Verifies fields exist and are accessible with defaults, but does not test setting values or type correctness. Missing MCPServerConfig import validation.

---

### S-02/T-02: `tests_pass`

```
uv run pytest tests/ -x --timeout=30 -q
```

**(a) Exit code reliability:** Reliable.

**(b) False-pass scenario:** Same issue as S-01/T-02. Full suite regression check only. An agent that changes nothing passes. An agent that wires the executor incorrectly but doesn't break existing tests also passes. No test specifically validates that the executor populates the new context fields.

**(c) Behavior vs existence:** Regression guard only.

**(d) Shell patterns masking exit codes:** None.

**(e) Rating: MODERATE.** Necessary regression guard. Does not verify the executor actually populates the new fields.

---

### S-02/T-03: `tests_pass`

```
uv run pytest tests/unit/test_execution_context_extension.py -v
```

**(a)-(e):** Same analysis as S-01/T-03. Quality depends on agent-written tests. Task context specifies 4 test scenarios. Circular dependency between task and verification.

**(e) Rating: MODERATE.**

---

### S-03/T-03: `tests_pass`

```
uv run pytest tests/unit/test_cli_tool_hints.py -v
```

**(a)-(e):** Same pattern. Agent writes tests, auto_verify checks they pass. Task specifies 5 test scenarios including auth token non-leakage. If agent follows instructions, strong. If not, weak.

**(e) Rating: MODERATE.**

---

### S-04/T-03: `tests_pass`

```
uv run pytest tests/unit/test_claude_sdk_tool_filtering.py -v
```

**(a)-(e):** Same pattern. Task specifies 8 test scenarios. Same circular dependency.

**(e) Rating: MODERATE.**

---

### S-05/T-03: `tests_pass`

```
uv run pytest tests/unit/test_codex_server_tool_filtering.py -v
```

**(a)-(e):** Same pattern. Task specifies 5 test scenarios.

**(e) Rating: MODERATE.**

---

### S-06/T-04: `tests_pass`

```
uv run pytest tests/unit/test_openhands_tool_filtering.py -v
```

**(a)-(e):** Same pattern. Task specifies 4 test scenarios.

**(e) Rating: MODERATE.**

---

### S-07/T-04: `tests_pass`

```
uv run pytest tests/unit/test_mcp_server_all_tools.py -v
```

**(a)-(e):** Same pattern. Task specifies 3 test scenarios.

**(e) Rating: MODERATE.**

---

### S-08/T-01: `integration_tests_pass`

```
uv run pytest tests/integration/test_step_tool_control.py -v
```

**(a)-(e):** Same "agent writes own tests" pattern, but for integration tests. Task specifies 8 test scenarios covering the full data flow. Same circular dependency, but the integration scope makes agent-written tests more meaningful -- they exercise real wiring, not mocks.

**(e) Rating: MODERATE.** Slightly stronger than unit test versions because integration tests exercise real code paths.

---

### S-08/T-01: `full_suite_pass`

```
uv run pytest tests/ -x --timeout=30 -q
```

**(a)-(e):** Full regression guard. Same analysis as S-01/T-02 and S-02/T-02.

**(e) Rating: MODERATE.** Regression guard only.

---

### S-09/T-01: `backend_tests`

```
uv run pytest tests/ --timeout=60 -q
```

**(a) Exit code reliability:** Reliable.

**(b) False-pass scenario:** Full suite pass. This is the final validation gate. However, it does not verify test COUNT meets baseline (the requirement says "meets or exceeds baseline"). An agent that deletes tests could reduce count and still pass.

**(c) Behavior vs existence:** Runs all tests but doesn't validate test count.

**(d) Shell patterns masking exit codes:** None.

**(e) Rating: MODERATE.** Final regression check but does not enforce test count baseline (R2).

---

### S-09/T-02: `precommit_pass`

```
uv run pre-commit run --all-files
```

**(a) Exit code reliability:** Reliable. Pre-commit exits non-zero on any hook failure.

**(b) False-pass scenario:** Depends entirely on what hooks are configured. If pre-commit config only checks formatting, it won't catch logical errors. However, this is appropriate for what it claims to test (code quality).

**(c) Behavior vs existence:** Tests code quality (formatting, linting, type checking). Does not test functional behavior.

**(d) Shell patterns masking exit codes:** None.

**(e) Rating: STRONG.** For its purpose (code quality verification), this is reliable and hard to game.

---

## 3. Coverage Matrix

The matrix below maps each task's requirements to auto_verify coverage. A requirement is "covered" if an auto_verify command would fail when the requirement is not met.

### Legend
- **COVERED**: An auto_verify directly tests this requirement
- **PARTIAL**: Auto_verify tests related behavior but could miss failures
- **INDIRECT**: Only covered by full suite regression or agent-written tests
- **UNCOVERED**: No auto_verify addresses this requirement

### S-01: Schema & Context Foundation

| Task | Req | Description | Auto-Verify Coverage | Notes |
|------|-----|-------------|---------------------|-------|
| T-01 | R1 | MCPServerConfig model with dual transport validation | PARTIAL (`model_importable`) | Only tests URL path; no STDIO construction tested |
| T-01 | R2 | Transport validator rejects both-set and neither-set | PARTIAL (`dual_transport_rejected`) | Only tests both-set; neither-set UNCOVERED; error masking in shell pattern |
| T-01 | R3 | auth_token_env stores env var name, not inline token | UNCOVERED | No auto_verify tests auth_token_env field at all |
| T-02 | R1 | StepConfig has available_tools and mcp_servers fields | UNCOVERED | `backward_compat` only checks no regressions, not that fields exist |
| T-02 | R2 | Existing routines parse unchanged | COVERED (`backward_compat`) | Full suite regression guard |
| T-03 | R1 | Unit tests cover MCPServerConfig and StepConfig | INDIRECT (`tests_pass`) | Circular: agent writes tests, auto_verify runs them |

### S-02: ExecutionContext Extension

| Task | Req | Description | Auto-Verify Coverage | Notes |
|------|-----|-------------|---------------------|-------|
| T-01 | R1 | ExecutionContext has step_id, available_tools, mcp_servers | PARTIAL (`context_fields`) | Tests defaults only, not setting values |
| T-01 | R2 | New fields default to None | COVERED (`context_fields`) | Directly tested |
| T-02 | R1 | Executor populates fields from step config | UNCOVERED | Full suite doesn't target this |
| T-02 | R2 | Both builder and verifier paths updated | UNCOVERED | No auto_verify tests verifier path |
| T-03 | R1 | Unit tests cover new fields | INDIRECT (`tests_pass`) | Circular dependency |

### S-03: CLI Agent Tool Hints + MCP Info

| Task | Req | Description | Auto-Verify Coverage | Notes |
|------|-----|-------------|---------------------|-------|
| T-01 | R1 | CLI prompt includes tool names when configured | UNCOVERED | No auto_verify on this task |
| T-01 | R2 | Prompt unchanged when available_tools is None | UNCOVERED | No auto_verify on this task |
| T-02 | R1 | MCP server info in prompt | UNCOVERED | No auto_verify on this task |
| T-02 | R2 | .mcp.json written with correct format | UNCOVERED | No auto_verify on this task |
| T-02 | R3 | Auth tokens never in prompt text | UNCOVERED | No auto_verify on this task |
| T-03 | R1 | Unit tests cover CLI tool hints and MCP info | INDIRECT (`tests_pass`) | Circular dependency |

### S-04: Claude SDK Tool Filtering + MCP Wiring

| Task | Req | Description | Auto-Verify Coverage | Notes |
|------|-----|-------------|---------------------|-------|
| T-01 | R1 | Step-level tools additive to phase tools | UNCOVERED | No auto_verify on this task |
| T-01 | R2 | Phase tools always included | UNCOVERED | No auto_verify on this task |
| T-01 | R3 | Unknown tool names produce warning | UNCOVERED | No auto_verify on this task |
| T-02 | R1 | MCP Connector beta API with correct headers | UNCOVERED | No auto_verify on this task |
| T-02 | R2 | STDIO-transport MCPs filtered with warning | UNCOVERED | No auto_verify on this task |
| T-02 | R3 | Standard API when no MCP servers | UNCOVERED | No auto_verify on this task |
| T-03 | R1 | Unit tests cover filtering and MCP params | INDIRECT (`tests_pass`) | Circular dependency |

### S-05: Codex Server Filtering + MCP Wiring

| Task | Req | Description | Auto-Verify Coverage | Notes |
|------|-----|-------------|---------------------|-------|
| T-01 | R1 | Builders don't see grade tool | UNCOVERED | No auto_verify on this task |
| T-01 | R2 | Verifiers get grade tool | UNCOVERED | No auto_verify on this task |
| T-01 | R3 | Default is_verifier=False backward compat | UNCOVERED | No auto_verify on this task |
| T-02 | R1 | Unknown step-level tools logged with warning | UNCOVERED | No auto_verify on this task |
| T-02 | R2 | MCP server entries in thread params | UNCOVERED | No auto_verify on this task |
| T-02 | R3 | No mcpServers key when None | UNCOVERED | No auto_verify on this task |
| T-03 | R1 | Unit tests cover phase filtering and MCP | INDIRECT (`tests_pass`) | Circular dependency |

### S-06: OpenHands Tool Filtering + MCP Wiring

| Task | Req | Description | Auto-Verify Coverage | Notes |
|------|-----|-------------|---------------------|-------|
| T-01 | R1 | Research findings documented | UNCOVERED | No auto_verify; research task |
| T-01 | R2 | Wiring approach decided | UNCOVERED | No auto_verify; research task |
| T-02 | R1 | Step-level tools additive to defaults | UNCOVERED | No auto_verify on this task |
| T-02 | R2 | Default tools always included | UNCOVERED | No auto_verify on this task |
| T-02 | R3 | Unknown tool names produce warning | UNCOVERED | No auto_verify on this task |
| T-03 | R1 | MCPServerConfig converted to OpenHands format | UNCOVERED | No auto_verify on this task |
| T-03 | R2 | Graceful fallback when mcp_config unsupported | UNCOVERED | No auto_verify on this task |
| T-03 | R3 | Auth tokens from env vars, never hardcoded | UNCOVERED | No auto_verify on this task |
| T-04 | R1 | Unit tests cover filtering and MCP conversion | INDIRECT (`tests_pass`) | Circular dependency |

### S-07: User-Managed MCP All-Tools + MCP Info

| Task | Req | Description | Auto-Verify Coverage | Notes |
|------|-----|-------------|---------------------|-------|
| T-01 | R1 | All tools registered at startup | UNCOVERED | No auto_verify on this task |
| T-01 | R2 | Runtime validation rejects phase-inappropriate calls | UNCOVERED | No auto_verify on this task |
| T-02 | R1 | CallbackInstructions has mcp_servers field | UNCOVERED | No auto_verify on this task |
| T-02 | R2 | JSON serialization includes mcp_servers | UNCOVERED | No auto_verify on this task |
| T-03 | R1 | Prompt response includes MCP server list | UNCOVERED | No auto_verify on this task |
| T-03 | R2 | Backward compatible when no mcp_servers | UNCOVERED | No auto_verify on this task |
| T-04 | R1 | Unit tests cover all-tools and MCP info | INDIRECT (`tests_pass`) | Circular dependency |

### S-08: Integration Tests + Examples

| Task | Req | Description | Auto-Verify Coverage | Notes |
|------|-----|-------------|---------------------|-------|
| T-01 | R1 | Integration tests cover tools, MCPs, compat | INDIRECT (`integration_tests_pass`) | Circular dependency |
| T-01 | R2 | All existing test suites pass | COVERED (`full_suite_pass`) | Direct regression guard |
| T-02 | R1 | Example routine demonstrates features | UNCOVERED | No auto_verify on this task |
| T-02 | R2 | Example routine parses without errors | UNCOVERED | No auto_verify on this task |

### S-09: Final Validation

| Task | Req | Description | Auto-Verify Coverage | Notes |
|------|-----|-------------|---------------------|-------|
| T-01 | R1 | All backend tests pass | COVERED (`backend_tests`) | Direct |
| T-01 | R2 | Test count meets/exceeds baseline | UNCOVERED | pytest -q doesn't enforce count |
| T-02 | R1 | Pre-commit checks pass cleanly | COVERED (`precommit_pass`) | Direct |
| T-03 | R1 | No unresolved TODOs in new code | UNCOVERED | No auto_verify on this task |
| T-03 | R2 | Auth tokens handled securely | UNCOVERED | No auto_verify on this task |
| T-03 | R3 | All Definition of Complete items addressed | UNCOVERED | No auto_verify on this task |

---

## 4. Summary Statistics

### Coverage breakdown (63 total requirements across 26 tasks)

| Coverage Level | Count | Percentage |
|---------------|-------|------------|
| COVERED | 5 | 7.9% |
| PARTIAL | 3 | 4.8% |
| INDIRECT (agent-written tests) | 8 | 12.7% |
| UNCOVERED | 47 | 74.6% |

### Rating distribution (16 auto_verify items)

| Rating | Count | Percentage |
|--------|-------|------------|
| STRONG | 1 | 6.3% |
| MODERATE | 14 | 87.5% |
| WEAK | 1 | 6.3% |

### Tasks with vs without auto_verify

| Category | Count | Percentage |
|----------|-------|------------|
| Tasks WITH auto_verify | 16 | 61.5% |
| Tasks WITHOUT auto_verify | 10 | 38.5% |

---

## 5. Key Findings

### Finding 1: The "Write Tests" Circular Dependency Pattern

Eight of the 16 auto_verify items follow the same pattern: a task instructs the agent to write unit tests, then auto_verify checks that the agent's tests pass. This creates a circular dependency where the verification relies on the quality of the thing being verified. An agent could write `def test_placeholder(): assert True` and pass auto_verify. The routine mitigates this somewhat by specifying exact test scenarios in `task_context`, but auto_verify cannot enforce that the agent actually implemented those scenarios.

**Impact:** These checks prevent crashes and import errors but do not guarantee test thoroughness.

### Finding 2: Implementation Tasks Lack Direct Auto-Verify

Steps S-03 through S-07 contain 15 implementation tasks (T-01 and T-02 in each step) with zero auto_verify items. These are the core feature work: CLI prompt generation, Claude SDK tool filtering, MCP Connector wiring, Codex Server phase filtering, OpenHands integration, and MCP server registration. All of these rely entirely on LLM verifier rubrics for quality assessment.

**Impact:** The most critical behavioral requirements (e.g., "auth tokens never appear in prompt text," "phase tools always included," "STDIO-transport MCPs filtered with warning") have no automated verification at all.

### Finding 3: Shell Pattern Weakness in `dual_transport_rejected`

The `2>/dev/null && exit 1 || exit 0` pattern in the `dual_transport_rejected` check suppresses all error output and treats ANY Python failure as a successful validation rejection. If the import itself fails, or the command has a typo, the check still passes. This is the only WEAK-rated check in the routine.

**Recommended fix:** Replace with a Python script that catches `ValidationError` specifically:
```
uv run python -c "
from pydantic import ValidationError
from orchestrator.config.models import MCPServerConfig
try:
    MCPServerConfig(name='bad', url='x', command='y')
    exit(1)  # should have raised
except ValidationError:
    exit(0)  # expected
"
```

### Finding 4: No Negative Testing Beyond Dual Transport

Only one auto_verify item tests a negative case (something that SHOULD fail). The entire routine lacks auto_verify for:
- Neither-transport-set rejection
- Phase-inappropriate tool call rejection
- Unknown tool name warning (not error) behavior
- Auth token leakage detection

### Finding 5: Full Suite Regression Used as Proxy for Feature Verification

Three auto_verify items run `pytest tests/ -x --timeout=30 -q` as their only check (S-01/T-02, S-02/T-02, S-08/T-01 `full_suite_pass`). While valuable as regression guards, these provide zero positive evidence that the required feature was implemented. An agent that makes no changes passes these checks.

### Finding 6: Auth Token Security Has Zero Automated Verification

Requirement R3 appears in S-01/T-01, S-03/T-02, S-06/T-03, and S-09/T-03 -- all emphasizing that auth tokens must never appear inline. None of these have auto_verify coverage. A grep-based check (e.g., searching for token values in generated files) would add meaningful security verification.

---

## 6. Recommendations

1. **Add targeted auto_verify to implementation tasks (S-03 through S-07).** Even simple import + construct checks would catch "agent did nothing" failures. For example, S-05/T-01 could verify `build_dynamic_tool_specs(is_verifier=False)` does not contain "grade" in output.

2. **Replace the `dual_transport_rejected` shell pattern** with a Python script that catches `ValidationError` specifically, and add a second check for the neither-set case.

3. **Add auto_verify for auth token security.** A grep-based check in generated files (`.mcp.json`, prompt output) for literal token values would be valuable.

4. **Add test count verification** to S-09/T-01. The command `pytest tests/ -q` outputs a count line; parsing it to verify minimum count would enforce the baseline requirement.

5. **Add auto_verify to example routine parsing** (S-08/T-02). A simple `uv run python -c "from orchestrator.config.models import RoutineConfig; RoutineConfig.from_yaml('examples/routines/...')"` would verify parsability.

6. **Consider pre-written "golden" tests** for critical requirements instead of relying on agent-written tests. A separate test file maintained alongside the routine would break the circular dependency.
