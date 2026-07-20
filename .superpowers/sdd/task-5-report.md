# Task 5: Runner Usage Metadata Report

## Delivered

- `ExecutionResult` carries plural finish reasons and separate reasoning output
  tokens.
- Codex terminal statuses normalize to `stop`, `cancelled`, or `error`; Codex
  output remains reasoning-inclusive exactly once while reasoning is separately
  observable.
- Claude CLI preserves provider stop reasons. Mock metadata passes through.
- Parent and every sub-agent usage fact receive the same execution-boundary
  latency, including sub-agent-only executions.
- `PhaseHandler` and `GraphDispatchExecutor` accept an injected monotonic clock
  and measure only their `agent.execute()` boundary.
- OpenHands local and Docker adapters now share the pure
  `build_openhands_execution_result()` seam. It preserves supplied metrics,
  output, and action log while always emitting empty finish reasons.

## Test-driven Evidence

Metadata semantics RED:

```text
uv run pytest tests/unit/test_runner_usage_metadata.py tests/unit/test_codex_server_token_capture.py tests/unit/test_codex_server_common.py -q -n 0
4 failed
```

The failures showed unnormalized Codex terminal statuses and missing latency on
sub-agent usage facts.

OpenHands seam RED:

```text
uv run pytest tests/unit/test_runner_usage_metadata.py tests/unit/test_codex_server_token_capture.py tests/unit/test_codex_server_common.py -q -n 0
ERROR: cannot import name 'build_openhands_execution_result'
```

GREEN:

```text
uv run pytest tests/unit/test_runner_usage_metadata.py tests/unit/test_codex_server_token_capture.py tests/unit/test_codex_server_common.py -q -n 0
132 passed
```

The deterministic unit tests exercise the shared pure seam and each adapter's
construction path. They require no SDK, Docker daemon, network service, skip,
mock, or monkeypatch.

## Verification

- Exact suite above: passed.
- `uv run pyright`: 0 errors, 0 warnings, 0 informations.
- Full pre-commit hooks: passed after the final semantic changes.

## Scope Note

The pre-existing `.superpowers/sdd/progress.md` modification remains outside
Task 5 commits.
