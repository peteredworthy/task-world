# Handoff: why graph dispatch tests cost 214s CPU

Investigate why the graph execution tests dominate the suite's CPU, and whether
the cause is a genuine runtime inefficiency in `graph_runtime` rather than a
test-shape problem. Recommend and, where clearly justified, implement fixes.

## Where this sits

`perf/api-route-cache` (commit `0d7d7f024`, not yet merged) just cut suite CPU
from 655.6s to 546.1s by caching compiled API routes. The graph integration
tests are the largest remaining block: **~214s CPU across 260 tests in 39
files** (`tests/integration/test_graph_*.py`), measured from a junit rollup.
Heaviest files: `test_graph_run_driver` (31.8s/16 tests),
`test_graph_dynamic_e2e` (22.5s/7), `test_graph_outbox_crash_points`
(19.5s/22), `test_graph_runner_e2e` (16.6s/10), `test_graph_default_carrier`
(13.5s/5), `test_graph_fr16_acceptance` (13.0s/5).

Background on the codebase's graph work is in
`docs/dynamic-graph/re-evaluation-2026-07-18.md`.

## Read this first: a trap that already produced one wrong conclusion

**cProfile's `ncalls` for `async def` functions counts coroutine resumptions,
not invocations.** An earlier pass reported "3218 calls to
`_handle_command_retry_stale` in one test" and called it a runaway loop. Direct
instrumentation showed the real count was **26**. There is no thousand-fold
loop. Always confirm counts by wrapping the function and counting entries
before drawing conclusions:

```python
# pytest plugin, loaded with -p <module>, PYTHONPATH pointing at its dir
def pytest_configure(config):
    from orchestrator.graph_runtime.dispatch import GraphDispatchExecutor
    orig = GraphDispatchExecutor._run_agent
    async def wrapper(*a, **kw):
        COUNTS["_run_agent"] += 1
        return await orig(*a, **kw)
    GraphDispatchExecutor._run_agent = wrapper
```

Prefer `sort_stats("tottime")` over `cumulative` for the same reason: `cumtime`
on a coroutine is inflated by every resumption.

## Verified starting facts

Entry point, a single test that takes ~3.5s on its own:

```
uv run pytest "tests/integration/test_graph_fr01_fr13_fr18_acceptance.py::test_fr13_partial_region_blockers_and_invalid_patch_in_blocked_state" -n0 -q
```

Real invocation counts for that one test (instrumented, not profiled):

| count | function |
|---|---|
| 47 | `GraphController.handle_command` (`graph_runtime/controller.py:74`) |
| 26 | `GraphDispatchExecutor._handle_command_retry_stale` (`graph_runtime/dispatch.py:687`) |
| 19 | `StaleProjectionError` raised (`graph_runtime/errors.py:8`) |
| 8 | `_acknowledge_start` (`dispatch.py:482`) |
| 6 | `_run_agent` (`dispatch.py:275`) |
| 6 | `_record_start_heartbeat` (`dispatch.py:496`) |
| 1 | `GraphRunDriver.run` (`workflow/graph_driver.py:313`) |

Top `tottime` entries for the same test:

| tottime | what |
|---|---|
| 0.768s | `select.poll` — event loop *waiting*, not CPU |
| 0.351s | `selectors.select`, 16414 calls |
| 0.347s | `gc.collect`, 5 calls |
| 0.313s | pydantic `validate_python`, 23952 calls |
| 0.220s | `_posixsubprocess.fork_exec`, **60 subprocess spawns** |
| 0.148s | `graph/projections.py:1805 _clone_projection`, 4842 calls |
| — | 1.59M `isinstance` calls, 11043 `json.loads` |

## Leads, roughly in order of promise

1. **19 stale-projection races in a single test.** 19 of the 26 commands routed
   through `_handle_command_retry_stale` lost an optimistic-concurrency race and
   had to re-read position and resend — which is why `handle_command` ran 47
   times for 26 logical commands. Establish whether that contention is inherent
   to the design or an artifact of how the driver sequences commands. Note the
   stale branch resends immediately (no backoff); only the "database is locked"
   branch sleeps, and it never fired here, so this is wasted work rather than
   wasted waiting. This looks like the most interesting thread: it is a
   correctness-adjacent design signal, not just a speed issue.

2. **60 subprocess spawns in one test.** Likely git: `capture_file_state_boundary`
   (`graph_runtime/file_state.py:77`) → `git/snapshot.py`. Count them per
   logical operation and check for repeated work that could be captured once.
   This probably also explains most of the 0.768s of event-loop waiting.

3. **4842 `_clone_projection` calls.** Commit `ef869c62b`
   ("perf(graph): share frozen projection models instead of deep-copying")
   already attacked this; find out what remains and whether it is avoidable.

4. **23952 pydantic validations + 11043 `json.loads`.** Payload
   serialization churn on the event/command path — possibly related to the W5
   typed-payload work.

## Method notes

- **Measure CPU, not wall.** Wall clock on this machine drifted up to 3x between
  identical runs (122s → 40s on the same work) as the machine heated and
  recovered. Use `/usr/bin/time -p` and sum user+sys, and **alternate configs**
  (A B A B) so drift cancels. Do not trust a single wall-clock pair.
- Full suite: `uv run pytest -n auto --dist worksteal --timeout=120 -q`
  (~546s CPU, ~100s wall, 4933 tests). Per-test timings via `--junitxml` then
  aggregate; note junit per-test times are ~2x inflated under xdist contention,
  so use `-n0` for clean single-test numbers.
- `TW_NO_ROUTE_CACHE=1` disables the new route cache if you need to rule it out.

## Constraints

- Run backend commands from `/Users/peter/code/task-world`.
- **Never** `rm orchestrator.db`. The project has no schema-upgrade contract;
  schema changes belong in current ORM metadata and are validated on a fresh
  temporary database. `init_db()` never alters existing tables.
- Don't `git stash`/`git checkout` casually from the main root:
  `.orchestrator/state/history.jsonl` is git-tracked and has been truncated that
  way before.

## What to deliver

A written assessment first: for each lead, whether it is a real inefficiency,
with numbers. Distinguish "the graph runtime does redundant work" from "these
tests exercise a lot of real machinery and are correctly expensive" — the second
is a legitimate finding and should be stated plainly if true. Only implement
changes that are clearly justified by a measurement, and re-verify with the
alternating-CPU method. The suite must stay green (4933 passed, 3 skipped) with
ruff and pyright clean.
