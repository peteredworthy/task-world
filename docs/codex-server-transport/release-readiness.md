# Codex Server Transport — Release Readiness

## Static Analysis Gate

Date: 2026-02-20

All static analysis checks pass with zero violations.

### Results

| Check | Command | Result |
|-------|---------|--------|
| ruff lint | `uv run ruff check .` | **PASSED** — 0 violations |
| ruff format | `uv run ruff format --check .` | **PASSED** — 268 files already formatted |
| pyright | `uv run pyright` | **PASSED** — 0 errors, 0 warnings, 0 informations |
| pre-commit (all hooks) | `uv run pre-commit run --all-files` | **PASSED** — all 6 hooks passed |

### Pre-commit Hook Details

```
ruff (legacy alias)......................................................Passed
ruff format..............................................................Passed
Detect secrets...........................................................Passed
pyright..................................................................Passed
ui-lint..................................................................Passed
ui-typecheck.............................................................Passed
```

## Transport Implementation Status

Both transports are complete:

- **`agents/codex_server.py`** — Local managed-process variant (stdio/loopback)
- **`agents/codex_server_remote.py`** — Remote bearer-authenticated HTTPS variant

### Callback Parity Matrix (2×2)

| | REST callback | MCP callback |
|---|---|---|
| `CodexServerAgent` (local) | ✓ | ✓ |
| `CodexServerRemoteAgent` (remote) | ✓ | ✓ |

Both agents support REST and MCP callback channels through the shared helpers in
`agents/codex_server_common.py`, and both are exercised via `execute()`.

## Unit Test Coverage (2026-02-21)

1,149 unit tests passed — 0 failures, 0 errors (195 s run time).

Key test files:
- `tests/unit/test_codex_server_transport.py` — local managed-process variant
- `tests/unit/test_codex_server_remote_transport.py` — remote bearer-auth variant

### Risk Coverage by Unit Tests

| Risk | Test | Result |
|------|------|--------|
| R-04 (allow-list enforcement) | `test_execute_silently_drops_disallowed_tool_call_events` | Disallowed tool (`bash`) → failure response sent, execution continues |
| R-05 (token leakage) | `test_remote_execute_bearer_token_not_in_error_message_on_auth_failure` | Bearer token absent from `AgentExecutionError.args[0]` |

## E2E Verification (2026-02-21)

Demo-task routine confirmed working end-to-end using the `cli_subprocess` agent (claude CLI).

| Task | Verification | Result |
|------|-------------|--------|
| T-01: Create README | `auto_verify` shell check | Passed |
| T-02: Create Config File | `auto_verify` shell check | Passed |
| T-03: Review Documentation Quality | LLM grading rubric (`grades_evaluated`) | Passed |

Run duration: ~3 minutes (13:14:39 → 13:17:23 UTC).
Full lifecycle confirmed: `building → checklist_gate_evaluated(passed) → verifying → auto_verify_completed(passed) → grades_evaluated(passed) → completed`.

### codex_server E2E Verification (2026-02-21)

Full demo-task run confirmed working end-to-end using the `codex_server` agent with `gpt-5.2-codex` and ChatGPT subscription auth.

| Task | Verification | Result |
|------|-------------|--------|
| T-01: Create README | `auto_verify` shell check + LLM grading | Passed |
| T-02: Create Config File | `auto_verify` shell check + LLM grading | Passed |
| T-03: Review Documentation Quality | LLM grading rubric (`grades_evaluated`) | Passed |

Run `f1e9d7e7-5df4-462a-bb84-91fb08562141`, duration ~8.5 minutes (18:11 → 18:19 UTC).
Auth held as `chatgpt` throughout (no overwrite).

**Auth fixes applied (required for live operation):**
1. `CodexServerAgent.__init__` no longer reads `OPENAI_API_KEY` from `os.environ` — prevents implicit `account/login/start` calls that overwrote `~/.codex/auth.json`.
2. `_spawn_transport` creates an isolated `CODEX_HOME` temp directory, copies the user's `auth.json` into it, and sets `CODEX_HOME=<tmpdir>` in the subprocess env — any auth writes by the subprocess go to the throwaway dir, not `~/.codex/`.
3. The server must be started via the API endpoint (`POST /api/runs/{id}/start`), not the CLI `runs start` command, which bypasses executor spawning.

**Codex API notes:**
- `gpt-5.3-codex`: fails when `dynamicTools` is included (GitHub issue #11927 — experimentalApi routing issue). Use `gpt-5.2-codex` in `agent_config`.
- ChatGPT subscription tokens expire after ~1 hour; run `codex login --device-auth` to refresh before spawning runs.

## Runtime Risk Items (Blocking for Production)

Static-analysis gates are **necessary but not sufficient** for production enablement.
The following runtime risk items remain open per `AGENTS.md`:

| ID | Condition | Variant | Status |
|----|-----------|---------|--------|
| R-01 | Runtime payload-drift tests pass | Both | Open |
| R-02 | Remote timeout/retry behaviour validated | Remote | Open |
| R-03 | REST and MCP callback parity confirmed | Both | Open |
| R-04 | Tool allow-list enforcement tested end-to-end | Both | Unit-tested (2026-02-21) — integration test pending |
| R-05 | Token leakage audit complete in error paths | Remote | Unit-tested (2026-02-21) — integration test pending |
| R-06 | Codex CLI version compatibility detection verified | Local | Open |

See `docs/codex-server/context/open-risks.md` for tracking.

Neither `codex_server` (local) nor `codex_server_remote` (remote) may be promoted
to a production-enabled default agent until all R-01 through R-06 items are resolved.
