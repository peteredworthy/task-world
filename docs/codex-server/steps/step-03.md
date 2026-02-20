# Step 03: Base Codex Server Agent Implementation

Implement managed local Codex server execution with callback/tool semantics, normalization, and lifecycle behavior consistent with existing managed agents.

## Intent Verification
**Original Intent**: `docs/codex-server/intent.md` requires builder/verifier phase support, callback tools, action logging, and metrics compatibility.

**Functionality to Produce**:
- `CodexServerAgent` implementing `execute`, `cancel`, and `info`
- Shared helper layer for prompt/tool/event normalization
- Strict v1 callback tool allow-list enforcement

**Final Verification Criteria**:
- Local managed execution can complete callback-driven builder/verifier flows
- Failure/cancellation paths map to explicit orchestrator errors

---

## Task 1: Scaffold Codex local agent and shared common module

**Description**: Create minimal compile-safe modules before adding runtime behavior.

**Implementation Plan (Do These Steps)**
- [ ] Add `src/orchestrator/agents/codex_server.py` with protocol-compliant class skeleton.
- [ ] Add `src/orchestrator/agents/codex_server_common.py` with placeholder interfaces for prompt assembly, tool registration, output normalization.
- [ ] Export/register modules where existing package import conventions require.

```bash
uv run pyright src/orchestrator/agents/codex_server.py src/orchestrator/agents/codex_server_common.py
```

**References**
- `docs/codex-server/step-03-plan.md`
- `src/orchestrator/agents/interface.py`
- `src/orchestrator/agents/types.py`

**Constraints**
- [ ] Atomicity budget: change <=4 files and <=250 LOC.
- [ ] Do not touch executor dispatch in this task.

**Functionality (Expected Outcomes)**
- [ ] New modules import cleanly and satisfy agent protocol surface.
- [ ] No runtime wiring yet, only safe scaffold.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run ruff check src/orchestrator/agents/codex_server.py src/orchestrator/agents/codex_server_common.py` passes.
- [ ] `uv run pyright` passes for changed files.

---

## Task 2: Implement execute path with prompt and callback-tool bridging

**Description**: Wire builder/verifier prompts and restricted callback tools for local Codex sessions.

**Implementation Plan (Do These Steps)**
- [ ] Implement phase-aware prompt assembly in `codex_server_common.py` using `ExecutionContext`.
- [ ] Register only allow-listed tools: `update_checklist`, `grade`, `submit`, `request_clarification`.
- [ ] Implement `CodexServerAgent.execute` to run a session, stream/process outputs, and capture metrics/action events.
- [ ] Map callback channel choice (REST/MCP) via existing execution context contract.
- [ ] Add/update a negative-path test that attempts a non-allow-listed tool call and asserts rejection plus policy-violation logging.

```bash
uv run pytest tests/unit -k "codex_server and execute" -v
```

**References**
- `docs/codex-server/context/contract-matrix.md`
- `docs/codex-server/step-03-plan.md`
- `src/orchestrator/agents/openhands_common.py`
- `src/orchestrator/mcp/tools.py`

**Constraints**
- [ ] Atomicity budget: change <=5 files and <=450 LOC.
- [ ] Do not add non-callback experimental tools.

**Functionality (Expected Outcomes)**
- [ ] Execute path emits normalized outputs consumable by existing UI/persistence.
- [ ] Unsupported tool calls are blocked and covered by an explicit failing test.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -k "codex_server and callbacks" -v` passes.
- [ ] `uv run pytest tests/unit -k "codex_server and disallowed tool" -v` passes.
- [ ] `uv run ruff check src/orchestrator/agents/codex_server.py src/orchestrator/agents/codex_server_common.py` passes.

---

## Task 3: Implement cancellation and explicit error mapping

**Description**: Ensure local agent cancellation and error behavior match existing managed agent expectations.

**Implementation Plan (Do These Steps)**
- [ ] Implement `cancel` handling in `codex_server.py` with idempotent semantics.
- [ ] Map startup failures, callback failures, and parser failures to `AgentNotAvailableError`, `AgentExecutionError`, or `AgentTimeoutError` as appropriate.
- [ ] Add/update unit coverage for success, failure, and cancel scenarios.

```bash
uv run pytest tests/unit -k "codex_server and cancel" -v
```

**References**
- `docs/codex-server/step-03-plan.md`
- `src/orchestrator/agents/errors.py`

**Constraints**
- [ ] Atomicity budget: change <=4 files and <=300 LOC.
- [ ] Keep error messages actionable and secret-safe.

**Functionality (Expected Outcomes)**
- [ ] Cancellation terminates local sessions cleanly.
- [ ] Failures are surfaced with explicit orchestrator error types.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -k "codex_server" -v` passes all new tests.
- [ ] `uv run pyright src/orchestrator/agents/codex_server.py` passes.
