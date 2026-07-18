# Claude SDK Runner Removal Decision

**Decision:** Remove

**Date:** 2026-07-18

**Status:** Implemented

## Context and failure evidence

The in-process Claude SDK runner did not provide a viable product surface:

- During the July 4 W4 incident, verifier work completed but orchestrator
  `grade` and `submit` callbacks repeatedly returned `Stream closed`. The
  server recorded `RuntimeError: Attempted to exit cancel scope in a different
  task than it was entered in` inside `claude_agent_sdk`, and dispatch retried
  sessions that could not submit their results.
- The runner lacked usable tool support for the product workflow. Its
  clarification hook was a logging stub and its graph callback path had to be
  gated off before graph seeding.
- It emitted only flat token totals rather than the action log used by the
  shared accounting path, omitting cache and sub-agent usage. Its default model
  also fell through the unknown-rate path, corrupting aggregate cost signals.

The dated incident remains in
`incident-2026-07-04-w2-driver-crash-w3-final-check-strand.md`; this decision
supersedes its proposed repair work without rewriting the historical facts.

## Decision and replacement

Remove the Claude SDK implementation, dependency, detector/factory/model
discovery wiring, prompt path, and executable routine work that names deleted
symbols. Do not leave it gated as a selectable legacy carrier. The selectable
runner values are:

- `openhands_local`
- `openhands_docker`
- `cli_subprocess`
- `codex_server`

`codex_server` is the supported replacement for former Claude SDK execution
and remains the supported graph runner. Replacement is explicit: an operator
must select Codex Server (or another active runner where valid) before a
retired draft/run can start or resume. The system does not silently change a
run's execution backend.

## Historical compatibility and migration

`AgentRunnerType.RETIRED` is a readback-only compatibility state. It is not
selectable, returned by active runner discovery, accepted by runner defaults,
or dispatchable by the factory, executor, lifecycle consumer, or graph driver.
The historical string `claude_sdk` normalizes to `retired` at repository,
session-state, and workflow-event deserialization boundaries.

Alembic migration `zg1h2i3j4k5l` converts mutable relational runner fields in
`runs`, `attempts`, `cost_records`, `interaction_log_artifacts`, and
`agent_runner_model_profile_defaults` to `retired`. Model-default collisions
are resolved deterministically before conversion. Immutable event payload and
state/journal bytes are not rewritten: normalization happens on in-memory
copies at read time and only for runner-typed keys.

There is no journal rewrite and no database wipe. Existing run history,
incident evidence, IDs, content, events, and audit files remain available.
Downgrade cannot recover whether a `retired` relational value originally came
from `claude_sdk`, so reintroduction must not attempt to infer that provenance.

## Consequences

- OQ-5 is closed as **remove**.
- New and resumed execution cannot select `claude_sdk` or `retired`.
- Historical API/state/event readback remains valid and labels the backend
  `retired` rather than pretending it is active.
- Archived Markdown can continue to name Claude SDK as historical evidence.
  Current-product docs and executable routines must not present it as live.
- Codex Server owns the supported graph callback/tool path; no compatibility
  shim recreates the deleted SDK symbols.

## Independent verifier evidence

On 2026-07-18, the separate no-context verifier passed exact source
`200102e0e4f9ab3d0b727faabe9f032f125894df`:

```bash
uv run pytest tests/ -q -n auto --dist worksteal
# 4791 passed, 3 skipped, 3 warnings in 103.33s (0:01:43)

uv run ruff check .
# All checks passed!

uv run pyright
# 0 errors, 0 warnings, 0 informations
# update notice: installed v1.1.408; v1.1.411 available

git diff --check
# clean; no output

uv run python scripts/export_enums.py --check
# OK: /Users/peter/code/task-world/worktrees/backlog-closeout/ui/src/types/generated-enums.ts is up to date.

uv run alembic -c alembic.ini heads
# zg1h2i3j4k5l (head)
```

The three warnings were Python 3.12 default-datetime-adapter
`DeprecationWarning`s from `aiosqlite/core.py:63`. The Pyright update notice was
advisory; the check itself reported zero errors, warnings, and informations.
Generated enums were up to date, and Alembic reported the single head
`zg1h2i3j4k5l`. The verifier's only dirty paths were the pre-existing SDD
scratch files. This documentation records that independent evidence; it does
not change the verified source SHA.

## Reintroduction criteria

An Anthropic SDK runner may return only as a new runner proposal, not by
reactivating `retired`. It must have a new active enum value and satisfy all of
the following before becoming selectable:

1. End-to-end builder and verifier tool use, including reliable checklist,
   grade, submit, clarification, and cancellation callbacks.
2. Graph callback reliability under repeated execution, cancellation, and
   reconnect scenarios, with no stream/cancel-scope failures.
3. Complete action-log and cost telemetry (model, cache, sub-agent, token, and
   rate-missing data) through the shared accounting path.
4. Factory, discovery, API-boundary, lifecycle, resume, and graph-driver tests
   proving unsupported states cannot dispatch.
5. A documented migration plan that preserves the meaning of existing
   `retired` history without journal/event rewrites or provenance guesses.

Until those criteria are met, `retired` remains permanently readback-only and
Codex Server remains the replacement.
