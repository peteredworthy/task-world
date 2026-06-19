# Slice DG-5.2b Spec: Hidden Oracle Isolation

## Objective

Make the true-comparison harness fair by keeping hidden oracle commands outside
planner, worker, verifier, and gap-planner prompts while preserving runtime
final-invariant execution.

DG-5.1 deliberately exposed `hidden_oracle_command` to prove the operational
dynamic graph path. DG-5.2 comparisons require a stricter rule from
`true-comparison-plan.md`: hidden acceptance tests are run outside all agents.

## Scope

In scope:

- Remove `hidden_oracle_command` from planner task context, planner packets, and
  dynamic worker fallback prompt lines.
- Replace planner-visible final-check instructions with the opaque binding
  `command_binding: dynamic_feature_hidden_oracle`.
- Allow patch validation for check nodes that use that binding.
- Resolve the binding to the real hidden oracle command at graph command-apply
  time from the stored routine snapshot.
- Preserve backward compatibility for existing planner patches that already
  provide `hidden_oracle_command` or explicit `command_definition`.

Out of scope:

- Re-running the full five-arm comparison.
- Changing the dynamic smoke feature spec.
- Hiding ordinary weak acceptance commands; those are intentionally visible.

## Required Behavior

- Planner packets may expose `hidden_oracle_binding:
  dynamic_feature_hidden_oracle` but must not expose the command string.
- Worker-like prompts may include feature spec, feature content, and weak
  acceptance command, but not `dynamic_hidden_oracle_command` or the hidden
  oracle command text.
- Final invariant horizon examples include
  `command_binding: dynamic_feature_hidden_oracle`.
- A planner-created check node with that binding is accepted by patch
  validation.
- When the patch is accepted, the graph command applier resolves the binding
  from the durable `routine-snapshot.dynamic_feature.hidden_oracle_command` and
  creates the check node with a concrete `command_definition`.

## Validation Commands

```bash
uv run pytest tests/unit/test_graph_planner_packet.py tests/unit/test_patch_validator.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_compiler.py tests/unit/test_graph_planner.py tests/integration/test_graph_routine_compile.py -q
uv run ruff check src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph/compiler.py src/orchestrator/graph_runtime/horizon_templates.py src/orchestrator/graph/patch_validator.py src/orchestrator/graph/commands.py tests/unit/test_graph_planner_packet.py tests/unit/test_patch_validator.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_compiler.py tests/unit/test_graph_planner.py tests/integration/test_graph_routine_compile.py
uv run pyright src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph/compiler.py src/orchestrator/graph_runtime/horizon_templates.py src/orchestrator/graph/patch_validator.py src/orchestrator/graph/commands.py tests/unit/test_graph_planner_packet.py tests/unit/test_patch_validator.py tests/unit/test_graph_horizon_templates.py tests/unit/test_graph_compiler.py tests/unit/test_graph_planner.py tests/integration/test_graph_routine_compile.py
```

## Done When

- Focused tests prove hidden oracle text is absent from planner and worker
  prompts.
- Focused patch-validator tests prove the opaque binding is accepted.
- Focused graph-command tests prove the binding resolves to a concrete command
  definition from runtime snapshot state.
- The comparison results ledger records that S1 is now suitable for controlled
  hidden-oracle comparison runs, subject to live smoke verification.
