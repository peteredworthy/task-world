# W8 — Drive-loop simplification and dead-code removal

Addresses weakness **W8** (low) and improvement **#9** in
`dynamic-graph-implementation-review.html` (re-assessed 2026-07-03).

## Status — partially closed 2026-07-07

Closed:
- `recovery.py` no-op deletion.
- Progress-signature comparison replaced with event-log position comparison.
- Quiescent `reconcile` returns the reconciled projection without an extra
  `schedule_tick` pass unless reconcile creates ready/schedulable work.
- Future outbox backoff is honored by the driver before it classifies a run as
  blocked.

Remaining:
- `graph/__init__.py` is still a broad re-export surface, though reduced from the
  original review's ~190-name surface to 175 lines.
- The driver remains a polling coordinator. Full event-triggered driving is not part
  of the closed W8 slice and should wait until the current safety guards have clear
  kernel equivalents and retirement conditions.
- A stopgap/retirement-condition ledger is still useful for driver/dispatch/recovery
  guards that were added during incidents.

Evidence:
- `0b725a463` (`refactor: drive graph progress by event position`)
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
- `graph/__init__.py` remains a broad package-level namespace, coupling consumers to
  a large public surface.

## Scope

**Slice A — dead code and export prune:**
1. Done: delete the `recovery.py` no-op.
2. Remaining: prune `graph/__init__.py` to the names actually imported elsewhere
   (`grep -rn "from orchestrator.graph import\|from ..graph import\|orchestrator\.graph\." src tests` to build the list).
   Keep everything with an external consumer; delete the rest.

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
the three-reads-per-iteration pattern is gone). *Expected.*

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
