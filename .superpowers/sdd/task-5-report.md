# Task 5: Runner Usage Metadata Report

## Delivered

- Added finish-reason and reasoning-token fields to `ExecutionResult`.
- Preserved raw Codex terminal statuses (`completed`, `interrupted`, and
  `systemError`) as finish reasons, and kept reasoning tokens distinct from the
  already-inclusive output token total.
- Captured Claude CLI `stop_reason`, kept OpenHands on the empty default, and
  passed mock metadata through unchanged.
- Propagated reasoning, finish reasons, and runner-boundary latency into the
  single parent `ModelTokenUsage` fact without duplicating reasoning output.
- Injected `perf_counter`-defaulted monotonic clocks into `PhaseHandler` and
  `GraphDispatchExecutor`; the timer surrounds only `agent.execute()`.

## Strict TDD Evidence

Initial RED command (new metadata surface absent):

```text
uv run pytest tests/unit/test_runner_usage_metadata.py tests/unit/test_codex_server_token_capture.py tests/unit/test_codex_server_common.py -q -n 0
ERROR: cannot import name 'extract_turn_finish_reasons'
```

Latency RED command (injected monotonic seams absent):

```text
uv run pytest tests/unit/test_runner_usage_metadata.py tests/unit/test_codex_server_token_capture.py tests/unit/test_codex_server_common.py -q -n 0
2 failed
```

The failures were the missing `PhaseHandler.monotonic` constructor argument and
the unchanged graph runner result duration (`999`, expected `125`).

GREEN command:

```text
uv run pytest tests/unit/test_runner_usage_metadata.py tests/unit/test_codex_server_token_capture.py tests/unit/test_codex_server_common.py -q -n 0
127 passed
```

## Broader Verification

- `uv run pytest tests/unit -q -n 0` — 3529 passed, 1 skipped.
- `uv run ruff check ...` — passed.
- `uv run pyright` — 0 errors, 0 warnings, 0 informations.

## Scope Note

The pre-existing `.superpowers/sdd/progress.md` modification was left out of
the task commit.
