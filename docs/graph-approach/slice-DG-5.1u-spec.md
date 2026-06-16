# Slice DG-5.1u Spec: Planner Patch Check Command Validation

## Objective

Reject planner graph patches that create executable check nodes without a
`command_definition` or `hidden_oracle_command`, so final invariant checks cannot
reach scheduler state with `precondition_failed:has_command_definition`.

## Scope

In scope:

- Validate planner-created `check` nodes at the graph patch boundary.
- Keep direct graph command tests able to construct commandless checks when they
  are intentionally exercising scheduler preconditions.
- Ground planner instructions and final invariant horizon templates in the
  command requirement.
- Retry the DG-5.1 dynamic smoke run after code-level validation.

Out of scope:

- Broad command-definition schema redesign.
- Manual event injection to unblock an already-created commandless check.
- Full five-arm comparison.

## Live Failure Evidence

Run `89d5347a-94d8-4881-8448-3dcfdca3f268` proved the DG-5.1t completion guard:
after corrective verifier evidence bound to `check-dynamic-smoke-invariant`, the
run remained active instead of completing prematurely. The next scheduler tick
then deferred that final invariant check with:

```text
precondition_failed:has_command_definition
```

The root planner had created `check-dynamic-smoke-invariant` with `kind:
"check"`, `role: "invariant_gate"`, `state: "planned"`, and
`task_region_id: "region-dynamic-smoke"`, but without `command_definition` or
`hidden_oracle_command`.

## Required Behavior

- `validate_patch` rejects any `create_node` operation for `kind: "check"` when
  neither a dict `command_definition` nor a nonempty string
  `hidden_oracle_command` is present.
- Patches that provide either field remain valid, subject to the existing
  invariant evidence-edge checks.
- Planner prompts explicitly instruct dynamic feature planners to use
  `dynamic_feature.hidden_oracle_command` for final invariant checks when
  present.
- The final invariant horizon template records that runtime command binding is
  required.

## Validation Commands

```bash
uv run pytest tests/unit/test_patch_validator.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner.py -q
uv run ruff check src/orchestrator/graph/patch_validator.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/horizon_templates.py tests/unit/test_patch_validator.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner.py
uv run pyright src/orchestrator/graph/patch_validator.py src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/horizon_templates.py tests/unit/test_patch_validator.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_planner.py
```

Then launch a fresh DG-5.1 smoke run with `dynamic-graph-feature` using
`cli_subprocess`/Claude CLI and confirm:

1. A commandless check patch is rejected, or the planner supplies
   `hidden_oracle_command`/`command_definition`.
2. The final invariant check has a command definition in graph projection.
3. The final invariant check reaches terminal evidence, or the run pauses with a
   new, accurate blocker unrelated to `has_command_definition`.

## Durable Update

Update `docs/graph-approach/dynamic-graph-operational-plan.md` with the focused
validation and fresh DG-5.1 retry result before moving to DG-5.2.
