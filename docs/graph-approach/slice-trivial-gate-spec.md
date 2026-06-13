# Trivial gate spec — graph dogfood verification

This is NOT a kernel slice. It is a deliberately trivial one-task spec used to
verify the production graph execution path end-to-end (slice 2.7 + 2.8): a
graph-mode run must compile, dispatch a worker, capture a file-state boundary,
pass the verifier, mark the task accepted, and complete the run in the server.

## Scope — what to build

Create a file `docs/graph-approach/GATE_PROOF.md` containing exactly one line:

```
Graph dogfood gate executed end-to-end through the production GraphRunDriver.
```

Do nothing else. Do not modify any other file. Do not run the test suite.

## Done when

1. `docs/graph-approach/GATE_PROOF.md` exists and contains the line above.

## Hard constraints

- Only create the one file. No other changes.
