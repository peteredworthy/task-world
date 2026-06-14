# Slice 4.4 — codex_server token capture

Size: S–M. Phase 4 follow-up: closes the one measurement gap left open by
slice 4.3 / commit `11d238bf1` ("Share token/cost accounting across carriers"),
whose own message records the remainder: **"Remaining gap: codex_server token
capture."** Runner-only change — NO kernel, compiler, or downstream-sink edits.

## Ground truth

- `docs/graph-approach/carrier-comparison.md` — the comparison this unblocks;
  "codex_server token capture" listed as the open observability gap.
- Commit `11d238bf1` — the run-level token sink and the graph path's
  `on_agent_usage` wiring are already in place and MUST NOT be changed:
  - `src/orchestrator/runners/execution/usage.py::extract_metrics_and_usage`
    reads `result.action_log.total_input_tokens / total_output_tokens /
    total_cache_read_tokens / total_cache_creation_tokens` (and per-entry
    `entry.metrics` as fallback).
  - `src/orchestrator/db/access/mutations.py::merge_token_usage_into_run`.
  - `src/orchestrator/api/deps.py::on_agent_usage` (graph path → the sink).
- `src/orchestrator/runners/agents/codex/agent.py` — notification loop
  (`_process_msg`, `_handle_notification`), where `turn_usage` is set.
- `src/orchestrator/runners/agents/codex/common.py::extract_turn_usage` (l.426)
  — current (insufficient) usage parser.

## Problem (precise)

The codex app-server (v0.139.0) delivers token usage in a
**`thread/tokenUsage/updated`** notification (confirmed from the codex binary's
embedded serde field names — see "Confirmed wire shape" below). The runner
**ignores this notification**: `_handle_notification` only extracts usage from
the terminal `turn/completed` payload via `extract_turn_usage`
(`params.turn.tokenUsage|usage`), which the app-server leaves empty. Result:
`turn_usage = {}` → zeros → `extract_metrics_and_usage` yields no
`ModelTokenUsage` → the run records zero tokens. Two secondary defects:
`_process_msg` does `turn_usage = usage` (overwrite, not accumulate, across
turns), and `reasoning_output_tokens` is dropped entirely.

### Confirmed wire shape (codex 0.139.0)

Method: `thread/tokenUsage/updated` (coexists with `turn/completed`,
`item/completed`, etc. — same protocol the runner already speaks). The params
carry a token-usage object whose fields appear in **camelCase** in app-server
notifications (snake_case in the core representation), with a cumulative vs
per-turn split:

- cumulative: `total_token_usage` (snake) — **prefer this**; per-turn:
  `last_token_usage`.
- per-object fields (both casings observed): `inputTokens`/`input_tokens`,
  `cachedInputTokens`/`cached_input_tokens`, `outputTokens`/`output_tokens`,
  `reasoningOutputTokens`/`reasoning_output_tokens`, `totalTokens`/`total_tokens`.

The exact params *nesting* (e.g. `params.tokenUsage` vs `params.usage` vs a
`{total_token_usage, last_token_usage}` wrapper) may vary by version, so the
parser MUST locate the usage object tolerantly (recursive search for the first
dict carrying an `inputTokens|input_tokens` key) rather than hard-coding a path.
A live sample captured for the fixture (Scope §0) pins the nesting for this
version; the tolerant search guards future drift.

## Scope — what to build

### 0. Pin the wire shape with a real fixture

The method + fields are already confirmed (above) from the codex 0.139.0 binary.
Still capture one real `thread/tokenUsage/updated` notification to pin the params
nesting for this version and commit it (trimmed) as the test fixture: add a
temporary debug log of each JSON-RPC `msg` in the `_process_msg` loop, run one
real codex_server session (any trivial routine), copy the captured
`thread/tokenUsage/updated` payload into `tests/fixtures/codex/`, then remove the
debug log. If a live capture is not feasible in the build environment, construct
the fixture from the confirmed schema above — but the parser's tolerant search
(below) is what guarantees correctness, not the exact fixture nesting.

### 1. `extract_token_usage_update` in `common.py`

New pure function `extract_token_usage_update(notification) -> dict[str,int] | None`
keyed on `method == "thread/tokenUsage/updated"`:

