# Slice DG-5.2c Spec: Gap Planner Final Evidence Safety

## Objective

Repair the first isolated-oracle dynamic smoke blocker found after DG-5.2b.
The live graph proved runtime oracle binding works, but the gap planner accepted
a patch that retired corrective work and created a late final-check edge to an
already completed verifier. The final check never became ready.

## Live Failure Evidence

Run `e4c168ea-d61a-469b-ae92-127c739557ed` used the isolated oracle binding
path:

- check node `check-final-invariant-dynamic-smoke` was created with
  `command_binding: dynamic_feature_hidden_oracle`;
- the command applier resolved it to `command_definition.source:
  dynamic_feature_hidden_oracle_binding`;
- the artifact contained only `dynamic-smoke`, so the hidden oracle would not
  pass;
- weak verifier `verifier-dynamic-smoke` passed;
- gap planner no-op patch `gap-no-op-dynamic-smoke` was correctly rejected;
- retry accepted patch `no-gap-retire-corrective-dynamic-smoke`, which retired
  `worker-corrective-dynamic-smoke` and `verifier-corrective-dynamic-smoke`;
- that patch created a late edge from `verifier-dynamic-smoke` to
  `check-final-invariant-dynamic-smoke`, but no `input_bound` event backfilled
  the already accepted verification record;
- the run paused `graph_blocked` with `last_error="graph quiescent without
  completion"` and final check still deferred on
  `missing_required_input:verification_evidence`.

Metrics for that failed run:

```text
isolated runs=1 completed=0 avg_in=14 avg_out=7721 avg_cache=127059 avg_tools=6.0 avg_cost$=0.2891
```

## Required Behavior

- Creating a new input edge must backfill matching already accepted output
  records into `input_bound` events.
- Backfilled bindings must respect `accepted_record_selector`.
- Gap planner patches must not retire executable `worker`, `verifier`, or
  `check` nodes. They may add corrective structure or evidence-routing edges,
  but cannot remove the corrective path as a substitute for satisfying it.

## Validation Commands

```bash
uv run pytest tests/unit/test_graph_commands.py tests/unit/test_patch_validator.py -q
uv run pytest tests/unit/test_graph_planner_packet.py tests/unit/test_patch_validator.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_compiler.py tests/unit/test_graph_planner.py tests/unit/test_graph_commands.py tests/integration/test_graph_routine_compile.py -q
uv run ruff check src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph/compiler.py src/orchestrator/graph_runtime/horizon_templates.py src/orchestrator/graph/patch_validator.py src/orchestrator/graph/commands.py tests/unit/test_graph_planner_packet.py tests/unit/test_patch_validator.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_compiler.py tests/unit/test_graph_planner.py tests/unit/test_graph_commands.py tests/integration/test_graph_routine_compile.py
uv run pyright src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph/compiler.py src/orchestrator/graph_runtime/horizon_templates.py src/orchestrator/graph/patch_validator.py src/orchestrator/graph/commands.py tests/unit/test_graph_planner_packet.py tests/unit/test_patch_validator.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_compiler.py tests/unit/test_graph_planner.py tests/unit/test_graph_commands.py tests/integration/test_graph_routine_compile.py
```

## Done When

- A unit test proves late-created verifier-to-check edges emit `input_bound`
  against existing verification records.
- A patch-validator test rejects the live gap-planner retire shape.
- Existing DG-5.2b oracle isolation tests still pass.
- A fresh isolated dynamic smoke retry either completes or exposes a new
  accurate blocker.
