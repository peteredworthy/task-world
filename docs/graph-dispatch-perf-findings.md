# Findings: why graph dispatch tests cost what they do

Answers the investigation in `docs/handoff-graph-dispatch-perf.md`.

**Headline:** the graph tests are *mostly correctly expensive*. They spawn real
git processes, drive a real event-sourced command loop, and capture real
file-state boundaries. One genuine runtime inefficiency was found and fixed —
a quadratic subprocess fan-out in snapshot dedup — but it is a **production
scalability bug that barely registers in the test suite**, not the explanation
for the suite's cost. Two of the four leads turned out to be non-issues, and a
third fix that looked worth ~1.5% on paper measured as noise and was reverted.

## How this was measured

Direct instrumentation, not cProfile, for exactly the reason the handoff warns
about: wrapping each function and counting entries, with `perf_counter` around
the call. Baseline is `tests/integration/test_graph_*.py` at `-n0`:
**260 tests, 85.0s wall, 84.0s CPU** (55.0 user + 29.0 sys).

| calls | accum. time | function |
|---|---|---|
| 1227 | 23.46s | `subprocess.run` (git) |
| 1126 | 21.30s | `GraphController.handle_command` |
| 1208 | 9.22s | `store.append_events` |
| 1127 | 5.39s | `store.load_projection_with_tail` |
| 1183 | 3.57s | `store.advance_projection_snapshot` |
| 1970 | 3.03s | `store.read_run` |
| 3450 | 2.84s | `store.current_position` |
| 2051 | 2.52s | `projection_from_checkpoint` |
| 50529 | 2.27s | `projections.reduce_event` |
| 67114 | 1.53s | `projections._clone_projection` |
| 1201 | 0.25s | `projection_to_checkpoint` |
| **49** | — | **`StaleProjectionError` raised** |

Read this as attribution, not a partition: entries for `async def` functions
accumulate time spent awaiting other tasks, so they overlap and nest. The
synchronous entries (`_clone_projection`, `projection_from_checkpoint`,
`_projection_from_snapshot_row`) are exclusive and trustworthy. **This
distinction turned out to matter** — see lead 4.

## Lead 1 — stale-projection races: real, but ~0.3% of cost

**Not a performance problem.** Across the whole block there were **49**
`StaleProjectionError` raises against 1126 commands — a 4.4% loss rate, not a
storm. The handoff's "19 in a single test" is an outlier from a deliberately
racy test; re-running that same test showed 10. Each lost race costs one
`current_position` query plus one discarded `load_projection_with_tail`
(~5ms), so the total wasted work is roughly **0.25s of 84s**.

The design observation in the handoff is still correct and worth recording,
just not for speed reasons:

- **Some of the contention is manufactured.** Callers read the head in one
  transaction (`dispatch._current_position` / `driver.current_position`) and
  then `handle_command` re-reads it in another. The window between those two
  reads is pure race surface that buys nothing, because phase 1 re-reads the
  position anyway and re-checks it. A "command at head" mode that let phase 1
  supply the position would close that window entirely.
- **The retry budget is shared.** `MAX_STALE_COMMAND_RETRIES = 5` covers both
  optimistic-concurrency losses and `database is locked` backoff. With enough
  concurrent agents appending to one run aggregate, budget exhaustion is a
  plausible (though unobserved here) failure mode.

Neither is worth changing for performance. Both are worth knowing if the
stale path ever starts failing in production.

## Lead 2 — subprocess spawns: the dominant cost, and one real bug

**28% of the block.** 1227 spawns / 23.5s. Grouped by call shape:

| spawns | ~time | what | verdict |
|---|---|---|---|
| ~464 | ~10s | boundary capture: `status --porcelain=v2` + `add -A` + `write-tree` + `for-each-ref` per capture (116 captures) | real work |
| 239 | ~4.9s | contamination guard: `rev-parse --git-common-dir` + `status --porcelain` per run | real safety work |
| ~208 | ~5.7s | `git init` / `add` / `commit` building fixture repos | test shape |
| **86** | **~1.7s** | **`git show -s --format=%T`, one per existing snapshot ref** | **bug — fixed** |

Boundary capture is already at its floor of 4 processes; there is no redundant
work left in it. The contamination guard is a per-run safety check that exists
because of prior worktree-escape incidents — leave it alone.

### The bug: quadratic snapshot dedup

`_find_snapshot_by_tree` listed the snapshot refs, then spawned **one
`git show -s --format=%T` per existing ref** to read each commit's tree. So one
capture cost O(snapshots) processes, and a run's captures cost **O(snapshots²)**
overall. The `%(tree)` atom reports the tree directly in the single
`for-each-ref` call, so the fan-out is unnecessary.

Alternating microbenchmark, 40 distinct snapshots in one repo:

