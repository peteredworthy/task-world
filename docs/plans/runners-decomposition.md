# Runners Module Decomposition Plan

## Goal

Decompose the monolithic `runners/` module (9,899 LOC, 26 files) into well-bounded
sub-packages where each agent type is self-contained and auto-discovered.

## Principles

1. Adding/removing an agent = adding/removing a sub-package under `runners/agents/`
2. No central type-switch or hardcoded agent list (auto-discovery via `pkgutil`)
3. Executor becomes a thin orchestration shell delegating to extracted classes
4. No behavior changes — pure structural refactor, all existing tests must pass

## Target Structure

```
runners/
  __init__.py
  interface.py            # AgentRunner protocol (unchanged)
  types.py                # ExecutionContext, ExecutionResult, callbacks (unchanged)
  errors.py               # Agent errors (unchanged)
  agent_factory.py        # NEW: registry + create() dispatch
  agent_detector.py       # NEW: registry-based detection (replaces detector.py)
  executor.py             # SLIMMED: delegates to extracted classes
  monitor.py              # (unchanged — operational utility)
  nudger.py               # (unchanged — operational utility)
  repetition_detector.py  # (unchanged — operational utility)
  quota.py                # (unchanged — operational utility)
  action_log.py           # (unchanged — shared types)
  profile_resolution.py   # (unchanged — shared utility)

  execution/              # NEW: extracted from executor.py
    __init__.py
    attempt_store.py      # Persistence helpers (store output/prompt/metrics/metadata)
    event_broadcaster.py  # Event emission (emit/error/health_check)
    phase_handler.py      # Unified build/verify/recover flow
    run_loop.py           # The while-true task loop + error handling

  agents/                 # NEW: auto-discovered agent packages
    __init__.py           # discover() via pkgutil.iter_modules

    claude_cli/
      __init__.py         # register(CLI_SUBPROCESS, create)
      agent.py            # CLIAgent (moved from runners/cli.py)
      parser.py           # ClaudeStreamParser (moved from runners/parsers/claude_parser.py)
      config.py           # CONFIG_SCHEMA + detect() (extracted from detector.py)
      factory.py          # create(agent_config, ...) -> CLIAgent

    claude_sdk/
      __init__.py         # register(CLAUDE_SDK, create)
      agent.py            # ClaudeSDKAgent (moved from runners/claude_sdk.py)
      config.py           # CONFIG_SCHEMA + detect() (extracted from detector.py)
      factory.py          # create(agent_config, ...) -> ClaudeSDKAgent

    codex/
      __init__.py         # register(CODEX_SERVER, create)
      agent.py            # CodexServerAgent (moved from runners/codex_server.py)
      common.py           # Shared Codex helpers (moved from runners/codex_server_common.py)
      parser.py           # CodexStreamParser (moved from runners/parsers/codex_parser.py)
      config.py           # CONFIG_SCHEMA + detect() + prepare_codex_config()
      factory.py          # create() — calls prepare_config() internally

    openhands/
      __init__.py         # register(OPENHANDS_LOCAL + OPENHANDS_DOCKER, ...)
      agent.py            # OpenHandsAgent (moved from runners/openhands.py)
      docker_agent.py     # DockerOpenHandsAgent (moved from runners/openhands_docker.py)
      common.py           # Shared OH helpers (moved from runners/openhands_common.py)
      parser.py           # OpenHandsStreamParser (moved from runners/parsers/openhands_parser.py)
      config.py           # CONFIG_SCHEMA (local + docker) + detect()
      factory.py          # create_local(), create_docker()

    user_managed/
      __init__.py         # register(USER_MANAGED, create)
      agent.py            # UserManagedAgent (moved from runners/user_managed.py)
      config.py           # CONFIG_SCHEMA + detect()
      factory.py          # create()

    mock/
      __init__.py         # NOT auto-registered (test-only)
      agent.py            # MockAgent (moved from runners/mock.py)
```

## Phases

### Phase 1: Create infrastructure (no moves yet)

1. Create `runners/agent_factory.py` with `register()`, `create()`, `get_registry()`
2. Create `runners/agents/__init__.py` with `discover()` using `pkgutil.iter_modules`
3. Create `runners/agent_detector.py` that iterates registry for `detect()` + `config_schema()`

### Phase 2: Extract executor internals

1. Create `runners/execution/attempt_store.py` — move `_store_attempt_output`,
   `_store_attempt_prompt`, `_store_attempt_metrics`, `_persist_agent_metadata`,
   `_merge_action_logs` from executor
2. Create `runners/execution/event_broadcaster.py` — move `_emit_log_event`,
   `_emit_error_event`, `_emit_health_check_event` from executor
3. Create `runners/execution/phase_handler.py` — unify `_execute_task`,
   `_handle_verification`, `_handle_recovery` into a single parameterized flow
4. Slim `executor.py` — it keeps `__init__`, `start_run_with_agent`, `_run_agent_loop`,
   `_find_next_task`, `spawn_for_run`, `cancel_run`, `is_running` but delegates
   to the extracted classes

### Phase 3: Move agents into sub-packages

For each agent (claude_cli, claude_sdk, codex, openhands, user_managed, mock):

1. Create the sub-package directory
2. Move agent implementation file(s)
3. Extract config schema + detect() from detector.py into config.py
4. Extract factory logic from executor._create_agent into factory.py
5. Write __init__.py with register() call
6. Add backward-compat re-exports in old locations

### Phase 4: Wire up auto-discovery

1. Replace executor._create_agent type-switch with `agent_factory.create()`
2. Replace detector.py internals with `agent_detector.py` registry iteration
3. Update `api/app.py` startup to call `runners.agents.discover()`
4. Update all imports across codebase (tests, api, cli, etc.)

### Phase 5: Cleanup

1. Remove old files (runners/cli.py, runners/claude_sdk.py, etc.) once all
   imports updated
2. Remove runners/parsers/ directory (parsers now live in agent packages)
3. Remove old detector.py (replaced by agent_detector.py)
4. Verify no remaining references to moved files
5. Run full test suite, fix any breakage

## Backward Compatibility

During migration, old import paths will have re-exports:
```python
# runners/cli.py (temporary shim)
from orchestrator.runners.agents.claude_cli.agent import CLIAgent  # noqa: F401
```

These shims are removed in Phase 5 after all imports are updated.

## Risk Mitigation

- Each phase is independently testable — tests should pass after each phase
- No behavior changes, only structural moves
- Factory registry is additive — old code paths work until switched over
- Shims prevent import breakage during transition

## Files That Import From runners/ (must be updated)

Key consumers (from AST analysis):
- `runners/executor.py` — imports all agent types + parsers
- `runners/detector.py` — imports agent types for detection
- `api/app.py` — imports executor
- `api/deps.py` — imports executor
- `api/routers/runners.py` — imports detector
- `cli/agents.py` — imports detector
- `state/models.py` — imports ActionLog (boundary leak, but out of scope)
- Tests: `tests/unit/test_claude_sdk_*`, `tests/unit/test_tool_detector*`,
  `tests/integration/test_claude_sdk_*`, `tests/integration/test_executor_*`, etc.
