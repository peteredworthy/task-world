# W8 — Drive-loop simplification and dead-code removal

Addresses weakness **W8** (low) and improvement **#9** in
`dynamic-graph-implementation-review.html` (re-assessed 2026-07-03).

## Status — closed 2026-07-18

Closed:
- `recovery.py` no-op deletion.
- Progress-signature comparison replaced with event-log position comparison.
- Quiescent `reconcile` returns the reconciled projection without an extra
  `schedule_tick` pass unless reconcile creates ready/schedulable work.
- Future outbox backoff is honored by the driver before it classifies a run as
  blocked.
- Pure projection-derived outcome, completion, retry-budget, and lease-wait policy
  moved from the effectful driver into `graph/projections.py`; the temporary private
  compatibility copies were then deleted.
- Replaceable projection mirrors now delegate to canonical builders or carry
  exhaustive field guards (`23fa05e80`).
- The AST consumer guard reduced `orchestrator.graph.__all__` from **180** names at
  source `2ccd20bce` to **165** names, retaining source and test consumers and
  removing only the 15 zero-consumer re-exports it reported.
- `guard-retirement-ledger.md` maps the retired, replaced, and load-bearing guards
  to incidents, behavior, regressions, retirement conditions, and dispositions.

The driver remains a polling coordinator. W8 did **not** convert polling to
event-triggered driving, and event-triggered driving is not a prerequisite for
retiring any incident guard.

Evidence:
- `0b725a463` (`refactor: drive graph progress by event position`)
- `23fa05e8091b68f2696f5d60d6fd74ffc28b164f` (`refactor: consolidate graph projection mirrors`)
- `f0b6c237dca0dd37caf715265ed004e61889c6aa` (`refactor: move graph outcome policy into kernel`)
- `2ccd20bce78c8cb5620813c840bcff8b9d2bf304` (`fix: remove duplicate graph driver policy`; export-prune baseline)
- `tests/unit/test_graph_driver_logic.py::test_driver_uses_event_position_to_detect_stuck_ready_node`
- `tests/unit/test_graph_driver_logic.py::test_driver_returns_reconciled_quiescent_projection_without_second_schedule_tick`
- `tests/unit/test_graph_driver_logic.py::test_driver_continues_when_reconcile_creates_schedulable_work`
- `tests/unit/test_graph_driver_logic.py::test_driver_waits_for_future_outbox_backoff_before_declaring_blocked`

**Ordering:** the loop-simplification half depends on W2 (`w2-recovery-at-source-spec.md`)
and W3 (`w3-incremental-snapshots-spec.md`) having landed. The dead-code half can go
any time.

## Problem

- `workflow/graph_driver.py` remains a large polling coordinator with lease renewal,
  orphan recovery, pause classification, and worktree-contamination guards.
- The original extra recovery tick and progress-signature concerns are closed.
- `graph_runtime/recovery.py` no longer carries the self-cancelling assignment.
- `graph/__init__.py` now exactly matches the 165 package-level names consumed by
  `src` and `tests`, enforced by `tests/unit/test_graph_public_exports.py`.

## Scope

**Slice A — dead code and export prune:**
1. Done: delete the `recovery.py` no-op.
2. Done: an AST scan covers `from orchestrator.graph import Name` and aliased
   `import orchestrator.graph as alias; alias.Name` access under `src` and `tests`.
   Its exact-set assertion retained all 165 current consumers and removed 15
   zero-consumer re-exports without changing underlying symbols or consumer imports.

**Slice B — loop simplification (after W2 + W3):**
1. Done: with per-tick `node_deferred` gone (W3), replace the progress-signature comparison
   with "did event position advance".
2. Done: with repair moved to source commands (W2), remove the extra recovery re-tick on
   quiescence; quiescence-with-blockers issues one `reconcile` command instead.
3. Partially done: redundant quiescent re-ticks are gone; the driver still reads
   projections at the main schedule/wait/renewal boundaries because those reads feed
   separate safety checks.
Do **not** attempt full event-triggered driving (push notifications from the kernel)
in this slice — keep the poll loop, just make each iteration honest.

## Requirements

**R1 — Behavior parity for runs.** Dynamic e2e and driver-logic tests pass: runs reach
the same terminal states, pause/blocked semantics unchanged (including the
no-progress → `graph_blocked` pause and worktree-contamination guard — do not touch
those guards). *Critical.*

**R2 — Position-based progress.** After Slice B, the signature mechanism is deleted and
a test proves an idle graph is detected as non-progressing within the same number of
iterations as before. *Critical.*

**R3 — Import prune is complete but not over-eager.** Full test suite collects and
passes after the `__init__` prune; no `ImportError` anywhere (`uv run pytest tests
--collect-only -q` as a fast check). *Critical.*

**R4 — Line-count outcome.** `drive_to_quiescence` body shrinks measurably (target:
the three-reads-per-iteration pattern is gone). *Expected.* Pure driver policy was
relocated to canonical kernel projections in `f0b6c237d`; duplicate private policy
was deleted in `2ccd20bce`. The remaining reads serve distinct dispatch, wait,
renewal, and quiescence safety boundaries.

## Constraints

- Do not change lease renewal/expiry semantics.
- The driver's guards exist because of real incidents (worktree escapes, silent
  stalls) — simplify around them, never remove them.
- Slices A and B are separate PRs.

## Acceptance

```
uv run pytest tests/unit/test_graph_driver_logic.py \
  tests/integration/test_graph_dynamic_e2e.py \
  tests/integration/test_graph_default_carrier.py -q
```

Slice A additionally: full-suite collection check. Slice B additionally: R2 test and
the full graph suite (`uv run pytest tests -k graph -q`).

## Closeout verification — baseline `2ccd20bce`, implementation `8ad825cf2`, 2026-07-18

```text
uv run pytest tests/unit/test_graph_public_exports.py -q
# 1 passed in 2.83s

uv run pytest tests/ --collect-only -q
# 4849 tests collected in 5.72s

uv run pytest tests/unit/test_graph_public_exports.py tests/unit/test_graph_*.py tests/integration/test_graph_*.py -q
# 911 passed in 112.74s

uv run pyright
# 0 errors, 0 warnings, 0 informations
```

The pre-prune RED was `180` exports versus `165` consumers, with 15 names only
on the export side and none only on the consumer side. The post-prune guard is
`165 == 165`. Test-only consumers deliberately remain public. Fresh-verifier
execution and its SHA are Step 6 work and are not claimed here. The audit baseline
was `2ccd20bce`; the GREEN collection, focused tests, and checks ran on the closeout
implementation tree committed as `8ad825cf2`.