- Returns `None` for non-usage notifications (so the caller distinguishes "no
  usage here" from "usage = 0").
- Locate the usage object **tolerantly**: prefer a `total_token_usage` wrapper
  (cumulative); else `last_token_usage`; else recursively find the first dict
  carrying an `inputTokens|input_tokens` key. Map, tolerating camelCase and
  snake_case:
  - `inputTokens|input_tokens` → `tokens_read`
  - `cachedInputTokens|cached_input_tokens|cache_read_input_tokens` → `tokens_cache`
  - `outputTokens|output_tokens` (+ `reasoningOutputTokens|reasoning_output_tokens`)
    → `tokens_write` (reasoning folded into write; the billed-output convention
    used elsewhere — document it in a comment).
  - also surface `tokens_reasoning` separately in the dict for observability,
    even though it is folded into write for the flat metric.
- Keep `extract_turn_usage` as the `turn/completed.tokenUsage|usage` fallback;
  add the same reasoning mapping there for parity.

### 2. Accumulate in the agent loop (`agent.py`)

- In `_handle_notification`, add a branch: when a notification is a
  `thread/tokenUsage/updated` event, parse it with `extract_token_usage_update`
  and return it to the loop **without** marking terminal. The return contract
  `(terminal, usage)` already exists — return the interim usage with
  `terminal=False`.
- In `_process_msg`, replace `turn_usage = usage` (overwrite) with a
  **cumulative-aware** update: when the source is cumulative `total_token_usage`,
  keep the latest (last cumulative wins per field); if only per-turn values are
  available, sum. The terminal `turn/completed` usage is used only if no
  `thread/tokenUsage/updated` was ever seen. End state: `turn_usage` reflects the
  whole session.
- Populate `action_log.total_input_tokens / total_output_tokens /
  total_cache_read_tokens` from final `turn_usage` (already done at l.789–791;
  add cache_creation if the app-server reports it, and ensure reasoning is in
  output). Also set the per-turn `ExecutionMetrics` (l.780–782) so the
  fallback path in `extract_metrics_and_usage` stays correct.

### 3. No downstream changes

`extract_metrics_and_usage`, `merge_token_usage_into_run`, and the
`on_agent_usage` wiring are untouched — this slice only makes the codex runner
feed them nonzero numbers.

## Tests

### Unit — `tests/unit/test_codex_server_common.py` (extend)

- `test_extract_token_usage_update_total_cumulative` — a real captured
  `thread/tokenUsage/updated` notification → read/write/cache/reasoning extracted
  from `total_token_usage`; reasoning folded into write.
- `test_extract_token_usage_update_camel_and_snake` — both field casings parse.
- `test_extract_token_usage_update_non_usage_returns_none` — unrelated
  notification → `None`.
- `test_extract_turn_usage_reasoning_folded` — `turn/completed` fallback also
  folds reasoning into write.

### Unit — `tests/unit/test_codex_server_*` (new, runner-level)

- `test_session_accumulates_token_usage` — a hand-written fake transport (NO
  mocks) replays a recorded stream of N `thread/tokenUsage/updated` events + a
  final `turn/completed`; drive the agent's notification loop; assert final
  `ExecutionResult.action_log.total_*_tokens` equal the cumulative totals (not
  the last turn only) and are nonzero.
- `test_extract_metrics_and_usage_nonzero_for_codex` — feed that
  `ExecutionResult` to `extract_metrics_and_usage`; assert a single nonzero
  `ModelTokenUsage` with the codex model and correct read/write/cache.

Fixtures: trimmed **real** captured payloads committed under the test module or
`tests/fixtures/codex/`.

## Done when

1. A recorded codex app-server `thread/tokenUsage/updated` stream is parsed into
   nonzero read/write/cache/reasoning by `extract_token_usage_update`.
2. The agent loop accumulates session usage (cumulative `total_token_usage`
   wins; multi-turn no longer keeps only the last turn) and writes it into
   `action_log.total_*` + per-turn metrics.
3. `extract_metrics_and_usage(result)` returns a nonzero `ModelTokenUsage` for a
   codex_server `ExecutionResult` built from the recorded stream.
4. `reasoning_output_tokens` is captured (folded into write, surfaced for
   observability); documented mapping.
5. `turn/completed.tokenUsage|usage` retained as fallback; older-server tests
   stay green.
6. All listed tests pass; full `tests/unit` + `tests/integration` green; ruff +
   pyright clean on `src/orchestrator/runners/agents/codex`.
7. No edits to `graph/`, the compiler, `extract_metrics_and_usage`,
   `merge_token_usage_into_run`, or the `on_agent_usage` wiring.

## Hard constraints (universal, per slice-process.md)

- NO `unittest.mock` / monkeypatching. Hand-written fake/recording transport
  classes injected via constructor only.
- Real SQLite tmp dirs only; never touch `orchestrator.db`; no server in tests.
- Kernel purity unaffected — changes confined to `runners/agents/codex/`.
- `graph_runtime` / `graph` import boundaries unchanged.
- No git mutation on the main repo; agent works in its run worktree branch only.
- Token *volume* is the hard metric; USD is indicative only — do not gate tests
  on dollar values.
