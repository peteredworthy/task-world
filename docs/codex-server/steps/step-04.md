# Step 04: Remote Codex Server Variant

Implement remote Codex app server execution using configuration-driven endpoint/auth behavior while reusing shared Codex execution abstractions.

## Intent Verification
**Original Intent**: `docs/codex-server/intent.md` requires a first-class `codex_server_remote` backend with bearer auth, callback parity, and explicit transport failure handling.

**Functionality to Produce**:
- `CodexServerRemoteAgent` with endpoint/auth/session config support
- Shared local/remote prompt/tool/event behavior through `codex_server_common`
- Retry/timeout/network/auth error normalization with redacted diagnostics

**Final Verification Criteria**:
- Remote execution can complete callback contract in builder and verifier phases
- Auth/network failures are explicit and safe for logs/UI

---

## Task 1: Create remote agent module and configuration adapter

**Description**: Introduce remote agent module with validated config parsing for endpoint, token source, and timeout options.

**Implementation Plan (Do These Steps)**
- [ ] Add `src/orchestrator/agents/codex_server_remote.py` implementing the agent protocol surface.
- [ ] Parse and validate remote settings from agent config: `base_url`, auth token source, model/session options, callback transport, timeout/retry.
- [ ] Enforce token-source precedence order in config contract: explicit `api_key` field -> `token_env_var` (default `CODEX_SERVER_API_KEY`) -> `OPENAI_API_KEY`; fail fast with explicit config error when unresolved.
- [ ] Reuse shared helper interfaces from `codex_server_common.py` for prompt/tool/event contracts.

```bash
uv run pyright src/orchestrator/agents/codex_server_remote.py
```

**References**
- `docs/codex-server/step-04-plan.md`
- `docs/codex-server/context/contract-matrix.md`
- `src/orchestrator/agents/codex_server_common.py`

**Constraints**
- [ ] Atomicity budget: change <=3 files and <=300 LOC.
- [ ] Do not duplicate common parser/normalizer logic from Step 03.

**Functionality (Expected Outcomes)**
- [ ] Remote agent can be constructed from valid config.
- [ ] Invalid/missing required remote config yields explicit validation errors.
- [ ] Token resolution behavior is deterministic and documented for local testing and production use.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run ruff check src/orchestrator/agents/codex_server_remote.py` passes.
- [ ] `uv run pytest tests/unit -k "codex_server_remote and config" -v` passes.

---

## Task 2: Implement authenticated remote execution and callback parity

**Description**: Wire remote transport with bearer auth and both callback channel paths.

**Implementation Plan (Do These Steps)**
- [ ] Implement remote execute path in `codex_server_remote.py` with `Authorization: Bearer <token>` injection.
- [ ] Ensure callback tool exposure is identical to local variant and limited to allow-list.
- [ ] Ensure both REST and MCP callback instructions are supported equally in remote sessions.
- [ ] Add an explicit 2x2 parity matrix to tests: builder+REST, builder+MCP, verifier+REST, verifier+MCP must all pass.
- [ ] Add/update unit tests for auth header generation and callback channel behavior.

```bash
uv run pytest tests/unit -k "codex_server_remote and callbacks" -v
```

**References**
- `docs/codex-server/clarifications.md`
- `docs/codex-server/step-04-plan.md`
- `src/orchestrator/agents/codex_server.py`

**Constraints**
- [ ] Atomicity budget: change <=5 files and <=450 LOC.
- [ ] Never log tokens or raw auth header values.

**Functionality (Expected Outcomes)**
- [ ] Remote agent sends authenticated requests with redacted telemetry.
- [ ] Callback parity behavior matches local agent semantics.
- [ ] Builder/verifier parity is proven for both callback transports, not inferred.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -k "codex_server_remote and auth" -v` passes.
- [ ] `uv run pytest tests/integration -k "codex_server_remote and (builder or verifier) and (rest or mcp)" -v` passes the 2x2 parity matrix.
- [ ] `uv run ruff check src/orchestrator/agents/codex_server_remote.py src/orchestrator/agents/codex_server_common.py` passes.

---

## Task 3: Add network resilience and transport error mapping

**Description**: Normalize timeout, unreachable endpoint, and contract mismatch failures to explicit orchestrator error types.

**Implementation Plan (Do These Steps)**
- [ ] Add bounded retry/timeout handling for remote calls.
- [ ] Map 401/403 to auth/config errors without token leakage.
- [ ] Map network timeout/unreachable conditions to `AgentTimeoutError`/`AgentExecutionError` with retry context.
- [ ] Add tests for 401/403, timeout, and schema mismatch failures.

```bash
uv run pytest tests/unit -k "codex_server_remote and timeout" -v
```

**References**
- `docs/codex-server/step-04-plan.md`
- `docs/codex-server/context/open-risks.md`
- `src/orchestrator/agents/errors.py`

**Constraints**
- [ ] Atomicity budget: change <=4 files and <=350 LOC.
- [ ] Keep failure output human-actionable and secret-safe.

**Functionality (Expected Outcomes)**
- [ ] Remote transport failures produce explicit, consistent orchestrator errors.
- [ ] Retry behavior is bounded and non-blocking.

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `uv run pytest tests/unit -k codex_server_remote -v` passes.
- [ ] `uv run pyright src/orchestrator/agents/codex_server_remote.py` passes.
