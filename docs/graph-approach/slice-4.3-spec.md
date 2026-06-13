# Slice 4.3 — Conclude the loop-vs-routine-vs-graph carrier experiment

Size: M. The project has carried three execution carriers in parallel — the
original loop, the routine/workflow engine (legacy), and the execution graph.
Phase 4 concludes the experiment by data: graph is the single carrier; the
redundant carriers are removed or frozen, and the decision is recorded so the
codebase stops paying the multi-carrier tax (the multi-source-of-truth bugs in
the event-driven-intent memory).

## Prerequisites

- 4.1 (graph default carrier) and 4.2 (oversight retired) merged.
- Enough live graph runs completed to compare against legacy on the metrics
  below (the dogfood gate run plus the 3.x slice runs themselves once re-run as
  graph, or a small dedicated comparison batch).

## Ground truth

- execution-graph-evaluation.md §4.4 (planner/token overhead), §4.5 (minimal
  graphs), §6.1 (single loop = graph readiness); slice-process.md Phase 4
  ("the loop-vs-routine-vs-graph mode experiment concludes by data").
- The cost/event records (slice 0.2) and activity/timeline (3.2) are the data
  sources for the comparison.

## Scope — what to build

### 1. Carrier comparison report (data, committed)

- A reproducible analysis (script + committed markdown summary under
  `docs/graph-approach/`) comparing graph vs legacy on: completion rate, retries
  per run, wall-clock to COMPLETED, token/cost per run (from the cost records),
  and operator-visible failure modes. Use the runs already recorded plus a small
  dedicated batch if coverage is thin. State the verdict explicitly.

### 2. Remove or freeze the redundant carrier(s)

- Based on the verdict (expected: graph wins), remove the dead carrier code that
  4.1/4.2 did not already delete, or — if any legacy path must remain for an
  un-portable routine class — freeze it behind the `default_execution_mode`
  opt-out (4.1) and document precisely which routine classes still need it and
  why. No carrier may remain "just in case" without a recorded reason.
- Delete the now-unreachable mode-selection branches and their tests; collapse
  carrier conditionals to the single live path.

### 3. Record the decision

- A short ADR-style note in `docs/graph-approach/` ("Carrier decision: graph")
  capturing the data, the verdict, what was removed, what (if anything) stays
  legacy and why, and the one-line rollback (`default_execution_mode`).

## Tests

- `tests/integration/test_single_carrier.py` (new): the run lifecycle exercises
  only the surviving carrier path(s); a run with no explicit mode is a graph run
  end-to-end; any frozen-legacy routine class is covered by an explicit test.
- The comparison script has a unit test over a fixed fixture of recorded
  runs/cost records proving the metric computation (pure; hand-built fixtures).
- Remove tests that only existed to cover deleted carrier-selection branches.

## Done when

1. A committed, reproducible carrier comparison report states the verdict with
   data (completion rate, retries, wall-clock, cost, failure modes).
2. The redundant carrier code is removed (or explicitly frozen behind the 4.1
   opt-out with a recorded reason); carrier conditionals collapse to the single
   live path.
3. An ADR-style decision note records the verdict, removals, any retained legacy
   class, and the one-line rollback.
4. Full suites green (unit/integration/vitest); ruff/pyright clean; kernel purity
   + `graph_runtime` boundary unchanged.

## Hard constraints (same as all slices)

- NO mocks/monkeypatching; pure fixtures for the metric computation; real SQLite
  tmp for lifecycle tests; never touch `orchestrator.db` / main repo git.
- The comparison must use recorded cost/event facts, not re-run estimates.
- Kernel purity + `graph_runtime` boundary + §28 rule 1 unchanged.
