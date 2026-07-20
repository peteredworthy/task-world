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

---

# Task 5 Metadata Semantics Follow-up

## Fixed

- Codex terminal statuses now normalize to OTel finish reasons: `completed` →
  `stop`, `interrupted` → `cancelled`, and `systemError`/`failed` → `error`.
- Every usage fact emitted by a single execution—including parent, each
  sub-agent, and sub-agent-only executions—receives the same execution-boundary
  latency.
- Codex server execution coverage verifies the injected transport runner path:
  mapped finish reason, separate reasoning component, and a single
  reasoning-inclusive output total.
- Exported `ExecutionContext` from `orchestrator.runners` so new runner-path
  tests use the public package boundary.
- Added OpenHands local and Docker execution-path tests gated on explicitly
  configured local (no external provider) runtimes. They verify the adapter
  leaves unsupported finish reasons empty when those real runtimes are enabled.

## TDD Evidence

RED:

```text
uv run pytest tests/unit/test_runner_usage_metadata.py tests/unit/test_codex_server_token_capture.py tests/unit/test_codex_server_common.py -q -n 0
4 failed
```

The failures showed unnormalized Codex statuses and zero latency on sub-agent
facts, including a sub-agent-only execution.

GREEN:

```text
uv run pytest tests/unit/test_runner_usage_metadata.py tests/unit/test_codex_server_token_capture.py tests/unit/test_codex_server_common.py -q -n 0
129 passed, 2 skipped
```

The two skips require opt-in local OpenHands/Docker runtimes through
`OPENHANDS_TEST_LOCAL_BASE_URL` and
`OPENHANDS_TEST_DOCKER_BASE_URL`/`OPENHANDS_TEST_DOCKER_API_KEY`; no external
provider is contacted.
