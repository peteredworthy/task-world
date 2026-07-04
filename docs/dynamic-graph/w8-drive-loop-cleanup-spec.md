# W8 — Drive-loop simplification and dead-code removal

Addresses weakness **W8** (low) and improvement **#9** in
`dynamic-graph-implementation-review.html` (re-assessed 2026-07-03).

**Ordering:** the loop-simplification half depends on W2 (`w2-recovery-at-source-spec.md`)
and W3 (`w3-incremental-snapshots-spec.md`) having landed. The dead-code half can go
any time.

## Problem

- `workflow/graph_driver.py` (`drive_to_quiescence`, now ~1,000 lines total in the
  module) re-ticks, re-reads the projection multiple times per iteration, retries an
  extra recovery tick on quiescence, and compares progress *signatures* because raw
  position always advances (per-tick `node_deferred` events — fixed by W3).
- `graph_runtime/recovery.py:62–63` carries a self-cancelling statement:
  `if not redispatched and pending_before: redispatched = []`.
- `graph/__init__.py` re-exports ~190 names, coupling every consumer to one namespace.

## Scope

**Slice A — dead code (do now, trivially safe):**
1. Delete the `recovery.py` no-op (verify by reading the surrounding function that it
   truly has no effect before deleting).
2. Prune `graph/__init__.py` to the names actually imported elsewhere
   (`grep -rn "from orchestrator.graph import\|from ..graph import\|orchestrator\.graph\." src tests` to build the list).
   Keep everything with an external consumer; delete the rest.

**Slice B — loop simplification (after W2 + W3):**
1. With per-tick `node_deferred` gone (W3), replace the progress-signature comparison
   with "did event position advance".
2. With repair moved to source commands (W2), remove the extra recovery re-tick on
   quiescence; quiescence-with-blockers issues one `reconcile` command instead.
3. Collapse redundant projection re-reads within one iteration to a single read
   passed through.
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
