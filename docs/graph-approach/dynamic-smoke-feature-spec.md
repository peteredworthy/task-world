# Dynamic Smoke Feature Spec

## Goal

Create a tiny artifact at `docs/graph-approach/dynamic-smoke-output.txt` that demonstrates the dynamic graph can discover and correct an initially weak validation plan.

## Initial Requirement

Write a one-line status artifact for a fictional feature named `dynamic-smoke`.

The first local acceptance check may only verify that the file exists and contains `dynamic-smoke`.

## Hidden Global Requirement

The final artifact must also contain a second line:

```text
validation-strengthened: true
```

This requirement is intentionally absent from the weak local acceptance check. A gap planner or invariant pass must discover that the local check is insufficient and append corrective work.

## Expected Dynamic Behavior

1. A planner creates initial worker/verifier/check work using `submit_graph_patch`.
2. A worker writes the initial artifact.
3. Local verification can pass with the weak existence/content check.
4. A gap planner identifies the missing `validation-strengthened: true` evidence.
5. A corrective region appends the missing line.
6. The final invariant gate blocks completion until the corrective evidence is present and all proposals are decided.

## Weak Acceptance Command

```bash
test -f docs/graph-approach/dynamic-smoke-output.txt && rg -q "dynamic-smoke" docs/graph-approach/dynamic-smoke-output.txt
```

## Hidden Oracle Command

```bash
test -f docs/graph-approach/dynamic-smoke-output.txt && rg -q "dynamic-smoke" docs/graph-approach/dynamic-smoke-output.txt && rg -q "validation-strengthened: true" docs/graph-approach/dynamic-smoke-output.txt
```
