# Slice DG-5.1a Spec: Dynamic Feature Context Wiring

## Objective

Repair the DG-5.1 smoke blocker by ensuring the `dynamic-graph-feature` graph seed gives the initial planner concrete feature inputs instead of an empty planner shell.

## Scope

In scope:

- Pass selected run configuration into graph routine seeding.
- Persist the dynamic feature inputs in the routine snapshot.
- Put the dynamic feature inputs and a non-empty grounded context on the initial planner node.
- Include the dynamic feature input block in the planner context packet and prompt contract.
- Prove the seed path and packet path with tests.

Out of scope:

- Changing graph patch validation semantics.
- Broad routine YAML redesign.
- Accepting mis-scoped worktree edits from the blocked DG-5.1 run.
- Completing the full DG-5.1 smoke run.

## Dynamic Feature Inputs

For `dynamic-graph-feature`, carry these run configuration fields:

- `feature_spec_path`
- `acceptance_command`
- `hidden_oracle_command`
- `patch_budget`
- `gap_policy_profile`

The planner packet must make clear that generated worker, verifier, gap-analysis, corrective-work, and final invariant regions should be grounded in those inputs.

## Done When

Accepted only if:

1. The compiler remains pure and takes run inputs only as an explicit argument.
2. `seed_run` and `GraphRunDriver` pass the run config into graph compilation.
3. A `dynamic-graph-feature` planner node has non-empty `task_context` naming the feature spec and validation commands.
4. The planner packet includes a `dynamic_feature` object with the selected run inputs.
5. Tests prove compile, seed, and planner-packet behavior without mocks or monkeypatching.

## Validation Commands

```bash
uv run pytest tests/unit/test_graph_compiler.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_routine_compile.py -q
uv run ruff check src/orchestrator/graph/compiler.py src/orchestrator/graph_runtime/seeding.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/workflow/graph_driver.py tests/unit/test_graph_compiler.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_routine_compile.py
uv run pyright src/orchestrator/graph/compiler.py src/orchestrator/graph_runtime/seeding.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/workflow/graph_driver.py tests/unit/test_graph_compiler.py tests/unit/test_graph_planner_packet.py tests/integration/test_graph_routine_compile.py
```

## Durable Update

Update `docs/graph-approach/dynamic-graph-operational-plan.md` with the verified result and whether DG-5.1 can be retried.
