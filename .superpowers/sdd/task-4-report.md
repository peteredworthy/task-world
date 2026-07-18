# Backlog Closeout Task 4 Report

## Status

Implemented Codex CLI model routing so `--model` follows `exec`, including
absolute Codex command paths and custom arguments. Non-Codex argument ordering
is unchanged, and MCP argument handling was not modified.

## Files

- `src/orchestrator/runners/agents/claude_cli/agent.py`
- `tests/unit/test_cli_agent.py`

## Test-driven evidence

Added exact argv tests for Codex factory defaults, absolute Codex paths with
custom args, and unchanged Claude ordering.

RED run:

```text
uv run pytest tests/unit/test_cli_agent.py -q
2 failed, 37 passed
```

Both failures showed `--model` at argv index 1 instead of after `exec`.

GREEN run:

```text
uv run pytest tests/unit/test_cli_agent.py -q
39 passed
```

## Verification

```text
uv run ruff check src/orchestrator/runners/agents/claude_cli/agent.py tests/unit/test_cli_agent.py
All checks passed!

uv run pyright
0 errors, 0 warnings, 0 informations

git diff --check
passed with no output
```

## Self-review

- Confirmed `Path(command).name` handles absolute Codex command paths.
- Confirmed custom args are copied and preserved around the inserted model flag.
- Confirmed Codex model placement requires an `exec` argument.
- Confirmed Claude ordering remains `--model`, model, then existing args.
- Confirmed MCP argument handling is unchanged.
- Confirmed pre-existing `.superpowers/sdd/progress.md` and `task-2-report.md`
  changes were not staged.

## Concerns

None identified within the requested scope.
