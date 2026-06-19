# Slice DG-5.2d Spec: Gap Planner Retry Obligation Signal

## Objective

Repair the next blocker found by the isolated Arm E smoke retry after DG-5.2c:
the graph run paused with a retry-ready gap planner and the gap planner packet
did not make pending corrective/final-invariant obligations explicit enough.

## Baseline

Live retry `2558d649-d27a-4816-b1f6-a68e33e3c59d` paused with
`pause_reason=graph_blocked` and `last_error="graph quiescent without
completion"`.

Verified summary events:

- root planner patch `patch-dynamic-smoke-full-plan` was rejected because the
  invariant check lacked a verification input edge;
- retry patch `patch-ds-full-plan-v3` was accepted;
- gap no-op patch `patch-ds-gap-no-op` was rejected because a required
  `classified_gap` successor remained unsatisfied;
- gap retire patch `patch-ds-gap-retire-corrective` was rejected by DG-5.2c with
  `gap planner cannot retire executable node: worker-ds-corrective`;
- final event position 110 re-readied `planner-ds-gap`.

## Deliverables

- Report ready-node and active-lease graph driver blockers explicitly instead
  of collapsing them to generic quiescence.
- Add gap-planner packet obligations for:
  - required `classified_gap` successors that are still waiting;
  - final invariant check nodes deferred on missing `verification_evidence`.
- Tell gap planners that obligations are blocking and a no-op patch is invalid
  while obligations remain.

## Done When

- Focused graph-driver logic tests prove a ready retry node is classified as a
  ready-node dispatch blocker.
- Focused planner packet tests prove gap planners receive blocking obligations
  for the live retry shapes.
- Focused ruff and pyright checks pass on touched implementation and test files.

## Validation

Accepted 2026-06-15 for code-level repair. Validation passed:

```bash
uv run pytest tests/unit/test_graph_driver_logic.py tests/unit/test_graph_planner_packet.py -q
uv run ruff check src/orchestrator/workflow/graph_driver.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_driver_logic.py tests/unit/test_graph_planner_packet.py
uv run pyright src/orchestrator/workflow/graph_driver.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_driver_logic.py tests/unit/test_graph_planner_packet.py
```

Next action: restart/reload with DG-5.2d loaded and run a fresh isolated Arm E
dynamic smoke retry.
