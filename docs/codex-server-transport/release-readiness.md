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

## Runtime Risk Items (Blocking for Production)

Static-analysis gates are **necessary but not sufficient** for production enablement.
The following runtime risk items remain open per `AGENTS.md`:

| ID | Condition | Variant | Status |
|----|-----------|---------|--------|
| R-01 | Runtime payload-drift tests pass | Both | Open |
| R-02 | Remote timeout/retry behaviour validated | Remote | Open |
| R-03 | REST and MCP callback parity confirmed | Both | Open |
| R-04 | Tool allow-list enforcement tested end-to-end | Both | Open |
| R-05 | Token leakage audit complete in error paths | Remote | Open |
| R-06 | Codex CLI version compatibility detection verified | Local | Open |

See `docs/codex-server/context/open-risks.md` for tracking.

Neither `codex_server` (local) nor `codex_server_remote` (remote) may be promoted
to a production-enabled default agent until all R-01 through R-06 items are resolved.