| | spawns | wall (run 1) | wall (run 2) |
|---|---|---|---|
| before | 980 | 16.4s | 18.4s |
| after | **200** | **3.8s** | **4.0s** |

Exactly `5N + N(N−1)/2` → `5N`. **4.3x faster at N=40, and the gap widens
with N.**

**Be honest about the scope:** this removes ~86 spawns from the test block
(~1.7s of 85s) because test runs only accumulate a handful of snapshots each.
It is worth shipping for the production path — a long run taking 50 boundary
captures spawns ~1250 git processes for dedup instead of 50 — not because it
speeds up CI.

## Lead 3 — `_clone_projection`: closed, nothing left

67114 calls but only **1.53s (1.8%)**, ~23µs each. Commit `ef869c62b`
("share frozen projection models instead of deep-copying") already took the
available win. The high call count is what drew attention; the cost per call
is now negligible. **No action.**

## Lead 4 — pydantic / json churn: real, structural, and not worth fixing

Every command round-trips the entire projection through JSON **three times**:
deserialize in phase 1 (`load_projection_with_tail`), deserialize again in
phase 2 (`advance_projection_snapshot`), and serialize once when persisting.
Deserialization is ~6x costlier per call than serialization (1.2ms vs 0.2ms).
Two of the three round-trips looked avoidable, since phase 2 re-derives a
projection the controller is already holding at exactly that position.

I implemented it: `append_events` gained optional `head_position` and
`base_projection` parameters, letting the controller hand over the head it had
just verified under `BEGIN IMMEDIATE` and the projection phase 1 had loaded.
That removes 1126 redundant head queries and ~1126 full checkpoint
deserializations per block. I first confirmed the kernel never mutates the
projection it is given (1116 `apply_command` calls checked, zero mutations),
since the change depends on that.

**Then I measured it, and it was noise.** Alternating A/B on the graph block:

| variant | run 1 | run 2 | mean CPU |
|---|---|---|---|
| unchanged | 91.48s | 91.31s | **91.40s** |
| with the change | 90.72s | 91.64s | **91.18s** |

0.24% apart, with the within-variant spread (0.92s) larger than the difference.
**Reverted.** The paper estimate of ~1.5% came from reading accumulated times
on `async` functions as if they were exclusive — the same trap the handoff
warns about for cProfile's `cumtime`, reached by a different route. The
underlying SQLite work is in-memory and far cheaper than the accumulated
figures suggest.

The structural observation stands and is worth recording: **the projection is
serialized and deserialized once per command, and the checkpoint round-trip is
the single most expensive pure-Python operation on the command path.** If graph
runs ever grow projections large enough for this to matter, phase 2's
deserialization is the first thing to remove — but today it does not matter.

## What shipped

- `src/orchestrator/git/snapshot.py` — dedup reads trees from the single
  `for-each-ref`; the per-ref `git show` remains only as a fallback for refs
  that do not point at a commit. Parsing and matching are split into pure
  functions (`parse_snapshot_refs`, `match_snapshot_by_tree`), and `snapshot()`
  takes an injectable `run_git` runner so the process-count invariant is
  testable without patching.
- `tests/unit/test_git_snapshot.py` — pure tests for parsing/matching, plus a
  constant-cost-per-capture test driven through the injected runner. Verified
  non-vacuous: it fails when `%(tree)` is dropped from the ref listing.
- `tests/unit/test_graph_commands.py` — pins that `apply_command` does not
  mutate the projection it is handed.

### Verification

`4940 passed, 3 skipped` — the 4933 baseline plus the 7 tests added here.
`ruff check` and `ruff format --check` clean over `src` and `tests`; `pyright`
reports 0 errors.

Full-suite CPU measured 549.7s against the 546.1s baseline. That difference is
**within noise and should not be read as a regression or an improvement** — the
within-variant spread on the graph block alone was ~1%, and this run's wall
clock (167s vs the baseline's ~100s) shows the machine was heavily loaded.
No suite-level speedup is claimed; see lead 2 for why none was expected.

## What did not ship, and why

- Passing `head_position` / `base_projection` into `append_events` — measured
  as noise (above).
- A "command at head" mode to close the manufactured stale-race window —
  the races it removes cost ~0.3%.
- Anything touching the contamination guard or boundary capture — both are
  doing real, non-redundant work.

## The actual answer to "why do these tests cost so much"

They exercise a lot of real machinery, and that machinery is not doing much
redundant work. Roughly: **~28% real git subprocesses** (of which about a
quarter is test-fixture repo setup rather than runtime), **~35% event-store and
projection work** across ~1100 real commands, and the remainder kernel folding,
app setup, and asyncio. The one true inefficiency found accounted for ~2% of
the block. This is a **legitimately expensive test suite**, not a slow runtime —
and the honest recommendation is that further speedups have to come from test
shape (fewer real git repos per test, shared fixtures) rather than from
optimizing `graph_runtime`.
