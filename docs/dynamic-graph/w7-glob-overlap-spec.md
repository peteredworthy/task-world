# W7 — Replace glob-probe overlap heuristic with segment analysis

Addresses weakness **W7** (medium) and improvement **#8** in
`dynamic-graph-implementation-review.html` (re-assessed 2026-07-03).

## Status — closed 2026-07-07

The W7 scope has landed in commits `018483a3b` and `cea6282c9`.

Closed:
- The synthetic suffix probe heuristic is gone.
- The scheduler uses a segment-wise comparator (`_segments_may_overlap`) for literal, glob, and recursive `**` path claims.
- Repo-relative normalization and `../` escape rejection are unchanged.
- Undecidable wildcard-vs-wildcard cases remain conservative.

Evidence:
- `tests/unit/test_scheduler.py::test_glob_path_overlap_detects_deep_literal_prefix_under_glob`
- `tests/unit/test_scheduler.py::test_glob_path_overlap_detects_literal_prefix_under_recursive_glob`
- `tests/unit/test_scheduler.py::test_glob_path_overlap_distinguishes_disjoint_roots`
- `tests/integration/test_graph_fr10_acceptance.py`
- `tests/integration/test_graph_fr11_acceptance.py`

## Problem

Claim-path overlap in `src/orchestrator/graph/scheduler.py`:

- `_literal_prefix_may_match_glob` decides "literal under glob" by probing three
  synthetic suffixes (`"x"`, `"x.py"`, `"nested/x.py"`). A pattern whose match depth
  exceeds the probes (e.g. `src/*/*/gen/*.py` vs literal `src/a`) is judged
  non-overlapping → **two writers admitted to overlapping paths**. This is a safety
  bug, not a perf issue.
- `_glob_prefixes_may_overlap` compares static prefixes; any two rootless patterns
  return True (over-serializes — safe but wasteful).

## Architecture

Replace both with one segment-wise comparator:

- Split both paths on `/`. Compare segment-by-segment: literal-vs-literal must be
  equal; a segment containing `*`/`?`/`[...]` matches via `fnmatch` against a literal
  segment; wildcard-vs-wildcard segments are undecidable → treat as overlapping.
- `**` matches zero or more whole segments (branch the comparison).
- A literal that is a strict *prefix path* of the other side overlaps (directory
  containment) — preserve the existing containment semantics; read the current
  call sites (`claims_conflict` and the path-overlap block around lines 300–345)
  before changing return conventions.
- Decision rule: return False only when overlap is provably impossible;
  conservative-True for anything undecidable. Over-serializing is acceptable;
  under-detecting is not.

Keep `../`-escape rejection and repo-relative normalization exactly as-is.

## Requirements

**R1 — Soundness.** Property test (Hypothesis; add as dev dependency if absent —
check `pyproject.toml`): generate patterns and literal paths from a small alphabet;
whenever a concrete path fnmatches both claims, `overlap(a, b)` must be True. The old
probe heuristic fails this immediately — the new comparator must not. *Critical.*

**R2 — Known false-negative fixed.** Direct regression test:
`src/*/*/gen/*.py` vs literal `src/a` (and one `**` case) now conflict. *Critical.*

**R3 — Precision improved or equal.** The rootless-pattern pair that today returns
blanket True still returns True only when genuinely undecidable; add at least one
case that provably cannot overlap (e.g. `docs/**` vs `src/**`) and now returns False.
*Expected.*

**R4 — Scheduler behavior otherwise unchanged.** Deterministic tie-ordering, deferral
reasons (`resource_conflict:*`), snapshot-scoped reads, external keys: untouched.
Existing scheduler tests pass unmodified. *Critical.*

## Constraints

- Pure function, kernel-side; no I/O, no caching with hidden state.
- Do not change claim data shapes or event payloads.
- Empty-path-list behavior (conflicts with everything) stays as-is this slice.

## Acceptance

```
uv run pytest tests/unit/test_scheduler.py \
  tests/integration/test_graph_fr10_acceptance.py \
  tests/integration/test_graph_fr11_acceptance.py \
  tests/integration/test_graph_dynamic_e2e.py -q
```

All pass, plus the new property test and regression cases.
